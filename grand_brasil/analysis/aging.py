"""Aging analysis — classifies vehicles by how long they've been in stock."""

from grand_brasil.config import AgingThresholds
from grand_brasil.models.analysis import AgingResult
from grand_brasil.models.enums import AgingBracket
from grand_brasil.models.vehicle import Vehicle


def classify_aging(
    vehicle: Vehicle,
    thresholds: AgingThresholds,
) -> AgingResult:
    """Classify a single vehicle into an aging bracket.

    Args:
        vehicle: Vehicle to classify.
        thresholds: Configurable day thresholds.

    Returns:
        AgingResult with bracket assignment.
    """
    days = vehicle.days_in_stock

    if days <= thresholds.green_max_days:
        bracket = AgingBracket.GREEN
    elif days <= thresholds.yellow_max_days:
        bracket = AgingBracket.YELLOW
    elif days <= thresholds.orange_max_days:
        bracket = AgingBracket.ORANGE
    else:
        bracket = AgingBracket.RED

    return AgingResult(
        brand=vehicle.brand,
        model=vehicle.model,
        year_model=vehicle.year_model,
        days_in_stock=days,
        bracket=bracket,
        plate=vehicle.plate,
        asking_price=vehicle.asking_price,
    )


def analyze_aging_batch(
    vehicles: list[Vehicle],
    thresholds: AgingThresholds,
) -> list[AgingResult]:
    """Classify all vehicles and sort by days_in_stock descending.

    Args:
        vehicles: List of vehicles to analyze.
        thresholds: Configurable day thresholds.

    Returns:
        List of AgingResult sorted by days (most aged first).
    """
    results = [classify_aging(v, thresholds) for v in vehicles]
    results.sort(key=lambda r: r.days_in_stock, reverse=True)
    return results


def aging_distribution(
    results: list[AgingResult],
) -> dict[str, int]:
    """Count vehicles in each aging bracket.

    Args:
        results: List of AgingResult from analyze_aging_batch.

    Returns:
        Dict mapping bracket value (str) to count.
    """
    distribution: dict[str, int] = {
        AgingBracket.GREEN.value: 0,
        AgingBracket.YELLOW.value: 0,
        AgingBracket.ORANGE.value: 0,
        AgingBracket.RED.value: 0,
    }

    for result in results:
        distribution[result.bracket.value] += 1

    return distribution
