"""Column name normalization and field mapping for DealerUp exports.

DealerUp Excel exports use Portuguese column headers. This module
maps them to canonical internal names used by the Vehicle model.
"""

import re
import unicodedata
from decimal import Decimal
from typing import Optional

import pandas as pd

from grand_brasil.utils.currency import parse_brl
from grand_brasil.utils.date_utils import parse_br_date, parse_year_model


# ── Column alias mapping ──────────────────────────────────────────────
# Maps our canonical field name -> list of possible DealerUp column names
# All aliases should be lowercase for matching
COLUMN_ALIASES: dict[str, list[str]] = {
    "brand":                ["marca"],
    "model":                ["modelo"],
    "transmission":         ["cambio", "câmbio"],
    "plate":                ["placa"],
    "year_model_raw":       ["a/m", "am", "ano/modelo", "ano modelo"],
    "color":                ["cor"],
    "fuel_type":            ["comb.", "comb", "combustivel", "combustível"],
    "mileage":              ["km", "quilometragem"],
    "days_in_stock":        ["d.e", "de", "d.e.", "dias em estoque", "dias estoque"],
    "branch":               ["filial"],
    "asking_price":         ["vl venda", "vl_venda", "valor venda", "preco venda"],
    "bonus_value":          ["vl bonus", "vl bônus", "vl_bonus", "bonus"],
    "operational_expense":  ["despesa operacional", "despesa_operacional", "desp operacional"],
    "purchase_cost":        ["vl custo", "vl_custo", "valor custo", "custo"],
    "adjusted_cost":        ["custo ajustado", "custo_ajustado"],
    "sale_result":          ["resultado venda", "resultado_venda", "res venda"],
    "result_percent":       ["%rv", "% rv", "percentual resultado", "rv"],
    "margin":               ["margem"],
    "fipe_code":            ["codigo fipe", "código fipe", "cod fipe", "cod_fipe"],
    "fipe_price":           ["fipe", "valor fipe", "preco fipe"],
    "status":               ["sit", "situacao", "situação", "status"],
    "entry_date":           ["data abertura", "data_abertura", "dt abertura",
                             "data entrada", "data_entrada"],
}

# Columns to skip during ingestion (redundant or not needed for stock BI)
SKIP_COLUMNS: set[str] = {
    "familia", "família",        # Redundant with MARCA
    "cor interna",               # Not relevant
    "proposta",                  # Sales-related, not needed
    "cliente",                   # Sales-related
    "vendedor",                  # Sales-related
    "opc",                       # Not needed
    "chassi",                    # Not needed for BI
    "veiculo", "veículo",        # Usually duplicate of modelo
    "renavan",                   # Not needed for BI
    "pago",                      # Not needed
    "calificacao", "qualificação",
    "nbs",
}

# Minimum required columns for a valid import
REQUIRED_COLUMNS: list[str] = [
    "brand",
    "model",
    "asking_price",
    "purchase_cost",
    "days_in_stock",
]

# Columns that contain currency values (Brazilian format)
CURRENCY_COLUMNS: set[str] = {
    "asking_price",
    "bonus_value",
    "operational_expense",
    "purchase_cost",
    "adjusted_cost",
    "sale_result",
    "margin",
    "fipe_price",
}


def _strip_accents(text: str) -> str:
    """Remove accents from a string for loose matching."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.category(c).startswith("M"))


def _normalize_header(header: str) -> str:
    """Normalize a column header for matching: lowercase, strip, remove accents."""
    return _strip_accents(header.strip().lower())


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename DataFrame columns from DealerUp aliases to canonical names.

    Args:
        df: Raw DataFrame from DealerUp export.

    Returns:
        DataFrame with canonical column names. Unrecognized columns are kept as-is.
    """
    # Build reverse lookup: normalized alias -> canonical name
    alias_lookup: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_lookup[_normalize_header(alias)] = canonical

    # Rename columns
    rename_map: dict[str, str] = {}
    for col in df.columns:
        normalized = _normalize_header(str(col))

        # Skip columns we don't need
        if normalized in SKIP_COLUMNS or _strip_accents(normalized) in SKIP_COLUMNS:
            rename_map[col] = f"_skip_{col}"
            continue

        if normalized in alias_lookup:
            rename_map[col] = alias_lookup[normalized]
        # Also try without accents
        elif _strip_accents(normalized) in alias_lookup:
            rename_map[col] = alias_lookup[_strip_accents(normalized)]

    df = df.rename(columns=rename_map)

    # Drop skipped columns
    skip_cols = [c for c in df.columns if str(c).startswith("_skip_")]
    df = df.drop(columns=skip_cols, errors="ignore")

    return df


def parse_currency_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Parse Brazilian currency strings to Decimal in known currency columns.

    Args:
        df: DataFrame with canonical column names.

    Returns:
        DataFrame with currency columns converted to Decimal.
    """
    for col in CURRENCY_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: parse_brl(str(x)) if pd.notna(x) else Decimal("0")
            )
    return df


def parse_year_model_column(df: pd.DataFrame) -> pd.DataFrame:
    """Parse the A/M column into year_model (integer).

    Extracts the model year (second value) from "2020/2021" format.

    Args:
        df: DataFrame with 'year_model_raw' column.

    Returns:
        DataFrame with 'year_model' as int and 'year_model_raw' dropped.
    """
    if "year_model_raw" in df.columns:
        df["year_model"] = df["year_model_raw"].apply(
            lambda x: parse_year_model(str(x)) if pd.notna(x) else 0
        )
        df = df.drop(columns=["year_model_raw"])
    return df


def parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Parse date columns from Brazilian format.

    Args:
        df: DataFrame with canonical column names.

    Returns:
        DataFrame with date columns converted to date objects.
    """
    if "entry_date" in df.columns:
        df["entry_date"] = df["entry_date"].apply(
            lambda x: parse_br_date(str(x)) if pd.notna(x) else None
        )
    return df


def parse_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Parse numeric columns (mileage, days_in_stock, result_percent).

    Args:
        df: DataFrame with canonical column names.

    Returns:
        DataFrame with numeric columns properly typed.
    """
    int_columns = ["mileage", "days_in_stock"]
    for col in int_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    float_columns = ["result_percent"]
    for col in float_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def detect_delimiter(file_path: str, sample_size: int = 5) -> str:
    """Auto-detect CSV delimiter by reading a few lines.

    Brazilian CSV exports commonly use semicolons.

    Args:
        file_path: Path to the CSV file.
        sample_size: Number of lines to sample.

    Returns:
        Detected delimiter character.
    """
    delimiters = [";", ",", "\t", "|"]
    scores: dict[str, int] = {d: 0 for d in delimiters}

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [f.readline() for _ in range(sample_size)]

    for line in lines:
        if not line.strip():
            continue
        for d in delimiters:
            count = line.count(d)
            scores[d] += count

    # Return the delimiter with the highest total count
    best = max(scores, key=lambda d: scores[d])
    return best if scores[best] > 0 else ","
