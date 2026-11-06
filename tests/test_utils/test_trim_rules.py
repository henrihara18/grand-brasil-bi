"""Trim rules on both bases + family prefix fallbacks."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis._comparable_selection import find_comparables
from grand_brasil.analysis.purchase_ratio import _resolve_model_key
from grand_brasil.utils.model_generation import apply_generation_split_df, apply_trim_rule


@pytest.mark.parametrize("model_red,text,expected", [
    ("HYUNDAI HB20", "HB20 1.0 TGDI FLEX PLATINUM AUTOMATICO", "HYUNDAI HB20 PLATINUM"),
    ("HYUNDAI HB20", "HB20 1.0 12V FLEX SENSE MANUAL", "HYUNDAI HB20 SENSE"),
    ("HYUNDAI HB20", "HB20 1.0 COMFORT 12V FLEX 4P", "HYUNDAI HB20"),                 # no listed marker -> family
    ("HONDA HR-V", "HR-V 1.5 TURBO TOURING", "HONDA HR-V TOURING"),
    ("HONDA HR-V", "HR-V 1.8 16V FLEX EXL 4P AUTOMATICO", "HONDA HR-V EXL"),
    ("TOYOTA COROLLA ALTIS", "2.0 ALTIS PREMIUM HYBRID", "TOYOTA COROLLA ALTIS HIBRIDO PREMIUM"),
    ("TOYOTA COROLLA ALTIS HIBRIDO", "1.8 VVT-I HYBRID FLEX ALTIS CVT", "TOYOTA COROLLA ALTIS HIBRIDO"),
    ("TOYOTA COROLLA ALTIS", "2.0 ALTIS 16V FLEX", "TOYOTA COROLLA ALTIS"),
    ("JEEP COMMANDER", "2.0 TD380 TURBO DIESEL OVERLAND", "JEEP COMMANDER DIESEL"),
    ("BYD SONG PLUS", "1.5 DM-I HIBRIDO PREMIUM", "BYD SONG PLUS"),                     # BYD: no rules (no evidence)
    ("HYUNDAI CRETA LIMITED", "1.0 TGDI LIMITED", "HYUNDAI CRETA LIMITED"),            # untouched family
])
def test_apply_trim_rule(model_red, text, expected):
    assert apply_trim_rule(model_red, text) == expected


def test_df_application_and_switch():
    df = pd.DataFrame({"model_red": ["HYUNDAI HB20", "HYUNDAI HB20"], "modelo_full": ["HB20 PLATINUM AUT", "HB20 SENSE MANUAL"],
                       "model_trim": ["HYUNDAI HB20 PLATINUM", "HYUNDAI HB20 SENSE"]})
    on = apply_generation_split_df(df.copy(), source_col="modelo_full", trim_rules=True)
    off = apply_generation_split_df(df.copy(), source_col="modelo_full", trim_rules=False)
    assert list(on["model_red"]) == ["HYUNDAI HB20 PLATINUM", "HYUNDAI HB20 SENSE"]
    assert list(off["model_red"]) == ["HYUNDAI HB20", "HYUNDAI HB20"]


def test_buy_ratio_family_fallback_includes_every_trim():
    df = pd.DataFrame({"model_red": ["HYUNDAI HB20 PLATINUM", "HYUNDAI HB20 SENSE", "HYUNDAI HB20", "HYUNDAI HB20S"], "ratio": [0.9, 0.8, 0.85, 0.7]})
    key, rows = _resolve_model_key("HYUNDAI HB20 PREMIUM", df)      # no PREMIUM rows -> family prefix
    assert key == "HYUNDAI HB20" and sorted(rows["model_red"]) == ["HYUNDAI HB20", "HYUNDAI HB20 PLATINUM", "HYUNDAI HB20 SENSE"]
    key, rows = _resolve_model_key("HYUNDAI HB20 SENSE", df)        # exact first
    assert key == "HYUNDAI HB20 SENSE" and len(rows) == 1


def test_sales_prefix_match():
    sales = pd.DataFrame({"model_red": ["HONDA HR-V EXL", "HONDA HR-V", "HONDA HR-V TOURING", "HONDA CITY"], "year_model": [2022] * 4})
    assert len(find_comparables(sales, "HONDA HR-V", year_model=2022)) == 1
    assert len(find_comparables(sales, "HONDA HR-V", year_model=2022, prefix=True)) == 3
