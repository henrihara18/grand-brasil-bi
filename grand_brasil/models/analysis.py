"""Analysis result models — outputs of the business logic engine."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from grand_brasil.models.enums import AgingBracket


class AgingResult(BaseModel):
    """Result of aging analysis for a single vehicle."""

    brand: str
    model: str
    year_model: int
    days_in_stock: int
    bracket: AgingBracket
    plate: Optional[str] = None
    asking_price: Decimal = Decimal("0")


class PriceRecommendation(BaseModel):
    """Recommended price adjustment for a single vehicle."""

    brand: str
    model: str
    year_model: int
    plate: Optional[str] = None
    current_price: Decimal
    recommended_price: Decimal
    reduction_percent: float
    days_in_stock: int
    current_margin_percent: float
    projected_margin_percent: float
    purchase_cost: Decimal
    fipe_price: Optional[Decimal] = None
    rationale: str  # Human-readable explanation in PT-BR


class B2BCandidate(BaseModel):
    """Vehicle scored as a B2B wholesale candidate."""

    brand: str
    model: str
    year_model: int
    plate: Optional[str] = None
    days_in_stock: int
    asking_price: Decimal
    purchase_cost: Decimal

    # Composite score (0-10)
    score: float
    aging_score_component: float          # 0-10 normalized
    concentration_score_component: float  # 0-10 normalized
    margin_score_component: float         # 0-10 normalized

    same_model_count: int                 # How many of this model in stock
    rationale: str                        # PT-BR explanation


class InventorySummary(BaseModel):
    """Aggregate statistics for the entire inventory."""

    total_vehicles: int
    total_stock_value: Decimal            # Sum of asking prices
    total_cost_value: Decimal             # Sum of purchase costs
    average_days_in_stock: float
    median_days_in_stock: float
    average_margin_percent: float
    count_by_bracket: dict[str, int]      # AgingBracket value -> count
    count_by_brand: dict[str, int]        # Brand name -> count
    vehicles_over_90_days: int
    b2b_candidates_count: int
