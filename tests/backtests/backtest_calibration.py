"""Backtest: measures the impact of the April-2026 calibration changes.

Calibration changes under test:
    1. Piecewise non-linear KM curve (replaces single linear factor per brand)
    2. avaliado_weight 0.40 → 0.25
    3. year_pct_per_year 10.0 → 7.5

Methodology (buy-ratio anchor — primary purchase driver):
    • Load the appraisal history (~17k rows).
    • Keep only closed deals (UTILIZADO / REPASSE) that have FIPE at time.
    • Random 80/20 split (deterministic seed): train = calibration base,
      test = held-out rows we pretend to be "new cars" coming in.
    • For each test row, call `compute_buy_ratio()` against the TRAIN set
      with OLD and NEW configs. Predicted price = ratio_median × fipe_at_time.
    • Compare predicted price vs actual appraised_value (what we really paid).

Metrics reported:
    • MAPE         — mean absolute percentage error
    • Bias         — mean signed error (positive = algo overpays)
    • Median error — median signed error (robust to tails)
    • Coverage     — % of test rows where the algo produced a prediction
                     (some rows may be too rare for tier matching)

Run with:
    py -3.12 -m tests.backtests.backtest_calibration

This is NOT a pytest test (it's slow and requires the real xlsx file).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.analysis.purchase_ratio import (
    BuyRatioResult,
    compute_buy_ratio,
    compute_year_ratio_profile,
)
from grand_brasil.config import BuyRatioConfig
from grand_brasil.ingestion.appraisal_history import (
    STATUS_WEIGHTS,
    load_appraisal_history,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(message)s")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _reweight(df: pd.DataFrame, avaliado_weight: float) -> pd.DataFrame:
    """Re-apply the status→weight mapping (used to simulate OLD vs NEW)."""
    weights = {
        "UTILIZADO": 1.0,
        "REPASSE": 1.0,
        "AVALIADO": avaliado_weight,
    }
    df = df.copy()
    df["weight"] = df["status_norm"].map(weights).fillna(0.0)
    return df


@dataclass
class BacktestMetrics:
    label: str
    n_predicted: int
    n_total: int
    mape_pct: float
    bias_pct: float
    median_err_pct: float
    rmse_brl: float

    def coverage_pct(self) -> float:
        return 100.0 * self.n_predicted / max(self.n_total, 1)


def _compute_metrics(label: str, y_true: np.ndarray, y_pred: np.ndarray, n_total: int) -> BacktestMetrics:
    mask = ~np.isnan(y_pred) & (y_true > 0)
    yt = y_true[mask]
    yp = y_pred[mask]
    errors_pct = (yp - yt) / yt * 100.0
    abs_errors_pct = np.abs(errors_pct)
    rmse = float(np.sqrt(np.mean((yp - yt) ** 2))) if len(yt) > 0 else float("nan")
    return BacktestMetrics(
        label=label,
        n_predicted=int(mask.sum()),
        n_total=n_total,
        mape_pct=float(np.mean(abs_errors_pct)) if len(yt) > 0 else float("nan"),
        bias_pct=float(np.mean(errors_pct)) if len(yt) > 0 else float("nan"),
        median_err_pct=float(np.median(errors_pct)) if len(yt) > 0 else float("nan"),
        rmse_brl=rmse,
    )


# ── Main backtest ────────────────────────────────────────────────────────────

def run_buy_ratio_backtest(
    appraisal_path: Path,
    test_fraction: float = 0.20,
    seed: int = 42,
) -> tuple[BacktestMetrics, BacktestMetrics]:
    """Backtest buy-ratio under OLD (avaliado=0.4) vs NEW (avaliado=0.25) weights.

    The year-profile is recomputed against the TRAIN set under each weighting.
    The KM curve change does NOT affect buy_ratio (the engine uses KM windows,
    not a multiplicative factor) — it is measured separately via end-to-end.
    """
    df = load_appraisal_history(appraisal_path)
    # Keep only closed deals for evaluation (we know the "truth": valor_avaliado)
    eval_pool = df[df["status_norm"].isin({"UTILIZADO", "REPASSE"})].copy()
    # Must have a valid FIPE and paid value to compute ratio & reconstruct
    eval_pool = eval_pool.dropna(subset=["fipe_value", "appraised_value", "km"])

    rng = np.random.default_rng(seed)
    n = len(eval_pool)
    n_test = int(n * test_fraction)
    test_idx = rng.choice(n, size=n_test, replace=False)
    mask_test = np.zeros(n, dtype=bool)
    mask_test[test_idx] = True

    test_set = eval_pool.iloc[mask_test].reset_index(drop=True)
    # Train = everything EXCEPT the test rows (from the full df, not just closed).
    # We leave AVALIADO rows in train because the algo uses them (with weight).
    test_plates = set(test_set["plate"].dropna().tolist())
    train_set = df[~df["plate"].isin(test_plates)].copy() if len(test_plates) > 0 else df.copy()

    print(f"\nHoldout backtest: train={len(train_set)} rows, test={len(test_set)} rows "
          f"(of which {len(test_set)} are closed deals).")
    print(f"Data source: {appraisal_path.name}\n")

    # Predict with OLD weight (0.4) and NEW weight (0.25)
    y_true = test_set["appraised_value"].to_numpy()

    preds_old = np.full(len(test_set), np.nan)
    preds_new = np.full(len(test_set), np.nan)

    train_old = _reweight(train_set, avaliado_weight=0.4)
    train_new = _reweight(train_set, avaliado_weight=0.25)

    profile_old = compute_year_ratio_profile(train_old)
    profile_new = compute_year_ratio_profile(train_new)

    cfg = BuyRatioConfig()  # tier thresholds remain as-is

    for i, row in test_set.iterrows():
        fipe_val = float(row["fipe_value"])
        km = int(row["km"]) if not pd.isna(row["km"]) else None
        year = int(row["year_model"])
        model_red = str(row["model_red"])

        res_old = compute_buy_ratio(
            model_red=model_red, year_model=year, km=km,
            appraisal_df=train_old, year_profile=profile_old, config=cfg,
        )
        if res_old.available:
            preds_old[i] = res_old.ratio_median * fipe_val

        res_new = compute_buy_ratio(
            model_red=model_red, year_model=year, km=km,
            appraisal_df=train_new, year_profile=profile_new, config=cfg,
        )
        if res_new.available:
            preds_new[i] = res_new.ratio_median * fipe_val

    m_old = _compute_metrics("OLD (avaliado_weight=0.40)", y_true, preds_old, len(test_set))
    m_new = _compute_metrics("NEW (avaliado_weight=0.25)", y_true, preds_new, len(test_set))
    return m_old, m_new


def _print_metrics_table(metrics: list[BacktestMetrics]) -> None:
    cols = ["Config", "Coverage", "MAPE", "Bias", "Median err", "RMSE"]
    widths = [40, 10, 8, 8, 11, 12]
    header = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
    print(header)
    print("-" * (sum(widths) + 2 * (len(cols) - 1)))
    for m in metrics:
        row = [
            m.label.ljust(widths[0]),
            f"{m.coverage_pct():.1f}%".ljust(widths[1]),
            f"{m.mape_pct:.2f}%".ljust(widths[2]),
            (f"+{m.bias_pct:.2f}%" if m.bias_pct >= 0 else f"{m.bias_pct:.2f}%").ljust(widths[3]),
            (f"+{m.median_err_pct:.2f}%" if m.median_err_pct >= 0 else f"{m.median_err_pct:.2f}%").ljust(widths[4]),
            f"R$ {m.rmse_brl:,.0f}".ljust(widths[5]),
        ]
        print("  ".join(row))


def main(appraisal_path: Optional[Path] = None) -> None:
    if appraisal_path is None:
        root = Path(__file__).resolve().parents[2]
        appraisal_path = root / "Avaliações 2025 e 2026.xlsx"

    if not appraisal_path.exists():
        print(f"ERRO: Arquivo nao encontrado: {appraisal_path}")
        print("Coloque o arquivo de avaliacoes no root do projeto ou passe o path.")
        return

    print("=" * 80)
    print("BACKTEST DE CALIBRAÇÃO — Grand Brasil Trade-in Engine")
    print("=" * 80)

    print("\n### Anchor: BUY-RATIO (avaliado_weight 0.40 → 0.25) ###")
    m_old, m_new = run_buy_ratio_backtest(appraisal_path)
    _print_metrics_table([m_old, m_new])

    # Quick interpretation
    improved_mape = m_new.mape_pct < m_old.mape_pct
    improved_bias = abs(m_new.bias_pct) < abs(m_old.bias_pct)
    delta_mape = m_new.mape_pct - m_old.mape_pct
    delta_bias = m_new.bias_pct - m_old.bias_pct

    print("\nResumo:")
    print(f"  • Δ MAPE  = {delta_mape:+.2f} pp  "
          f"({'MELHORIA' if improved_mape else 'PIORA'})")
    print(f"  • Δ Bias  = {delta_bias:+.2f} pp  "
          f"({'MELHORIA' if improved_bias else 'PIORA'} — bias mais proximo de 0)")

    print(
        "\nLembretes:\n"
        "  - O buy-ratio NÃO usa o km_curve (usa janelas de KM). A curva piecewise\n"
        "    afeta apenas o preço-alvo de VENDA na ancora secundaria.\n"
        "  - O year_pct_per_year (10→7.5) afeta o caminho FIPE de fallback. Um\n"
        "    backtest end-to-end (usando appraise() completo) mediria isso, mas\n"
        "    exige sales_df calibrado ao FIPE histórico — deixado como próximo passo.\n"
    )


if __name__ == "__main__":
    main()
