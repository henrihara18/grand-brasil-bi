"""Official price vs suggestion gate (config.official_gate)."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from grand_brasil.analysis.appraisal import _apply_official_gate
from grand_brasil.config import AppraisalConfig, OfficialGateConfig
from grand_brasil.models.appraisal import AppraisalRequest, AppraisalSuggestion

REF = pd.Timestamp("2026-10-30")


def _sug(confidence="alta", value="80000", closed=5) -> AppraisalSuggestion:
    s = AppraisalSuggestion(brand="HYUNDAI", model_red="HYUNDAI CRETA", year_model=2022)
    s.recommended_value = Decimal(value) if value else None
    s.confidence = confidence
    s.buy_ratio_closed_deal_count = closed
    return s


def _req(brand="HYUNDAI", model="HYUNDAI CRETA", year=2022, km=50_000, blindado=False) -> AppraisalRequest:
    return AppraisalRequest(brand=brand, model_red=model, year_model=year, km=km, fipe_price=Decimal("100000"), blindado=blindado)


def _cfg(**kw) -> AppraisalConfig:
    return AppraisalConfig(official_gate=OfficialGateConfig(**kw))


def test_inside_gate_is_official():
    s = _sug()
    _apply_official_gate(s, _req(), _cfg(), REF)
    assert s.price_mode == "oficial" and s.price_mode_reasons == []


@pytest.mark.parametrize("sug_kw,req_kw,needle", [
    ({"confidence": "baixa"}, {}, "confiança baixa"),
    ({"confidence": "sem dados"}, {}, "confiança sem dados"),
    ({}, {"year": 2015}, "11 anos"),
    ({}, {"km": 180_000}, "180.000 km"),
    ({}, {"km": 10}, "0 km"),
    ({}, {"year": 2027, "km": 20_000}, "ano-modelo seguinte"),
    ({}, {"brand": "AUDI", "model": "AUDI Q3"}, "marca AUDI"),
    ({}, {"blindado": True}, "blindado"),
])
def test_each_rule_turns_it_into_a_suggestion(sug_kw, req_kw, needle):
    s = _sug(**sug_kw)
    _apply_official_gate(s, _req(**req_kw), _cfg(), REF)
    assert s.price_mode == "sugestao"
    assert any(needle in r for r in s.price_mode_reasons), s.price_mode_reasons


def test_reasons_accumulate():
    s = _sug(confidence="baixa")
    _apply_official_gate(s, _req(year=2012, km=220_000), _cfg(), REF)
    assert s.price_mode == "sugestao" and len(s.price_mode_reasons) == 3


def test_model_prefix_and_min_closed_and_media_allowed():
    s = _sug(confidence="media", closed=2)
    cfg = _cfg(exclude_models=["HYUNDAI CRETA"], min_closed_deals=3)
    _apply_official_gate(s, _req(), cfg, REF)
    assert s.price_mode == "sugestao"
    assert any("modelo HYUNDAI CRETA" in r for r in s.price_mode_reasons)
    assert any("2 compras fechadas" in r for r in s.price_mode_reasons)
    assert not any("confiança" in r for r in s.price_mode_reasons)


def test_km_unknown_only_fails_km_rules_when_known():
    s = _sug()
    _apply_official_gate(s, _req(km=None), _cfg(), REF)
    assert s.price_mode == "oficial"


def test_disabled_leaves_mode_unset_and_no_value_is_suggestion():
    s = _sug()
    _apply_official_gate(s, _req(), _cfg(enabled=False), REF)
    assert s.price_mode is None
    s2 = _sug(value=None)
    _apply_official_gate(s2, _req(), _cfg(), REF)
    assert s2.price_mode == "sugestao" and s2.price_mode_reasons == ["sem valor recomendado"]


def test_default_config_loads_gate():
    cfg = AppraisalConfig()
    assert cfg.official_gate.enabled and cfg.official_gate.allowed_confidence == ["alta", "media"]
    assert "BMW" in cfg.official_gate.exclude_brands
