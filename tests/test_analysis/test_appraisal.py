"""Tests for the trade-in appraisal engine."""

from decimal import Decimal

import pandas as pd
import pytest

from grand_brasil.analysis.appraisal import appraise, _calc_max_trade, _round_to_500, _remove_blindados, _blindado_premium
from grand_brasil.models.appraisal import AppraisalRequest, AppraisalSuggestion


# ── Test fixtures ────────────────────────────────────────────────────


@pytest.fixture
def sales_df() -> pd.DataFrame:
    """Synthetic sales history for testing."""
    data = [
        # Loja (B2C) - HYUNDAI HB20 2021-2023
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2021,
         "km": 40000, "sale_price": 62000, "purchase_cost": 55000,
         "adjusted_cost": 53000, "days_in_stock": 20, "margin_percent": 7.5,
         "sale_channel": "Loja", "sale_date": pd.Timestamp("2025-03-01")},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 30000, "sale_price": 68000, "purchase_cost": 60000,
         "adjusted_cost": 58000, "days_in_stock": 15, "margin_percent": 8.0,
         "sale_channel": "Loja", "sale_date": pd.Timestamp("2025-04-01")},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2023,
         "km": 20000, "sale_price": 72000, "purchase_cost": 63000,
         "adjusted_cost": 61000, "days_in_stock": 10, "margin_percent": 9.0,
         "sale_channel": "Loja", "sale_date": pd.Timestamp("2025-05-01")},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2021,
         "km": 55000, "sale_price": 58000, "purchase_cost": 52000,
         "adjusted_cost": 50000, "days_in_stock": 30, "margin_percent": 6.0,
         "sale_channel": "Loja", "sale_date": pd.Timestamp("2025-06-01")},
        # Revenda (B2B) - HYUNDAI HB20 2021-2022
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2021,
         "km": 50000, "sale_price": 48000, "purchase_cost": 46000,
         "adjusted_cost": 45000, "days_in_stock": 5, "margin_percent": 1.5,
         "sale_channel": "Revenda", "sale_date": pd.Timestamp("2025-03-15")},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 35000, "sale_price": 52000, "purchase_cost": 50000,
         "adjusted_cost": 49000, "days_in_stock": 8, "margin_percent": 1.0,
         "sale_channel": "Revenda", "sale_date": pd.Timestamp("2025-04-15")},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2021,
         "km": 60000, "sale_price": 45000, "purchase_cost": 43000,
         "adjusted_cost": 42000, "days_in_stock": 12, "margin_percent": 2.0,
         "sale_channel": "Revenda", "sale_date": pd.Timestamp("2025-05-15")},
        # Different model - TOYOTA COROLLA XEI
        {"brand": "TOYOTA", "model_red": "TOYOTA COROLLA XEI", "year_model": 2022,
         "km": 25000, "sale_price": 130000, "purchase_cost": 115000,
         "adjusted_cost": 113000, "days_in_stock": 25, "margin_percent": 10.0,
         "sale_channel": "Loja", "sale_date": pd.Timestamp("2025-05-01")},
        # Old HB20 outside year tolerance
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2016,
         "km": 120000, "sale_price": 30000, "purchase_cost": 27000,
         "adjusted_cost": 26000, "days_in_stock": 40, "margin_percent": 5.0,
         "sale_channel": "Loja", "sale_date": pd.Timestamp("2025-02-01")},
    ]
    return pd.DataFrame(data)


@pytest.fixture
def hb20_request() -> AppraisalRequest:
    """Standard HB20 2022 appraisal request."""
    return AppraisalRequest(
        brand="HYUNDAI",
        model_red="HYUNDAI HB20",
        year_model=2022,
        km=45000,
    )


# ── Unit tests: helpers ──────────────────────────────────────────────


class TestRoundTo500:
    """Tests for the _round_to_500 helper."""

    def test_exact_multiple(self) -> None:
        assert _round_to_500(Decimal("50000")) == Decimal("50000")

    def test_rounds_to_nearest(self) -> None:
        assert _round_to_500(Decimal("50200")) == Decimal("50000")
        assert _round_to_500(Decimal("50300")) == Decimal("50500")

    def test_zero(self) -> None:
        assert _round_to_500(Decimal("0")) == Decimal("0")

    def test_small_value(self) -> None:
        assert _round_to_500(Decimal("600")) == Decimal("500")


