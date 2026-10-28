"""Tests for the dynamic target-margin engine (analysis/dynamic_margin.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.dynamic_margin import (
    compute_target_margin,
    _base_margin_for_band,
    _lookup_threshold,
)
from grand_brasil.config import DynamicMarginConfig


# ── Helpers ─────────────────────────────────────────────────────────────────


def _default_cfg() -> DynamicMarginConfig:
    return DynamicMarginConfig()


def _make_sale(
    model_red: str = "HYUNDAI CRETA",
    channel: str = "Loja",
    sale_price: float = 100_000,
    adjusted_cost: float = 88_000,
    days: int = 20,
) -> dict:
    return {
        "model_red": model_red.upper(),
        "sale_channel": channel,
        "sale_price": sale_price,
        "adjusted_cost": adjusted_cost,
        "days_in_stock": days,
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ── Base band lookup ────────────────────────────────────────────────────────


class TestBaseBand:
    def test_loja_cheap_band_20pct(self):
        cfg = _default_cfg()
        assert _base_margin_for_band(50_000, "Loja", cfg) == 20.0

    def test_loja_mid_band_12pct(self):
        cfg = _default_cfg()
        assert _base_margin_for_band(100_000, "Loja", cfg) == 12.0

    def test_loja_premium_band_10pct(self):
        cfg = _default_cfg()
        assert _base_margin_for_band(500_000, "Loja", cfg) == 10.0

    def test_loja_boundary_uses_inclusive_max(self):
        cfg = _default_cfg()
        # Exactly 60k should hit the first band (<=60k = 20%)
        assert _base_margin_for_band(60_000, "Loja", cfg) == 20.0
        # 60k + 1 falls into the next band
        assert _base_margin_for_band(60_001, "Loja", cfg) == 14.0

    def test_revenda_bands(self):
        cfg = _default_cfg()
        assert _base_margin_for_band(50_000, "Revenda", cfg) == 6.0
        assert _base_margin_for_band(80_000, "Revenda", cfg) == 3.5
        assert _base_margin_for_band(200_000, "Revenda", cfg) == 3.0

    def test_channel_case_insensitive(self):
        cfg = _default_cfg()
        assert _base_margin_for_band(50_000, "LOJA", cfg) == 20.0
        assert _base_margin_for_band(50_000, "loja", cfg) == 20.0
        assert _base_margin_for_band(80_000, "REVENDA", cfg) == 3.5


# ── Threshold lookup ────────────────────────────────────────────────────────


class TestLookupThreshold:
    def test_returns_highest_matching_threshold(self):
        cfg = _default_cfg()
        # Speed adjustments: >60 → 4.0, >45 → 2.0, >30 → 1.0
        assert _lookup_threshold(70.0, cfg.speed_adjustments) == 4.0
        assert _lookup_threshold(50.0, cfg.speed_adjustments) == 2.0
        assert _lookup_threshold(35.0, cfg.speed_adjustments) == 1.0
        assert _lookup_threshold(25.0, cfg.speed_adjustments) == 0.0

    def test_volatility_thresholds(self):
        cfg = _default_cfg()
        # Vol adjustments: >8 → 3.0, >6 → 2.0, >4 → 1.0
        assert _lookup_threshold(10.0, cfg.volatility_adjustments) == 3.0
        assert _lookup_threshold(7.0, cfg.volatility_adjustments) == 2.0
        assert _lookup_threshold(5.0, cfg.volatility_adjustments) == 1.0
        assert _lookup_threshold(3.0, cfg.volatility_adjustments) == 0.0

    def test_order_independent(self):
        """Rules declared out of order still produce the same result."""
        from grand_brasil.config import DynamicMarginAdjustment
        reversed_rules = [
            DynamicMarginAdjustment(threshold=30.0, adjustment_pp=1.0),
            DynamicMarginAdjustment(threshold=60.0, adjustment_pp=4.0),
            DynamicMarginAdjustment(threshold=45.0, adjustment_pp=2.0),
        ]
        assert _lookup_threshold(70.0, reversed_rules) == 4.0


# ── compute_target_margin ──────────────────────────────────────────────────


class TestComputeTargetMargin:
    def test_no_model_data_returns_base_only(self):
        cfg = _default_cfg()
        empty = pd.DataFrame(columns=[
            "model_red", "sale_channel", "sale_price", "adjusted_cost", "days_in_stock"
        ])
        r = compute_target_margin(100_000, "Loja", "UNKNOWN MODEL", empty, cfg)
        assert r.target_pct == 12.0
        assert r.base_pct == 12.0
        assert r.speed_adjustment_pp == 0.0
        assert r.volatility_adjustment_pp == 0.0

    def test_below_min_sample_skips_adjustments(self):
        cfg = _default_cfg()
        # Only 3 rows (< 10 = min_model_sample) → no adjustments
        rows = [_make_sale(days=120) for _ in range(3)]
        r = compute_target_margin(100_000, "Loja", "HYUNDAI CRETA", _df(rows), cfg)
        assert r.target_pct == 12.0
        assert r.speed_adjustment_pp == 0.0

    def test_slow_model_gets_speed_penalty(self):
        cfg = _default_cfg()
        # 15 rows, median_days=70 → speed +4pp
        rows = [
            _make_sale(days=70, sale_price=100_000, adjusted_cost=87_000)
            for _ in range(15)
        ]
        r = compute_target_margin(100_000, "Loja", "HYUNDAI CRETA", _df(rows), cfg)
        assert r.speed_adjustment_pp == 4.0
        assert r.base_pct == 12.0
        # Volatility is 0 (all margins identical) → no vol adjustment
        assert r.volatility_adjustment_pp == 0.0
        assert r.target_pct == 16.0
        assert r.model_sample_size == 15

    def test_volatile_model_gets_volatility_penalty(self):
        cfg = _default_cfg()
        # 15 rows all fast but with high margin variance → vol adjustment fires.
        # The exact magnitude depends on the resulting std (threshold bands
        # 4/6/8pp → 1/2/3pp). We assert that SOMETHING > 0 is added.
        import random
        random.seed(42)
        rows = []
        for _ in range(15):
            margin = random.choice([0.25, 0.05])
            sale = 100_000
            cost = sale * (1 - margin)
            rows.append(_make_sale(days=20, sale_price=sale, adjusted_cost=cost))
        r = compute_target_margin(100_000, "Loja", "HYUNDAI CRETA", _df(rows), cfg)
        assert r.speed_adjustment_pp == 0.0
        assert r.volatility_adjustment_pp >= 2.0  # std well above 6pp threshold
        assert r.target_pct >= 14.0

    def test_cap_applied_when_both_adjustments_fire(self):
        cfg = _default_cfg()
        # Slow (+4pp) + very volatile (+3pp) = 7pp, capped at 5
        import random
        random.seed(1)
        rows = []
        for _ in range(20):
            margin = random.choice([0.25, 0.00])  # huge swing
            sale = 100_000
            cost = sale * (1 - margin)
            rows.append(_make_sale(days=75, sale_price=sale, adjusted_cost=cost))
        r = compute_target_margin(100_000, "Loja", "HYUNDAI CRETA", _df(rows), cfg)
        assert r.capped is True
        # target = base (12) + cap (5) = 17, not 12+7=19
        assert r.target_pct == 12.0 + 5.0

    def test_channel_filter_respected(self):
        cfg = _default_cfg()
        # All Revenda rows — Loja query should not find them
        rows = [
            _make_sale(channel="Revenda", days=70, sale_price=100_000, adjusted_cost=88_000)
            for _ in range(15)
        ]
        r = compute_target_margin(100_000, "Loja", "HYUNDAI CRETA", _df(rows), cfg)
        # No Loja data → no adjustments
        assert r.speed_adjustment_pp == 0.0
        assert r.target_pct == 12.0

    def test_model_key_normalized(self):
        cfg = _default_cfg()
        rows = [
            _make_sale(model_red="HYUNDAI CRETA", days=70, adjusted_cost=88_000)
            for _ in range(15)
        ]
        r = compute_target_margin(100_000, "Loja", "hyundai creta", _df(rows), cfg)
        assert r.speed_adjustment_pp == 4.0

    def test_disabled_config_still_produces_base(self):
        """Calling with an enabled=False config isn't this module's job, but
        if called directly, it should still return a valid base."""
        cfg = DynamicMarginConfig(enabled=False)
        rows = [_make_sale(days=70, adjusted_cost=88_000) for _ in range(15)]
        r = compute_target_margin(100_000, "Loja", "HYUNDAI CRETA", _df(rows), cfg)
        # Module itself doesn't know about `enabled` — the caller does.
        # But the base should be correct.
        assert r.base_pct == 12.0


# ── Realistic scenarios from the analysis ──────────────────────────────────


class TestRealisticScenarios:
    """Based on the calibration examples presented to the user."""

    def test_byd_song_plus_premium_gets_conservative_margin(self):
        cfg = _default_cfg()
        # Price 180k → band 160-220k = 10%
        # Simulated: median days 58 (+2pp)
        rows = [
            _make_sale(model_red="BYD SONG PLUS", days=58,
                       sale_price=180_000, adjusted_cost=170_000)
            for _ in range(20)
        ]
        for i, r in enumerate(rows):
            if i % 3 == 0:
                r["adjusted_cost"] = 165_000  # higher margin outlier → adds variance
        r = compute_target_margin(
            180_000, "Loja", "BYD SONG PLUS", _df(rows), cfg
        )
        assert r.base_pct == 10.0
        assert r.speed_adjustment_pp == 2.0  # days_med = 58 is > 45 threshold
        assert r.target_pct >= 12.0

    def test_fast_predictable_model_keeps_base(self):
        cfg = _default_cfg()
        rows = [
            _make_sale(model_red="TOYOTA YARIS", days=15,
                       sale_price=90_000, adjusted_cost=79_000)
            for _ in range(20)
        ]
        r = compute_target_margin(90_000, "Loja", "TOYOTA YARIS", _df(rows), cfg)
        assert r.speed_adjustment_pp == 0.0
        assert r.volatility_adjustment_pp == 0.0
        assert r.target_pct == r.base_pct
