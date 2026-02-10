"""Price reduction recommendation engine.

Suggests price reductions based on aging thresholds, respecting
minimum margin constraints and FIPE reference prices.
"""

from decimal import Decimal

from grand_brasil.config import PriceReductionRule
from grand_brasil.models.analysis import PriceRecommendation
from grand_brasil.models.vehicle import Vehicle


def recommend_price(
    vehicle: Vehicle,
    rules: list[PriceReductionRule],
) -> PriceRecommendation | None:
    """Apply price reduction rules to a single vehicle.

    Rules are sorted by days_threshold descending; the first (most severe)
    rule that matches is applied.

    Logic:
    1. Find the most severe applicable rule (highest days_threshold that
       the vehicle exceeds).
    2. Calculate recommended_price = asking_price * (1 - reduction_percent/100).
    3. If projected margin < min_margin_percent, cap the reduction.
    4. If recommended price falls below FIPE, note it in the rationale.

    Args:
        vehicle: Vehicle to analyze.
        rules: List of price reduction rules from config.

    Returns:
        PriceRecommendation if a reduction is warranted, None otherwise.
    """
    if not rules:
        return None

    # Sort rules by threshold descending (most severe first)
    sorted_rules = sorted(rules, key=lambda r: r.days_threshold, reverse=True)

    # Find the first applicable rule
    applicable_rule: PriceReductionRule | None = None
    for rule in sorted_rules:
        if vehicle.days_in_stock >= rule.days_threshold:
            applicable_rule = rule
            break

    if applicable_rule is None:
        return None

    # Calculate recommended price
    reduction_factor = Decimal(str(1 - applicable_rule.reduction_percent / 100))
    recommended_price = vehicle.asking_price * reduction_factor

    # Calculate projected margin
    if vehicle.purchase_cost > 0:
        projected_margin_pct = float(
            (recommended_price - vehicle.purchase_cost)
            / vehicle.purchase_cost
            * 100
        )
    else:
        projected_margin_pct = 0.0

    # Cap reduction if margin goes below minimum
    capped = False
    if projected_margin_pct < applicable_rule.min_margin_percent:
        # Calculate the price that achieves min_margin_percent
        min_factor = Decimal(str(1 + applicable_rule.min_margin_percent / 100))
        recommended_price = vehicle.purchase_cost * min_factor
        projected_margin_pct = applicable_rule.min_margin_percent
        capped = True

    # Actual reduction percentage
    if vehicle.asking_price > 0:
        actual_reduction = float(
            (vehicle.asking_price - recommended_price)
            / vehicle.asking_price
            * 100
        )
    else:
        actual_reduction = 0.0

    # Build rationale in PT-BR
    rationale_parts: list[str] = []
    rationale_parts.append(
        f"Veiculo com {vehicle.days_in_stock} dias em estoque "
        f"(regra: {applicable_rule.days_threshold}+ dias = "
        f"{applicable_rule.reduction_percent}% reducao)."
    )

    if capped:
        rationale_parts.append(
            f"Reducao limitada para manter margem minima de "
            f"{applicable_rule.min_margin_percent}%."
        )

    if vehicle.fipe_price and recommended_price < vehicle.fipe_price:
        rationale_parts.append(
            f"ATENCAO: Preco sugerido abaixo da FIPE "
            f"(R$ {vehicle.fipe_price:,.2f})."
        )

    return PriceRecommendation(
        brand=vehicle.brand,
        model=vehicle.model,
        year_model=vehicle.year_model,
        plate=vehicle.plate,
        current_price=vehicle.asking_price,
        recommended_price=recommended_price.quantize(Decimal("0.01")),
        reduction_percent=round(actual_reduction, 2),
        days_in_stock=vehicle.days_in_stock,
        current_margin_percent=vehicle.margin_percent,
        projected_margin_percent=round(projected_margin_pct, 2),
        purchase_cost=vehicle.purchase_cost,
        fipe_price=vehicle.fipe_price,
        rationale=" ".join(rationale_parts),
    )


def recommend_prices_batch(
    vehicles: list[Vehicle],
    rules: list[PriceReductionRule],
) -> list[PriceRecommendation]:
    """Apply price recommendations to all eligible vehicles.

    Args:
        vehicles: List of vehicles to analyze.
        rules: Price reduction rules from config.

    Returns:
        List of recommendations (only for vehicles that warrant a reduction),
        sorted by reduction_percent descending.
    """
    recommendations: list[PriceRecommendation] = []

    for vehicle in vehicles:
        rec = recommend_price(vehicle, rules)
        if rec is not None:
            recommendations.append(rec)

    recommendations.sort(key=lambda r: r.reduction_percent, reverse=True)
    return recommendations