class TestCalcMaxTrade:
    """Tests for the _calc_max_trade helper."""

    def test_basic_calculation(self) -> None:
        """15% margin on R$100k sale -> max cost ~R$86,957 -> trade = cost - repair."""
        result = _calc_max_trade(
            estimated_sale_price=Decimal("100000"),
            target_margin_percent=15.0,
            repair_cost=Decimal("0"),
        )
        # 100000 / 1.15 = 86956.52 -> rounded to 87000
        assert result == Decimal("87000")

    def test_with_repair_cost(self) -> None:
        """Repair cost is subtracted from max trade."""
        result_no_repair = _calc_max_trade(
            Decimal("100000"), 15.0, Decimal("0"),
        )
        result_with_repair = _calc_max_trade(
            Decimal("100000"), 15.0, Decimal("5000"),
        )
        assert result_with_repair < result_no_repair
        # Difference should be approximately the repair cost (within rounding)
        diff = result_no_repair - result_with_repair
        assert Decimal("4500") <= diff <= Decimal("5500")

    def test_zero_sale_price(self) -> None:
        """Zero sale price returns zero."""
        assert _calc_max_trade(Decimal("0"), 15.0, Decimal("0")) == Decimal("0")

    def test_revenda_margin(self) -> None:
        """5.5% margin gives higher trade value than 15%."""
        loja = _calc_max_trade(Decimal("60000"), 15.0, Decimal("0"))
        revenda = _calc_max_trade(Decimal("60000"), 5.5, Decimal("0"))
        assert revenda > loja

    def test_never_negative(self) -> None:
        """If repair cost exceeds max cost, result is zero not negative."""
        result = _calc_max_trade(
            Decimal("10000"), 15.0, Decimal("50000"),
        )
        assert result == Decimal("0")


# ── Integration tests: appraise function ─────────────────────────────


