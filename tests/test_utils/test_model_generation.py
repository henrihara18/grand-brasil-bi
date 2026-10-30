"""Tests for grand_brasil/utils/model_generation.py."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.utils.model_generation import (
    GENERATION_RULES,
    apply_generation_split,
    apply_generation_split_df,
)


# ── apply_generation_split ──────────────────────────────────────────────────

class TestApplyGenerationSplit:
    def test_tiguan_allspace_marker(self):
        out = apply_generation_split(
            "VOLKSWAGEN TIGUAN",
            "TIGUAN 1.4 250 TSI TOTAL FLEX ALLSPACE COMFORTLINE",
        )
        assert out == "VOLKSWAGEN TIGUAN ALLSPACE"

    def test_tiguan_plain_stays_plain(self):
        out = apply_generation_split(
            "VOLKSWAGEN TIGUAN",
            "TIGUAN 1.4 TSI 16V TURBO GASOLINA 4P TIPTRONIC",
        )
        assert out == "VOLKSWAGEN TIGUAN"

    def test_tucson_tgdi_with_dash(self):
        out = apply_generation_split(
            "HYUNDAI TUCSON",
            "TUCSON 1.6 16V T-GDI GASOLINA GLS ECOSHIFT",
        )
        assert out == "HYUNDAI TUCSON T-GDI"

    def test_tucson_tgdi_without_dash(self):
        out = apply_generation_split(
            "HYUNDAI TUCSON",
            "TUCSON 1.6 TGDI LIMITED",
        )
        assert out == "HYUNDAI TUCSON T-GDI"

    def test_tucson_old_generation_stays(self):
        out = apply_generation_split(
            "HYUNDAI TUCSON",
            "TUCSON 2.0 MPFI GLS 16V 143CV 2WD FLEX 4P AUTOMATICO",
        )
        assert out == "HYUNDAI TUCSON"

    def test_yaris_sedan_marker(self):
        out = apply_generation_split(
            "TOYOTA YARIS",
            "YARIS 1.5 16V FLEX SEDAN XL MULTIDRIVE",
        )
        assert out == "TOYOTA YARIS SEDAN"

    def test_yaris_hatch_stays(self):
        out = apply_generation_split(
            "TOYOTA YARIS",
            "YARIS 1.3 16V FLEX XL AUTOMATICO",
        )
        assert out == "TOYOTA YARIS"

    def test_yaris_hatch_explicit_stays(self):
        out = apply_generation_split(
            "TOYOTA YARIS",
            "YARIS 1.5 16V FLEX HATCH XS CONNECT",
        )
        assert out == "TOYOTA YARIS"

    def test_outlander_sport_split(self):
        out = apply_generation_split(
            "MITSUBISHI OUTLANDER",
            "OUTLANDER 2.0 MIVEC FLEX SPORT HPE AUTOMÁTICO",
        )
        assert out == "MITSUBISHI OUTLANDER SPORT"

    def test_outlander_plain_stays(self):
        out = apply_generation_split(
            "MITSUBISHI OUTLANDER",
            "OUTLANDER 2.0 COMFORT 16V GASOLINA 4P AUTOMATICO",
        )
        assert out == "MITSUBISHI OUTLANDER"

    def test_unrelated_model_untouched(self):
        """Model not listed in rules passes through unchanged."""
        out = apply_generation_split(
            "HONDA CIVIC",
            "CIVIC 2.0 16V FLEXONE EXL 4P CVT",
        )
        assert out == "HONDA CIVIC"

    def test_case_insensitive_match(self):
        out = apply_generation_split(
            "volkswagen tiguan",
            "tiguan 1.4 tsi allspace",
        )
        assert out == "VOLKSWAGEN TIGUAN ALLSPACE"

    def test_accent_normalized(self):
        out = apply_generation_split(
            "MITSUBISHI OUTLANDER",
            "OUTLANDER 2.0 MIVEC FLEX SPORT HPE AUTOMÁTICO",
        )
        assert out == "MITSUBISHI OUTLANDER SPORT"

    def test_empty_inputs(self):
        assert apply_generation_split("", "foo") == ""
        assert apply_generation_split("VOLKSWAGEN TIGUAN", "") == "VOLKSWAGEN TIGUAN"

    def test_partial_word_not_matched(self):
        """'SPORT' inside 'TRANSPORT' must not trigger the Outlander Sport rule."""
        out = apply_generation_split(
            "MITSUBISHI OUTLANDER",
            "OUTLANDER TRANSPORT EDITION",  # contrived
        )
        # SPORT is a standalone word here too, so this actually *would* match.
        # Use a case where SPORT is embedded:
        out2 = apply_generation_split(
            "MITSUBISHI OUTLANDER",
            "OUTLANDER TRANSPORTATION SPECIAL",
        )
        assert out2 == "MITSUBISHI OUTLANDER"


# ── apply_generation_split_df ───────────────────────────────────────────────

class TestApplyGenerationSplitDf:
    def test_updates_model_red_and_trim_in_df(self):
        df = pd.DataFrame({
            "model_red": [
                "VOLKSWAGEN TIGUAN",
                "VOLKSWAGEN TIGUAN",
                "HONDA CIVIC",
            ],
            "model_trim": [
                "VOLKSWAGEN TIGUAN COMFORTLINE",
                "VOLKSWAGEN TIGUAN",
                "HONDA CIVIC EXL",
            ],
            "modelo_full": [
                "TIGUAN 1.4 250 TSI TOTAL FLEX ALLSPACE COMFORTLINE",
                "TIGUAN 1.4 TSI 16V TURBO GASOLINA 4P TIPTRONIC",
                "CIVIC 2.0 16V FLEXONE EXL 4P CVT",
            ],
        })
        result = apply_generation_split_df(df, source_col="modelo_full")
        assert list(result["model_red"]) == [
            "VOLKSWAGEN TIGUAN ALLSPACE",
            "VOLKSWAGEN TIGUAN",
            "HONDA CIVIC",
        ]
        # model_trim rewritten when prefix matched (old model_red in trim)
        assert list(result["model_trim"]) == [
            "VOLKSWAGEN TIGUAN ALLSPACE COMFORTLINE",
            "VOLKSWAGEN TIGUAN",
            "HONDA CIVIC EXL",
        ]

    def test_handles_missing_source_column(self):
        df = pd.DataFrame({"model_red": ["VOLKSWAGEN TIGUAN"]})
        result = apply_generation_split_df(df, source_col="modelo_full")
        # No source column → no change
        assert list(result["model_red"]) == ["VOLKSWAGEN TIGUAN"]

    def test_no_trim_column_ok(self):
        df = pd.DataFrame({
            "model_red": ["TOYOTA YARIS"],
            "version": ["YARIS 1.5 FLEX SEDAN XL"],
        })
        result = apply_generation_split_df(df, source_col="version", model_trim_col=None)
        assert list(result["model_red"]) == ["TOYOTA YARIS SEDAN"]


# ── Rule consistency ────────────────────────────────────────────────────────

class TestGenerationRulesConsistency:
    def test_rules_are_uppercase(self):
        for rule in GENERATION_RULES:
            assert rule.base_model_red == rule.base_model_red.upper()
            assert rule.new_model_red == rule.new_model_red.upper()

    def test_new_model_red_starts_with_base(self):
        """Invariant: the rewritten name extends the base (doesn't replace
        the brand/model prefix)."""
        for rule in GENERATION_RULES:
            assert rule.new_model_red.startswith(rule.base_model_red), (
                f"Rule {rule}: new_model_red must extend base_model_red"
            )

    def test_rules_are_deterministic(self):
        """Applying the same rule twice must be a fixed point — once a
        model_red is rewritten, the rule's base_model_red doesn't match
        anymore so nothing else happens."""
        for rule in GENERATION_RULES:
            # Pretend the source text still contains the marker.
            # Apply once — goes from base to new.
            once = apply_generation_split(rule.base_model_red, rule.new_model_red)
            assert once == rule.new_model_red
            # Apply again — stays at new (base_model_red no longer matches)
            twice = apply_generation_split(once, rule.new_model_red)
            assert twice == rule.new_model_red
