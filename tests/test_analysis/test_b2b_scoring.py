"""Tests for the B2B candidate scoring engine."""

from decimal import Decimal

from grand_brasil.analysis.b2b_scoring import (
    _calculate_aging_score,
    _calculate_concentration_score,
    _calculate_margin_score,
    identify_b2b_candidates,
    score_all_vehicles,
)
from grand_brasil.config import AgingThresholds, B2BScoringWeights
from grand_brasil.models.vehicle import Vehicle


class TestAgingScore:
    """Tests for aging score normalization."""

    def test_zero_days(self) -> None:
        """0 days = 0 urgency."""
        thresholds = AgingThresholds()
        assert _calculate_aging_score(0, thresholds) == 0.0

    def test_at_max_days(self) -> None:
        """At orange_max_days = 10.0."""
        thresholds = AgingThresholds(orange_max_days=90)
        assert _calculate_aging_score(90, thresholds) == 10.0

    def test_over_max_days(self) -> None:
        """Over max days still caps at 10.0."""
        thresholds = AgingThresholds(orange_max_days=90)
        assert _calculate_aging_score(200, thresholds) == 10.0

    def test_midpoint(self) -> None:
        """45 days with 90 max = 5.0."""
        thresholds = AgingThresholds(orange_max_days=90)
        assert _calculate_aging_score(45, thresholds) == 5.0


class TestConcentrationScore:
    """Tests for concentration score normalization."""

    def test_single_unit(self) -> None:
        """1 unit = 0 urgency."""
        assert _calculate_concentration_score(1, 3) == 0.0

    def test_at_limit(self) -> None:
        """At concentration limit = 10.0."""
        assert _calculate_concentration_score(3, 3) == 10.0

    def test_over_limit(self) -> None:
        """Over limit caps at 10.0."""
        assert _calculate_concentration_score(10, 3) == 10.0

    def test_two_units(self) -> None:
        """2 units with limit 3 = 5.0."""
        assert _calculate_concentration_score(2, 3) == 5.0


class TestMarginScore:
    """Tests for inverse margin score."""

    def test_zero_margin(self) -> None:
        """0% margin = maximum urgency (10.0)."""
        assert _calculate_margin_score(0.0) == 10.0

    def test_high_margin(self) -> None:
        """20%+ margin = 0 urgency."""
        assert _calculate_margin_score(20.0) == 0.0

    def test_ten_percent(self) -> None:
        """10% margin = 5.0."""
        assert _calculate_margin_score(10.0) == 5.0

    def test_negative_margin(self) -> None:
        """Negative margin = maximum urgency."""
        assert _calculate_margin_score(-5.0) == 10.0


class TestIdentifyB2BCandidates:
    """Tests for the full B2B candidate identification."""

    def test_returns_above_threshold(self, sample_vehicles: list[Vehicle]) -> None:
        """Only vehicles above score_threshold are returned."""
        weights = B2BScoringWeights(score_threshold=5.0)
        thresholds = AgingThresholds()
        candidates = identify_b2b_candidates(sample_vehicles, weights, thresholds)
        for c in candidates:
            assert c.score >= 5.0

    def test_sorted_by_score(self, sample_vehicles: list[Vehicle]) -> None:
        """Results sorted by score descending."""
        weights = B2BScoringWeights(score_threshold=0.0)
        thresholds = AgingThresholds()
        candidates = identify_b2b_candidates(sample_vehicles, weights, thresholds)
        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_concentration_detected(self) -> None:
        """Vehicles with model concentration get higher concentration score."""
        # 3 of the same model
        vehicles = [
            Vehicle(
                brand="CHEVROLET", model="ONIX 1.0", year_model=2021,
                days_in_stock=30, asking_price=Decimal("50000"),
                purchase_cost=Decimal("45000"),
            )
            for _ in range(3)
        ]
        weights = B2BScoringWeights(concentration_limit=3, score_threshold=0.0)
        thresholds = AgingThresholds()
        candidates = identify_b2b_candidates(vehicles, weights, thresholds)
        # All should have concentration_score = 10 (3 units = limit)
        for c in candidates:
            assert c.concentration_score_component == 10.0
            assert c.same_model_count == 3

    def test_empty_inventory(self) -> None:
        """Empty input returns empty list."""
        weights = B2BScoringWeights()
        thresholds = AgingThresholds()
        assert identify_b2b_candidates([], weights, thresholds) == []


class TestScoreAllVehicles:
    """Tests for scoring all vehicles (regardless of threshold)."""

    def test_returns_all(self, sample_vehicles: list[Vehicle]) -> None:
        """All vehicles are scored."""
        weights = B2BScoringWeights()
        thresholds = AgingThresholds()
        scored = score_all_vehicles(sample_vehicles, weights, thresholds)
        assert len(scored) == len(sample_vehicles)