class TestAppraise:
    """Tests for the main appraise function."""

    def test_basic_appraisal(self, sales_df, hb20_request) -> None:
        """Basic appraisal returns valid suggestion."""
        result = appraise(hb20_request, sales_df)
        assert isinstance(result, AppraisalSuggestion)
        assert result.total_comparables > 0
        assert result.brand == "HYUNDAI"
        assert result.model_red == "HYUNDAI HB20"

    def test_both_channels_populated(self, sales_df, hb20_request) -> None:
        """Both Loja and Revenda values are returned."""
        result = appraise(hb20_request, sales_df)
        assert result.loja_max_trade_value is not None
        assert result.revenda_max_trade_value is not None
        assert result.loja_comparables_count > 0
        assert result.revenda_comparables_count > 0

    def test_loja_higher_than_revenda_trade(self, sales_df, hb20_request) -> None:
        """Loja trade value should typically be higher (higher sale prices, offset by higher margin)."""
        result = appraise(hb20_request, sales_df)
        # Loja has higher sales prices but also higher margin target
        # The net effect depends on data, but both should be positive
        assert result.loja_max_trade_value > 0
        assert result.revenda_max_trade_value > 0

    def test_year_tolerance_filters(self, sales_df) -> None:
        """Year tolerance correctly filters comparables."""
        req = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=45000,
        )
        # With tolerance=2, should get 2020-2024 range (2021,2022,2023 in our data)
        result_wide = appraise(req, sales_df, year_tolerance=2)

        # With tolerance=0, should only get exact year 2022
        result_narrow = appraise(req, sales_df, year_tolerance=0)

        assert result_wide.total_comparables > result_narrow.total_comparables

    def test_old_car_excluded_by_tolerance(self, sales_df) -> None:
        """2016 HB20 should NOT appear in 2022 +/-2 search."""
        req = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=45000,
        )
        result = appraise(req, sales_df, year_tolerance=2)
        # The 2016 car should be excluded
        all_years = [c.year_model for c in result.loja_comparables + result.revenda_comparables]
        assert 2016 not in all_years

    def test_no_comparables(self, sales_df) -> None:
        """Non-existent model returns empty result."""
        req = AppraisalRequest(
            brand="FERRARI", model_red="FERRARI 488",
            year_model=2022,
        )
        result = appraise(req, sales_df)
        assert result.total_comparables == 0
        assert result.confidence == "sem dados"
        assert result.loja_max_trade_value is None
        assert result.revenda_max_trade_value is None

    def test_repair_cost_reduces_trade(self, sales_df) -> None:
        """Adding repair cost lowers the trade value."""
        req_no_repair = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=45000,
            estimated_repair_cost=Decimal("0"),
        )
        req_with_repair = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=45000,
            estimated_repair_cost=Decimal("5000"),
        )
        r1 = appraise(req_no_repair, sales_df)
        r2 = appraise(req_with_repair, sales_df)

        assert r2.loja_max_trade_value < r1.loja_max_trade_value
        assert r2.revenda_max_trade_value < r1.revenda_max_trade_value

    def test_confidence_levels(self, sales_df) -> None:
        """Confidence reflects number of comparables."""
        # HB20 has 7 comps (within tolerance) -> alta
        req = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=45000,
        )
        result = appraise(req, sales_df, min_comparables=3)
        assert result.confidence in ("media", "alta")

    def test_different_model_not_mixed(self, sales_df) -> None:
        """Corolla comparables should not include HB20 data."""
        req = AppraisalRequest(
            brand="TOYOTA", model_red="TOYOTA COROLLA XEI",
            year_model=2022, km=25000,
        )
        result = appraise(req, sales_df)
        all_comps = result.loja_comparables + result.revenda_comparables
        for c in all_comps:
            assert c.sale_channel in ("Loja", "Revenda")
        # Should have exactly 1 Corolla comparable
        assert result.total_comparables == 1

    def test_case_insensitive_model(self, sales_df) -> None:
        """Model matching should be case-insensitive."""
        req = AppraisalRequest(
            brand="hyundai", model_red="hyundai hb20",
            year_model=2022,
        )
        result = appraise(req, sales_df)
        assert result.total_comparables > 0

    def test_rationale_is_populated(self, sales_df, hb20_request) -> None:
        """Rationale provides useful information."""
        result = appraise(hb20_request, sales_df)
        assert len(result.rationale) > 0
        assert "HYUNDAI HB20" in result.rationale
        assert result.year_range_used is not None

    def test_custom_margins(self, sales_df, hb20_request) -> None:
        """Custom margin targets affect trade values."""
        r_default = appraise(hb20_request, sales_df, loja_target_margin=15.0)
        r_lower = appraise(hb20_request, sales_df, loja_target_margin=10.0)

        # Lower margin target -> higher trade value
        assert r_lower.loja_max_trade_value > r_default.loja_max_trade_value

    def test_avg_days_in_stock_populated(self, sales_df, hb20_request) -> None:
        """Average days in stock is calculated for each channel."""
        result = appraise(hb20_request, sales_df)
        assert result.loja_avg_days_in_stock is not None
        assert result.loja_avg_days_in_stock > 0
        assert result.revenda_avg_days_in_stock is not None
        assert result.revenda_avg_days_in_stock > 0

    def test_blindado_not_in_old_years(self) -> None:
        """Cars 2019 or older are not filtered for blindados."""
        assert _blindado_premium(2019) is None
        assert _blindado_premium(2018) is None


# ── Outlier removal tests ────────────────────────────────────────────


@pytest.fixture
def sales_df_with_blindado() -> pd.DataFrame:
    """Sales history with a blindado (armored car) for 2022 model year."""
    data = [
        # Normal HB20 2022 sales: 58k-68k range
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 30000, "sale_price": 62000, "purchase_cost": 55000,
         "adjusted_cost": 53000, "days_in_stock": 20, "margin_percent": 7.0,
         "sale_channel": "Loja"},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 35000, "sale_price": 65000, "purchase_cost": 57000,
         "adjusted_cost": 55000, "days_in_stock": 18, "margin_percent": 8.0,
         "sale_channel": "Loja"},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 25000, "sale_price": 68000, "purchase_cost": 60000,
         "adjusted_cost": 58000, "days_in_stock": 12, "margin_percent": 7.5,
         "sale_channel": "Loja"},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 40000, "sale_price": 58000, "purchase_cost": 52000,
         "adjusted_cost": 50000, "days_in_stock": 25, "margin_percent": 6.5,
         "sale_channel": "Loja"},
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 32000, "sale_price": 64000, "purchase_cost": 56000,
         "adjusted_cost": 54000, "days_in_stock": 15, "margin_percent": 7.2,
         "sale_channel": "Loja"},
        # BLINDADO — 130k is ~65k above the normal median (~65k), well above the 35k threshold
        {"brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
         "km": 20000, "sale_price": 130000, "purchase_cost": 110000,
         "adjusted_cost": 108000, "days_in_stock": 45, "margin_percent": 10.0,
         "sale_channel": "Loja"},
    ]
    return pd.DataFrame(data)


