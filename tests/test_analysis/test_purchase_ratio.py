"""Tests for the buy-ratio engine (analysis/purchase_ratio.py).

Covers:
- Tiered matching (same_year_km6k → same_year_km12k → same_year → year±1 → year±2 → fallback)
- Year-delta adjustment using the empirical ratio profile
- Weighted median (closed-deal weight 1.0, AVALIADO weight 0.4)
- "Closed-deal first" policy: AVALIADO only used when UTILIZADO < 5
- Empty / missing / edge cases
"""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.purchase_ratio import (
    BuyRatioResult,
    _weighted_quantile,
    compute_buy_ratio,
    compute_year_ratio_profile,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _row(
    model_red: str,
    year_model: int,
    km: int | None,
    ratio: float,
    status: str = "UTILIZADO",
    weight: float | None = None,
) -> dict:
    """Build one synthetic appraisal row in the shape produced by appraisal_history."""
    return {
        "model_red": model_red.upper(),
        "year_model": year_model,
        "km": km,
        "ratio": ratio,
        "status_norm": status,
        "weight": weight if weight is not None else (1.0 if status in {"UTILIZADO", "REPASSE"} else 0.4),
        "fipe_value": 100_000.0,
        "appraised_value": ratio * 100_000.0,
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ── _weighted_quantile ───────────────────────────────────────────────────────


class TestWeightedQuantile:
    def test_all_equal_weights_matches_plain_quantile(self):
        v = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        w = pd.Series([1.0] * 5)
        assert _weighted_quantile(v, w, 0.5) == pytest.approx(3.0, abs=0.01)

    def test_heavier_weight_shifts_median(self):
        # Value 1.0 gets 10x weight → median should move toward 1.0
        v = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        w = pd.Series([10.0, 1.0, 1.0, 1.0, 1.0])
        assert _weighted_quantile(v, w, 0.5) == pytest.approx(1.0, abs=0.01)

    def test_zero_weights_fallback_to_unweighted(self):
        v = pd.Series([1.0, 2.0, 3.0])
        w = pd.Series([0.0, 0.0, 0.0])
        assert _weighted_quantile(v, w, 0.5) == 2.0

    def test_quartiles(self):
        v = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        w = pd.Series([1.0] * 5)
        assert _weighted_quantile(v, w, 0.25) == pytest.approx(20.0, abs=0.01)
        assert _weighted_quantile(v, w, 0.75) == pytest.approx(40.0, abs=0.01)


# ── compute_year_ratio_profile ───────────────────────────────────────────────


class TestYearRatioProfile:
    def test_builds_profile_per_year(self):
        df = _df([
            _row("HYUNDAI CRETA", 2023, 30_000, 0.85),
            _row("HYUNDAI CRETA", 2023, 50_000, 0.87),
            _row("HYUNDAI CRETA", 2024, 20_000, 0.89),
            _row("HYUNDAI CRETA", 2024, 40_000, 0.88),
            _row("TOYOTA COROLLA", 2023, 25_000, 0.92),
        ])
        profile = compute_year_ratio_profile(df)
        assert 2023 in profile and 2024 in profile
        assert profile[2023] == pytest.approx(0.87, abs=0.02)  # includes corolla 0.92
        assert profile[2024] == pytest.approx(0.885, abs=0.01)

    def test_empty_df_returns_empty_profile(self):
        assert compute_year_ratio_profile(pd.DataFrame()) == {}

    def test_df_missing_required_columns_returns_empty(self):
        df = pd.DataFrame({"some_other_col": [1, 2, 3]})
        assert compute_year_ratio_profile(df) == {}

    def test_weighted_when_mixed_statuses(self):
        # 3 AVALIADO at 0.80, 1 UTILIZADO at 0.90
        # UTILIZADO weight 1.0, AVALIADO weight 0.4 → effective 1.0 vs 1.2
        df = _df([
            _row("X Y", 2024, 10_000, 0.80, status="AVALIADO"),
            _row("X Y", 2024, 10_000, 0.80, status="AVALIADO"),
            _row("X Y", 2024, 10_000, 0.80, status="AVALIADO"),
            _row("X Y", 2024, 10_000, 0.90, status="UTILIZADO"),
        ])
        profile = compute_year_ratio_profile(df)
        # Weighted median should lean toward 0.80 (more total weight) but not 0.80 exactly
        assert 0.80 <= profile[2024] <= 0.90


# ── compute_buy_ratio — tiered matching ──────────────────────────────────────


class TestTieredMatching:
    def test_tier1_same_year_km6k(self):
        """5+ rows with same year and KM within ±6k → use only those."""
        df = _df([
            _row("HYUNDAI CRETA", 2023, 30_000, 0.85),
            _row("HYUNDAI CRETA", 2023, 32_000, 0.86),
            _row("HYUNDAI CRETA", 2023, 28_000, 0.84),
            _row("HYUNDAI CRETA", 2023, 34_000, 0.87),
            _row("HYUNDAI CRETA", 2023, 31_000, 0.85),
            _row("HYUNDAI CRETA", 2023, 80_000, 0.70),   # outside KM window
        ])
        result = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df)
        assert result.available
        assert result.tier == "same_year_km6k"
        assert result.sample_size == 5
        assert result.ratio_median == pytest.approx(0.85, abs=0.02)

    def test_tier2_falls_back_to_km12k(self):
        """< 5 in tight window but >= 5 in wider window → use wider."""
        df = _df([
            _row("HB20", 2023, 20_000, 0.88),
            _row("HB20", 2023, 22_000, 0.89),   # within 6k
            _row("HB20", 2023, 40_000, 0.82),   # outside 6k but within 12k
            _row("HB20", 2023, 42_000, 0.81),
            _row("HB20", 2023, 44_000, 0.80),
            _row("HB20", 2023, 35_000, 0.83),
        ])
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        assert result.available
        assert result.tier in {"same_year_km12k", "same_year_km6k"}

    def test_tier3_same_year_no_km_window(self):
        """Widely scattered KMs in same year → falls to same_year tier."""
        df = _df([
            _row("TOYOTA ETIOS", 2020, 10_000, 0.80),
            _row("TOYOTA ETIOS", 2020, 70_000, 0.72),
            _row("TOYOTA ETIOS", 2020, 120_000, 0.65),
            _row("TOYOTA ETIOS", 2020, 150_000, 0.60),
            _row("TOYOTA ETIOS", 2020, 50_000, 0.75),
        ])
        # Request km=300k (nothing close in window), must degrade to same_year
        result = compute_buy_ratio("TOYOTA ETIOS", 2020, 300_000, df)
        assert result.available
        assert result.tier == "same_year"
        assert result.sample_size == 5

    def test_tier4_adjacent_year_with_adjustment(self):
        """Target year has no data, ±1 does. Year adjustment must shift ratio."""
        rows = []
        # Profile-building rows across many models/years
        for y, base in [(2022, 0.85), (2023, 0.87), (2024, 0.89)]:
            for _ in range(10):
                rows.append(_row(f"COMMON MODEL", y, 30_000, base))
        # Rare model only in 2022 and 2024, need 2023 appraisal
        for _ in range(6):
            rows.append(_row("RARE MODEL", 2022, 50_000, 0.84))
        df = _df(rows)

        profile = compute_year_ratio_profile(df)
        result = compute_buy_ratio("RARE MODEL", 2023, 50_000, df, profile)
        assert result.available
        assert result.year_delta_applied is True
        # Adjusted ratio should be >= the 2022 base since 2023 has higher typical ratio
        assert result.ratio_median > 0.84

    def test_model_not_found_returns_empty(self):
        df = _df([_row("HB20", 2023, 30_000, 0.85)])
        result = compute_buy_ratio("PORSCHE 911 GT3", 2024, 10_000, df)
        assert not result.available
        assert "Sem avaliacoes historicas" in result.description

    def test_insufficient_sample_returns_empty(self):
        # Only 2 rows — below MIN_FALLBACK_SAMPLE (3)
        df = _df([
            _row("EXOTIC", 2023, 30_000, 0.85),
            _row("EXOTIC", 2023, 35_000, 0.86),
        ])
        result = compute_buy_ratio("EXOTIC", 2023, 30_000, df)
        assert not result.available

    def test_km_none_skips_km_tiers_and_uses_same_year(self):
        df = _df([
            _row("HB20", 2023, 20_000, 0.88),
            _row("HB20", 2023, 40_000, 0.82),
            _row("HB20", 2023, 60_000, 0.78),
            _row("HB20", 2023, 80_000, 0.74),
            _row("HB20", 2023, 100_000, 0.70),
        ])
        result = compute_buy_ratio("HB20", 2023, None, df)
        assert result.available
        assert result.tier == "same_year"


# ── Closed-deal-first policy ─────────────────────────────────────────────────


class TestClosedDealFirstPolicy:
    def test_uses_only_closed_when_enough(self):
        """5+ UTILIZADO exists → AVALIADO rows are ignored entirely."""
        df = _df(
            [_row("HB20", 2023, 30_000, 0.90, status="UTILIZADO") for _ in range(5)]
            + [_row("HB20", 2023, 30_000, 0.75, status="AVALIADO") for _ in range(20)]
        )
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        assert result.available
        assert result.closed_deal_count == 5
        assert result.offered_count == 0          # AVALIADO NOT included
        assert result.ratio_median == pytest.approx(0.90, abs=0.02)

    def test_falls_back_to_avaliado_when_closed_insufficient(self):
        """< 5 UTILIZADO → include AVALIADO as fallback with weight 0.4."""
        df = _df(
            [_row("HB20", 2023, 30_000, 0.88, status="UTILIZADO") for _ in range(2)]
            + [_row("HB20", 2023, 30_000, 0.82, status="AVALIADO") for _ in range(10)]
        )
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        assert result.available
        assert result.closed_deal_count == 2
        assert result.offered_count == 10
        # Weighted median: 2 closed (weight 1.0) + 10 offered (weight 0.4) → 2.0 vs 4.0
        # AVALIADO dominates → median should lean toward 0.82
        assert 0.82 <= result.ratio_median <= 0.88

    def test_repasse_counts_as_closed_deal(self):
        """REPASSE has weight 1.0 like UTILIZADO."""
        df = _df(
            [_row("HB20", 2023, 30_000, 0.90, status="REPASSE") for _ in range(5)]
        )
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        assert result.available
        assert result.closed_deal_count == 5
        assert result.offered_count == 0


# ── Confidence band (P25/P75) ────────────────────────────────────────────────


class TestConfidenceBand:
    def test_p25_lt_median_lt_p75(self):
        ratios = [0.75, 0.78, 0.82, 0.85, 0.88, 0.90, 0.92]
        df = _df([_row("HB20", 2023, 30_000, r) for r in ratios])
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        assert result.ratio_p25 < result.ratio_median < result.ratio_p75

    def test_band_useful_for_pricing(self):
        df = _df([_row("HB20", 2023, 30_000, 0.80 + i * 0.01) for i in range(10)])
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        low, high = result.band_at(100_000.0)
        assert low < 100_000.0 * result.ratio_median < high


# ── price_at helper ──────────────────────────────────────────────────────────


class TestPriceAt:
    def test_applies_ratio_to_fipe(self):
        df = _df([_row("HB20", 2023, 30_000, 0.85) for _ in range(5)])
        result = compute_buy_ratio("HB20", 2023, 30_000, df)
        assert result.price_at(100_000.0) == pytest.approx(85_000.0, abs=500)

    def test_returns_none_when_unavailable(self):
        # Model exists but only with 2 rows → below the minimum fallback threshold
        df = _df([
            _row("NOTHING", 2023, 30_000, 0.85),
            _row("NOTHING", 2023, 35_000, 0.86),
        ])
        result = compute_buy_ratio("NOTHING", 2023, 30_000, df)
        assert result.price_at(100_000.0) is None


# ── Family fallback (trim-level model_red → family in the appraisal base) ────


class TestFamilyFallback:
    def _base(self) -> pd.DataFrame:
        return _df([_row("HYUNDAI CRETA", 2023, 30_000 + i * 1_000, 0.85 + i * 0.01) for i in range(6)])

    def test_trim_key_falls_back_to_family(self):
        r = compute_buy_ratio("HYUNDAI CRETA LIMITED", 2023, 32_000, self._base())
        assert r.available
        assert r.model_key_used == "HYUNDAI CRETA"
        assert r.family_fallback is True
        assert r.tier == "same_year_km6k"
        assert "HYUNDAI CRETA LIMITED" in r.description and "familia HYUNDAI CRETA" in r.description

    def test_multi_token_trim_strips_until_family_matches(self):
        r = compute_buy_ratio("HYUNDAI CRETA N LINE NIGHT EDITION", 2023, 32_000, self._base())
        assert r.available and r.model_key_used == "HYUNDAI CRETA"

    def test_exact_key_has_no_fallback_flag(self):
        r = compute_buy_ratio("HYUNDAI CRETA", 2023, 32_000, self._base())
        assert r.available and r.family_fallback is False and r.model_key_used == "HYUNDAI CRETA"

    def test_exact_trim_rows_win_over_family(self):
        rows = [_row("HYUNDAI CRETA", 2023, 30_000, 0.80) for _ in range(6)]
        rows += [_row("HYUNDAI CRETA LIMITED", 2023, 30_000, 0.95) for _ in range(6)]
        r = compute_buy_ratio("HYUNDAI CRETA LIMITED", 2023, 30_000, _df(rows))
        assert r.model_key_used == "HYUNDAI CRETA LIMITED" and r.family_fallback is False
        assert r.ratio_median == pytest.approx(0.95)

    def test_never_strips_past_brand_plus_model(self):
        r = compute_buy_ratio("TOYOTA COROLLA ALTIS", 2023, 30_000, self._base())
        assert not r.available
        assert r.model_key_used == "" and "TOYOTA COROLLA ALTIS" in r.description
