"""Tests for the aging analysis module."""

from decimal import Decimal

from grand_brasil.analysis.aging import (
    aging_distribution,
    analyze_aging_batch,
    classify_aging,
)
from grand_brasil.config import AgingThresholds
from grand_brasil.models.enums import AgingBracket
from grand_brasil.models.vehicle import Vehicle


class TestClassifyAging:
    """Tests for single vehicle aging classification."""

    def test_green_bracket(self) -> None:
        """Vehicle within green threshold."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=15, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        thresholds = AgingThresholds(
            green_max_days=30, yellow_max_days=60, orange_max_days=90
        )
        result = classify_aging(vehicle, thresholds)
        assert result.bracket == AgingBracket.GREEN

    def test_yellow_bracket(self) -> None:
        """Vehicle in yellow range."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=45, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        thresholds = AgingThresholds()
        result = classify_aging(vehicle, thresholds)
        assert result.bracket == AgingBracket.YELLOW

    def test_orange_bracket(self) -> None:
        """Vehicle in orange range."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=75, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        thresholds = AgingThresholds()
        result = classify_aging(vehicle, thresholds)
        assert result.bracket == AgingBracket.ORANGE

    def test_red_bracket(self) -> None:
        """Vehicle over 90 days = red."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=120, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        thresholds = AgingThresholds()
        result = classify_aging(vehicle, thresholds)
        assert result.bracket == AgingBracket.RED

    def test_boundary_green_exact(self) -> None:
        """Exactly at green threshold = green."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=30, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        thresholds = AgingThresholds()
        result = classify_aging(vehicle, thresholds)
        assert result.bracket == AgingBracket.GREEN

    def test_boundary_yellow_exact(self) -> None:
        """One day over green threshold = yellow."""
        vehicle = Vehicle(
            brand="CHEVROLET", model="ONIX", year_model=2021,
            days_in_stock=31, asking_price=Decimal("50000"),
            purchase_cost=Decimal("45000"),
        )
        thresholds = AgingThresholds()
        result = classify_aging(vehicle, thresholds)
        assert result.bracket == AgingBracket.YELLOW


class TestAnalyzeAgingBatch:
    """Tests for batch aging analysis."""

    def test_batch_sorted_descending(self, sample_vehicles: list[Vehicle]) -> None:
        """Results are sorted by days_in_stock descending."""
        thresholds = AgingThresholds()
        results = analyze_aging_batch(sample_vehicles, thresholds)
        days = [r.days_in_stock for r in results]
        assert days == sorted(days, reverse=True)

    def test_batch_returns_all_vehicles(self, sample_vehicles: list[Vehicle]) -> None:
        """All vehicles in input are present in output."""
        thresholds = AgingThresholds()
        results = analyze_aging_batch(sample_vehicles, thresholds)
        assert len(results) == len(sample_vehicles)


class TestAgingDistribution:
    """Tests for aging distribution counting."""

    def test_distribution_sums_to_total(self, sample_vehicles: list[Vehicle]) -> None:
        """Distribution counts sum to total vehicle count."""
        thresholds = AgingThresholds()
        results = analyze_aging_batch(sample_vehicles, thresholds)
        distribution = aging_distribution(results)
        total = sum(distribution.values())
        assert total == len(sample_vehicles)

    def test_empty_input(self) -> None:
        """Empty input returns zero counts."""
        distribution = aging_distribution([])
        assert all(v == 0 for v in distribution.values())
