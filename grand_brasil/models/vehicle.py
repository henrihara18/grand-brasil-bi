"""Core Vehicle domain model — the canonical representation of a vehicle in stock."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from grand_brasil.models.enums import FuelType, VehicleStatus


class Vehicle(BaseModel):
    """
    A vehicle in the dealership inventory.

    Mapped from DealerUp Excel exports. All financial values are in BRL.
    """

    # Identification
    brand: str                                    # MARCA
    model: str                                    # MODELO
    year_model: int                               # A/M (second value, e.g., 2021)
    transmission: Optional[str] = None            # CÂMBIO
    plate: Optional[str] = None                   # PLACA
    color: Optional[str] = None                   # COR
    fuel_type: Optional[str] = None               # COMB.
    mileage: Optional[int] = None                 # KM

    # Stock timing
    days_in_stock: int                            # D.E (Dias em Estoque, from DealerUp)
    entry_date: Optional[date] = None             # Data Abertura (when available)

    # Financial - core
    asking_price: Decimal                         # VL VENDA
    purchase_cost: Decimal                        # VL CUSTO

    # Financial - detailed
    bonus_value: Decimal = Decimal("0")           # VL BÔNUS
    operational_expense: Decimal = Decimal("0")   # DESPESA OPERACIONAL
    adjusted_cost: Optional[Decimal] = None       # CUSTO AJUSTADO = Custo + Despesas - Bônus
    sale_result: Optional[Decimal] = None         # RESULTADO VENDA
    result_percent: Optional[float] = None        # %RV
    margin: Optional[Decimal] = None              # MARGEM

    # FIPE reference
    fipe_code: Optional[str] = None               # CÓDIGO FIPE (coming soon)
    fipe_price: Optional[Decimal] = None          # FIPE price (enriched via API)

    # Metadata
    branch: Optional[str] = None                  # FILIAL
    status: VehicleStatus = VehicleStatus.IN_STOCK  # SIT
    source: str = "csv"                           # Ingestion source
    imported_at: datetime = Field(default_factory=datetime.now)

    @computed_field
    @property
    def margin_percent(self) -> float:
        """Margin as percentage of purchase cost."""
        if self.purchase_cost == 0:
            return 0.0
        return float(
            (self.asking_price - self.purchase_cost) / self.purchase_cost * 100
        )

    @computed_field
    @property
    def computed_adjusted_cost(self) -> Decimal:
        """Custo Ajustado = VL CUSTO + DESPESA OPERACIONAL - VL BÔNUS."""
        return self.purchase_cost + self.operational_expense - self.bonus_value

    @computed_field
    @property
    def fipe_delta_percent(self) -> Optional[float]:
        """How much asking_price deviates from FIPE price (%).

        Positive = above FIPE, Negative = below FIPE.
        """
        if self.fipe_price is None or self.fipe_price == 0:
            return None
        return float(
            (self.asking_price - self.fipe_price) / self.fipe_price * 100
        )

    @computed_field
    @property
    def model_key(self) -> str:
        """Normalized key for grouping by model (brand + model + year).

        Used for B2B concentration analysis.
        """
        return f"{self.brand.strip().upper()} {self.model.strip().upper()}"
