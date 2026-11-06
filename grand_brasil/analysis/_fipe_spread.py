"""FIPE-spread analytics for the appraisal engine.

The "FIPE spread" measures how each historical sale priced relative to the
FIPE value at the time of sale:

    spread = (sale_price / fipe_at_sale_date) - 1

Aggregating these spreads with recency weighting gives an empirical estimate
of our pricing behavior vs FIPE — used to anchor the expected SELLING price
when FIPE is the primary reference.

Also exposes a `fipe_ratio()` helper used when displaying metrics.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def compute_fipe_spreads(
    channel_df: pd.DataFrame,
    fipe_client,
    brand_code: str,
    model_code: str,
    year_code: str,
    reference_date: pd.Timestamp,
    halflife_days: float,
    per_row_year: bool = False,
    aggregation: str = "mean",
) -> tuple[Optional[float], int]:
    """Recency-weighted mean (or median) spread between historical sale prices and FIPE.

    per_row_year: look up the FIPE of each comparable's OWN model year (the
    request's year_code only lends its fuel suffix). Without it, a 2022
    comparable is divided by the FIPE of the requested year, so comparables
    from adjacent years carry a spurious ±7-15 % spread.

    For each comparable sale with a valid `sale_date`, looks up the FIPE value
    that was in effect at the time of sale, then computes the spread. Spreads
    are averaged with exponential recency weighting.

    Args:
        channel_df: Comparable sales for a given channel (Loja or Revenda).
        fipe_client: FipeClient instance with `get_reference_code_for_date`
            and `get_historical_price`.
        brand_code, model_code, year_code: FIPE identifiers.
        reference_date: Anchor for recency weighting (typically "today").
        halflife_days: Half-life of the exponential decay, in days.

    Returns:
        (weighted_spread, n_comparables_with_fipe). Returns (None, 0) if the
        input frame is empty, lacks `sale_date`, or no FIPE lookups succeeded.
    """
    if len(channel_df) == 0 or "sale_date" not in channel_df.columns:
        return None, 0

    spreads = []
    weights = []
    lam = math.log(2) / max(halflife_days, 1.0)

    for _, row in channel_df.iterrows():
        sale_date = row.get("sale_date")
        if pd.isna(sale_date):
            continue

        ref_code = fipe_client.get_reference_code_for_date(sale_date)
        if ref_code is None:
            continue

        try:
            row_year_code = _year_code_for_row(year_code, row) if per_row_year else year_code
            hist_price = fipe_client.get_historical_price(
                brand_code, model_code, row_year_code, ref_code
            )
            if hist_price.value <= 0:
                continue
            spread = float(row["sale_price"]) / float(hist_price.value) - 1.0
            days = max((reference_date - pd.Timestamp(sale_date)).days, 0)
            w = math.exp(-lam * days)
            spreads.append(spread)
            weights.append(w)
        except Exception as e:
            logger.debug(f"Nao foi possivel obter FIPE historica para {sale_date}: {e}")
            continue

    if not spreads:
        return None, 0

    total_w = sum(weights)
    if aggregation == "median":
        return _weighted_median(spreads, weights if total_w > 0 else [1.0] * len(spreads)), len(spreads)
    if total_w == 0:
        return float(sum(spreads) / len(spreads)), len(spreads)

    weighted_spread = sum(s * w for s, w in zip(spreads, weights)) / total_w
    return weighted_spread, len(spreads)


def _year_code_for_row(request_year_code: str, row: pd.Series) -> str:
    """"2020-1" + comparable year 2022 -> "2022-1" (keeps the fuel suffix)."""
    row_year = row.get("year_model")
    if row_year is None or pd.isna(row_year):
        return request_year_code
    head, sep, suffix = str(request_year_code).partition("-")
    return f"{int(row_year)}{sep}{suffix}" if sep else str(int(row_year))


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return float(v)
    return float(pairs[-1][0])


def fipe_ratio(
    estimated_sale_price: Optional[Decimal],
    fipe_price: Optional[Decimal],
) -> Optional[float]:
    """Return estimated_sale_price / fipe_price, or None if either is missing."""
    if estimated_sale_price is None or fipe_price is None or fipe_price <= 0:
        return None
    return float(estimated_sale_price / fipe_price)
