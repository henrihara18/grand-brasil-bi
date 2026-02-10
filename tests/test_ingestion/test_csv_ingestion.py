"""Tests for CSV/Excel ingestion strategy."""

from pathlib import Path

import pytest

from grand_brasil.ingestion.csv_ingestion import CsvIngestionStrategy
from grand_brasil.ingestion.ingestion_manager import IngestionManager


class TestCsvIngestionStrategy:
    """Tests for the CSV ingestion strategy."""

    def test_validate_csv_file(self, fixtures_dir: Path) -> None:
        """CSV file is validated as valid source."""
        strategy = CsvIngestionStrategy()
        csv_path = fixtures_dir / "sample_stock.csv"
        assert strategy.validate_source(csv_path) is True

    def test_validate_missing_file(self) -> None:
        """Missing file is invalid."""
        strategy = CsvIngestionStrategy()
        assert strategy.validate_source(Path("/nonexistent.csv")) is False

    def test_validate_unsupported_extension(self, tmp_path: Path) -> None:
        """Unsupported file extensions are rejected."""
        strategy = CsvIngestionStrategy()
        txt_file = tmp_path / "data.txt"
        txt_file.write_text("data")
        assert strategy.validate_source(txt_file) is False

    def test_ingest_csv_file(self, fixtures_dir: Path) -> None:
        """CSV file is ingested and normalized successfully."""
        strategy = CsvIngestionStrategy()
        csv_path = fixtures_dir / "sample_stock.csv"
        df = strategy.ingest(csv_path)

        assert len(df) > 0
        assert "brand" in df.columns
        assert "model" in df.columns
        assert "asking_price" in df.columns
        assert "days_in_stock" in df.columns

    def test_ingest_no_source_raises(self) -> None:
        """Ingestion without source raises ValueError."""
        strategy = CsvIngestionStrategy()
        with pytest.raises(ValueError, match="Nenhum arquivo"):
            strategy.ingest(None)


class TestIngestionManager:
    """Tests for the ingestion manager."""

    def test_load_data_from_csv(self, fixtures_dir: Path) -> None:
        """Manager loads CSV and returns Vehicle models."""
        manager = IngestionManager()
        csv_path = fixtures_dir / "sample_stock.csv"
        vehicles = manager.load_data(source=csv_path)

        assert len(vehicles) > 0
        # Check first vehicle has expected fields
        v = vehicles[0]
        assert v.brand
        assert v.model
        assert v.asking_price > 0
        assert v.days_in_stock >= 0

    def test_vehicles_sorted_by_days(self, fixtures_dir: Path) -> None:
        """Vehicles are sorted by days_in_stock descending."""
        manager = IngestionManager()
        csv_path = fixtures_dir / "sample_stock.csv"
        vehicles = manager.load_data(source=csv_path)

        days = [v.days_in_stock for v in vehicles]
        assert days == sorted(days, reverse=True)

    def test_brand_cleaned(self, fixtures_dir: Path) -> None:
        """Brand names have VU/VN prefix removed."""
        manager = IngestionManager()
        csv_path = fixtures_dir / "sample_stock.csv"
        vehicles = manager.load_data(source=csv_path)

        for v in vehicles:
            assert not v.brand.startswith("VU ")
            assert not v.brand.startswith("VN ")

    def test_strategy_name(self) -> None:
        """Default strategy is CSV/Excel."""
        manager = IngestionManager()
        assert manager.active_strategy_name == "Upload CSV/Excel"
