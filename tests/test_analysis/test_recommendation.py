"""Tests for the headline selection (_apply_recommendation)."""

from __future__ import annotations

from decimal import Decimal

from grand_brasil.analysis.appraisal import _apply_recommendation
from grand_brasil.config import AppraisalConfig
from grand_brasil.models.appraisal import AppraisalSuggestion


def _sug(a=None, b=None, tier="same_year_km6k") -> AppraisalSuggestion:
    s = AppraisalSuggestion(brand="HYUNDAI", model_red="HYUNDAI CRETA", year_model=2022)
    if a is not None:
        s.buy_ratio_available = True
        s.buy_ratio_price = Decimal(a)
        s.buy_ratio_tier = tier
    if b is not None:
        s.blended_max_trade_value = Decimal(b)
        s.blended_reason = "mistura"
    return s


def test_legacy_prefers_buy_ratio_when_available():
    s = _sug(a="80000", b="70000")
    _apply_recommendation(s, AppraisalConfig(headline_mode="buy_ratio_first"))
    assert s.recommended_value == Decimal("80000") and s.recommended_source == "buy_ratio"


def test_legacy_falls_back_to_blend():
    s = _sug(a=None, b="70000")
    _apply_recommendation(s, AppraisalConfig(headline_mode="buy_ratio_first"))
    assert s.recommended_value == Decimal("70000") and s.recommended_source == "blend"


def test_ensemble_mixes_and_rounds_to_500():
    s = _sug(a="80000", b="70000")
    _apply_recommendation(s, AppraisalConfig(headline_mode="ensemble", ensemble_weight_buy_ratio=0.7))
    assert s.recommended_value == Decimal("77000")   # 0.7*80k + 0.3*70k = 77k
    assert s.recommended_source == "ensemble" and "70%" in s.recommended_reason


def test_ensemble_weight_by_tier_overrides_default():
    s = _sug(a="80000", b="70000", tier="model_fallback")
    cfg = AppraisalConfig(headline_mode="ensemble", ensemble_weight_buy_ratio=0.7,
                          ensemble_weight_by_tier={"model_fallback": 0.4})
    _apply_recommendation(s, cfg)
    assert s.recommended_value == Decimal("74000")   # 0.4*80k + 0.6*70k


def test_ensemble_with_single_anchor_uses_it():
    s = _sug(a="80000", b=None)
    _apply_recommendation(s, AppraisalConfig(headline_mode="ensemble"))
    assert s.recommended_value == Decimal("80000") and s.recommended_source == "buy_ratio"


def test_nothing_available_leaves_none():
    s = _sug()
    _apply_recommendation(s, AppraisalConfig(headline_mode="ensemble"))
    assert s.recommended_value is None and s.recommended_source is None


# ── Alert: headline above X % of FIPE (forensic item 9) ──────────────────────

from grand_brasil.analysis.appraisal import _apply_fipe_ratio_alert
from grand_brasil.models.appraisal import AppraisalRequest


def _req(fipe="100000"):
    return AppraisalRequest(brand="HYUNDAI", model_red="HYUNDAI HB20S", year_model=2026, km=10, fipe_price=Decimal(fipe))


def test_alert_fires_above_threshold():
    s = _sug(a="97000", b="97000")
    _apply_recommendation(s, AppraisalConfig(headline_mode="ensemble"))
    _apply_fipe_ratio_alert(s, _req(), AppraisalConfig(fipe_ratio_alert=0.95))
    assert s.recommended_fipe_ratio == 0.97
    assert s.above_fipe_alert and "97%" in s.above_fipe_alert and "margem negativa" in s.above_fipe_alert


def test_no_alert_at_or_below_threshold():
    s = _sug(a="95000", b="95000")
    _apply_recommendation(s, AppraisalConfig(headline_mode="ensemble"))
    _apply_fipe_ratio_alert(s, _req(), AppraisalConfig(fipe_ratio_alert=0.95))
    assert s.recommended_fipe_ratio == 0.95 and s.above_fipe_alert is None


def test_alert_switch_off_and_missing_inputs():
    s = _sug(a="99000", b="99000")
    _apply_recommendation(s, AppraisalConfig(headline_mode="ensemble"))
    _apply_fipe_ratio_alert(s, _req(), AppraisalConfig(fipe_ratio_alert=None))
    assert s.recommended_fipe_ratio == 0.99 and s.above_fipe_alert is None
    s2 = _sug()
    _apply_fipe_ratio_alert(s2, _req(), AppraisalConfig())
    assert s2.recommended_fipe_ratio is None and s2.above_fipe_alert is None
