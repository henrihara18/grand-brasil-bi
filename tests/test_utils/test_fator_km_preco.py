"""Tests for the brand-specific KM depreciation factors (utils/fator_km_preco.py).

Covers:
- km_referencia: 10k km per year of car age, min 10k
- get_fator_km: brand lookup with fallback to FATOR_KM_DEFAULT, case-insensitive
- ajuste_km_pct: sign conventions (less KM → positive, more KM → negative) and magnitude
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from grand_brasil.utils.fator_km_preco import (
    FATOR_KM,
    FATOR_KM_DEFAULT,
    ajuste_km_pct,
    get_fator_km,
    km_referencia,
)


# ── km_referencia ────────────────────────────────────────────────────────────


class TestKmReferencia:
    def _fake_now(self, year: int):
        """Return a patcher that pins datetime.now() to a given year."""
        return patch(
            "grand_brasil.utils.fator_km_preco.datetime",
            new=type("D", (), {"now": staticmethod(lambda: datetime(year, 6, 1))}),
        )

    def test_one_year_old(self):
        with self._fake_now(2026):
            assert km_referencia(2025) == 10_000

    def test_two_years_old(self):
        with self._fake_now(2026):
            assert km_referencia(2024) == 20_000

    def test_three_years_old(self):
        with self._fake_now(2026):
            assert km_referencia(2023) == 30_000

    def test_ten_years_old(self):
        with self._fake_now(2026):
            assert km_referencia(2016) == 100_000

    def test_same_year_returns_minimum_10k(self):
        """A brand-new zero-km car still gets a 10k reference."""
        with self._fake_now(2026):
            assert km_referencia(2026) == 10_000

    def test_future_year_returns_minimum_10k(self):
        """Protect against data entry errors with year > current."""
        with self._fake_now(2026):
            assert km_referencia(2027) == 10_000


# ── get_fator_km ─────────────────────────────────────────────────────────────


class TestGetFatorKm:
    def test_known_brand_loja(self):
        assert get_fator_km("TOYOTA", "Loja") == 0.022

    def test_known_brand_revenda(self):
        assert get_fator_km("TOYOTA", "Revenda") == 0.001

    def test_case_insensitive_brand(self):
        assert get_fator_km("toyota", "Loja") == 0.022
        assert get_fator_km("Toyota", "Loja") == 0.022
        assert get_fator_km("TOYOTA", "Loja") == 0.022

    def test_case_insensitive_canal(self):
        assert get_fator_km("TOYOTA", "loja") == 0.022
        assert get_fator_km("TOYOTA", "LOJA") == 0.022
        assert get_fator_km("TOYOTA", "Loja") == 0.022

    def test_brand_whitespace_trimmed(self):
        assert get_fator_km("  TOYOTA  ", "Loja") == 0.022

    def test_unknown_brand_falls_back_to_default(self):
        """Unknown brand returns the per-channel default."""
        assert get_fator_km("TESLA", "Loja") == FATOR_KM_DEFAULT["Loja"]
        assert get_fator_km("TESLA", "Revenda") == FATOR_KM_DEFAULT["Revenda"]

    def test_invalid_canal_falls_back_to_loja(self):
        """Typos or unknown channels default to Loja (safer choice)."""
        assert get_fator_km("TOYOTA", "Outro") == 0.022   # Loja value for Toyota
        assert get_fator_km("TOYOTA", "B2C") == 0.022

    def test_all_loja_brands_positive(self):
        for brand, fator in FATOR_KM["Loja"].items():
            assert 0 < fator < 0.10, f"{brand} Loja fator fora do range: {fator}"

    def test_all_revenda_brands_positive(self):
        for brand, fator in FATOR_KM["Revenda"].items():
            assert 0 < fator < 0.10, f"{brand} Revenda fator fora do range: {fator}"


# ── ajuste_km_pct ────────────────────────────────────────────────────────────


class TestAjusteKmPct:
    def _fake_now(self, year: int):
        return patch(
            "grand_brasil.utils.fator_km_preco.datetime",
            new=type("D", (), {"now": staticmethod(lambda: datetime(year, 6, 1))}),
        )

    def test_km_equals_reference_zero_adjustment(self):
        """KM real == KM de referência → ajuste zero."""
        with self._fake_now(2026):
            # 2024 → ref 20k, if car has exactly 20k KM → no adjustment
            assert ajuste_km_pct("TOYOTA", "Loja", 20_000, 2024) == 0.0

    def test_less_km_than_reference_positive_adjustment(self):
        """Fewer KM than reference → car is worth MORE (positive adjustment)."""
        with self._fake_now(2026):
            # 2024 → ref 20k. Car has 10k (10k below). Fator Loja Toyota = 0.022
            # ajuste = -0.022 × (10k - 20k) / 10k = -0.022 × (-1) = +0.022
            result = ajuste_km_pct("TOYOTA", "Loja", 10_000, 2024)
            assert result == pytest.approx(0.022, abs=0.001)

    def test_more_km_than_reference_negative_adjustment(self):
        """More KM than reference → car is worth LESS (negative adjustment)."""
        with self._fake_now(2026):
            # 2024 → ref 20k. Car has 40k (20k above). Fator Loja Toyota = 0.022
            # ajuste = -0.022 × (40k - 20k) / 10k = -0.022 × 2 = -0.044
            result = ajuste_km_pct("TOYOTA", "Loja", 40_000, 2024)
            assert result == pytest.approx(-0.044, abs=0.001)

    def test_adjustment_scales_linearly_with_km_delta(self):
        """Double the KM delta → double the adjustment magnitude."""
        with self._fake_now(2026):
            small = ajuste_km_pct("HYUNDAI", "Loja", 30_000, 2024)   # delta +10k
            big = ajuste_km_pct("HYUNDAI", "Loja", 40_000, 2024)     # delta +20k
            assert big == pytest.approx(small * 2, abs=0.001)

    def test_revenda_uses_different_factors_than_loja(self):
        """Revenda should give a different (usually smaller) adjustment."""
        with self._fake_now(2026):
            loja = ajuste_km_pct("TOYOTA", "Loja", 40_000, 2024)        # -0.044
            revenda = ajuste_km_pct("TOYOTA", "Revenda", 40_000, 2024)  # smaller
            # Toyota Revenda is 0.001 → ajuste ≈ -0.002
            assert abs(revenda) < abs(loja)

    def test_unknown_brand_uses_default_factor(self):
        """Unknown brand uses the channel default factor."""
        with self._fake_now(2026):
            expected = -FATOR_KM_DEFAULT["Loja"] * (30_000 - 20_000) / 10_000
            got = ajuste_km_pct("SPACEX ROADSTER", "Loja", 30_000, 2024)
            assert got == pytest.approx(expected, abs=0.001)


# ── Piecewise (non-linear) curve ─────────────────────────────────────────────


class TestAjusteKmPctPiecewise:
    """Tests for the non-linear piecewise KM curve (km_curve.enabled=True)."""

    def _fake_now(self, year: int):
        return patch(
            "grand_brasil.utils.fator_km_preco.datetime",
            new=type("D", (), {"now": staticmethod(lambda: datetime(year, 6, 1))}),
        )

    def _default_curve(self):
        """Curve matching the production defaults in config.yaml."""
        from grand_brasil.config import KMCurveConfig, KMCurveSegment
        return KMCurveConfig(
            enabled=True,
            segments=[
                KMCurveSegment(km_max=20_000,     pp_per_10k=0.5),
                KMCurveSegment(km_max=50_000,     pp_per_10k=1.2),
                KMCurveSegment(km_max=100_000,    pp_per_10k=1.6),
                KMCurveSegment(km_max=160_000,    pp_per_10k=1.0),
                KMCurveSegment(km_max=10_000_000, pp_per_10k=0.7),
            ],
        )

    def test_disabled_curve_falls_back_to_linear(self):
        from grand_brasil.config import KMCurveConfig
        curve = KMCurveConfig(enabled=False)
        with self._fake_now(2026):
            linear = ajuste_km_pct("TOYOTA", "Loja", 40_000, 2024)
            piece = ajuste_km_pct("TOYOTA", "Loja", 40_000, 2024, km_curve=curve)
            assert piece == pytest.approx(linear)

    def test_km_equals_reference_zero_adjustment(self):
        """Still zero at the reference, regardless of mode."""
        curve = self._default_curve()
        with self._fake_now(2026):
            assert ajuste_km_pct("TOYOTA", "Loja", 20_000, 2024, km_curve=curve) == 0.0

    def test_low_km_band_shallower_decay_than_mid_band(self):
        """Going 20k→40k (in the 1.2pp/10k band) costs MORE than 0→20k (0.5pp/10k band).

        Same brand (default multiplier=1), same KM delta (20k), but the mid-range
        band has a higher marginal pp → bigger adjustment magnitude.
        """
        curve = self._default_curve()
        with self._fake_now(2026):
            # Reference = 20k (model 2024 in 2026). Test 0-20k band vs 20-40k band.
            # Car with 0 km (20k below ref) → integrates 0→20k band (0.5pp/10k).
            low_band = ajuste_km_pct("TOYOTA", "Loja", 0, 2024, km_curve=curve)
            # Car with 40k (20k above ref) → integrates 20k→40k band (1.2pp/10k).
            mid_band = ajuste_km_pct("TOYOTA", "Loja", 40_000, 2024, km_curve=curve)
            assert abs(mid_band) > abs(low_band)

    def test_peak_band_steepest(self):
        """50-100k band should be the steepest (empirical peak at 1.6pp/10k)."""
        curve = self._default_curve()
        with self._fake_now(2026):
            # Use a 2016 model → ref = 100k. Going to 150k hits 100-160k (1.0pp) only.
            #   expected: 50k × 1.0pp/10k = 5pp
            upper_tail = ajuste_km_pct("TOYOTA", "Loja", 150_000, 2016, km_curve=curve)
            # Use a 2021 model → ref = 50k. Going to 100k hits 50-100k band (1.6pp).
            #   expected: 50k × 1.6pp/10k = 8pp
            peak = ajuste_km_pct("TOYOTA", "Loja", 100_000, 2021, km_curve=curve)
            assert abs(peak) > abs(upper_tail)

    def test_brand_multiplier_scales_result(self):
        """A brand with 2x the default linear factor should yield ~2x the piecewise adjustment."""
        from grand_brasil.utils.fator_km_preco import FATOR_KM, FATOR_KM_DEFAULT
        curve = self._default_curve()
        # BYD Loja = 0.031, default = 0.021 → multiplier ≈ 1.476
        ratio = FATOR_KM["Loja"]["BYD"] / FATOR_KM_DEFAULT["Loja"]
        with self._fake_now(2026):
            byd = ajuste_km_pct("BYD", "Loja", 60_000, 2024, km_curve=curve)
            default = ajuste_km_pct("UNKNOWNBRAND", "Loja", 60_000, 2024, km_curve=curve)
            assert byd == pytest.approx(default * ratio, rel=0.01)

    def test_negative_delta_is_symmetric(self):
        """Car with less KM than ref gets a positive adjustment symmetric to a car with more KM."""
        curve = self._default_curve()
        with self._fake_now(2026):
            # 2021 → ref = 50k. Two cars, symmetric: 30k (−20k) and 70k (+20k).
            below = ajuste_km_pct("TOYOTA", "Loja", 30_000, 2021, km_curve=curve)
            above = ajuste_km_pct("TOYOTA", "Loja", 70_000, 2021, km_curve=curve)
            # They integrate over different bands so they won't be exactly symmetric
            # in magnitude, but signs must be opposite and both non-zero.
            assert below > 0
            assert above < 0

    def test_high_km_tail_is_gentler(self):
        """Beyond 160k the curve flattens (0.7pp/10k) — less brutal than peak."""
        curve = self._default_curve()
        with self._fake_now(2026):
            # 2010 → ref = 160k. Going to 200k integrates 40k @ 0.7pp/10k = 2.8pp
            # For default brand, multiplier=1 → -0.028
            tail = ajuste_km_pct("UNKNOWNBRAND", "Loja", 200_000, 2010, km_curve=curve)
            assert tail == pytest.approx(-0.028, abs=0.002)
