"""Tests for trim/version extractor utility."""

import pytest

from grand_brasil.utils.trim_extractor import extract_trim, build_model_trim


# ── extract_trim tests ───────────────────────────────────────────────


class TestExtractTrim:
    """Tests for the extract_trim function."""

    # ── Honda HR-V ──

    def test_hrv_exl(self) -> None:
        assert extract_trim("HR-V 1.8 16V FLEX EXL 4P AUTOMATICO", "HR-V") == "EXL"

    def test_hrv_ex(self) -> None:
        assert extract_trim("HR-V 1.8 16V FLEX EX 4P AUTOMATICO", "HR-V") == "EX"

    def test_hrv_touring(self) -> None:
        assert extract_trim("HR-V 1.5 DI TURBO FLEX TOURING CVT", "HR-V") == "TOURING"

    def test_hrv_advance(self) -> None:
        assert extract_trim("HR-V 1.5 DI I-VTEC FLEX ADVANCE CVT", "HR-V") == "ADVANCE"

    # ── VW Nivus ──

    def test_nivus_highline(self) -> None:
        assert extract_trim(
            "NIVUS 1.0 200 TSI TOTAL FLEX HIGHLINE AUTOMATICO", "NIVUS"
        ) == "HIGHLINE"

    def test_nivus_comfortline(self) -> None:
        assert extract_trim(
            "NIVUS 1.0 200 TSI TOTAL FLEX COMFORTLINE AUTOMAT", "NIVUS"
        ) == "COMFORTLINE"

    # ── VW T-Cross ──

    def test_tcross_highline(self) -> None:
        assert extract_trim(
            "T-CROSS 1.0 200 TSI TOTAL FLEX HIGHLINE AUTOMATICO", "T-CROSS"
        ) == "HIGHLINE"

    def test_tcross_comfortline(self) -> None:
        assert extract_trim(
            "T-CROSS 1.0 200 TSI TOTAL FLEX COMFORTLINE AUTOMAT", "T-CROSS"
        ) == "COMFORTLINE"

    # ── Hyundai HB20 ──

    def test_hb20_comfort(self) -> None:
        result = extract_trim(
            "HB20 1.0 12V FLEX COMFORT PLUS 4P MANUAL", "HB20"
        )
        assert result == "COMFORT PLUS"

    def test_hb20_vision(self) -> None:
        result = extract_trim(
            "HB20 1.0 12V FLEX VISION 4P MANUAL", "HB20"
        )
        assert result == "VISION"

    def test_hb20_evolution(self) -> None:
        result = extract_trim(
            "HB20 1.0 TGDI FLEX EVOLUTION AUTOMATICO", "HB20"
        )
        assert result == "EVOLUTION"

    # ── Chevrolet Onix ──

    def test_onix_lt(self) -> None:
        assert extract_trim("ONIX 1.0 MPFI LT 8V FLEX 4P MANUAL", "ONIX") == "LT"

    def test_onix_ltz(self) -> None:
        result = extract_trim("ONIX 1.0 TURBO FLEX LTZ AUTOMATICO", "ONIX")
        assert result == "LTZ"

    # ── Toyota Corolla (trim already in model_red, but test extraction) ──

    def test_corolla_xei(self) -> None:
        result = extract_trim(
            "COROLLA 2.0 VVT-IE FLEX XEI DIRECT SHIFT", "COROLLA"
        )
        assert result == "XEI"

    def test_corolla_gli(self) -> None:
        result = extract_trim(
            "COROLLA 2.0 VVT-IE FLEX GLI DIRECT SHIFT", "COROLLA"
        )
        assert result == "GLI"

    # ── Edge cases ──

    def test_returns_base_when_no_trim(self) -> None:
        """When all words are noise/engine specs, returns BASE."""
        result = extract_trim("MODELO 1.0 16V FLEX 4P AUTOMATICO", "MODELO")
        assert result == "BASE"

    def test_case_insensitive_extraction(self) -> None:
        """Input casing should not matter."""
        result = extract_trim(
            "hr-v 1.8 16v flex exl 4p automatico", "hr-v"
        )
        assert result == "EXL"

    def test_empty_modelo_returns_base(self) -> None:
        assert extract_trim("", "HR-V") == "BASE"

    def test_nan_handling(self) -> None:
        """NaN from pandas should not crash."""
        result = extract_trim("nan", "nan")
        assert isinstance(result, str)

    def test_i_vtec_noise_removed(self) -> None:
        """I-VTEC engine spec should not appear in trim."""
        result = extract_trim(
            "HR-V 1.5 DI I-VTEC FLEX EXL CVT", "HR-V"
        )
        assert "VTEC" not in result
        assert result == "EXL"

    def test_vvt_ie_noise_removed(self) -> None:
        """VVT-IE engine spec should not appear in trim."""
        result = extract_trim(
            "COROLLA 2.0 VVT-IE FLEX XEI DIRECT SHIFT", "COROLLA"
        )
        assert "VVT" not in result

    def test_truncated_automat_removed(self) -> None:
        """Truncated 'AUTOMAT' should not appear in trim."""
        result = extract_trim(
            "NIVUS 1.0 200 TSI TOTAL FLEX COMFORTLINE AUTOMAT", "NIVUS"
        )
        assert "AUTOMAT" not in result

    # ── Jeep ──

    def test_jeep_longitude(self) -> None:
        result = extract_trim(
            "COMPASS 2.0 16V FLEX LONGITUDE AUTOMATICO", "COMPASS"
        )
        assert result == "LONGITUDE"

    # ── Hyundai Creta (trim already in model_red) ──

    def test_creta_limited(self) -> None:
        result = extract_trim(
            "CRETA 1.0 TGDI FLEX LIMITED AUTOMATICO", "CRETA"
        )
        assert result == "LIMITED"


