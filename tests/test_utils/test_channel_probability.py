"""Tests for grand_brasil/utils/channel_probability.py."""

from __future__ import annotations

import pytest

from grand_brasil.utils.channel_probability import (
    ChannelProbabilityConfig,
    _age_bucket,
    _km_bucket,
    predict_channel_probability,
)


class TestKmBucket:
    def test_none_km_returns_first_bucket(self):
        assert _km_bucket(None) == "0-30k"

    def test_zero_km(self):
        assert _km_bucket(0) == "0-30k"

    def test_edge_30k(self):
        # Upper bound is exclusive
        assert _km_bucket(29_999) == "0-30k"
        assert _km_bucket(30_000) == "30-60k"

    def test_edge_90k(self):
        assert _km_bucket(89_999) == "60-90k"
        assert _km_bucket(90_000) == "90-120k"

    def test_very_high_km(self):
        assert _km_bucket(500_000) == "150k+"

    def test_negative_km_returns_first_bucket(self):
        assert _km_bucket(-1) == "0-30k"


class TestAgeBucket:
    def test_new_car(self):
        assert _age_bucket(0) == "0-2"
        assert _age_bucket(2) == "0-2"

    def test_boundary_3(self):
        assert _age_bucket(3) == "3-4"

    def test_mid(self):
        assert _age_bucket(5) == "5-7"
        assert _age_bucket(7) == "5-7"

    def test_older(self):
        assert _age_bucket(8) == "8-11"
        assert _age_bucket(11) == "8-11"

    def test_very_old(self):
        assert _age_bucket(20) == "12+"

    def test_negative_age_clamped(self):
        assert _age_bucket(-3) == "0-2"


