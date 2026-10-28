"""Tests for the Fase-4 sales-anchor toggles: per-row-year FIPE spread, median spread, margin basis."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from grand_brasil.analysis._fipe_spread import _year_code_for_row, compute_fipe_spreads
from grand_brasil.analysis.appraisal import _calc_max_trade
from grand_brasil.models.fipe import FipePrice


class _Client:
    """FIPE stub: price depends on the year code only (2020 -> 80k, 2022 -> 100k)."""
    prices = {"2020-1": 80_000, "2022-1": 100_000}

    def __init__(self):
        self.calls: list[str] = []

    def get_reference_code_for_date(self, d):
        return "300"

    def get_historical_price(self, brand, model, year_code, ref):
        self.calls.append(year_code)
        return FipePrice(fipe_code="x", value=Decimal(self.prices[year_code]), brand=brand, model=model,
                         fuel="Flex", reference_month="m", year_model=int(year_code[:4]))


def _df():
    return pd.DataFrame([
        {"sale_price": 100_000.0, "sale_date": pd.Timestamp("2026-01-10"), "year_model": 2022},
        {"sale_price": 80_000.0, "sale_date": pd.Timestamp("2026-01-10"), "year_model": 2020},
    ])


def test_year_code_keeps_fuel_suffix():
    assert _year_code_for_row("2020-1", pd.Series({"year_model": 2022})) == "2022-1"
    assert _year_code_for_row("2020", pd.Series({"year_model": 2022})) == "2022"
    assert _year_code_for_row("2020-1", pd.Series({"year_model": None})) == "2020-1"


def test_legacy_uses_request_year_for_every_comparable():
    c = _Client()
    spread, n = compute_fipe_spreads(_df(), c, "b", "m", "2020-1", pd.Timestamp("2026-02-01"), 180.0)
    assert c.calls == ["2020-1", "2020-1"] and n == 2
    # 100k/80k-1 = +25 % and 80k/80k-1 = 0 -> mean +12.5 % (the spurious spread)
    assert spread == pytest.approx(0.125)


def test_per_row_year_removes_spurious_spread():
    c = _Client()
    spread, n = compute_fipe_spreads(_df(), c, "b", "m", "2020-1", pd.Timestamp("2026-02-01"), 180.0,
                                     per_row_year=True)
    assert c.calls == ["2022-1", "2020-1"]
    assert spread == pytest.approx(0.0)


def test_median_aggregation_resists_one_outlier():
    df = pd.concat([_df().assign(year_model=2020, sale_price=80_000.0)] * 2 + [
        pd.DataFrame([{"sale_price": 160_000.0, "sale_date": pd.Timestamp("2026-01-10"), "year_model": 2020}])
    ], ignore_index=True)
    mean, _ = compute_fipe_spreads(df, _Client(), "b", "m", "2020-1", pd.Timestamp("2026-02-01"), 180.0)
    median, _ = compute_fipe_spreads(df, _Client(), "b", "m", "2020-1", pd.Timestamp("2026-02-01"), 180.0,
                                     aggregation="median")
    assert mean == pytest.approx(0.20) and median == pytest.approx(0.0)


class TestMarginBasis:
    def test_markup_is_legacy(self):
        assert _calc_max_trade(Decimal("114000"), 14.0, Decimal("0")) == Decimal("100000")

    def test_sale_basis_with_taxes(self):
        # 100k sale, 2 % tax, 10 % margin on the sale -> cost 88k
        assert _calc_max_trade(Decimal("100000"), 10.0, Decimal("0"), basis="sale", tax_pct=2.0) == Decimal("88000")

    def test_sale_basis_subtracts_repair_and_rounds(self):
        assert _calc_max_trade(Decimal("100000"), 10.0, Decimal("1200"), basis="sale", tax_pct=2.0) == Decimal("87000")
