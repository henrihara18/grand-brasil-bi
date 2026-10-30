"""Tests for grand_brasil/utils/brand_tier.py."""

from __future__ import annotations

import pytest

from grand_brasil.utils.brand_tier import (
    BrandTierConfig,
    classify_brand,
)


class TestClassifyBrand:
    def test_safe_brand(self):
        info = classify_brand("TOYOTA")
        assert info.tier == "SAFE"
        # A/B backtest showed team already prices SAFE correctly — baseline 0.0
        assert info.adjustment_pp == 0.0
        assert "SAFE" in info.reason

    def test_safe_brand_case_insensitive(self):
        info = classify_brand("toyota")
        assert info.tier == "SAFE"

    def test_safe_brand_with_whitespace(self):
        info = classify_brand("  Honda  ")
        assert info.tier == "SAFE"

    def test_risky_brand(self):
        info = classify_brand("FORD")
        assert info.tier == "RISKY"
        assert info.adjustment_pp == 2.0
        assert "RISKY" in info.reason

    def test_neutral_brand(self):
        info = classify_brand("VOLKSWAGEN")
        assert info.tier == "NEUTRAL"
        assert info.adjustment_pp == 0.0

    def test_jeep_is_neutral(self):
        """Jeep stays NEUTRAL — age/km channel probability handles its dynamics."""
        info = classify_brand("JEEP")
        assert info.tier == "NEUTRAL"

    def test_peugeot_is_risky(self):
        assert classify_brand("PEUGEOT").tier == "RISKY"

    def test_renault_is_risky(self):
        assert classify_brand("RENAULT").tier == "RISKY"

    def test_citroen_is_risky(self):
        assert classify_brand("CITROEN").tier == "RISKY"

    def test_hyundai_is_safe(self):
        assert classify_brand("HYUNDAI").tier == "SAFE"

    def test_unknown_brand_is_neutral(self):
        info = classify_brand("CHINA BRAND XYZ")
        assert info.tier == "NEUTRAL"
        assert info.adjustment_pp == 0.0

    def test_disabled_config_returns_neutral(self):
        cfg = BrandTierConfig(enabled=False)
        info = classify_brand("TOYOTA", cfg)
        assert info.tier == "NEUTRAL"
        assert info.adjustment_pp == 0.0
        assert "desativada" in info.reason.lower()

    def test_custom_config_overrides_defaults(self):
        cfg = BrandTierConfig(
            safe_brands=["BYD"],
            risky_brands=["TOYOTA"],
            safe_adjustment_pp=-3.0,
            risky_adjustment_pp=4.0,
        )
        assert classify_brand("BYD", cfg).adjustment_pp == -3.0
        assert classify_brand("TOYOTA", cfg).adjustment_pp == 4.0
        # HONDA no longer SAFE under this custom config
        assert classify_brand("HONDA", cfg).tier == "NEUTRAL"

    def test_adjustment_direction_invariant(self):
        """SAFE adjustment must be <= 0 (more aggressive); RISKY >= 0."""
        safe = classify_brand("TOYOTA")
        risky = classify_brand("FORD")
        assert safe.adjustment_pp <= 0
        assert risky.adjustment_pp >= 0

    def test_reason_mentions_brand_name(self):
        info = classify_brand("toyota")
        assert "TOYOTA" in info.reason


class TestBrandTierConfigDefaults:
    def test_defaults_have_three_safe_brands(self):
        cfg = BrandTierConfig()
        assert set(cfg.safe_brands) == {"TOYOTA", "HONDA", "HYUNDAI"}

    def test_defaults_have_four_risky_brands(self):
        cfg = BrandTierConfig()
        assert set(cfg.risky_brands) == {"FORD", "PEUGEOT", "RENAULT", "CITROEN"}

    def test_defaults_enabled(self):
        assert BrandTierConfig().enabled is True