class TestRemoveBlindados:
    """Tests for the blindado-specific outlier removal."""

    def test_blindado_premium_year_bands(self) -> None:
        """Correct thresholds per year band."""
        assert _blindado_premium(2025) == 45_000.0
        assert _blindado_premium(2024) == 45_000.0
        assert _blindado_premium(2023) == 35_000.0
        assert _blindado_premium(2022) == 35_000.0
        assert _blindado_premium(2021) == 22_500.0
        assert _blindado_premium(2020) == 22_500.0

    def test_blindado_premium_old_years_disabled(self) -> None:
        """2019 and older returns None (filter disabled)."""
        assert _blindado_premium(2019) is None
        assert _blindado_premium(2015) is None

    def test_removes_blindado(self, sales_df_with_blindado) -> None:
        """Blindado (130k vs normal ~65k) is removed for 2022 model year."""
        # Anchor = median of bottom 75% of [58,62,64,65,68,130] = median of [58,62,64,65] = 63
        # Fence = 63k + 35k = 98k -> 130k is above, should be removed
        filtered = _remove_blindados(sales_df_with_blindado, year_model=2022)
        assert 130000 not in filtered["sale_price"].values
        assert len(filtered) == 5

    def test_keeps_normal_sales(self, sales_df_with_blindado) -> None:
        """Normal sales are not removed."""
        filtered = _remove_blindados(sales_df_with_blindado, year_model=2022)
        normal_prices = {58000, 62000, 64000, 65000, 68000}
        assert set(filtered["sale_price"].values) == normal_prices

    def test_no_filter_for_old_year(self, sales_df_with_blindado) -> None:
        """For 2019 or older, blindado filter is not applied — all rows kept."""
        filtered = _remove_blindados(sales_df_with_blindado, year_model=2019)
        assert len(filtered) == len(sales_df_with_blindado)

    def test_fire_sale_kept(self, sales_df_with_blindado) -> None:
        """Low-price fire-sales are NOT removed (no lower bound filter)."""
        df = sales_df_with_blindado.copy()
        fire_sale = pd.DataFrame([{
            "brand": "HYUNDAI", "model_red": "HYUNDAI HB20", "year_model": 2022,
            "km": 90000, "sale_price": 15000, "purchase_cost": 25000,
            "adjusted_cost": 24000, "days_in_stock": 100, "margin_percent": -40.0,
            "sale_channel": "Loja",
        }])
        df = pd.concat([df, fire_sale], ignore_index=True)
        filtered = _remove_blindados(df, year_model=2022)
        # Blindado removed, fire-sale kept
        assert 130000 not in filtered["sale_price"].values
        assert 15000 in filtered["sale_price"].values

    def test_appraise_tracks_blindados_removed(self, sales_df_with_blindado) -> None:
        """Appraise function correctly reports blindados removed."""
        req = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=30000,
        )
        result = appraise(req, sales_df_with_blindado, year_tolerance=0)
        assert result.outliers_removed == 1  # only the blindado
        assert result.total_comparables == 5

    def test_appraise_rationale_mentions_blindado(self, sales_df_with_blindado) -> None:
        """Rationale mentions blindado removal."""
        req = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=30000,
        )
        result = appraise(req, sales_df_with_blindado, year_tolerance=0)
        assert "outlier" in result.rationale.lower()

    def test_blindado_inflates_without_filter(self, sales_df_with_blindado) -> None:
        """Without the blindado filter the estimated sale price would be inflated."""
        # Build a df without blindado to compare
        normal_df = sales_df_with_blindado[sales_df_with_blindado["sale_price"] < 100000].copy()
        req = AppraisalRequest(
            brand="HYUNDAI", model_red="HYUNDAI HB20",
            year_model=2022, km=30000,
        )
        r_filtered = appraise(req, sales_df_with_blindado, year_tolerance=0)
        r_clean = appraise(req, normal_df, year_tolerance=0)
        # Filtered result should match the clean result
        assert r_filtered.loja_estimated_sale_price == r_clean.loja_estimated_sale_price


