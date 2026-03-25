"""Appraisal models — input/output for the trade-in valuation engine."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class AppraisalRequest(BaseModel):
    """Input for a trade-in appraisal."""

    brand: str                                  # Marca (ex: HYUNDAI)
    model_red: str                              # MODELO RED (ex: HYUNDAI HB20)
    model_trim: Optional[str] = None            # Trim-level key (ex: HONDA HR-V EXL)
    year_model: int                             # Ano modelo
    km: Optional[int] = None                    # Quilometragem
    estimated_repair_cost: Decimal = Decimal("0")  # Custo estimado de reparo
    fipe_price: Optional[Decimal] = None        # Valor FIPE de referencia
    fipe_code: Optional[str] = None             # Codigo FIPE (ex: "004278-1")
    fipe_reference_month: Optional[str] = None  # Mes de referencia (ex: "abril de 2026")
    fipe_model_name: Optional[str] = None       # Nome completo do modelo na FIPE


class Comparable(BaseModel):
    """A single historical sale used as a comparable."""

    sale_price: Decimal                         # Vl Venda
    purchase_cost: Decimal                      # Custo (what we paid the customer)
    adjusted_cost: Decimal                      # Custo Ajustado (Custo - Bonus)
    year_model: int
    km: Optional[int] = None
    days_in_stock: int
    sale_channel: str                           # "Loja" or "Revenda"
    margin_percent: float                       # % MF


class AppraisalSuggestion(BaseModel):
    """Output of the appraisal engine — suggested trade values.

    Provides both Loja (B2C) and Revenda (B2B) scenarios.
    """

    # Request echo
    brand: str
    model_red: str
    model_trim: Optional[str] = None            # Trim used for matching
    year_model: int
    km: Optional[int] = None
    estimated_repair_cost: Decimal = Decimal("0")
    used_trim_level: bool = False                # True if matched at trim level

    # Loja (B2C) scenario — target ~15% margin
    loja_estimated_sale_price: Optional[Decimal] = None
    loja_target_margin_percent: float = 15.0
    loja_max_trade_value: Optional[Decimal] = None
    loja_comparables_count: int = 0
    loja_avg_days_in_stock: Optional[float] = None

    # Revenda (B2B) scenario — target ~5-6% margin
    revenda_estimated_sale_price: Optional[Decimal] = None
    revenda_target_margin_percent: float = 5.5
    revenda_max_trade_value: Optional[Decimal] = None
    revenda_comparables_count: int = 0
    revenda_avg_days_in_stock: Optional[float] = None

    # Confidence
    total_comparables: int = 0
    outliers_removed: int = 0                    # Removed by IQR filter (blindados, etc.)
    confidence: str = "baixa"  # baixa, media, alta
    year_range_used: Optional[str] = None       # e.g. "2019 - 2023"

    # V2: KM adjustment
    km_adjustment_pct: Optional[float] = None   # % aplicado (mesmo para Loja e Revenda)
    comparables_median_km: Optional[int] = None # KM mediano dos comparaveis

    # V2: FIPE comparison
    loja_fipe_ratio: Optional[float] = None     # loja_estimated_sale / fipe_price
    revenda_fipe_ratio: Optional[float] = None  # revenda_estimated_sale / fipe_price

    # V3: FIPE as primary anchor
    fipe_code: Optional[str] = None
    fipe_reference_month: Optional[str] = None
    fipe_model_name: Optional[str] = None
    fipe_used_as_anchor: bool = False            # True when FIPE price is the base
    fipe_historical_spread_pct: Optional[float] = None  # (hist_median - fipe) / fipe

    # V2: Weighting metadata
    used_weighted_median: bool = False           # True if recency/year weights were applied

    # Rationale
    rationale: str = ""

    # Raw comparables for transparency
    loja_comparables: list[Comparable] = Field(default_factory=list)
    revenda_comparables: list[Comparable] = Field(default_factory=list)
