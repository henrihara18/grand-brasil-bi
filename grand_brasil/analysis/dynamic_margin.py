"""Dynamic target-margin engine.

Replaces the old fixed targets (15% Loja, 5.5% Revenda) with an empirically
calibrated function of price band + per-model adjustments.

Pipeline, per appraisal:
    1. Pick the base margin for the car's price band (per channel).
    2. If the model has enough historical sales, add two adjustments:
         (a) Speed penalty  — slower models (high median days_in_stock)
                              need a bigger margin cushion.
         (b) Volatility penalty — high-variance margin models are unpredictable;
                                  pay more conservative.
    3. Cap the total adjustment to prevent extreme values.

The calibration was derived from 2,281 real sales; see the analysis notes in
the repo history for the reasoning behind each number. All thresholds live in
config.yaml → appraisal.dynamic_margin and can be re-tuned without touching
this code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class DynamicMarginResult:
    """Details of how the final target margin was derived. Useful for UI/rationale."""

    target_pct: float                      # Final margin (%) — what appraise() uses
    base_pct: float                        # Base from price band
    speed_adjustment_pp: float = 0.0       # Contribution from days-in-stock
    volatility_adjustment_pp: float = 0.0  # Contribution from margin std
    capped: bool = False                   # True if the sum hit the cap
    model_sample_size: int = 0             # How many historical rows backed the adjustments
    model_median_days: Optional[float] = None
    model_margin_std: Optional[float] = None


def compute_target_margin(
    sale_price: float,
    channel: str,
    model_red: str,
    sales_df: pd.DataFrame,
    config,
) -> DynamicMarginResult:
    """Return the target margin (%) for a given car + channel.

    Args:
        sale_price: Estimated sale price (BRL) — drives the band lookup.
        channel: "Loja" or "Revenda".
        model_red: Model key (e.g. "HYUNDAI CRETA") for per-model stats.
        sales_df: Sales history DataFrame with columns `model_red`, `sale_channel`,
            `sale_price`, `adjusted_cost`, `days_in_stock`.
        config: DynamicMarginConfig (from AppraisalConfig.dynamic_margin).

    Returns:
        DynamicMarginResult with the final margin and the components that
        produced it.
    """
    base = _base_margin_for_band(sale_price, channel, config)
    result = DynamicMarginResult(target_pct=base, base_pct=base)

    # Per-model adjustments require enough history + the right columns
    if not _model_stats_available(sales_df, config.min_model_sample):
        return result

    model_rows = _rows_for_model(sales_df, model_red, channel)
    if len(model_rows) < config.min_model_sample:
        return result

    median_days = float(model_rows["days_in_stock"].median())
    margin_std = _compute_margin_std(model_rows)

    speed_adj = _lookup_threshold(median_days, config.speed_adjustments)
    vol_adj = _lookup_threshold(margin_std, config.volatility_adjustments) if margin_std is not None else 0.0
    total_adj = speed_adj + vol_adj

    capped = False
    if total_adj > config.max_total_adjustment_pp:
        total_adj = config.max_total_adjustment_pp
        capped = True

    result.speed_adjustment_pp = speed_adj
    result.volatility_adjustment_pp = vol_adj
    result.capped = capped
    result.model_sample_size = len(model_rows)
    result.model_median_days = median_days
    result.model_margin_std = margin_std
    result.target_pct = base + total_adj

    logger.debug(
        f"Dynamic margin {model_red} {channel}: "
        f"base={base:.1f} + speed={speed_adj:.1f} + vol={vol_adj:.1f} "
        f"= {result.target_pct:.1f}% "
        f"(days_med={median_days:.0f}, std={margin_std or 0:.1f}, n={len(model_rows)})"
    )
    return result


# ── Helpers ─────────────────────────────────────────────────────────────────


def _base_margin_for_band(sale_price: float, channel: str, config) -> float:
    """Lookup the base margin for a price band.

    The bands list is evaluated in order; the first band whose max_price is
    >= sale_price wins. If none matches (shouldn't happen if the last band's
    max_price is huge), returns the last band's margin as a safe fallback.
    """
    bands = config.loja_bands if channel.lower() == "loja" else config.revenda_bands
    for band in bands:
        if sale_price <= band.max_price:
            return band.margin_pct
    return bands[-1].margin_pct if bands else 15.0


def _lookup_threshold(value: float, rules: list) -> float:
    """Return the adjustment_pp for the HIGHEST threshold that `value` exceeds.

    Rules are expected to be declared in decreasing threshold order, but we
    sort defensively so ordering bugs can't silently change behavior.
    """
    rules_sorted = sorted(rules, key=lambda r: r.threshold, reverse=True)
    for rule in rules_sorted:
        if value > rule.threshold:
            return rule.adjustment_pp
    return 0.0


def _model_stats_available(sales_df: pd.DataFrame, _min_sample: int) -> bool:
    """Cheap up-front check before filtering."""
    if sales_df is None or len(sales_df) == 0:
        return False
    required = {"model_red", "sale_channel", "sale_price", "adjusted_cost", "days_in_stock"}
    return required.issubset(sales_df.columns)


def _rows_for_model(sales_df: pd.DataFrame, model_red: str, channel: str) -> pd.DataFrame:
    """Filter to a specific model + channel, normalizing case."""
    key = model_red.strip().upper()
    mask = (
        (sales_df["model_red"].astype(str).str.upper() == key)
        & (sales_df["sale_channel"].astype(str).str.strip().str.lower() == channel.lower())
    )
    return sales_df[mask]


def _compute_margin_std(df: pd.DataFrame) -> Optional[float]:
    """Standard deviation of the real margin (%) for a subset of sales.

    Returns None if we can't compute it (empty, all-zero prices, etc.).
    """
    if len(df) < 2:
        return None
    valid = df[df["sale_price"] > 0]
    if len(valid) < 2:
        return None
    margins = (valid["sale_price"] - valid["adjusted_cost"]) / valid["sale_price"] * 100
    # Drop absurd outliers that can explode the std
    margins = margins[(margins >= -30) & (margins <= 80)]
    if len(margins) < 2:
        return None
    return float(margins.std())
