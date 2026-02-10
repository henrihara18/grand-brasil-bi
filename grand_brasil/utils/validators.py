"""Data validation helpers for ingested vehicle data."""

from decimal import Decimal
from typing import Optional

import pandas as pd


def validate_required_columns(
    df: pd.DataFrame,
    required: list[str],
) -> list[str]:
    """Check that required columns exist in the DataFrame.

    Args:
        df: DataFrame to validate.
        required: List of required column names.

    Returns:
        List of missing column names (empty if all present).
    """
    return [col for col in required if col not in df.columns]


def safe_decimal(value: object) -> Decimal:
    """Safely convert a value to Decimal, defaulting to 0.

    Handles NaN, None, empty strings, and already-Decimal values.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float) and pd.isna(value):
        return Decimal("0")
    if isinstance(value, str) and not value.strip():
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def safe_int(value: object, default: int = 0) -> int:
    """Safely convert a value to int, with a default."""
    if value is None:
        return default
    if isinstance(value, float):
        if pd.isna(value):
            return default
        return int(value)
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return default


def safe_str(value: object, default: str = "") -> str:
    """Safely convert a value to string, handling NaN and None."""
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    result = str(value).strip()
    return result if result else default


def clean_brand_name(brand: str) -> str:
    """Clean brand name from DealerUp format.

    DealerUp prefixes brands with category codes like "VU" (veiculos usados).
    e.g., "VU CHEVROLET" -> "CHEVROLET"
         "VU-CHEVROLET" -> "CHEVROLET"

    Args:
        brand: Raw brand string from DealerUp.

    Returns:
        Cleaned brand name.
    """
    cleaned = brand.strip().upper()

    # Common DealerUp prefixes
    prefixes = ["VU ", "VU-", "VN ", "VN-", "VD ", "VD-"]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    return cleaned
