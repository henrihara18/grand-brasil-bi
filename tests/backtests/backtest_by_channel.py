"""Backtest split by destination channel (Loja vs Revenda).

The vanilla buy-ratio backtest (`backtest_calibration.py`) reports a single
aggregate MAPE/bias, hiding whether the algorithm is fair to BOTH sides of
the business. Cars destined for B2C resale (Loja) command different price
points than cars sent to wholesale (Revenda), and a calibration that's
average-good could still be systematically off in one channel.

Method:
    1. Same holdout split as `backtest_calibration.py` (random 20% of closed
       deals UTILIZADO/REPASSE).
    2. Cross-reference each test row's `plate` against the sales history to
       discover the ACTUAL `sale_channel` that the car ended up in. Plates
       not found in sales (still in stock, sold pre-2025, or unmatched) are
       reported separately.
    3. Run buy-ratio prediction (NEW config: avaliado_weight=0.25) and
       compute MAPE / bias / median error PER channel.

What we want to learn:
    - Is the buy-ratio biased toward overpaying for one channel?
    - Does the algorithm's accuracy differ between Loja and Revenda?
    - Should we consider channel-aware ratio profiles?

Run:
    py -3.12 -m tests.backtests.backtest_by_channel

Not a pytest test (slow, requires real data files).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.analysis.purchase_ratio import (
    compute_buy_ratio,
    compute_year_ratio_profile,
)
from grand_brasil.config import BuyRatioConfig
from grand_brasil.ingestion.appraisal_history import load_appraisal_history
from grand_brasil.ingestion.sales_history import load_sales_history

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(message)s")


@dataclass
class ChannelMetrics:
    label: str
    n: int
    mape_pct: float
    bias_pct: float
    median_err_pct: float
    p25_err_pct: float
    p75_err_pct: float
    rmse_brl: float


def _compute_metrics(label: str, y_true: np.ndarray, y_pred: np.ndarray) -> ChannelMetrics:
    mask = ~np.isnan(y_pred) & (y_true > 0)
    yt = y_true[mask]
    yp = y_pred[mask]
    if len(yt) == 0:
        return ChannelMetrics(label, 0, float("nan"), float("nan"),
                              float("nan"), float("nan"), float("nan"), float("nan"))
    err_pct = (yp - yt) / yt * 100.0
    return ChannelMetrics(
        label=label,
        n=len(yt),
        mape_pct=float(np.mean(np.abs(err_pct))),
        bias_pct=float(np.mean(err_pct)),
        median_err_pct=float(np.median(err_pct)),
        p25_err_pct=float(np.percentile(err_pct, 25)),
        p75_err_pct=float(np.percentile(err_pct, 75)),
        rmse_brl=float(np.sqrt(np.mean((yp - yt) ** 2))),
    )


def _normalize_plate(plate) -> Optional[str]:
    """Normalize plate string for cross-matching."""
    if plate is None or pd.isna(plate):
        return None
    s = str(plate).strip().upper().replace("-", "").replace(" ", "")
    if not s or s in ("NAN", "NONE"):
        return None
    return s


def _find_channel_map(sales_df: pd.DataFrame) -> dict[str, str]:
    """Build {normalized_plate: sale_channel} from the sales history."""
    plate_to_chan: dict[str, str] = {}
    for _, r in sales_df.iterrows():
        p = _normalize_plate(r.get("plate"))
        if p is None:
            continue
        chan = str(r.get("sale_channel", "")).strip()
        if chan and chan.upper() not in ("NAN", "NONE"):
            plate_to_chan[p] = chan
    return plate_to_chan


def _classify_channel(raw: str) -> str:
    """Bucketize sales_channel string into 'Loja' / 'Revenda' / 'Other'.

    Handles variants like 'Atacado', 'Varejo', etc.
    """
    if not raw:
        return "Other"
    s = raw.upper()
    if "REVENDA" in s or "ATACADO" in s or "REPASSE" in s:
        return "Revenda"
    if "LOJA" in s or "VAREJO" in s or "VENDA" in s:
        return "Loja"
    return "Other"


def run() -> None:
    root = Path(__file__).resolve().parents[2]
    appr_path = root / "Avaliações 2025 e 2026.xlsx"
    sales_path = root / "Relatorio vendas 20255 processado.xlsx"

    if not appr_path.exists():
        print(f"ERRO: {appr_path}")
        return
    if not sales_path.exists():
        print(f"ERRO: {sales_path}")
        return

    print("=" * 80)
    print("BACKTEST POR CANAL — Loja vs Revenda")
    print("=" * 80)

    print("\nCarregando avaliações...")
    df_appr = load_appraisal_history(appr_path)
    print(f"  {len(df_appr):,} avaliações carregadas")

    print("Carregando vendas...")
    df_sales = load_sales_history(sales_path)
    print(f"  {len(df_sales):,} vendas carregadas")

    print("Cruzando placas para descobrir canal de venda...")
    chan_map = _find_channel_map(df_sales)
    print(f"  {len(chan_map):,} placas únicas encontradas em vendas")

    # Holdout split (same seed as backtest_calibration.py for comparability)
    eval_pool = df_appr[df_appr["status_norm"].isin({"UTILIZADO", "REPASSE"})].copy()
    eval_pool = eval_pool.dropna(subset=["fipe_value", "appraised_value", "km"])

    rng = np.random.default_rng(42)
    n = len(eval_pool)
    n_test = int(n * 0.20)
    test_idx = rng.choice(n, size=n_test, replace=False)
    mask_test = np.zeros(n, dtype=bool)
    mask_test[test_idx] = True
    test_set = eval_pool.iloc[mask_test].reset_index(drop=True)
    test_plates = set(test_set["plate"].dropna().astype(str).tolist())
    train_set = df_appr[~df_appr["plate"].astype(str).isin(test_plates)].copy()

    print(f"\nHoldout: train={len(train_set):,} | test={len(test_set):,}\n")

    # Tag each test row with its eventual channel (via plate cross-reference)
    test_set["_plate_norm"] = test_set["plate"].apply(_normalize_plate)
    test_set["sale_channel_raw"] = test_set["_plate_norm"].map(chan_map).fillna("")
    test_set["channel_bucket"] = test_set["sale_channel_raw"].apply(_classify_channel)

    bucket_counts = test_set["channel_bucket"].value_counts()
    print("Distribuição de canal (placas cruzadas):")
    for k, v in bucket_counts.items():
        print(f"  {k:<10} {v:>5} ({100*v/len(test_set):.1f}%)")

    # Run predictions (NEW config only — we already know NEW vs OLD is neutral)
    profile = compute_year_ratio_profile(train_set)
    cfg = BuyRatioConfig()
    y_pred = np.full(len(test_set), np.nan)
    for i, row in test_set.iterrows():
        km = int(row["km"]) if not pd.isna(row["km"]) else None
        res = compute_buy_ratio(
            model_red=str(row["model_red"]),
            year_model=int(row["year_model"]),
            km=km,
            appraisal_df=train_set,
            year_profile=profile,
            config=cfg,
        )
        if res.available:
            y_pred[i] = res.ratio_median * float(row["fipe_value"])

    y_true = test_set["appraised_value"].to_numpy()

    # Compute metrics per channel
    print("\n" + "=" * 80)
    print("MÉTRICAS POR CANAL")
    print("=" * 80)
    print(f"{'Canal':<14} {'n':>5}  {'MAPE':>7}  {'Bias':>8}  {'Median':>8}  {'P25 err':>9}  {'P75 err':>9}  {'RMSE':>14}")
    print("-" * 95)

    overall = _compute_metrics("Geral (com pred)", y_true, y_pred)
    rows_to_print = [overall]

    for bucket in ["Loja", "Revenda", "Other"]:
        sub_mask = (test_set["channel_bucket"] == bucket).to_numpy()
        if sub_mask.sum() == 0:
            continue
        m = _compute_metrics(bucket, y_true[sub_mask], y_pred[sub_mask])
        rows_to_print.append(m)

    # Also: cars NOT yet sold (no plate match) — proxy = appraisal status
    not_found = (test_set["sale_channel_raw"] == "").to_numpy()
    if not_found.sum() > 0:
        m_nf = _compute_metrics("(sem venda*)", y_true[not_found], y_pred[not_found])
        rows_to_print.append(m_nf)

    for m in rows_to_print:
        bias_str = f"+{m.bias_pct:.2f}%" if m.bias_pct >= 0 else f"{m.bias_pct:.2f}%"
        med_str = f"+{m.median_err_pct:.2f}%" if m.median_err_pct >= 0 else f"{m.median_err_pct:.2f}%"
        p25_str = f"+{m.p25_err_pct:.2f}%" if m.p25_err_pct >= 0 else f"{m.p25_err_pct:.2f}%"
        p75_str = f"+{m.p75_err_pct:.2f}%" if m.p75_err_pct >= 0 else f"{m.p75_err_pct:.2f}%"
        print(f"{m.label:<14} {m.n:>5}  {m.mape_pct:>6.2f}%  {bias_str:>8}  {med_str:>8}  "
              f"{p25_str:>9}  {p75_str:>9}  R$ {m.rmse_brl:>10,.0f}")

    print("\n* (sem venda) = placa do appraisal não encontrada nas vendas processadas — pode estar")
    print("  em estoque, vendida antes/depois do export de vendas, ou com mismatch de placa.")

    # ── Status_norm proxy (UTILIZADO ≈ Loja, REPASSE ≈ Revenda direto) ────
    print("\n" + "=" * 80)
    print("PROXY ALTERNATIVO: status_norm da própria avaliação")
    print("(UTILIZADO geralmente vai p/ Loja, REPASSE direto para wholesale)")
    print("=" * 80)
    print(f"{'Status':<14} {'n':>5}  {'MAPE':>7}  {'Bias':>8}  {'Median':>8}  {'P25 err':>9}  {'P75 err':>9}")
    print("-" * 80)
    for status in ["UTILIZADO", "REPASSE"]:
        sub_mask = (test_set["status_norm"] == status).to_numpy()
        if sub_mask.sum() == 0:
            continue
        m = _compute_metrics(status, y_true[sub_mask], y_pred[sub_mask])
        bias_str = f"+{m.bias_pct:.2f}%" if m.bias_pct >= 0 else f"{m.bias_pct:.2f}%"
        med_str = f"+{m.median_err_pct:.2f}%" if m.median_err_pct >= 0 else f"{m.median_err_pct:.2f}%"
        p25_str = f"+{m.p25_err_pct:.2f}%" if m.p25_err_pct >= 0 else f"{m.p25_err_pct:.2f}%"
        p75_str = f"+{m.p75_err_pct:.2f}%" if m.p75_err_pct >= 0 else f"{m.p75_err_pct:.2f}%"
        print(f"{status:<14} {m.n:>5}  {m.mape_pct:>6.2f}%  {bias_str:>8}  {med_str:>8}  "
              f"{p25_str:>9}  {p75_str:>9}")


if __name__ == "__main__":
    run()
