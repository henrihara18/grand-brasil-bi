"""Blindado (armored vehicle) helpers.

Two concerns live here:
  1. FILTERING blindados OUT of the comparable sales used for median estimation
     (`_blindado_filter_premium` + `remove_blindados`) — so that a handful of armored
     cars sold at extreme prices don't inflate the anchor.
  2. APPLYING a sale-price premium when the vehicle BEING appraised is armored
     (`_blindado_sale_premium`) — reflecting the extra value blindagem adds.

Both behave independently and both read their thresholds from config when
available; module-level defaults exist for tests/scripts.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Sale-price premium (applied to armored cars being appraised) ────────────

# Default table — used when no BlindadoConfig is injected.
# Production flows through config.yaml → AppraisalConfig.blindado.premium_by_year.
_DEFAULT_BLINDADO_SALE_PREMIUM: dict[int, int] = {
    2026: 25_000,
    2025: 25_000,
    2024: 25_000,
    2023: 20_000,
    2022: 20_000,
    2021: 20_000,
    2020: 15_000,
    2019: 15_000,
    2018: 15_000,
    2017: 10_000,
    2016: 15_000,
    2015: 20_000,
    2014: 10_000,
}


def blindado_sale_premium(
    year_model: int,
    premium_table: Optional[dict[int, int]] = None,
) -> Decimal:
    """Return the armored-car premium for the estimated SALE price.

    Args:
        year_model: Vehicle model year.
        premium_table: Custom {year: premium_in_BRL}. When None, the default
            table is used (same values as config.yaml defaults).

    Returns:
        Decimal premium. Years not in the table return Decimal("0").
    """
    table = premium_table if premium_table is not None else _DEFAULT_BLINDADO_SALE_PREMIUM
    return Decimal(str(table.get(year_model, 0)))


# ── Filter: remove blindados from a comparable-sales DataFrame ──────────────

def _blindado_filter_premium(year_model: int) -> Optional[float]:
    """Return the year-band threshold used to DETECT blindados in sales data.

    Distinct from `blindado_sale_premium`: this is a *detection* threshold used
    to flag outlier sales that probably belonged to armored cars. A sale is
    flagged blindado if its price exceeds (anchor + this premium).

    Returns None for 2019 or older — detection is disabled in that range
    because armored older cars are rare and the band would miss too much.

    Year bands and thresholds (midpoint of the domain-knowledge ranges):
        2024+         -> R$ 45.000  (range: 40k-50k)
        2022-2023     -> R$ 35.000  (range: 30k-40k)
        2020-2021     -> R$ 22.500  (range: 15k-30k)
        2019 or older -> None       (no filtering)
    """
    if year_model >= 2024:
        return 45_000.0
    if year_model >= 2022:
        return 35_000.0
    if year_model >= 2020:
        return 22_500.0
    return None


def remove_blindados(df: pd.DataFrame, year_model: int) -> pd.DataFrame:
    """Remove likely-blindado rows from a comparable-sales DataFrame.

    Strategy:
        anchor = median of the bottom 75% of `sale_price` (immune to blindado
                 inflation even when multiple armored cars are in the sample)
        fence  = anchor + `_blindado_filter_premium(year_model)`
        Keep rows where sale_price <= fence.

    For 2019 or older, no filtering is applied (helper returns None).

    Args:
        df: DataFrame of comparable sales. Must contain `sale_price`.
        year_model: The model year being appraised (drives the threshold).

    Returns:
        Filtered DataFrame. Empty input is returned unchanged.
    """
    premium = _blindado_filter_premium(year_model)

    if premium is None:
        logger.info(f"Blindado filter disabled for year_model {year_model} (2019 or older)")
        return df

    if len(df) == 0:
        return df

    p75_cutoff = df["sale_price"].quantile(0.75)
    lower_half = df[df["sale_price"] <= p75_cutoff]["sale_price"]
    anchor = float(lower_half.median())

    upper_fence = anchor + premium
    filtered = df[df["sale_price"] <= upper_fence]

    removed = len(df) - len(filtered)
    if removed > 0:
        logger.info(
            f"Removed {removed} blindado(s): anchor={anchor:.0f}, "
            f"premium={premium:.0f}, fence={upper_fence:.0f}"
        )

    return filtered
