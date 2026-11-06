"""Market anchor (M): what the market pays for this car, read from OUR OWN SALES.

    ratio_i = sale_price_i / FIPE_i(at the sale month)        one per past sale
    ratio   = similarity- and recency-weighted median of ratio_i, after moving each
              comparable to the requested KM and age with slopes fitted on the sales
    est_sale = FIPE_today × ratio

The anchor only looks at sales (never at what we paid), so it does not feed on the
engine's own suggestions once the engine is in production. It replaces the legacy
"FIPE spread" anchor (B), which averaged the same ratio over a loose year window
without KM or age adjustment.

`prepare_sales_ratios` enriches the sales frame once (dashboard: on load; backtest:
per run) with the FIPE of the sale month taken from an offline table built from the
appraisal base (`backtest.fipe_table.FipeTable`), falling back to the FIPE column the
ERP writes on the sale when the table has no value for that model/year/month.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RATIO_COL = "ratio_fipe"
FIPE_SALE_COL = "fipe_sale"


@dataclass
class MarketAnchorResult:
    ratio: float                 # est_sale / FIPE_today
    estimated_sale: Decimal
    n: int                       # comparables used
    n_eff: float                 # effective sample size after similarity weights
    tier: str                    # "kernel" | "brand_age"
    km_slope: float              # ratio change per 10k km (<= 0)
    age_slope: float             # ratio change per year of age (<= 0)
    km_adjustment: float         # ratio points moved by the KM/age adjustment (median)


def prepare_sales_ratios(
    sales_df: pd.DataFrame,
    fipe_table,
    erp_fipe_fallback: bool = True,
    ratio_min: float = 0.4,
    ratio_max: float = 1.4,
) -> pd.DataFrame:
    """Return a copy of `sales_df` with `fipe_sale`, `ratio_fipe`, `age_at_sale`.

    Rows without a usable FIPE, or with an implausible ratio, get NaN and are
    ignored by the anchor. `fipe_table` must expose `lookup(model_red, year_model,
    month: pd.Period) -> Optional[float]`.
    """
    df = sales_df.copy()
    if "sale_date" not in df.columns or "sale_price" not in df.columns:
        df[FIPE_SALE_COL] = np.nan
        df[RATIO_COL] = np.nan
        return df
    months = pd.to_datetime(df["sale_date"], errors="coerce").dt.to_period("M")
    fipe = []
    for model, year, month in zip(df["model_red"], df["year_model"], months):
        if pd.isna(year) or pd.isna(month) or fipe_table is None:
            fipe.append(np.nan)
            continue
        try:
            v = fipe_table.lookup(str(model), int(year), month)
        except Exception:  # defensive: table variants
            v = None
        fipe.append(float(v) if v else np.nan)
    df[FIPE_SALE_COL] = fipe
    if erp_fipe_fallback and "FIPE" in df.columns:
        erp = pd.to_numeric(df["FIPE"], errors="coerce").where(lambda s: s > 1000)
        df[FIPE_SALE_COL] = df[FIPE_SALE_COL].where(df[FIPE_SALE_COL].notna(), erp)
    ratio = pd.to_numeric(df["sale_price"], errors="coerce") / df[FIPE_SALE_COL]
    df[RATIO_COL] = ratio.where(ratio.between(ratio_min, ratio_max))
    df["age_at_sale"] = pd.to_datetime(df["sale_date"], errors="coerce").dt.year - pd.to_numeric(df["year_model"], errors="coerce")
    n_ok = int(df[RATIO_COL].notna().sum())
    logger.info(f"Market anchor: {n_ok} of {len(df)} sales with a usable sale/FIPE ratio")
    return df


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    c = np.cumsum(w)
    return float(v[min(int(np.searchsorted(c, c[-1] / 2.0)), len(v) - 1)])


def fit_slopes(pool: pd.DataFrame) -> tuple[float, float]:
    """(km_slope per 10k km, age_slope per year) of the sale/FIPE ratio, fitted
    inside model groups (demeaned) so that model mix does not leak into the slope.
    Clipped to plausible, non-positive ranges; defaults when the pool is thin."""
    km_slope, age_slope = -0.012, -0.02
    p = pool[pool[RATIO_COL].notna() & pool["km"].notna()]
    if len(p) >= 100:
        g = p.groupby(["model_red", "year_model"])
        size = g[RATIO_COL].transform("size")
        d = p[size >= 3]
        if len(d) >= 50:
            r = d[RATIO_COL] - d.groupby(["model_red", "year_model"])[RATIO_COL].transform("mean")
            k = (d["km"] - d.groupby(["model_red", "year_model"])["km"].transform("mean")) / 1e4
            km_slope = float(np.clip(np.polyfit(k, r, 1)[0], -0.03, 0.0))
        ga = p.groupby("model_red")
        d = p[ga[RATIO_COL].transform("size") >= 5]
        if len(d) >= 100:
            r = d[RATIO_COL] - d.groupby("model_red")[RATIO_COL].transform("mean")
            a = d["age_at_sale"] - d.groupby("model_red")["age_at_sale"].transform("mean")
            age_slope = float(np.clip(np.polyfit(a, r, 1)[0], -0.05, 0.0))
    return km_slope, age_slope


_SLOPE_CACHE: dict[tuple, tuple[float, float]] = {}


def _cached_slopes(pool: pd.DataFrame, channel: str) -> tuple[float, float]:
    """Slopes depend only on the sales pool, which changes once per data load (dashboard)
    or once per month cutoff (backtest); fitting them per appraisal is pure waste."""
    try:
        key = (len(pool), str(pool["sale_date"].max()), float(pool[RATIO_COL].sum()), channel)
    except Exception:
        return fit_slopes(pool)
    hit = _SLOPE_CACHE.get(key)
    if hit is None:
        hit = fit_slopes(pool)
        if len(_SLOPE_CACHE) > 64:
            _SLOPE_CACHE.clear()
        _SLOPE_CACHE[key] = hit
    return hit


def compute_market_anchor(
    model_red: str,
    brand: str,
    year_model: int,
    km: Optional[int],
    fipe_price: Decimal,
    sales_df: pd.DataFrame,
    reference_date: pd.Timestamp,
    cfg,
    channel: str = "Loja",
    slopes: Optional[tuple[float, float]] = None,
) -> Optional[MarketAnchorResult]:
    """Market anchor for one car. Returns None when the sales frame has no ratios
    or no comparable sale exists (model within `year_window` years, else brand × age)."""
    if sales_df is None or RATIO_COL not in sales_df.columns or fipe_price is None or fipe_price <= 0:
        return None
    pool = sales_df[sales_df[RATIO_COL].notna() & sales_df["km"].notna()]
    if "sale_channel" in pool.columns and channel:
        pool = pool[pool["sale_channel"].astype(str).str.lower() == channel.lower()]
    if len(pool) == 0:
        return None
    km_slope, age_slope = slopes if slopes is not None else _cached_slopes(pool, channel)
    km_req = float(km) if km is not None else float(pool["km"].median())
    age_req = float(reference_date.year - int(year_model))
    lam = math.log(2) / max(float(cfg.halflife_days), 1.0)

    same = pool[pool["model_red"].astype(str).str.upper() == str(model_red).upper()]
    same = same[(same["year_model"] - year_model).abs() <= cfg.year_window]
    tier = None
    if len(same) >= cfg.min_comparables:
        days = (reference_date - pd.to_datetime(same["sale_date"])).dt.days.clip(lower=0).to_numpy(dtype=float)
        w = np.exp(-lam * days)
        w *= np.exp(-np.abs(same["year_model"].to_numpy(dtype=float) - year_model) / max(cfg.year_scale, 1e-6))
        w *= np.exp(-np.abs(same["km"].to_numpy(dtype=float) - km_req) / max(cfg.km_scale, 1.0))
        n_eff = float(w.sum() / w.max()) if w.max() > 0 else 0.0
        if n_eff >= cfg.min_effective_comparables:
            adj = (same[RATIO_COL].to_numpy(dtype=float)
                   + km_slope * (km_req - same["km"].to_numpy(dtype=float)) / 1e4
                   + age_slope * (age_req - same["age_at_sale"].to_numpy(dtype=float)))
            ratio = _weighted_median(adj, w)
            shift = ratio - _weighted_median(same[RATIO_COL].to_numpy(dtype=float), w)
            tier, n, used = "kernel", len(same), (ratio, n_eff, shift)
    if tier is None:
        fb = pool[(pool["brand"].astype(str).str.upper() == str(brand).upper()) & (pool["age_at_sale"] == age_req)]
        if len(fb) < cfg.fallback_min_comparables:
            return None
        days = (reference_date - pd.to_datetime(fb["sale_date"])).dt.days.clip(lower=0).to_numpy(dtype=float)
        w = np.exp(-lam * days)
        base = _weighted_median(fb[RATIO_COL].to_numpy(dtype=float), w)
        shift = km_slope * (km_req - _weighted_median(fb["km"].to_numpy(dtype=float), w)) / 1e4
        ratio = base + shift
        tier, n, used = "brand_age", len(fb), (ratio, float(w.sum() / w.max()), shift)
    ratio, n_eff, shift = used
    ratio = float(np.clip(ratio, cfg.ratio_min, cfg.ratio_max))
    est = Decimal(str(round(float(fipe_price) * ratio, 2)))
    return MarketAnchorResult(ratio=ratio, estimated_sale=est, n=int(n), n_eff=round(n_eff, 1), tier=tier,
                              km_slope=km_slope, age_slope=age_slope, km_adjustment=round(float(shift), 4))
