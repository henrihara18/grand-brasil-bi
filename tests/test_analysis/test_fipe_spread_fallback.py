"""Tests for the FIPE-spread fallback logic in analysis/appraisal.py.

When historical data is insufficient (< min_sample_for_spread), the algorithm
falls back to a fixed FIPE × ratio reference instead of a noisy computed spread.

Revenda fallback default: 0.80 (B2B dealer-to-dealer discount).
Loja fallback default: None (FIPE stays as-is).
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from grand_brasil.analysis.appraisal import _apply_fipe_spreads
from grand_brasil.config import FipeSpreadConfig
from grand_brasil.models.appraisal import AppraisalSuggestion


# ── Fake FIPE client for controlled tests ──────────────────────────────────


class _FakeFipeClient:
    """Returns a canned historical price for every date/code lookup.

    Not exercised when we want to force "no spread data" — we just pass
    empty DataFrames so compute_fipe_spreads returns (None, 0).
    """

    def __init__(self, price: float = 100_000):
        self._price = price

    def get_reference_code_for_date(self, _date):
        return "ref-1"

    def get_historical_price(self, *_args, **_kwargs):
        return SimpleNamespace(value=self._price)


def _empty_channel_df() -> pd.DataFrame:
    """Channel DataFrame with zero rows → compute_fipe_spreads → (None, 0)."""
    return pd.DataFrame(columns=["sale_date", "sale_price"])


def _suggestion_skeleton() -> AppraisalSuggestion:
    """Minimal AppraisalSuggestion for testing _apply_fipe_spreads output."""
    return AppraisalSuggestion(
        brand="HYUNDAI",
        model_red="HYUNDAI CRETA",
        year_model=2023,
    )


def _config_with_fipe_spread(
    min_sample: int = 3,
    revenda_ratio: float | None = 0.80,
    loja_ratio: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        fipe_spread=FipeSpreadConfig(
            min_sample_for_spread=min_sample,
            revenda_fallback_ratio=revenda_ratio,
            loja_fallback_ratio=loja_ratio,
        )
    )


# ── Core fallback behavior ──────────────────────────────────────────────────


class TestRevendaFallback:
    def test_triggers_when_no_historical_data(self):
        suggestion = _suggestion_skeleton()
        cfg = _config_with_fipe_spread()

        loja_spread, revenda_spread = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=True,
            fipe_client=_FakeFipeClient(),
            fipe_brand_code="1",
            fipe_model_code="1",
            fipe_year_code="2023-1",
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=cfg,
        )

        # Revenda fallback = 0.80 → effective spread = -0.20
        assert revenda_spread == pytest.approx(-0.20)
        assert suggestion.revenda_used_fallback_spread is True
        assert suggestion.revenda_fallback_ratio == 0.80
        # Raw data-derived spread remains None (for UI transparency)
        assert suggestion.revenda_fipe_spread_pct is None
        assert suggestion.revenda_spread_sample_size == 0

    def test_loja_does_not_fall_back_by_default(self):
        suggestion = _suggestion_skeleton()
        cfg = _config_with_fipe_spread()  # loja_ratio=None by default

        loja_spread, _ = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=True,
            fipe_client=_FakeFipeClient(),
            fipe_brand_code="1",
            fipe_model_code="1",
            fipe_year_code="2023-1",
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=cfg,
        )

        assert loja_spread is None   # no fallback → stays None
        assert suggestion.loja_used_fallback_spread is False
        assert suggestion.loja_fallback_ratio is None

    def test_fallback_disabled_when_ratio_is_none(self):
        """Setting revenda_fallback_ratio=None disables the fallback."""
        suggestion = _suggestion_skeleton()
        cfg = _config_with_fipe_spread(revenda_ratio=None)

        _, revenda_spread = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=True,
            fipe_client=_FakeFipeClient(),
            fipe_brand_code="1",
            fipe_model_code="1",
            fipe_year_code="2023-1",
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=cfg,
        )

        assert revenda_spread is None
        assert suggestion.revenda_used_fallback_spread is False

    def test_custom_ratio_respected(self):
        suggestion = _suggestion_skeleton()
        cfg = _config_with_fipe_spread(revenda_ratio=0.75)  # more aggressive discount

        _, revenda_spread = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=True,
            fipe_client=_FakeFipeClient(),
            fipe_brand_code="1",
            fipe_model_code="1",
            fipe_year_code="2023-1",
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=cfg,
        )

        assert revenda_spread == pytest.approx(-0.25)
        assert suggestion.revenda_fallback_ratio == 0.75

    def test_loja_fallback_enabled_if_ratio_set(self):
        suggestion = _suggestion_skeleton()
        cfg = _config_with_fipe_spread(loja_ratio=0.95)

        loja_spread, _ = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=True,
            fipe_client=_FakeFipeClient(),
            fipe_brand_code="1",
            fipe_model_code="1",
            fipe_year_code="2023-1",
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=cfg,
        )

        assert loja_spread == pytest.approx(-0.05)
        assert suggestion.loja_used_fallback_spread is True
        assert suggestion.loja_fallback_ratio == 0.95


class TestFallbackGuards:
    def test_no_fallback_outside_fipe_mode(self):
        """If fipe_mode is False, we use the historical-median path — no fallback."""
        suggestion = _suggestion_skeleton()
        cfg = _config_with_fipe_spread()

        loja_spread, revenda_spread = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=False,  # ← key difference
            fipe_client=None,
            fipe_brand_code=None,
            fipe_model_code=None,
            fipe_year_code=None,
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=cfg,
        )

        assert loja_spread is None
        assert revenda_spread is None
        assert suggestion.revenda_used_fallback_spread is False

    def test_no_fallback_when_config_is_none(self):
        """Passing appraisal_config=None keeps the legacy behavior."""
        suggestion = _suggestion_skeleton()

        _, revenda_spread = _apply_fipe_spreads(
            suggestion=suggestion,
            loja_df=_empty_channel_df(),
            revenda_df=_empty_channel_df(),
            fipe_mode=True,
            fipe_client=_FakeFipeClient(),
            fipe_brand_code="1",
            fipe_model_code="1",
            fipe_year_code="2023-1",
            reference_date=pd.Timestamp.now(),
            recency_halflife_days=180.0,
            appraisal_config=None,
        )

        assert revenda_spread is None
        assert suggestion.revenda_used_fallback_spread is False
