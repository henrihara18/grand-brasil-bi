"""Tests for the blended single-price logic in appraise().

Covers:
  - purpose='auto' blends Loja/Revenda by p_revenda
  - purpose='loja' / 'revenda' force the channel
  - missing channel fallbacks
  - boundary cases (p_revenda 0/1, missing prices)
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from grand_brasil.analysis.appraisal import _apply_blended_price
from grand_brasil.models.appraisal import AppraisalRequest, AppraisalSuggestion


def _make_suggestion(
    loja: int | None,
    revenda: int | None,
    p_revenda: float | None,
) -> AppraisalSuggestion:
    s = AppraisalSuggestion(
        brand="HYUNDAI",
        model_red="HB20",
        year_model=2022,
    )
    if loja is not None:
        s.loja_max_trade_value = Decimal(str(loja))
    if revenda is not None:
        s.revenda_max_trade_value = Decimal(str(revenda))
    s.p_revenda = p_revenda
    if p_revenda is not None:
        s.p_loja = 1.0 - p_revenda
    return s


def _make_request(purpose: str = "auto") -> AppraisalRequest:
    return AppraisalRequest(
        brand="HYUNDAI",
        model_red="HB20",
        year_model=2022,
        purpose=purpose,
    )


class TestBlendedAuto:
    def test_blend_with_p_revenda_50(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.5)
        _apply_blended_price(s, _make_request("auto"))
        # 0.5 * 60000 + 0.5 * 40000 = 50000
        assert s.blended_max_trade_value == Decimal("50000")
        assert s.blended_source == "blend"
        assert s.blended_weight_loja == 0.5
        assert s.blended_weight_revenda == 0.5

    def test_blend_favors_loja_when_p_low(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.1)
        _apply_blended_price(s, _make_request("auto"))
        # 0.9 * 60000 + 0.1 * 40000 = 58000
        assert s.blended_max_trade_value == Decimal("58000")

    def test_blend_favors_revenda_when_p_high(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.9)
        _apply_blended_price(s, _make_request("auto"))
        # 0.1 * 60000 + 0.9 * 40000 = 42000
        assert s.blended_max_trade_value == Decimal("42000")

    def test_blend_p_revenda_zero(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.0)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value == Decimal("60000")

    def test_blend_p_revenda_one(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=1.0)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value == Decimal("40000")

    def test_blend_falls_back_to_neutral_when_p_missing(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=None)
        _apply_blended_price(s, _make_request("auto"))
        # Defaults to 50/50 average
        assert s.blended_max_trade_value == Decimal("50000")

    def test_blend_only_loja_available(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=None, p_revenda=0.5)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value == Decimal("60000")
        assert s.blended_source == "loja"
        assert s.blended_weight_loja == 1.0

    def test_blend_only_revenda_available(self) -> None:
        s = _make_suggestion(loja=None, revenda=40_000, p_revenda=0.5)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value == Decimal("40000")
        assert s.blended_source == "revenda"
        assert s.blended_weight_revenda == 1.0

    def test_blend_neither_channel_available(self) -> None:
        s = _make_suggestion(loja=None, revenda=None, p_revenda=0.5)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value is None
        assert s.blended_source is None


class TestBlendedForcedChannel:
    def test_purpose_loja_uses_loja_value(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.9)
        _apply_blended_price(s, _make_request("loja"))
        assert s.blended_max_trade_value == Decimal("60000")
        assert s.blended_source == "loja"
        assert s.blended_weight_loja == 1.0
        assert s.blended_weight_revenda == 0.0

    def test_purpose_revenda_uses_revenda_value(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.1)
        _apply_blended_price(s, _make_request("revenda"))
        assert s.blended_max_trade_value == Decimal("40000")
        assert s.blended_source == "revenda"
        assert s.blended_weight_revenda == 1.0

    def test_purpose_loja_with_missing_loja_yields_none(self) -> None:
        s = _make_suggestion(loja=None, revenda=40_000, p_revenda=0.5)
        _apply_blended_price(s, _make_request("loja"))
        # Refuses to fall back when channel is forced
        assert s.blended_max_trade_value is None

    def test_purpose_revenda_with_missing_revenda_yields_none(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=None, p_revenda=0.5)
        _apply_blended_price(s, _make_request("revenda"))
        assert s.blended_max_trade_value is None


class TestBlendedNormalisation:
    def test_unknown_purpose_treated_as_auto(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.5)
        _apply_blended_price(s, _make_request("garbage"))
        assert s.purpose == "auto"
        assert s.blended_source == "blend"

    def test_purpose_case_insensitive(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.5)
        _apply_blended_price(s, _make_request("LOJA"))
        assert s.purpose == "loja"
        assert s.blended_source == "loja"

    def test_p_revenda_clamped_above_one(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=1.5)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value == Decimal("40000")

    def test_p_revenda_clamped_below_zero(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=-0.3)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_max_trade_value == Decimal("60000")

    def test_blended_reason_populated(self) -> None:
        s = _make_suggestion(loja=60_000, revenda=40_000, p_revenda=0.7)
        _apply_blended_price(s, _make_request("auto"))
        assert s.blended_reason is not None
        assert "70%" in s.blended_reason