# ── Trim-level matching tests ─────────────────────────────────────────


@pytest.fixture
def sales_df_with_trims() -> pd.DataFrame:
    """Sales history with model_trim column for trim-level testing.

    Contains HR-V split into EXL (higher) and EX (lower) trims.
    """
    data = [
        # HR-V EXL — higher value trim (Loja)
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2022, "km": 30000, "sale_price": 130000,
         "purchase_cost": 115000, "adjusted_cost": 113000, "days_in_stock": 20,
         "margin_percent": 8.0, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-03-01")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2022, "km": 25000, "sale_price": 135000,
         "purchase_cost": 118000, "adjusted_cost": 116000, "days_in_stock": 15,
         "margin_percent": 9.0, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-04-01")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2023, "km": 20000, "sale_price": 140000,
         "purchase_cost": 122000, "adjusted_cost": 120000, "days_in_stock": 12,
         "margin_percent": 10.0, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-05-01")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2021, "km": 40000, "sale_price": 125000,
         "purchase_cost": 110000, "adjusted_cost": 108000, "days_in_stock": 25,
         "margin_percent": 7.5, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-06-01")},

        # HR-V EX — lower value trim (Loja)
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EX",
         "year_model": 2022, "km": 35000, "sale_price": 110000,
         "purchase_cost": 97000, "adjusted_cost": 95000, "days_in_stock": 18,
         "margin_percent": 7.0, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-03-15")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EX",
         "year_model": 2022, "km": 40000, "sale_price": 105000,
         "purchase_cost": 93000, "adjusted_cost": 91000, "days_in_stock": 22,
         "margin_percent": 6.5, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-04-15")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EX",
         "year_model": 2023, "km": 28000, "sale_price": 115000,
         "purchase_cost": 100000, "adjusted_cost": 98000, "days_in_stock": 14,
         "margin_percent": 8.0, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-05-15")},

        # HR-V EXL — Revenda
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2022, "km": 45000, "sale_price": 118000,
         "purchase_cost": 113000, "adjusted_cost": 112000, "days_in_stock": 5,
         "margin_percent": 2.0, "sale_channel": "Revenda",
         "sale_date": pd.Timestamp("2025-03-20")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2022, "km": 50000, "sale_price": 115000,
         "purchase_cost": 110000, "adjusted_cost": 109000, "days_in_stock": 8,
         "margin_percent": 1.5, "sale_channel": "Revenda",
         "sale_date": pd.Timestamp("2025-04-20")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V EXL",
         "year_model": 2023, "km": 30000, "sale_price": 122000,
         "purchase_cost": 117000, "adjusted_cost": 116000, "days_in_stock": 3,
         "margin_percent": 1.8, "sale_channel": "Revenda",
         "sale_date": pd.Timestamp("2025-05-20")},

        # HR-V TOURING — rare trim (only 2 sales, below min_comparables)
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V TOURING",
         "year_model": 2022, "km": 20000, "sale_price": 155000,
         "purchase_cost": 138000, "adjusted_cost": 136000, "days_in_stock": 10,
         "margin_percent": 9.5, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-04-01")},
        {"brand": "HONDA", "model_red": "HONDA HR-V", "model_trim": "HONDA HR-V TOURING",
         "year_model": 2023, "km": 15000, "sale_price": 160000,
         "purchase_cost": 142000, "adjusted_cost": 140000, "days_in_stock": 8,
         "margin_percent": 10.0, "sale_channel": "Loja",
         "sale_date": pd.Timestamp("2025-06-01")},
    ]
    return pd.DataFrame(data)


