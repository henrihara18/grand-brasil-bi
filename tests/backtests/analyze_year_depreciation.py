"""Empirical calibration of annual depreciation curve.

Context:
    The appraisal engine uses `year_pct_per_year` (currently 7.5%) as a
    LINEAR year-adjustment factor: when a comparable sale is N years away
    from the target year, we multiply its price by (1 + 7.5% * N).

    This script explores whether the real depreciation curve is linear
    or if a piecewise non-linear curve (steep for new cars, flat for
    older cars) would better match the data.

Method:
    Uses the appraisal history (~17k rows) because it carries FIPE at
    the time of appraisal for each record. FIPE is a clean proxy for
    the market price of a car of that (brand, model, year) at that moment
    and already encodes Brazilian-market depreciation patterns.

    For each (brand, model_red) we:
        1. Compute the median FIPE per year_model (controlling for KM
           at the group level is not needed because FIPE itself normalizes
           KM — it's a catalog price, not a transaction price).
        2. Normalize: fipe_ratio_per_age = median_fipe_age_N / median_fipe_age_0
           where age_0 is the youngest observed age (usually 0 or 1 year).
        3. Aggregate across models: weighted median of fipe_ratio at each age.

    Also cross-validates using sales_history: for (brand, model_red) with
    sufficient volume we compute the actual sale_price trajectory by age
    and the implied annual depreciation.

Output:
    Table of median depreciation % per age-year (age 0→1, 1→2, ..., 8→9),
    plus a fitted piecewise recommendation for `year_pct_per_year`.

Run:
    py -3.12 -m tests.backtests.analyze_year_depreciation

Not a pytest test (slow, I/O-heavy, investigative).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.ingestion.appraisal_history import load_appraisal_history
from grand_brasil.ingestion.sales_history import load_sales_history


# ── Config ──────────────────────────────────────────────────────────────────
MIN_MODEL_ROWS_PER_AGE = 5     # Skip (model, age) groups smaller than this
MIN_AGES_PER_MODEL = 3         # A model must have >=3 ages to contribute
MAX_AGE = 10                   # Cap for charting
CURRENT_LINEAR_RATE = 0.075    # What we use today (year_pct_per_year)


def _load_appraisals() -> pd.DataFrame:
    """Load appraisal history with age column added."""
    path = Path("Avaliações 2025 e 2026.xlsx")
    df = load_appraisal_history(path, include_avaliado=True)

    # Age = appraisal_date.year - year_model (handle NaT dates)
    df["appraisal_year"] = df["appraisal_date"].dt.year
    # Fall back to 2025 (earliest year in the export) if date missing
    df["appraisal_year"] = df["appraisal_year"].fillna(2025).astype(int)
    df["year_model"] = pd.to_numeric(df["year_model"], errors="coerce")
    df = df.dropna(subset=["year_model"]).copy()
    df["year_model"] = df["year_model"].astype(int)
    df["age"] = df["appraisal_year"] - df["year_model"]

    # Clip absurd ages (data errors): negative or > 25 years
    df = df[(df["age"] >= 0) & (df["age"] <= 25)].copy()
    return df


def _load_sales() -> pd.DataFrame:
    """Load sales history with age column added."""
    # Try common file names
    for fname in ("Relatorio vendas 20255 processado.xlsx",
                  "Relatorio vendas 2025 processado.xlsx"):
        p = Path(fname)
        if p.exists():
            df = load_sales_history(p)
            break
    else:
        raise FileNotFoundError("Sales file not found")

    df["sale_year"] = pd.to_datetime(df["sale_date"], errors="coerce").dt.year
    df["sale_year"] = df["sale_year"].fillna(2025).astype(int)
    df["year_model"] = pd.to_numeric(df["year_model"], errors="coerce")
    df = df.dropna(subset=["year_model", "sale_price"]).copy()
    df["year_model"] = df["year_model"].astype(int)
    df["age"] = df["sale_year"] - df["year_model"]
    df = df[(df["age"] >= 0) & (df["age"] <= 25)].copy()
    return df


def depreciation_curve_from_fipe(df: pd.DataFrame) -> pd.DataFrame:
    """Compute median fipe-ratio per age, normalized per-model to age 0.

    Returns DataFrame indexed by age with columns:
        n_models      : how many models contributed
        ratio_median  : median(fipe_age_N / fipe_age_0) across models
        ratio_p25     : P25
        ratio_p75     : P75
    """
    # Per (model_red, age): median FIPE
    grp = (
        df.groupby(["model_red", "age"])["fipe_value"]
        .agg(["median", "size"])
        .rename(columns={"median": "fipe_median", "size": "n"})
        .reset_index()
    )
    grp = grp[grp["n"] >= MIN_MODEL_ROWS_PER_AGE].copy()

    # For each model, compute ratio to its youngest observed age
    rows = []
    for model, sub in grp.groupby("model_red"):
        if sub["age"].nunique() < MIN_AGES_PER_MODEL:
            continue
        sub = sub.sort_values("age")
        base_age = int(sub["age"].iloc[0])
        base_fipe = float(sub["fipe_median"].iloc[0])
        if base_fipe <= 0:
            continue
        for _, r in sub.iterrows():
            rows.append({
                "model_red": model,
                "base_age": base_age,
                "age": int(r["age"]),
                "age_from_base": int(r["age"]) - base_age,
                "ratio": float(r["fipe_median"]) / base_fipe,
                "n": int(r["n"]),
            })

    ratios = pd.DataFrame(rows)
    if ratios.empty:
        return pd.DataFrame()

    # Aggregate by age_from_base (how many years older than model's youngest)
    out = (
        ratios.groupby("age_from_base")["ratio"]
        .agg(["median", lambda s: s.quantile(0.25), lambda s: s.quantile(0.75), "size"])
        .rename(columns={
            "median": "ratio_median",
            "<lambda_0>": "ratio_p25",
            "<lambda_1>": "ratio_p75",
            "size": "n_models",
        })
        .reset_index()
    )
    return out


def depreciation_curve_from_sales(df: pd.DataFrame) -> pd.DataFrame:
    """Same method, but using real sale_price instead of FIPE. More noisy."""
    grp = (
        df.groupby(["model_red", "age"])["sale_price"]
        .agg(["median", "size"])
        .rename(columns={"median": "price_median", "size": "n"})
        .reset_index()
    )
    grp = grp[grp["n"] >= MIN_MODEL_ROWS_PER_AGE].copy()

    rows = []
    for model, sub in grp.groupby("model_red"):
        if sub["age"].nunique() < MIN_AGES_PER_MODEL:
            continue
        sub = sub.sort_values("age")
        base_age = int(sub["age"].iloc[0])
        base_price = float(sub["price_median"].iloc[0])
        if base_price <= 0:
            continue
        for _, r in sub.iterrows():
            rows.append({
                "model_red": model,
                "age_from_base": int(r["age"]) - base_age,
                "ratio": float(r["price_median"]) / base_price,
                "n": int(r["n"]),
            })

    ratios = pd.DataFrame(rows)
    if ratios.empty:
        return pd.DataFrame()

    out = (
        ratios.groupby("age_from_base")["ratio"]
        .agg(["median", lambda s: s.quantile(0.25), lambda s: s.quantile(0.75), "size"])
        .rename(columns={
            "median": "ratio_median",
            "<lambda_0>": "ratio_p25",
            "<lambda_1>": "ratio_p75",
            "size": "n_models",
        })
        .reset_index()
    )
    return out


def marginal_depreciation(curve: pd.DataFrame) -> pd.DataFrame:
    """Compute the marginal YoY depreciation from a cumulative ratio curve.

    If curve has ratio_median at age 0 = 1.00 and age 1 = 0.88, the
    marginal depreciation between age 0 and 1 is 12%.
    """
    c = curve.sort_values("age_from_base").reset_index(drop=True)
    rows = []
    for i in range(1, len(c)):
        prev = c.iloc[i - 1]
        cur = c.iloc[i]
        if prev["ratio_median"] <= 0:
            continue
        # Marginal = (prev - cur) / prev — i.e. % drop going from prev age to cur age
        pct_drop = 100.0 * (float(prev["ratio_median"]) - float(cur["ratio_median"])) / float(prev["ratio_median"])
        rows.append({
            "age_transition": f"{int(prev['age_from_base'])}→{int(cur['age_from_base'])}",
            "ratio_prev": float(prev["ratio_median"]),
            "ratio_curr": float(cur["ratio_median"]),
            "marginal_pct": pct_drop,
            "n_models_prev": int(prev["n_models"]),
            "n_models_curr": int(cur["n_models"]),
        })
    return pd.DataFrame(rows)


def recommend_piecewise(marginal_df: pd.DataFrame) -> list[dict]:
    """Suggest piecewise segments based on marginal curve shape.

    Looks for natural break points: clusters of ages with similar marginal rates.
    Returns list of {age_range: str, rate_pct: float, n_transitions: int}.
    """
    if marginal_df.empty:
        return []

    # Simple rule: bucket into early (ages 0-2), middle (3-5), late (6+)
    early = marginal_df[marginal_df["age_transition"].str.startswith(("0", "1"))]
    middle = marginal_df[marginal_df["age_transition"].str.startswith(("2", "3", "4"))]
    late = marginal_df[marginal_df["age_transition"].str.startswith(("5", "6", "7", "8", "9"))]

    buckets = []
    if not early.empty:
        buckets.append({
            "age_range": "0→2 (novo)",
            "rate_pct": float(early["marginal_pct"].median()),
            "n_transitions": len(early),
        })
    if not middle.empty:
        buckets.append({
            "age_range": "2→5 (meia-idade)",
            "rate_pct": float(middle["marginal_pct"].median()),
            "n_transitions": len(middle),
        })
    if not late.empty:
        buckets.append({
            "age_range": "5+ (velho)",
            "rate_pct": float(late["marginal_pct"].median()),
            "n_transitions": len(late),
        })
    return buckets


def _print_curve(label: str, curve: pd.DataFrame) -> None:
    print(f"\n=== {label}: Cumulative depreciation ratio (normalized to model's youngest age) ===")
    if curve.empty:
        print("  (no data)")
        return
    print(f"{'age_delta':>10}  {'ratio_median':>13}  {'ratio_p25':>10}  {'ratio_p75':>10}  {'n_models':>9}")
    for _, r in curve.iterrows():
        print(f"{int(r['age_from_base']):>10}  {r['ratio_median']:>13.3f}  "
              f"{r['ratio_p25']:>10.3f}  {r['ratio_p75']:>10.3f}  {int(r['n_models']):>9}")


def _print_marginal(label: str, marg: pd.DataFrame) -> None:
    print(f"\n=== {label}: Marginal depreciation per age transition ===")
    if marg.empty:
        print("  (no data)")
        return
    print(f"{'transition':>11}  {'marginal %':>11}  {'n_models':>9}")
    for _, r in marg.iterrows():
        print(f"{r['age_transition']:>11}  {r['marginal_pct']:>10.2f}%  {int(r['n_models_curr']):>9}")


def _print_recommendation(buckets: list[dict], source: str) -> None:
    print(f"\n=== Recommendation (source: {source}) ===")
    if not buckets:
        print("  (no data)")
        return
    print(f"  Current config: year_pct_per_year = {CURRENT_LINEAR_RATE*100:.1f}% (LINEAR)")
    print(f"  Suggested piecewise bands:")
    for b in buckets:
        print(f"    {b['age_range']:>25}: {b['rate_pct']:>5.2f}%/ano  (n={b['n_transitions']} transitions)")


def main() -> None:
    print("Loading appraisal history...")
    appr = _load_appraisals()
    print(f"  {len(appr):,} appraisal rows with age")

    print("\nLoading sales history...")
    sales = _load_sales()
    print(f"  {len(sales):,} sales rows with age")

    # ── FIPE-based curve (catalog price, ~clean signal) ─────────────────
    print("\nBuilding FIPE depreciation curve...")
    fipe_curve = depreciation_curve_from_fipe(appr)
    _print_curve("FIPE (from appraisal history)", fipe_curve.head(MAX_AGE + 1))
    fipe_marg = marginal_depreciation(fipe_curve.head(MAX_AGE + 1))
    _print_marginal("FIPE", fipe_marg)

    # ── Sales-based curve (actual transactions, noisier but real) ──────
    print("\nBuilding sales depreciation curve...")
    sales_curve = depreciation_curve_from_sales(sales)
    _print_curve("SALES (from sale_price)", sales_curve.head(MAX_AGE + 1))
    sales_marg = marginal_depreciation(sales_curve.head(MAX_AGE + 1))
    _print_marginal("SALES", sales_marg)

    # ── Recommendations ───────────────────────────────────────────────
    fipe_buckets = recommend_piecewise(fipe_marg)
    sales_buckets = recommend_piecewise(sales_marg)
    _print_recommendation(fipe_buckets, "FIPE")
    _print_recommendation(sales_buckets, "SALES")

    # Compare vs current linear rate
    if not fipe_marg.empty:
        overall_median = float(fipe_marg["marginal_pct"].median())
        overall_mean = float(fipe_marg["marginal_pct"].mean())
        print(f"\n=== Overall comparison ===")
        print(f"  Current linear rate   : {CURRENT_LINEAR_RATE*100:.2f}% /ano")
        print(f"  FIPE median marginal  : {overall_median:.2f}% /ano")
        print(f"  FIPE mean marginal    : {overall_mean:.2f}% /ano")
        spread = max([b["rate_pct"] for b in fipe_buckets]) - min([b["rate_pct"] for b in fipe_buckets]) if fipe_buckets else 0.0
        print(f"  Early→late spread     : {spread:.2f} pp")
        print(f"  → Piecewise gain if spread > 2pp; otherwise linear is fine")


if __name__ == "__main__":
    main()