# ── build_model_trim tests ───────────────────────────────────────────


class TestBuildModelTrim:
    """Tests for the build_model_trim function."""

    def test_appends_trim_to_model_red(self) -> None:
        """When trim is NOT in model_red, it gets appended."""
        result = build_model_trim(
            model_red="HONDA HR-V",
            modelo_full="HR-V 1.8 16V FLEX EXL 4P AUTOMATICO",
            shortname="HR-V",
        )
        assert result == "HONDA HR-V EXL"

    def test_does_not_duplicate_trim(self) -> None:
        """When model_red already contains the trim, no duplication."""
        result = build_model_trim(
            model_red="HYUNDAI CRETA PLATINUM",
            modelo_full="CRETA 2.0 16V FLEX PLATINUM AUTOMATICO",
            shortname="CRETA",
        )
        assert result == "HYUNDAI CRETA PLATINUM"
        assert result.count("PLATINUM") == 1

    def test_base_trim_returns_model_red(self) -> None:
        """When no trim is extracted, returns model_red as-is."""
        result = build_model_trim(
            model_red="UNKNOWN MODEL",
            modelo_full="UNKNOWN 1.0 16V FLEX 4P AUTOMATICO",
            shortname="UNKNOWN",
        )
        assert result == "UNKNOWN MODEL"

    def test_corolla_xei_already_in_model_red(self) -> None:
        """Corolla XEI — trim already present in MODELO RED."""
        result = build_model_trim(
            model_red="TOYOTA COROLLA XEI",
            modelo_full="COROLLA 2.0 VVT-IE FLEX XEI DIRECT SHIFT",
            shortname="COROLLA",
        )
        assert result == "TOYOTA COROLLA XEI"
        assert result.count("XEI") == 1

    def test_nivus_highline(self) -> None:
        result = build_model_trim(
            model_red="VOLKSWAGEN NIVUS",
            modelo_full="NIVUS 1.0 200 TSI TOTAL FLEX HIGHLINE AUTOMATICO",
            shortname="NIVUS",
        )
        assert result == "VOLKSWAGEN NIVUS HIGHLINE"

    def test_hb20_comfort_plus(self) -> None:
        result = build_model_trim(
            model_red="HYUNDAI HB20",
            modelo_full="HB20 1.0 12V FLEX COMFORT PLUS 4P MANUAL",
            shortname="HB20",
        )
        assert result == "HYUNDAI HB20 COMFORT PLUS"

    def test_normalizes_accents(self) -> None:
        """Accented characters should be normalized."""
        result = build_model_trim(
            model_red="HONDA HR-V",
            modelo_full="HR-V 1.8 16V FLEX EXL 4P AUTOMÁTICO",
            shortname="HR-V",
        )
        assert result == "HONDA HR-V EXL"

    def test_case_normalization(self) -> None:
        """Output should be uppercase."""
        result = build_model_trim(
            model_red="honda hr-v",
            modelo_full="HR-V 1.8 16V FLEX EXL 4P AUTOMATICO",
            shortname="HR-V",
        )
        assert result == "HONDA HR-V EXL"
        assert result == result.upper()
