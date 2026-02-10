"""Ingestion orchestrator — converts raw DataFrames to Vehicle models."""

import logging
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from grand_brasil.ingestion.base import IngestionStrategy
from grand_brasil.ingestion.csv_ingestion import CsvIngestionStrategy
from grand_brasil.models.enums import VehicleStatus
from grand_brasil.models.vehicle import Vehicle
from grand_brasil.utils.validators import (
    clean_brand_name,
    safe_decimal,
    safe_int,
    safe_str,
)

logger = logging.getLogger(__name__)


# Map DealerUp status values to our enum
STATUS_MAP: dict[str, VehicleStatus] = {
    "estoque": VehicleStatus.IN_STOCK,
    "em estoque": VehicleStatus.IN_STOCK,
    "disponivel": VehicleStatus.IN_STOCK,
    "reservado": VehicleStatus.RESERVED,
    "vendido": VehicleStatus.SOLD,
}


class IngestionManager:
    """Orchestrates data ingestion: strategy → DataFrame → list[Vehicle].

    Usage:
        manager = IngestionManager()
        vehicles = manager.load_data(source=Path("stock.xlsx"))
    """

    def __init__(self, strategy: Optional[IngestionStrategy] = None):
        """Initialize with an ingestion strategy.

        Args:
            strategy: Strategy to use. Defaults to CsvIngestionStrategy.
        """
        self._strategy = strategy or CsvIngestionStrategy()

    @property
    def active_strategy_name(self) -> str:
        """Name of the currently active ingestion strategy."""
        return self._strategy.strategy_name

    def set_strategy(self, strategy: IngestionStrategy) -> None:
        """Swap the ingestion strategy at runtime."""
        self._strategy = strategy

    def load_data(
        self,
        source: Optional[Union[Path, object]] = None,
    ) -> list[Vehicle]:
        """Execute the active strategy and convert results to Vehicle models.

        Args:
            source: Data source (file path or Streamlit UploadedFile).

        Returns:
            List of Vehicle models, sorted by days_in_stock descending.
        """
        df = self._strategy.ingest(source=source)
        vehicles = self._dataframe_to_vehicles(df)

        # Sort by days in stock (most aged first)
        vehicles.sort(key=lambda v: v.days_in_stock, reverse=True)

        logger.info(
            "Importacao concluida: %d veiculos via %s",
            len(vehicles),
            self.active_strategy_name,
        )
        return vehicles

    def _dataframe_to_vehicles(self, df: pd.DataFrame) -> list[Vehicle]:
        """Convert each DataFrame row to a Vehicle model.

        Rows that fail validation are logged and skipped.

        Args:
            df: Normalized DataFrame from ingestion strategy.

        Returns:
            List of successfully parsed Vehicle models.
        """
        vehicles: list[Vehicle] = []
        errors: list[str] = []

        for idx, row in df.iterrows():
            try:
                vehicle = self._row_to_vehicle(row)
                vehicles.append(vehicle)
            except Exception as e:
                model_name = safe_str(row.get("model", "???"))
                errors.append(f"Linha {idx}: {model_name} - {e}")

        if errors:
            logger.warning(
                "Erros na importacao (%d de %d linhas):\n%s",
                len(errors),
                len(df),
                "\n".join(errors[:10]),  # Log first 10 errors
            )

        return vehicles

    def _row_to_vehicle(self, row: pd.Series) -> Vehicle:
        """Convert a single DataFrame row to a Vehicle model.

        Args:
            row: A pandas Series representing one vehicle.

        Returns:
            Vehicle model instance.

        Raises:
            ValueError: If essential fields are missing or invalid.
        """
        # Parse brand (clean DealerUp prefix)
        brand = clean_brand_name(safe_str(row.get("brand", "")))
        if not brand:
            raise ValueError("Marca ausente")

        model = safe_str(row.get("model", ""))
        if not model:
            raise ValueError("Modelo ausente")

        # Parse status
        raw_status = safe_str(row.get("status", "")).lower().strip()
        status = STATUS_MAP.get(raw_status, VehicleStatus.IN_STOCK)

        return Vehicle(
            brand=brand,
            model=model,
            year_model=safe_int(row.get("year_model", 0)),
            transmission=safe_str(row.get("transmission")) or None,
            plate=safe_str(row.get("plate")) or None,
            color=safe_str(row.get("color")) or None,
            fuel_type=safe_str(row.get("fuel_type")) or None,
            mileage=safe_int(row.get("mileage")) or None,
            days_in_stock=safe_int(row.get("days_in_stock", 0)),
            entry_date=row.get("entry_date") if pd.notna(row.get("entry_date")) else None,
            asking_price=safe_decimal(row.get("asking_price", 0)),
            purchase_cost=safe_decimal(row.get("purchase_cost", 0)),
            bonus_value=safe_decimal(row.get("bonus_value", 0)),
            operational_expense=safe_decimal(row.get("operational_expense", 0)),
            adjusted_cost=safe_decimal(row.get("adjusted_cost")) or None,
            sale_result=safe_decimal(row.get("sale_result")) or None,
            result_percent=float(row.get("result_percent", 0)) if pd.notna(row.get("result_percent")) else None,
            margin=safe_decimal(row.get("margin")) or None,
            fipe_code=safe_str(row.get("fipe_code")) or None,
            fipe_price=safe_decimal(row.get("fipe_price")) or None,
            branch=safe_str(row.get("branch")) or None,
            status=status,
            source="csv",
        )
