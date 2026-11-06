"""A/B backtest — does the brand_tier adjustment (Alavanca B) improve
max_trade_value accuracy?

Method:
    1. Load appraisal history (UTILIZADO + REPASSE = we actually paid).
    2. Cross-reference each row's plate with sales to discover the ACTUAL
       channel the car later went through. Keep only rows with a channel.
    3. For each row, run `appraise()` TWICE with the same inputs:
         CONTROL    — brand_tier.enabled = False
         TREATMENT  — brand_tier.enabled = True  (SAFE −2pp / RISKY +2pp)
    4. For the row's ACTUAL channel, pick max_trade_value from each run
       and compare to the row's actual appraised_value (what we paid).
    5. Report MAPE / bias / median error split by:
         - overall (all rows)
         - per tier × channel (SAFE/NEUTRAL/RISKY × Loja/Revenda)

Why `max_trade_value` and not `estimated_sale_price`? Because the
engineering trade-off of Alavanca B is specifically "how much should
we OFFER for this car", and that is what max_trade_value represents.
A change that pays closer to the actual historical payment reduces
both our under-buying (losing deals) and over-paying (eroding margin).

Alavanca A (channel_probability) only surfaces a UI badge today — it
doesn't change max_trade_value. It is NOT exercised in this backtest.

Run:
    py -3.12 -m tests.backtests.backtest_ab_tier
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.analysis.appraisal import appraise
from grand_brasil.config import AppraisalConfig
from grand_brasil.ingestion.appraisal_history import load_appraisal_history
from grand_brasil.ingestion.sales_history import load_sales_history
from grand_brasil.models.appraisal import AppraisalRequest
from grand_brasil.utils.brand_tier import BrandTierConfig, classify_brand

logging.basicConfig(level=logging.ERROR, format="%(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Metrics:
    label: str
    n: int
    mape: float
    bias: float
    median_err: float

    def fmt(self) -> str:
        bias = f"+{self.bias:.2f}%" if self.bias >= 0 else f"{self.bias:.2f}%"
        med = f"+{self.median_err:.2f}%" if self.median_err >= 0 else f"{self.median_err:.2f}%"
        return f"{self.label:<26} n={self.n:>4}  MAPE {self.mape:>5.2f}%  bias {bias:>7}  median {med:>7}"


def _normalize_plate(plate) -> Optional[str]:
    if plate is None or pd.isna(plate):
        return None
    s = str(plate).strip().upper().replace("-", "").replace(" ", "")
    if not s or s in ("NAN", "NONE"):
        return None
    return s


def _classify_channel(raw: str) -> str:
    if not raw:
        return "Other"
    s = str(raw).upper()
    if "REVENDA" in s or "ATACADO" in s or "REPASSE" in s:
        return "Revenda"
    if "LOJA" in s or "VAREJO" in s or "VENDA" in s:
        return "Loja"
    return "Other"


def _build_plate_channel_map(sales: pd.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    for _, r in sales.iterrows():
        p = _normalize_plate(r.get("plate"))
        if p is None:
            continue
        ch = str(r.get("sale_channel", ""))
        if ch and ch.upper() not in ("NAN", "NONE"):
            out[p] = ch
    return out


def _compute_metrics(label: str, y_true: np.ndarray, y_pred: np.ndarray) -> Metrics:
    mask = ~np.isnan(y_pred) & (y_true > 0)
    yt = y_true[mask]
    yp = y_pred[mask]
    if len(yt) == 0:
        return Metrics(label, 0, float("nan"), float("nan"), float("nan"))
    err_pct = (yp - yt) / yt * 100.0
    return Metrics(
        label=label,
        n=len(yt),
        mape=float(np.mean(np.abs(err_pct))),
        bias=float(np.mean(err_pct)),
        median_err=float(np.median(err_pct)),
    )


def _predict_max_trade(
    brand: str,
    model_red: str,
    year_model: int,
    km: Optional[int],
    fipe_value: float,
    actual_channel: str,
    sales_df: pd.DataFrame,
    appraisal_df: pd.DataFrame,
    appraisal_cfg: AppraisalConfig,
) -> Optional[float]:
    """Run appraise() and return max_trade_value for the ACTUAL channel."""
    try:
        req = AppraisalRequest(
            brand=brand,
            model_red=model_red,
            year_model=int(year_model),
            km=int(km) if km is not None and not pd.isna(km) else None,
            fipe_price=Decimal(str(float(fipe_value))),
        )
        res = appraise(
            request=req,
            sales_df=sales_df,
            appraisal_df=appraisal_df,
            appraisal_config=appraisal_cfg,
            loja_target_margin=appraisal_cfg.loja_target_margin,
            revenda_target_margin=appraisal_cfg.revenda_target_margin,
            year_tolerance=appraisal_cfg.year_tolerance,
            min_comparables=appraisal_cfg.min_comparables,
            year_pct_per_year=appraisal_cfg.year_pct_per_year,
        )
    except Exception as e:
        logger.debug(f"Predict failed for {brand} {model_red}: {e}")
        return None

    mt = (
        res.loja_max_trade_value
        if actual_channel == "Loja"
        else res.revenda_max_trade_value
    )
    return float(mt) if mt is not None and mt > 0 else None


def run() -> None:
    root = Path(__file__).resolve().parents[2]
    appr_path = root / "Avaliações 2025 e 2026.xlsx"
    sales_path = root / "Relatorio vendas 20255 processado.xlsx"

    if not appr_path.exists() or not sales_path.exists():
        print("ERRO: arquivos de entrada não encontrados.")
        return

    print("=" * 95)
    print("  A/B BACKTEST — Alavanca B (brand_tier) — impacto em max_trade_value")
    print("=" * 95)

    print("\nCarregando avaliações...")
    df_appr_full = load_appraisal_history(appr_path)

    print("Carregando vendas...")
    df_sales = load_sales_history(sales_path)

    print("Cruzando placas...")
    chan_map = _build_plate_channel_map(df_sales)

    # ── Test set: UTILIZADO/REPASSE com plate no sales e dados completos ──
    eval_pool = df_appr_full[df_appr_full["status_norm"].isin({"UTILIZADO", "REPASSE"})].copy()
    eval_pool = eval_pool.dropna(subset=["fipe_value", "appraised_value", "km", "brand", "model_red"])

    eval_pool["_plate_norm"] = eval_pool["plate"].apply(_normalize_plate)
    eval_pool["sale_channel_raw"] = eval_pool["_plate_norm"].map(chan_map).fillna("")
    eval_pool["channel"] = eval_pool["sale_channel_raw"].apply(_classify_channel)
    eval_pool = eval_pool[eval_pool["channel"].isin(["Loja", "Revenda"])].reset_index(drop=True)

    print(f"  test set: {len(eval_pool):,} linhas com canal conhecido\n")

    # Tag tier
    def _tier(b: str) -> str:
        cfg = BrandTierConfig()
        safe = {x.upper() for x in cfg.safe_brands}
        risky = {x.upper() for x in cfg.risky_brands}
        bu = str(b).upper().strip()
        if bu in safe:
            return "SAFE"
        if bu in risky:
            return "RISKY"
        return "NEUTRAL"

    eval_pool["tier"] = eval_pool["brand"].apply(_tier)

    print("Distribuição do test set:")
    print(eval_pool.groupby(["tier", "channel"]).size().unstack(fill_value=0).to_string())
    print()

    # ── Rodar CONTROL e TREATMENT ───────────────────────────────────────
    cfg_control = AppraisalConfig(brand_tier=BrandTierConfig(enabled=False))
    cfg_treat = AppraisalConfig(brand_tier=BrandTierConfig(enabled=True))

    y_true = eval_pool["appraised_value"].astype(float).to_numpy()
    y_ctrl = np.full(len(eval_pool), np.nan)
    y_treat = np.full(len(eval_pool), np.nan)

    print("Rodando predições (control + treatment)... isto demora um pouco.\n")

    for i, row in eval_pool.iterrows():
        pred_ctrl = _predict_max_trade(
            brand=str(row["brand"]),
            model_red=str(row["model_red"]),
            year_model=int(row["year_model"]),
            km=row["km"],
            fipe_value=float(row["fipe_value"]),
            actual_channel=row["channel"],
            sales_df=df_sales,
            appraisal_df=df_appr_full,
            appraisal_cfg=cfg_control,
        )
        pred_t = _predict_max_trade(
            brand=str(row["brand"]),
            model_red=str(row["model_red"]),
            year_model=int(row["year_model"]),
            km=row["km"],
            fipe_value=float(row["fipe_value"]),
            actual_channel=row["channel"],
            sales_df=df_sales,
            appraisal_df=df_appr_full,
            appraisal_cfg=cfg_treat,
        )
        if pred_ctrl is not None:
            y_ctrl[i] = pred_ctrl
        if pred_t is not None:
            y_treat[i] = pred_t

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(eval_pool)} linhas processadas...")

    # ── Resultados ──────────────────────────────────────────────────────
    print("\n" + "=" * 95)
    print("  MÉTRICAS GLOBAIS")
    print("=" * 95)
    m_ctrl = _compute_metrics("CONTROL   (tier off)", y_true, y_ctrl)
    m_treat = _compute_metrics("TREATMENT (tier on) ", y_true, y_treat)
    print(m_ctrl.fmt())
    print(m_treat.fmt())

    dl_mape = m_treat.mape - m_ctrl.mape
    dl_bias = m_treat.bias - m_ctrl.bias
    print(f"\n  Δ MAPE:  {dl_mape:+.2f}pp   (negativo = melhora)")
    print(f"  Δ Bias:  {dl_bias:+.2f}pp")

    # ── Breakdown por tier × canal ──────────────────────────────────────
    print("\n" + "=" * 95)
    print("  POR TIER × CANAL")
    print("=" * 95)
    for tier in ["SAFE", "NEUTRAL", "RISKY"]:
        for chan in ["Loja", "Revenda"]:
            mask = ((eval_pool["tier"] == tier) & (eval_pool["channel"] == chan)).to_numpy()
            if mask.sum() < 5:
                continue
            m_c = _compute_metrics(f"[{tier:<7} {chan}] CONTROL  ", y_true[mask], y_ctrl[mask])
            m_t = _compute_metrics(f"[{tier:<7} {chan}] TREAT    ", y_true[mask], y_treat[mask])
            print(f"\n{m_c.fmt()}")
            print(f"{m_t.fmt()}")
            dmape = m_t.mape - m_c.mape
            dbias = m_t.bias - m_c.bias
            print(f"  Δ MAPE {dmape:+.2f}pp | Δ Bias {dbias:+.2f}pp")

    # ── Verdict ─────────────────────────────────────────────────────────
    print("\n" + "=" * 95)
    print("  VEREDICTO")
    print("=" * 95)
    if np.isnan(dl_mape):
        print("  Sem dados suficientes para verdict.")
    elif dl_mape < -0.3:
        print(f"  ✓ Alavanca B REDUZ MAPE global em {abs(dl_mape):.2f}pp — ACEITAR.")
    elif dl_mape > 0.3:
        print(f"  ✗ Alavanca B PIORA MAPE global em {dl_mape:.2f}pp — REVISAR.")
    else:
        print(f"  ~ Efeito pequeno no MAPE global (Δ={dl_mape:+.2f}pp).")
        print("    Ver breakdown por tier — o ganho pode estar concentrado em SAFE/RISKY.")

    print("\n(Lembre-se: Alavanca A é puramente de UI e não foi exercida neste backtest.)")


if __name__ == "__main__":
    run()
