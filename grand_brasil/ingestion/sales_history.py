"""Sales history loader — reads processed DealerUp sales exports.

Loads the 2025 sales spreadsheet (already processed with MODELO RED column)
into a DataFrame ready for the appraisal engine.
"""

import logging
from pathlib import Path
from typing import Union

import pandas as pd

logger = logging.getLogger(__name__)

# Column mapping from the processed sales file to internal names
SALES_COLUMN_MAP = {
    "Marca": "brand",
    "MODELO RED": "model_red",
    "Modelo": "modelo_full",       # Full model description (for trim extraction)
    "Shortname": "shortname",      # Short model name (for trim extraction)
    "Modelo.1": "year_model",
    "KM": "km",
    "Vl Venda": "sale_price",
    "Custo": "purchase_cost",
    "Custo Ajustado": "adjusted_cost",
    "Despesa Operacional": "operational_expense",
    "Vl Bônus": "bonus_value",
    "Vl Impostos": "taxes",
    "D.E": "days_in_stock",
    "% MF": "margin_percent",
    "Margem Final": "margin_final",
    "Dt Venda": "sale_date",
    "Situação": "sale_channel",     # "Loja" or "Revenda"
    "Loja Venda": "store",
    "Cor": "color",
    "Placa": "plate",
    "Km Range": "km_range",
    "range ano": "year_range",
    "Range Valor Venda": "sale_price_range",
}

REQUIRED_COLUMNS = [
    "brand", "model_red", "year_model", "sale_price",
    "purchase_cost", "adjusted_cost", "sale_channel",
]


def load_sales_history(
    source: Union[str, Path, "UploadedFile"],
    header_row: int = 1,
) -> pd.DataFrame:
    """Load a processed sales history file into a clean DataFrame.

    Args:
        source: Path to Excel/CSV file, or Streamlit UploadedFile.
        header_row: Row index for headers (0-based). Default 1 for processed file.

    Returns:
        DataFrame with normalized column names and clean types.

    Raises:
        ValueError: If required columns are missing after mapping.
    """
    # Read file
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix in (".xlsx", ".xls"):
            df = pd.read_excel(path, header=header_row)
        else:
            df = pd.read_csv(path, header=header_row, sep=";")
    else:
        # Streamlit UploadedFile
        name = getattr(source, "name", "")
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(source, header=header_row)
        else:
            df = pd.read_csv(source, header=header_row, sep=";")

    logger.info(f"Loaded {len(df)} rows from sales history")

    # Rename columns using mapping
    rename_map = {}
    for orig, internal in SALES_COLUMN_MAP.items():
        # Handle encoding issues with column names
        for col in df.columns:
            if _normalize_col(col) == _normalize_col(orig):
                rename_map[col] = internal
                break

    df = df.rename(columns=rename_map)

    # Check required columns
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colunas obrigatorias ausentes apos mapeamento: {missing}. "
            f"Colunas disponiveis: {list(df.columns)}"
        )

    # Clean types
    df["year_model"] = pd.to_numeric(df["year_model"], errors="coerce").astype("Int64")
    df["km"] = pd.to_numeric(df["km"], errors="coerce").astype("Int64")
    df["sale_price"] = pd.to_numeric(df["sale_price"], errors="coerce")
    df["purchase_cost"] = pd.to_numeric(df["purchase_cost"], errors="coerce")
    df["adjusted_cost"] = pd.to_numeric(df["adjusted_cost"], errors="coerce")
    df["days_in_stock"] = pd.to_numeric(df["days_in_stock"], errors="coerce").fillna(0).astype(int)
    df["margin_percent"] = pd.to_numeric(df["margin_percent"], errors="coerce")

    if "sale_date" in df.columns:
        df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")

    # Normalize brand and model_red to uppercase
    df["brand"] = df["brand"].astype(str).str.strip().str.upper()
    df["model_red"] = df["model_red"].astype(str).str.strip().str.upper()
    df["sale_channel"] = df["sale_channel"].astype(str).str.strip()

    # Drop rows with missing critical data
    df = df.dropna(subset=["sale_price", "purchase_cost", "year_model"])
    df = df[df["sale_price"] > 0]

    # Build model_trim column (MODELO RED + extracted trim)
    _add_model_trim(df)

    logger.info(f"Sales history cleaned: {len(df)} valid rows")
    return df


def _add_model_trim(df: pd.DataFrame) -> None:
    """Add model_trim column by extracting trim from full model description.

    Uses the trim_extractor utility to parse DealerUp's verbose model names
    into clean model+trim keys (e.g. "HONDA HR-V EXL").
    """
    from grand_brasil.utils.trim_extractor import build_model_trim

    if "modelo_full" in df.columns and "shortname" in df.columns:
        df["model_trim"] = df.apply(
            lambda r: build_model_trim(
                str(r["model_red"]),
                str(r["modelo_full"]),
                str(r["shortname"]),
            ),
            axis=1,
        )
        logger.info(f"Built model_trim: {df['model_trim'].nunique()} unique trims")
    else:
        # Fallback: model_trim = model_red
        df["model_trim"] = df["model_red"]
        logger.warning("modelo_full/shortname columns not found, model_trim = model_red")


def _normalize_col(name: str) -> str:
    """Normalize column name for comparison (handles encoding diffs)."""
    import unicodedata
    name = unicodedata.normalize("NFKD", str(name))
    name = name.encode("ascii", "ignore").decode("ascii")
    return name.strip().lower().replace(" ", "_")