class TestPredictChannelProbability:
    def test_safe_new_low_km(self):
        """Toyota 2025 with 15k km in 2026 — tier SAFE, age 0-2, km 0-30k."""
        info = predict_channel_probability(
            brand="TOYOTA", km=15_000, year_model=2025, reference_year=2026
        )
        assert info.tier == "SAFE"
        assert info.age_bucket == "0-2"
        assert info.km_bucket == "0-30k"
        assert info.p_revenda == 0.05
        assert info.p_loja == 0.95
        assert not info.is_revenda_profile

    def test_risky_old_high_km(self):
        """Ford 2014 with 180k km in 2026 — should be near-certain Revenda."""
        info = predict_channel_probability(
            brand="FORD", km=180_000, year_model=2014, reference_year=2026
        )
        assert info.tier == "RISKY"
        assert info.age_bucket == "12+"
        assert info.km_bucket == "150k+"
        assert info.p_revenda >= 0.95
        assert info.is_revenda_profile

    def test_neutral_mid(self):
        """VW 2022 (4 anos) 70k km -> NEUTRAL, 3-4, 60-90k."""
        info = predict_channel_probability(
            brand="VOLKSWAGEN", km=70_000, year_model=2022, reference_year=2026
        )
        assert info.tier == "NEUTRAL"
        assert info.age_bucket == "3-4"
        assert info.km_bucket == "60-90k"
        assert 0.0 < info.p_revenda < 1.0

    def test_revenda_profile_threshold_triggers(self):
        """Ford 2019 120k km should cross the 0.70 threshold."""
        info = predict_channel_probability(
            brand="FORD", km=125_000, year_model=2019, reference_year=2026
        )
        assert info.is_revenda_profile
        assert info.p_revenda >= 0.70

    def test_revenda_profile_threshold_respects_custom_config(self):
        cfg = ChannelProbabilityConfig(revenda_profile_threshold=0.99)
        info = predict_channel_probability(
            brand="FORD", km=100_000, year_model=2019,
            reference_year=2026, config=cfg,
        )
        # With a 99% threshold, only the most extreme profiles trigger
        assert not info.is_revenda_profile or info.p_revenda >= 0.99

    def test_disabled_returns_neutral_default(self):
        cfg = ChannelProbabilityConfig(enabled=False)
        info = predict_channel_probability(
            brand="TOYOTA", km=10_000, year_model=2024,
            reference_year=2026, config=cfg,
        )
        assert info.p_revenda == 0.5
        assert info.p_loja == 0.5
        assert "desativada" in info.reason.lower()

    def test_future_year_model_clamps_age_to_zero(self):
        """Model year > reference year => age clamped to 0."""
        info = predict_channel_probability(
            brand="TOYOTA", km=0, year_model=2030, reference_year=2026
        )
        assert info.age_bucket == "0-2"

    def test_probabilities_sum_to_one(self):
        info = predict_channel_probability(
            brand="HYUNDAI", km=50_000, year_model=2020, reference_year=2026
        )
        assert pytest.approx(info.p_revenda + info.p_loja) == 1.0

    def test_reason_includes_tier_and_buckets(self):
        info = predict_channel_probability(
            brand="HONDA", km=40_000, year_model=2020, reference_year=2026
        )
        assert "SAFE" in info.reason
        assert info.km_bucket in info.reason
        assert info.age_bucket in info.reason

    def test_monotonicity_across_km_same_age_tier(self):
        """Within a tier and age bucket, p_revenda is non-decreasing in km."""
        brand = "VOLKSWAGEN"
        year_model = 2022   # age 4 -> bucket 3-4
        ref_year = 2026
        kms = [10_000, 40_000, 75_000, 100_000, 130_000, 200_000]
        ps = [
            predict_channel_probability(
                brand=brand, km=k, year_model=year_model, reference_year=ref_year
            ).p_revenda
            for k in kms
        ]
        for i in range(1, len(ps)):
            assert ps[i] >= ps[i - 1], f"p_revenda dropped from {ps[i-1]} at {kms[i-1]}km to {ps[i]} at {kms[i]}km"

    def test_monotonicity_across_age_same_km_tier(self):
        """Within a tier and km bucket, p_revenda is non-decreasing in age."""
        brand = "VOLKSWAGEN"
        km = 40_000
        ref_year = 2026
        years = [2026, 2022, 2020, 2016, 2010]  # ages 0, 4, 6, 10, 16
        ps = [
            predict_channel_probability(
                brand=brand, km=km, year_model=y, reference_year=ref_year
            ).p_revenda
            for y in years
        ]
        for i in range(1, len(ps)):
            assert ps[i] >= ps[i - 1]

    def test_tier_ordering_holds_on_average(self):
        """Across the full profile grid, RISKY >= NEUTRAL >= SAFE on average.

        Note: empirical data has noise and the ordering can flip in isolated
        cells (especially where RISKY has few observations and stays on the
        prior while NEUTRAL reflects a strong sample). The average ordering
        is what the tier concept ultimately promises.
        """
        ref = 2026
        safes, neus, riskies = [], [], []
        for year in (2026, 2022, 2020, 2016, 2010):
            for km in (10_000, 40_000, 75_000, 100_000, 130_000, 200_000):
                safes.append(predict_channel_probability("TOYOTA", km, year, ref).p_revenda)
                neus.append(predict_channel_probability("VOLKSWAGEN", km, year, ref).p_revenda)
                riskies.append(predict_channel_probability("FORD", km, year, ref).p_revenda)
        avg_safe = sum(safes) / len(safes)
        avg_neu = sum(neus) / len(neus)
        avg_risky = sum(riskies) / len(riskies)
        assert avg_risky >= avg_neu >= avg_safe

    def test_tier_ordering_at_high_age_high_km(self):
        """For a clearly Revenda-leaning profile (old car, high km), the
        tier ordering is preserved because most cells saturate at 1.0."""
        ref = 2026
        safe = predict_channel_probability("TOYOTA", 200_000, 2012, ref).p_revenda
        neu = predict_channel_probability("VOLKSWAGEN", 200_000, 2012, ref).p_revenda
        risky = predict_channel_probability("FORD", 200_000, 2012, ref).p_revenda
        assert risky >= neu >= safe

    def test_probability_bounds(self):
        """All returned probabilities are in [0, 1]."""
        for brand in ("TOYOTA", "FORD", "VOLKSWAGEN"):
            for km in (0, 50_000, 200_000):
                for year in (2026, 2020, 2010):
                    info = predict_channel_probability(
                        brand=brand, km=km, year_model=year, reference_year=2026
                    )
                    assert 0.0 <= info.p_revenda <= 1.0
                    assert 0.0 <= info.p_loja <= 1.0
