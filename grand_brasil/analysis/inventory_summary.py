"""Aggregate inventory statistics."""

from decimal import Decimal
from statistics import median

from grand_brasil.models.analysis import AgingResult, InventorySummary
from grand_brasil.models.vehicle import Vehicle


def compute_summary(
    vehicles: list[Vehicle],
    aging_results: list[AgingResult],
    b2b_count: int,
) -> InventorySummary:
    """Aggregate all inventory statistics into a single summary model.

    Args:
        vehicles: Full vehicle inventory.
        aging_results: Aging classification results.
        b2b_count: Number of B2B candidates identified.

    Returns:
        InventorySummary with all aggregated metrics.
    """
    if not vehicles:
        return InventorySummary(
            total_vehicles=0,
            total_stock_value=Decimal("0"),
            total_cost_value=Decimal("0"),
            average_days_in_stock=0.0,
            median_days_in_stock=0.0,
            average_margin_percent=0.0,
            count_by_bracket={},
            count_by_brand={},
            vehicles_over_90_days=0,
            b2b_candidates_count=0,
        )

    total_stock_value = sum(v.asking_price for v in vehicles)
    total_cost_value = sum(v.purchase_cost for v in vehicles)

    days_list = [v.days_in_stock for v in vehicles]
    avg_days = sum(days_list) / len(days_list)
    med_days = float(median(days_list))

    margins = [v.margin_percent for v in vehicles]
    avg_margin = sum(margins) / len(margins) if margins else 0.0

    # Count by aging bracket
    count_by_bracket: dict[str, int] = {}
    for result in aging_results:
        bracket_val = result.bracket.value
        count_by_bracket[bracket_val] = count_by_bracket.get(bracket_val, 0) + 1

    # Count by brand
    count_by_brand: dict[str, int] = {}
    for vehicle in vehicles:
        count_by_brand[vehicle.brand] = count_by_brand.get(vehicle.brand, 0) + 1

    vehicles_over_90 = sum(1 for v in vehicles if v.days_in_stock > 90)

    return InventorySummary(
        total_vehicles=len(vehicles),
        total_stock_value=total_stock_value,
        total_cost_value=total_cost_value,
        average_days_in_stock=round(avg_days, 1),
        median_days_in_stock=round(med_days, 1),
        average_margin_percent=round(avg_margin, 2),
        count_by_bracket=count_by_bracket,
        count_by_brand=count_by_brand,
        vehicles_over_90_days=vehicles_over_90,
        b2b_candidates_count=b2b_count,
    )
