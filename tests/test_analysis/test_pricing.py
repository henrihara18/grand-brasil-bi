"""Tests for the price reduction recommendation engine."""

from decimal import Decimal

from grand_brasil.analysis.pricing import recommend_price, recommend_prices_batch
from grand_brasil.config import PriceReductionRule
from grand_brasil.models.vehicle import Vehicle


RULES = [
    PriceReductionRule(days_threshold=45, reduction_percent=5.0, min_margin_percent=3.0),
    PriceReductionRule(days_threshold=60, reduction_percent=10.0, min_margin_percent=2.0),
    PriceReductionRule(days_threshold=90, reduction_percent=15.0, min_margin_percent=1.0),
]


class TestRecommendPrice:
    """Tests for single vehicle price recommendation."""

    def test_no_recommendation_under_threshold(self) -> None:
        """Vehicle below lowest threshold gets no recommendation."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=30, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        result = recommend_price(vehicle, RULES)
        assert result is None

    def test_45_day_rule_applied(self) -> None:
        """Vehicle at 45 days gets 5% reduction."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=50, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        result = recommend_price(vehicle, RULES)
        assert result is not None
        assert result.reduction_percent > 0
        assert result.recommended_price < vehicle.asking_price

    def test_90_day_rule_most_severe(self) -> None:
        """Vehicle at 100 days gets the 90-day rule (15%)."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=100, asking_price=Decimal("50000"),
            purchase_cost=Decimal("40000"),
        )
        result = recommend_price(vehicle, RULES)
        assert result is not None
        # 15% of 50000 = 7500; recommended = 42500
        assert result.recommended_price <= Decimal("42500.00")

    def test_margin_floor_respected(self) -> None:
        """Reduction is capped when margin would drop below minimum."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=100, asking_price=Decimal("50000"),
            purchase_cost=Decimal("49000"),
        )
        result = recommend_price(vehicle, RULES)
        assert result is not None
        # Min margin is 1% for 90+ day rule
        # 49000 * 1.01 = 49490
        assert result.projected_margin_percent >= 1.0

    def test_fipe_warning_in_rationale(self) -> None:
        """Rationale mentions FIPE when recommended price goes below FIPE."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=100, asking_price=Decimal("50000"),
            purchase_cost=Decimal("40000"),
            fipe_price=Decimal("48000"),
        )
        result = recommend_price(vehicle, RULES)
        assert result is not None
        assert "FIPE" in result.rationale

    def test_empty_rules(self) -> None:
        """No rules returns None."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=100, asking_price=Decimal("50000"),
            purchase_cost=Decimal("40000"),
        )
        assert recommend_price(vehicle, []) is None


class TestRecommendPricesBatch:
    """Tests for batch price recommendations."""

    def test_batch_returns_only_eligible(self, sample_vehicles: list[Vehicle]) -> None:
        """Batch only returns vehicles that warrant reduction."""
        results = recommend_prices_batch(sample_vehicles, RULES)
        for rec in results:
            assert rec.days_in_stock >= 45  # Lowest threshold

    def test_batch_sorted_by_reduction(self, sample_vehicles: list[Vehicle]) -> None:
        """Results sorted by reduction_percent descending."""
        results = recommend_prices_batch(sample_vehicles, RULES)
        if len(results) > 1:
            reductions = [r.reduction_percent for r in results]
            assert reductions == sorted(reductions, reverse=True)
