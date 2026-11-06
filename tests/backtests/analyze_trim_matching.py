"""Trim / version matching diagnostic.

The appraisal engine tries to match comparables at the `model_trim` level
first (e.g. "HONDA HR-V EXL"), falling back to `model_red` (e.g. "HONDA HR-V")
when trim extraction fails or cannot be verified. Trim mismatches can cause
significant price errors because within the same model family, trim levels
often differ by R$ 20k-40k.

This script answers:
    1. TRIM COVERAGE — What % of sales/appraisals have trim data extracted?
    2. TRIM-PRICE SPREAD — Within a model_red, how much does median price
       vary across trim levels? (This is the "cost" of getting it wrong.)
    3. FALLBACK RATE — How often does the engine fall back to model_red
       matching because trim info is unavailable?
    4. TOP OFFENDERS — Which models have (a) largest trim price gaps AND
       (b) high fallback rates? These are the highest-ROI fixes.

Run:
    py -3.12 -m tests.backtests.analyze_trim_matching
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.ingestion.sales_history import load_sales_history


MIN_ROWS_FOR_ANALYSIS = 6      # Skip model_reds with fewer rows (too noisy)
MIN_TRIM_ROWS = 3              # A trim-level group needs at least this many sales


def _load_sales() -> pd.DataFrame:
    for fname in ("Relatorio vendas 20255 processado.xlsx",
                  "Relatorio vendas 2025 processado.xlsx"):
        p = Path(fname)
        if p.exists():
            return load_sales_history(p)
    raise FileNotFoundError("Sales file not found in project root")


def trim_coverage(df: pd.DataFrame) -> dict:
    """How many rows have real trim info vs model_trim == model_red?"""
    total = len(df)
    has_trim = (df["model_trim"].str.upper() != df["model_red"].str.upper()).sum()
    return {
        "total_rows": total,
        "with_trim_data": int(has_trim),
        "without_trim_data": int(total - has_trim),
        "coverage_pct": 100.0 * has_trim / max(total, 1),
    }


def fallback_rate_by_model(df: pd.DataFrame) -> pd.DataFrame:
    """Per model_red, fraction of rows where model_trim == model_red (= no trim)."""
    rows = []
    for model, sub in df.groupby("model_red"):
        if len(sub) < MIN_ROWS_FOR_ANALYSIS:
            continue
        no_trim = (sub["model_trim"].str.upper() == model.upper()).sum()
        rows.append({
            "model_red": model,
            "n_rows": len(sub),
            "no_trim_rows": int(no_trim),
            "fallback_pct": 100.0 * no_trim / len(sub),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("fallback_pct", ascending=False)


def trim_price_spread(df: pd.DataFrame) -> pd.DataFrame:
    """For each model_red, measure price spread ACROSS its trims.

    Returns DataFrame with:
        model_red, n_trims, n_rows, median_low, median_high,
        spread_pct   : (median_high - median_low) / median_low * 100
        spread_brl   : median_high - median_low
        top_trim     : highest-priced trim
        bot_trim     : lowest-priced trim
    """
    rows = []
    for model, sub in df.groupby("model_red"):
        if len(sub) < MIN_ROWS_FOR_ANALYSIS:
            continue
        # Group by trim, require at least MIN_TRIM_ROWS for a trim's median to be meaningful
        trim_medians = (
            sub.groupby("model_trim")["sale_price"]
            .agg(["median", "size"])
            .query(f"size >= {MIN_TRIM_ROWS}")
        )
        if len(trim_medians) < 2:
            # Only one trim-group with enough data → no spread to report
            continue
        low_med = float(trim_medians["median"].min())
        high_med = float(trim_medians["median"].max())
        if low_med <= 0:
            continue
        bot_trim = trim_medians["median"].idxmin()
        top_trim = trim_medians["median"].idxmax()
        rows.append({
            "model_red": model,
            "n_trims": len(trim_medians),
            "n_rows": len(sub),
            "median_low": low_med,
            "median_high": high_med,
            "spread_brl": high_med - low_med,
            "spread_pct": 100.0 * (high_med - low_med) / low_med,
            "bot_trim": bot_trim,
            "top_trim": top_trim,
        })
    return pd.DataFrame(rows).sort_values("spread_pct", ascending=False)


def mismatch_error_simulation(df: pd.DataFrame) -> dict:
    """Simulate: if we ignored trim (used model_red median only) for every sale,
    what would the average prediction error be?

    For each row where we DO have trim data: compute
        err = (overall_model_median - actual_sale_price) / actual_sale_price
    and aggregate.
    """
    errors_pct = []
    errors_brl = []
    for model, sub in df.groupby("model_red"):
        if len(sub) < MIN_ROWS_FOR_ANALYSIS:
            continue
        has_trim_mask = (sub["model_trim"].str.upper() != model.upper())
        if has_trim_mask.sum() < MIN_TRIM_ROWS:
            continue
        model_median = float(sub["sale_price"].median())
        for _, row in sub[has_trim_mask].iterrows():
            actual = float(row["sale_price"])
            if actual <= 0:
                continue
            errors_pct.append((model_median - actual) / actual * 100.0)
            errors_brl.append(model_median - actual)

    if not errors_pct:
        return {}
    arr_pct = np.array(errors_pct)
    arr_brl = np.array(errors_brl)
    return {
        "n": len(errors_pct),
        "mape_pct": float(np.mean(np.abs(arr_pct))),
        "bias_pct": float(np.mean(arr_pct)),
        "median_abs_pct": float(np.median(np.abs(arr_pct))),
        "p90_abs_pct": float(np.percentile(np.abs(arr_pct), 90)),
        "mae_brl": float(np.mean(np.abs(arr_brl))),
    }


def high_risk_models(fallback_df: pd.DataFrame, spread_df: pd.DataFrame) -> pd.DataFrame:
    """Merge fallback_rate × spread to find the highest-ROI targets for fixes.

    A model is HIGH RISK if:
        • fallback_pct is large (many rows will be model_red-matched) AND
        • spread_pct is large (model_red matching will hurt a lot when wrong)
    """
    merged = fallback_df.merge(spread_df, on="model_red", how="inner", suffixes=("", "_sp"))
    if merged.empty:
        return merged
    # Risk score = fallback_pct × spread_pct / 100  (both in %, yields same unit)
    merged["risk_score"] = merged["fallback_pct"] * merged["spread_pct"] / 100.0
    return merged.sort_values("risk_score", ascending=False)


def main() -> None:
    print("=" * 80)
    print("DIAGNÓSTICO DE TRIM MATCHING")
    print("=" * 80)

    print("\nCarregando vendas...")
    df = _load_sales()
    print(f"  {len(df):,} vendas carregadas")

    # ── 1. Coverage ───────────────────────────────────────────────────────
    cov = trim_coverage(df)
    print("\n## 1. COBERTURA DE TRIM")
    print(f"  Total de vendas ........ {cov['total_rows']:,}")
    print(f"  Com trim extraído ...... {cov['with_trim_data']:,} ({cov['coverage_pct']:.1f}%)")
    print(f"  Sem trim (fallback) .... {cov['without_trim_data']:,} ({100-cov['coverage_pct']:.1f}%)")

    # ── 2. Fallback rate por modelo ──────────────────────────────────────
    fb = fallback_rate_by_model(df)
    print("\n## 2. TOP 15 MODELOS COM MAIOR % DE FALLBACK (trim extraction falha)")
    print(f"{'model_red':<35} {'n_rows':>7} {'no_trim':>8} {'fallback%':>10}")
    print("-" * 65)
    for _, r in fb.head(15).iterrows():
        print(f"{r['model_red']:<35} {r['n_rows']:>7} {r['no_trim_rows']:>8} {r['fallback_pct']:>9.1f}%")

    # ── 3. Trim price spread ──────────────────────────────────────────────
    sp = trim_price_spread(df)
    print("\n## 3. TOP 15 MODELOS COM MAIOR SPREAD DE PREÇO ENTRE TRIMS")
    print(f"{'model_red':<35} {'trims':>5} {'low→high (R$)':>24} {'spread%':>8}")
    print("-" * 80)
    for _, r in sp.head(15).iterrows():
        price_str = f"{r['median_low']:>8,.0f} → {r['median_high']:,.0f}"
        print(f"{r['model_red']:<35} {int(r['n_trims']):>5} {price_str:>24} {r['spread_pct']:>7.1f}%")
        print(f"  └─ barato: {r['bot_trim']}  |  caro: {r['top_trim']}")

    # ── 4. Simulated mismatch error ──────────────────────────────────────
    err = mismatch_error_simulation(df)
    print("\n## 4. CUSTO SIMULADO DE IGNORAR TRIM (usar só median do model_red)")
    if err:
        print(f"  n vendas c/ trim ....... {err['n']:,}")
        print(f"  MAPE (erro médio) ...... {err['mape_pct']:.2f}%")
        print(f"  Viés ................... {err['bias_pct']:+.2f}%")
        print(f"  Mediana |erro| ......... {err['median_abs_pct']:.2f}%")
        print(f"  P90 |erro| ............. {err['p90_abs_pct']:.2f}%")
        print(f"  MAE em R$ .............. R$ {err['mae_brl']:,.0f}")
    else:
        print("  (sem dados suficientes)")

    # ── 5. High-risk models (fallback × spread) ──────────────────────────
    hr = high_risk_models(fb, sp)
    print("\n## 5. TOP 15 MODELOS DE MAIOR RISCO (fallback% × spread% / 100)")
    print("(onde corrigir o trim matching teria maior impacto prático)")
    print(f"{'model_red':<35} {'fallback%':>9} {'spread%':>8} {'risk_score':>11} {'n_rows':>7}")
    print("-" * 75)
    for _, r in hr.head(15).iterrows():
        print(f"{r['model_red']:<35} {r['fallback_pct']:>8.1f}% "
              f"{r['spread_pct']:>7.1f}% {r['risk_score']:>11.2f} {int(r['n_rows']):>7}")

    # ── 6. Summary ────────────────────────────────────────────────────────
    total_models = df["model_red"].nunique()
    covered_models = len(fb[fb["fallback_pct"] < 50])
    heavy_fallback = len(fb[fb["fallback_pct"] > 50])
    print("\n## RESUMO")
    print(f"  Total model_reds em vendas ......... {total_models}")
    print(f"  Modelos analisáveis (>={MIN_ROWS_FOR_ANALYSIS} rows) . {len(fb)}")
    print(f"  Com fallback > 50% (trim ruim) ..... {heavy_fallback}")
    print(f"  Com fallback < 50% (OK) ............ {covered_models}")
    if err:
        print(f"\n  → Ignorar trim adiciona ~{err['mape_pct']:.1f}% de MAPE.")
        print(f"    Backtest atual: 6.5%. Com trim pior: ~{6.5 + err['mape_pct'] * (100-cov['coverage_pct'])/100:.1f}%")


if __name__ == "__main__":
    main()
