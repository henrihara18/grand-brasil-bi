"""Tests for the Fase-4 buy-ratio refinements: tier order, recency, KM adjustment."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.purchase_ratio import (
    _tier_sequence,
    compute_buy_ratio,
    compute_km_slope,
)
from grand_brasil.config import BuyRatioConfig


def _row(model_red, year, km, ratio, status="UTILIZADO", date="2026-01-15"):
    return {
        "model_red": model_red, "year_model": year, "km": km, "ratio": ratio,
        "status_norm": status, "weight": 1.0 if status != "AVALIADO" else 0.25,
        "fipe_value": 100_000.0, "appraised_value": ratio * 100_000.0,
        "appraisal_date": pd.Timestamp(date),
    }


class TestTierOrder:
    def test_sequences(self):
        names = lambda order: [t.name for t in _tier_sequence(order, 6000, 12000, 24000)]
        assert names("year_first") == ["same_year_km6k", "same_year_km12k", "same_year", "year_pm1_km12k", "year_pm2_km24k"]
        assert names("km_first") == ["same_year_km6k", "same_year_km12k", "year_pm1_km12k", "year_pm2_km24k", "same_year"]

    def test_km_first_prefers_adjacent_year_with_km_over_same_year_without(self):
        rows = [_row("HB20", 2023, 90_000, 0.70) for _ in range(5)]          # same year, far KM
        rows += [_row("HB20", 2022, 30_000, 0.85) for _ in range(5)]         # adjacent year, KM matched
        df = pd.DataFrame(rows)
        legacy = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(tier_order="year_first"))
        km_first = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(tier_order="km_first"))
        assert legacy.tier == "same_year"
        assert km_first.tier == "year_pm1_km12k" and km_first.year_delta_applied


class TestRecency:
    def test_recent_rows_dominate_when_halflife_set(self):
        rows = [_row("HB20", 2023, 30_000, 0.70, date="2024-01-01") for _ in range(5)]   # old, low
        rows += [_row("HB20", 2023, 31_000, 0.90, date="2026-01-10") for _ in range(5)]  # recent, high
        df = pd.DataFrame(rows)
        off = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(recency_halflife_days=None),
                                reference_date=pd.Timestamp("2026-01-15"))
        on = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(recency_halflife_days=90),
                               reference_date=pd.Timestamp("2026-01-15"))
        assert off.ratio_median == pytest.approx(0.70, abs=0.11)   # weighted median lands at the boundary
        assert on.ratio_median == pytest.approx(0.90)

    def test_effective_sample_shrinks_with_recency(self):
        rows = [_row("HB20", 2023, 30_000, 0.80, date="2025-01-01") for _ in range(6)]
        df = pd.DataFrame(rows)
        on = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(recency_halflife_days=180),
                               reference_date=pd.Timestamp("2026-01-01"))
        assert on.sample_size == 6 and on.effective_sample < 3.0


class TestKmAdjust:
    def test_slope_recovers_within_group_relationship(self):
        rows = []
        for model in ("HB20", "CRETA"):
            for i in range(6):
                rows.append(_row(model, 2023, 10_000 + i * 10_000, 0.90 - 0.02 * i))   # -0.02 per 10k
        slope = compute_km_slope(pd.DataFrame(rows))
        assert slope == pytest.approx(-0.02, abs=1e-6)

    def test_slope_is_clipped_and_none_without_columns(self):
        rows = [_row("HB20", 2023, 10_000 + i * 10_000, 0.95 - 0.10 * i) for i in range(5)]
        assert compute_km_slope(pd.DataFrame(rows)) == -0.05
        assert compute_km_slope(pd.DataFrame([{"ratio": 0.8}])) is None

    def test_adjustment_moves_high_km_comparables_to_target(self):
        rows = [_row("HB20", 2023, 80_000, 0.70) for _ in range(5)]   # all 50k km above target
        df = pd.DataFrame(rows)
        off = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(km_adjust=False), km_slope=-0.02)
        on = compute_buy_ratio("HB20", 2023, 30_000, df, config=BuyRatioConfig(km_adjust=True), km_slope=-0.02)
        assert off.ratio_median == pytest.approx(0.70)
        assert on.ratio_median == pytest.approx(0.80)   # 0.70 + 0.02 * 5
        assert on.tier == "same_year"                    # no KM window matched; adjusted instead
