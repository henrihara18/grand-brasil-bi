"""Tests for field mapping and column normalization."""

from decimal import Decimal

import pandas as pd

from grand_brasil.ingestion.field_mapping import (
    normalize_columns,
    parse_currency_columns,
    parse_numeric_columns,
    parse_year_model_column,
)


class TestNormalizeColumns:
    """Tests for column name normalization."""

    def test_dealerUp_columns(self) -> None:
        """DealerUp Portuguese column names are mapped correctly."""
        df = pd.DataFrame({
            "MARCA": ["CHEVROLET"],
            "MODELO": ["ONIX"],
            "A/M": ["2020/2021"],
            "D.E": [50],
            "VL VENDA": ["50.000,00"],
            "VL CUSTO": ["45.000,00"],
            "SIT": ["ESTOQUE"],
        })
        normalized = normalize_columns(df)
        assert "brand" in normalized.columns
        assert "model" in normalized.columns
        assert "year_model_raw" in normalized.columns
        assert "days_in_stock" in normalized.columns
        assert "asking_price" in normalized.columns
        assert "purchase_cost" in normalized.columns
        assert "status" in normalized.columns

    def test_skip_familia_column(self) -> None:
        """FAMÍLIA column is skipped (redundant with MARCA)."""
        df = pd.DataFrame({
            "MARCA": ["CHEVROLET"],
            "FAMÍLIA": ["VU-CHEVROLET"],
            "MODELO": ["ONIX"],
        })
        normalized = normalize_columns(df)
        assert "brand" in normalized.columns
        assert "family" not in normalized.columns
        # FAMÍLIA should have been dropped
        assert not any("familia" in str(c).lower() for c in normalized.columns)

    def test_accent_handling(self) -> None:
        """Columns with accents are matched correctly."""
        df = pd.DataFrame({
            "CÂMBIO": ["MANUAL"],
            "COMBUSTÍVEL": ["FLEX"],
        })
        normalized = normalize_columns(df)
        assert "transmission" in normalized.columns
        assert "fuel_type" in normalized.columns

    def test_unrecognized_columns_kept(self) -> None:
        """Unknown columns are kept as-is."""
        df = pd.DataFrame({
            "MARCA": ["CHEVROLET"],
            "CUSTOM_FIELD": ["value"],
        })
        normalized = normalize_columns(df)
        assert "brand" in normalized.columns
        assert "CUSTOM_FIELD" in normalized.columns


class TestParseYearModel:
    """Tests for year/model parsing."""

    def test_split_year_model(self) -> None:
        """'2020/2021' extracts model year 2021."""
        df = pd.DataFrame({"year_model_raw": ["2020/2021"]})
        result = parse_year_model_column(df)
        assert "year_model" in result.columns
        assert result["year_model"].iloc[0] == 2021

    def test_single_year(self) -> None:
        """Single year '2021' is used as-is."""
        df = pd.DataFrame({"year_model_raw": ["2021"]})
        result = parse_year_model_column(df)
        assert result["year_model"].iloc[0] == 2021


class TestParseCurrencyColumns:
    """Tests for Brazilian currency parsing."""

    def test_brazilian_format(self) -> None:
        """'50.000,00' is parsed correctly."""
        df = pd.DataFrame({"asking_price": ["50.000,00"]})
        result = parse_currency_columns(df)
        assert result["asking_price"].iloc[0] == Decimal("50000.00")

    def test_with_real_symbol(self) -> None:
        """'R$ 50.000,00' is parsed correctly."""
        df = pd.DataFrame({"asking_price": ["R$ 50.000,00"]})
        result = parse_currency_columns(df)
        assert result["asking_price"].iloc[0] == Decimal("50000.00")

    def test_nan_defaults_to_zero(self) -> None:
        """NaN values default to Decimal('0')."""
        df = pd.DataFrame({"asking_price": [None]})
        result = parse_currency_columns(df)
        assert result["asking_price"].iloc[0] == Decimal("0")
