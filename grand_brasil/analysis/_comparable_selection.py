"""Helpers for selecting and weighting comparable sales in the appraisal engine.

Three responsibilities:
  1. `find_comparables`     — filter the sales DataFrame by model+year window.
  2. `build_comparables`    — convert DataFrame rows into Comparable models.
  3. Price/weight utilities — `year_adjusted_prices`, `weighted_median`,
                               `compute_weights` for recency weighting.

All functions here are pure/stateless and trivially testable without touching
the full `appraise()` orchestrator.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal

import pandas as pd

from grand_brasil.models.appraisal import Comparable

logger = logging.getLogger(__name__)


def find_comparables(
    sales_df: pd.DataFrame,
    model_key: str,
    match_column: str = "model_red",
    year_model: int = 0,
    year_tolerance: int = 2,
) -> pd.DataFrame:
    """Filter sales history to rows matching a model key within a year window.

    Args:
        sales_df: Sales history DataFrame.
        model_key: Value to match (e.g. "HYUNDAI CRETA" or "HYUNDAI CRETA PLATINUM").
        match_column: Column to match against. Falls back to `model_red` if the
            requested column is missing.
        year_model: Target model year.
        year_tolerance: +/- years to include around `year_model`.

    Returns:
        Filtered DataFrame. A copy, so the caller may freely mutate.
    """
    key_upper = model_key.strip().upper()

    if match_column not in sales_df.columns:
        match_column = "model_red"

    mask = (
        (sales_df[match_column] == key_upper)
        & (sales_df["year_model"] >= year_model - year_tolerance)
        & (sales_df["year_model"] <= year_model + year_tolerance)
    )
    result = sales_df[mask].copy()

    logger.info(
        f"Found {len(result)} comparables for {key_upper} "
        f"(col={match_column}) year {year_model} (+/-{year_tolerance})"
    )
    return result


def build_comparables(df: pd.DataFrame) -> list[Comparable]:
    """Convert DataFrame rows to Comparable Pydantic models (for the API/UI)."""
    comps = []
    for _, row in df.iterrows():
        comps.append(Comparable(
            sale_price=Decimal(str(row["sale_price"])),
            purchase_cost=Decimal(str(row["purchase_cost"])),
            adjusted_cost=Decimal(str(row["adjusted_cost"])),
            year_model=int(row["year_model"]),
            km=int(row["km"]) if pd.notna(row.get("km")) else None,
            days_in_stock=int(row["days_in_stock"]),
            sale_channel=str(row["sale_channel"]),
            margin_percent=float(row["margin_percent"]) if pd.notna(row.get("margin_percent")) else 0.0,
            plate=str(row["plate"]) if pd.notna(row.get("plate")) else None,
            model_red=str(row["model_red"]) if pd.notna(row.get("model_red")) else None,
        ))
    return comps


# ── Weighting & price adjustment ────────────────────────────────────────────

def year_adjusted_prices(
    df: pd.DataFrame,
    target_year: int,
    year_pct_per_year: float,
) -> pd.Series:
    """Adjust each comparable's sale_price to reflect the target year model.

    Formula: adjusted = sale_price × (1 + (target_year - comparable_year) × pct/100)

    Examples (year_pct_per_year=10):
        Comparable 2023, appraising 2024 → × 1.10 (newer = worth more)
        Comparable 2023, appraising 2022 → × 0.90 (older = worth less)
        Comparable 2023, appraising 2023 → × 1.00 (no change)
    """
    factor = df["year_model"].apply(
        lambda y: 1 + (target_year - int(y)) * (year_pct_per_year / 100)
    )
    return df["sale_price"].astype(float) * factor


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    """Compute a weighted median.

    Falls back to the plain median when all weights are zero.
    """
    total = weights.sum()
    if total == 0:
        return float(values.median())

    df = pd.DataFrame({"v": values.values, "w": weights.values})
    df = df.sort_values("v")
    df["cumw"] = df["w"].cumsum() / total
    return float(df.loc[df["cumw"] >= 0.5, "v"].iloc[0])


def compute_weights(
    df: pd.DataFrame,
    reference_date: pd.Timestamp,
    halflife_days: float,
) -> pd.Series:
    """Compute recency weights for each row via exponential decay.

    w = exp(-λ × days_since_sale), where λ = ln(2) / halflife_days.
    NaT sale_dates receive a neutral weight of 0.5.
    """
    lam = math.log(2) / max(halflife_days, 1.0)
    weights = []

    for _, row in df.iterrows():
        sd = row.get("sale_date")
        if pd.isna(sd):
            weights.append(0.5)
        else:
            days = max((reference_date - pd.Timestamp(sd)).days, 0)
            weights.append(math.exp(-lam * days))

    return pd.Series(weights, index=df.index)
