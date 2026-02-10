"""CSV/Excel ingestion strategy — primary data source from DealerUp exports."""

import logging
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from grand_brasil.ingestion.base import IngestionStrategy
from grand_brasil.ingestion.field_mapping import (
    REQUIRED_COLUMNS,
    detect_delimiter,
    normalize_columns,
    parse_currency_columns,
    parse_date_columns,
    parse_numeric_columns,
    parse_year_model_column,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


class CsvIngestionStrategy(IngestionStrategy):
    """Ingests data from user-uploaded CSV or Excel files.

    This is the primary ingestion strategy for Grand Brasil,
    reading exports from the DealerUp platform.
    """

    @property
    def strategy_name(self) -> str:
        return "Upload CSV/Excel"

    def validate_source(self, source: Optional[Path] = None) -> bool:
        """Check file exists and has a supported extension."""
        if source is None:
            return False
        path = Path(source)
        return path.exists() and path.suffix.lower() in SUPPORTED_EXTENSIONS

    def ingest(
        self,
        source: Optional[Union[Path, "UploadedFile"]] = None,
    ) -> pd.DataFrame:
        """Read CSV or Excel file, normalize columns, parse values.

        Handles both file paths (Path) and Streamlit UploadedFile objects.

        Args:
            source: Path to file or Streamlit UploadedFile.

        Returns:
            Standardized DataFrame ready for Vehicle model conversion.

        Raises:
            ValueError: If source is invalid or missing required columns.
        """
        if source is None:
            raise ValueError("Nenhum arquivo fornecido para importacao.")

        # Read the raw file
        df = self._read_file(source)
        logger.info(
            "Arquivo lido: %d linhas, %d colunas",
            len(df),
            len(df.columns),
        )

        # Normalize column names
        df = normalize_columns(df)
        logger.info("Colunas normalizadas: %s", list(df.columns))

        # Validate required columns
        missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(
                f"Colunas obrigatorias ausentes: {', '.join(missing)}. "
                f"Colunas encontradas: {', '.join(df.columns)}"
            )

        # Parse data types
        df = parse_year_model_column(df)
        df = parse_currency_columns(df)
        df = parse_date_columns(df)
        df = parse_numeric_columns(df)

        # Remove fully empty rows
        df = df.dropna(how="all")

        # Filter out rows without a model name
        if "model" in df.columns:
            df = df[df["model"].notna() & (df["model"].astype(str).str.strip() != "")]

        logger.info("Apos limpeza: %d veiculos validos", len(df))
        return df

    def _read_file(
        self,
        source: Union[Path, "UploadedFile"],
    ) -> pd.DataFrame:
        """Read CSV (auto-detect delimiter) or Excel file.

        Args:
            source: File path or Streamlit UploadedFile object.

        Returns:
            Raw DataFrame before normalization.
        """
        # Check if it's a Streamlit UploadedFile (has a .name attribute)
        if hasattr(source, "name"):
            name = source.name.lower()
            if name.endswith((".xlsx", ".xls")):
                return pd.read_excel(source, engine="openpyxl")
            else:
                # Try common delimiters for CSV
                return pd.read_csv(source, sep=None, engine="python")

        # It's a Path
        path = Path(source)
        suffix = path.suffix.lower()

        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(path, engine="openpyxl")
        elif suffix == ".csv":
            delimiter = detect_delimiter(str(path))
            logger.info("Delimitador CSV detectado: '%s'", delimiter)
            return pd.read_csv(
                path,
                sep=delimiter,
                encoding="utf-8",
                on_bad_lines="skip",
            )
        else:
            raise ValueError(
                f"Formato de arquivo nao suportado: {suffix}. "
                f"Use .csv, .xlsx ou .xls"
            )