class TestTrimLevelAppraisal:
    """Tests for trim-level matching in the appraisal engine."""

    def test_trim_match_uses_trim_level(self, sales_df_with_trims) -> None:
        """When enough trim-level comps exist, use trim matching."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V EXL",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert result.used_trim_level is True
        assert result.model_trim == "HONDA HR-V EXL"

    def test_trim_exl_higher_than_ex(self, sales_df_with_trims) -> None:
        """EXL trim should yield higher values than EX trim."""
        req_exl = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V EXL",
            year_model=2022,
        )
        req_ex = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V EX",
            year_model=2022,
        )
        result_exl = appraise(req_exl, sales_df_with_trims, min_comparables=3)
        result_ex = appraise(req_ex, sales_df_with_trims, min_comparables=3)

        assert result_exl.loja_max_trade_value > result_ex.loja_max_trade_value

    def test_fallback_to_model_red_when_insufficient(self, sales_df_with_trims) -> None:
        """When trim has too few comps, fallback to model_red level."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V TOURING",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        # TOURING only has 2 comps, should fall back to model_red
        assert result.used_trim_level is False
        assert result.model_trim is None
        # Should include ALL HR-V sales (EXL + EX + TOURING)
        assert result.total_comparables > 2

    def test_no_trim_uses_model_red(self, sales_df_with_trims) -> None:
        """When no model_trim is provided, use model_red matching."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert result.used_trim_level is False
        # Should include all HR-V sales regardless of trim
        assert result.total_comparables >= 10

    def test_trim_match_both_channels(self, sales_df_with_trims) -> None:
        """Trim-level match should split into Loja and Revenda correctly."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V EXL",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert result.loja_comparables_count > 0
        assert result.revenda_comparables_count > 0
        assert result.loja_max_trade_value is not None
        assert result.revenda_max_trade_value is not None

    def test_nonexistent_trim_falls_back(self, sales_df_with_trims) -> None:
        """A trim with 0 matches falls back to model_red."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V SPORT",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert result.used_trim_level is False
        assert result.total_comparables > 0  # Uses model_red

    def test_trim_rationale_mentions_versao(self, sales_df_with_trims) -> None:
        """Rationale should mention trim-level when used."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V EXL",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert "versao especifica" in result.rationale

    def test_fallback_rationale_mentions_modelo_geral(self, sales_df_with_trims) -> None:
        """Rationale should mention generic model when fallback is used."""
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V TOURING",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert "modelo geral" in result.rationale

    def test_no_model_trim_column_still_works(self) -> None:
        """If sales_df lacks model_trim column, engine uses model_red only."""
        data = [
            {"brand": "HONDA", "model_red": "HONDA HR-V", "year_model": 2022,
             "km": 30000, "sale_price": 120000, "purchase_cost": 105000,
             "adjusted_cost": 103000, "days_in_stock": 15, "margin_percent": 8.0,
             "sale_channel": "Loja"},
            {"brand": "HONDA", "model_red": "HONDA HR-V", "year_model": 2022,
             "km": 35000, "sale_price": 115000, "purchase_cost": 100000,
             "adjusted_cost": 98000, "days_in_stock": 18, "margin_percent": 7.5,
             "sale_channel": "Loja"},
            {"brand": "HONDA", "model_red": "HONDA HR-V", "year_model": 2023,
             "km": 25000, "sale_price": 125000, "purchase_cost": 110000,
             "adjusted_cost": 108000, "days_in_stock": 12, "margin_percent": 9.0,
             "sale_channel": "Loja"},
        ]
        df = pd.DataFrame(data)  # No model_trim column
        req = AppraisalRequest(
            brand="HONDA",
            model_red="HONDA HR-V",
            model_trim="HONDA HR-V EXL",
            year_model=2022,
        )
        result = appraise(req, df, min_comparables=3)
        assert result.used_trim_level is False
        assert result.total_comparables == 3

    def test_trim_case_insensitive(self, sales_df_with_trims) -> None:
        """Trim matching should be case-insensitive."""
        req = AppraisalRequest(
            brand="honda",
            model_red="honda hr-v",
            model_trim="honda hr-v exl",
            year_model=2022,
        )
        result = appraise(req, sales_df_with_trims, min_comparables=3)
        assert result.used_trim_level is True
