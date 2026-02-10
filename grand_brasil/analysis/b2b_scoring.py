"""B2B candidate scoring engine.

Scores vehicles as wholesale (B2B) candidates based on three factors:
1. Aging — how long the vehicle has been in stock
2. Concentration — how many of the same model are in stock
3. Margin (inverse) — vehicles with lower margins are higher B2B urgency

The composite score is weighted: score = (aging × w1) + (concentration × w2) + (margin × w3)
All component scores are normalized to 0-10 scale.
"""

from collections import Counter

from grand_brasil.config import AgingThresholds, B2BScoringWeights
from grand_brasil.models.analysis import B2BCandidate
from grand_brasil.models.vehicle import Vehicle


def _calculate_aging_score(
    days_in_stock: int,
    thresholds: AgingThresholds,
) -> float:
    """Normalize aging to 0-10 scale.

    0 days = 0.0 (no urgency), orange_max_days+ = 10.0 (maximum urgency).
    Linear interpolation in between.

    Args:
        days_in_stock: Number of days the vehicle has been in stock.
        thresholds: Aging threshold configuration.

    Returns:
        Score from 0.0 to 10.0.
    """
    max_days = thresholds.orange_max_days  # 90 by default
    if max_days <= 0:
        return 0.0

    score = min(days_in_stock / max_days, 1.0) * 10.0
    return round(score, 2)


def _calculate_concentration_score(
    same_model_count: int,
    concentration_limit: int,
) -> float:
    """Normalize model concentration to 0-10 scale.

    1 unit = 0.0, concentration_limit or more = 10.0.
    Linear interpolation in between.

    Args:
        same_model_count: Number of vehicles of the same model in stock.
        concentration_limit: Threshold count from config.

    Returns:
        Score from 0.0 to 10.0.
    """
    if concentration_limit <= 1:
        return 10.0 if same_model_count > 1 else 0.0

    # Normalize: 1 unit = 0, limit+ = 10
    normalized = (same_model_count - 1) / (concentration_limit - 1)
    score = min(normalized, 1.0) * 10.0
    return round(score, 2)


def _calculate_margin_score(margin_percent: float) -> float:
    """Inverse margin score: high margin = low B2B urgency.

    0% margin = 10.0 (high urgency to sell B2B).
    20%+ margin = 0.0 (no urgency, good retail margin).
    Linear interpolation in between.

    Args:
        margin_percent: Current margin as percentage.

    Returns:
        Score from 0.0 to 10.0.
    """
    max_margin = 20.0  # 20% margin = no B2B urgency

    if margin_percent <= 0:
        return 10.0
    if margin_percent >= max_margin:
        return 0.0

    score = (1.0 - margin_percent / max_margin) * 10.0
    return round(score, 2)


def score_b2b_candidate(
    vehicle: Vehicle,
    model_counts: dict[str, int],
    weights: B2BScoringWeights,
    thresholds: AgingThresholds,
) -> B2BCandidate:
    """Compute composite B2B score for one vehicle.

    Args:
        vehicle: Vehicle to score.
        model_counts: Dict of model_key -> count in current inventory.
        weights: Scoring weights from config.
        thresholds: Aging thresholds from config.

    Returns:
        B2BCandidate with all score components.
    """
    same_model_count = model_counts.get(vehicle.model_key, 1)

    aging_score = _calculate_aging_score(vehicle.days_in_stock, thresholds)
    concentration_score = _calculate_concentration_score(
        same_model_count, weights.concentration_limit
    )
    margin_score = _calculate_margin_score(vehicle.margin_percent)

    # Weighted composite
    composite = (
        aging_score * weights.aging_weight
        + concentration_score * weights.concentration_weight
        + margin_score * weights.margin_weight
    )

    # Build rationale
    rationale_parts: list[str] = []

    if aging_score >= 7:
        rationale_parts.append(
            f"Envelhecimento alto ({vehicle.days_in_stock} dias)"
        )
    if concentration_score >= 7:
        rationale_parts.append(
            f"Concentracao alta ({same_model_count} unidades do mesmo modelo)"
        )
    if margin_score >= 7:
        rationale_parts.append(
            f"Margem baixa ({vehicle.margin_percent:.1f}%)"
        )

    if not rationale_parts:
        rationale_parts.append("Pontuacao moderada em multiplos fatores")

    return B2BCandidate(
        brand=vehicle.brand,
        model=vehicle.model,
        year_model=vehicle.year_model,
        plate=vehicle.plate,
        days_in_stock=vehicle.days_in_stock,
        asking_price=vehicle.asking_price,
        purchase_cost=vehicle.purchase_cost,
        score=round(composite, 2),
        aging_score_component=aging_score,
        concentration_score_component=concentration_score,
        margin_score_component=margin_score,
        same_model_count=same_model_count,
        rationale=". ".join(rationale_parts) + ".",
    )


def identify_b2b_candidates(
    vehicles: list[Vehicle],
    weights: B2BScoringWeights,
    thresholds: AgingThresholds,
) -> list[B2BCandidate]:
    """Score all vehicles and return those above the B2B threshold.

    Args:
        vehicles: Full inventory list.
        weights: B2B scoring configuration.
        thresholds: Aging thresholds.

    Returns:
        List of B2B candidates (above score_threshold), sorted by score descending.
    """
    # Count model concentration across inventory
    model_counts: dict[str, int] = Counter(v.model_key for v in vehicles)

    # Score all vehicles
    all_candidates: list[B2BCandidate] = []
    for vehicle in vehicles:
        candidate = score_b2b_candidate(vehicle, model_counts, weights, thresholds)
        all_candidates.append(candidate)

    # Filter by threshold and sort
    candidates = [c for c in all_candidates if c.score >= weights.score_threshold]
    candidates.sort(key=lambda c: c.score, reverse=True)

    return candidates


def score_all_vehicles(
    vehicles: list[Vehicle],
    weights: B2BScoringWeights,
    thresholds: AgingThresholds,
) -> list[B2BCandidate]:
    """Score all vehicles regardless of threshold (for dashboard display).

    Args:
        vehicles: Full inventory list.
        weights: B2B scoring configuration.
        thresholds: Aging thresholds.

    Returns:
        All vehicles scored as B2BCandidate, sorted by score descending.
    """
    model_counts: dict[str, int] = Counter(v.model_key for v in vehicles)

    all_scored = [
        score_b2b_candidate(vehicle, model_counts, weights, thresholds)
        for vehicle in vehicles
    ]
    all_scored.sort(key=lambda c: c.score, reverse=True)
    return all_scored
