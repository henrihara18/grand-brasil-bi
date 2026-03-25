"""Pydantic data models for the Grand Brasil BI system."""

from grand_brasil.models.enums import AgingBracket, FuelType, VehicleStatus
from grand_brasil.models.vehicle import Vehicle
from grand_brasil.models.analysis import (
    AgingResult,
    B2BCandidate,
    InventorySummary,
    PriceRecommendation,
)
from grand_brasil.models.appraisal import (
    AppraisalRequest,
    AppraisalSuggestion,
    Comparable,
)

__all__ = [
    "AgingBracket",
    "AgingResult",
    "AppraisalRequest",
    "AppraisalSuggestion",
    "B2BCandidate",
    "Comparable",
    "FuelType",
    "InventorySummary",
    "PriceRecommendation",
    "Vehicle",
    "VehicleStatus",
]
