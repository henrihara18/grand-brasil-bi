"""Tests for backtest case linking and target definition."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.backtest.dataset import (
    MarginTargets,
    add_targets,
    link_cases,
    loja_margin_targets,
    price_band,
    realized_margin,
)


def _appr(plate, date, status="UTILIZADO", value=80_000.0, fipe=100_000.0, year=2022):
    return {"plate": plate, "appraisal_date": pd.Timestamp(date), "status_norm": status,
            "appraised_value": value, "fipe_value": fipe, "year_model": year, "km": 30_000,
            "brand": "HYUNDAI", "model_red": "HYUNDAI CRETA"}


def _sale(plate, date, price=100_000.0, taxes=2_000.0, cost=80_000.0, channel="Loja", filial="72 - HYU"):
    return {"plate": plate, "sale_date": pd.Timestamp(date), "sale_price": price, "taxes": taxes,
            "adjusted_cost": cost, "purchase_cost": cost, "sale_channel": channel, "Filial": filial,
            "days_in_stock": 30, "brand": "HYUNDAI", "model_red": "HYUNDAI CRETA LIMITED",
            "model_trim": "HYUNDAI CRETA LIMITED", "year_model": 2022, "km": 31_000}


class TestLinkCases:
    def test_links_to_first_sale_on_or_after_appraisal(self):
        appr = pd.DataFrame([_appr("ABC1D23", "2026-02-10")])
        sales = pd.DataFrame([_sale("ABC-1D23", "2026-01-05", price=90_000), _sale("ABC1D23", "2026-03-20", price=100_000)])
        cases = link_cases(appr, sales, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"))
        assert len(cases) == 1
        assert cases.iloc[0]["sale_price"] == 100_000 and cases.iloc[0]["lag_days"] == 38

    def test_ignores_sales_beyond_max_lag_and_open_appraisals(self):
        appr = pd.DataFrame([_appr("AAA1111", "2026-02-10"), _appr("BBB2222", "2026-02-10", status="AVALIADO")])
        sales = pd.DataFrame([_sale("AAA1111", "2027-06-01"), _sale("BBB2222", "2026-03-01")])
        cases = link_cases(appr, sales, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"), max_lag_days=365)
        assert cases.empty

    def test_two_closed_appraisals_before_one_sale_keep_latest(self):
        appr = pd.DataFrame([_appr("AAA1111", "2026-01-10", value=70_000), _appr("AAA1111", "2026-02-10", value=75_000)])
        sales = pd.DataFrame([_sale("AAA1111", "2026-03-01")])
        cases = link_cases(appr, sales, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"))
        assert len(cases) == 1 and cases.iloc[0]["appraised_value"] == 75_000

    def test_respects_test_window(self):
        appr = pd.DataFrame([_appr("AAA1111", "2025-12-10")])
        sales = pd.DataFrame([_sale("AAA1111", "2026-01-15")])
        cases = link_cases(appr, sales, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"))
        assert cases.empty


class TestTargets:
    def test_realized_margin_after_taxes(self):
        df = pd.DataFrame([{"sale_price": 100_000.0, "taxes": 2_000.0, "adjusted_cost": 88_000.0}])
        assert realized_margin(df).iloc[0] == pytest.approx(0.10)

    def test_price_band_edges(self):
        assert list(price_band(pd.Series([60_000, 60_001, 250_000]))) == ["<=60k", "60-90k", ">220k"]

    def test_loja_targets_use_only_sales_before_cutoff(self):
        sales = pd.DataFrame([
            _sale("A", "2025-06-01", price=50_000, taxes=1_000, cost=39_000),   # margin 20%
            _sale("B", "2026-02-01", price=50_000, taxes=1_000, cost=49_000),   # margin 0% (after cutoff)
            _sale("C", "2025-07-01", price=50_000, taxes=1_000, cost=44_000, channel="Revenda"),
        ])
        t = loja_margin_targets(sales, until=pd.Timestamp("2026-01-01"))
        assert t.loja_by_band["<=60k"] == pytest.approx(0.20)
        assert t.revenda == 0.0

    def test_custo_ideal_per_channel(self):
        cases = pd.DataFrame([
            {**_sale("A", "2026-02-01", price=100_000, taxes=2_000, channel="Loja"), "appraised_value": 85_000.0},
            {**_sale("B", "2026-02-01", price=100_000, taxes=2_000, channel="Revenda"), "appraised_value": 99_000.0},
        ])
        t = MarginTargets(loja_by_band={b: 0.10 for b in ["<=60k", "60-90k", "90-120k", "120-160k", "160-220k", ">220k"]}, revenda=0.0)
        out = add_targets(cases, t)
        assert out.loc[0, "custo_ideal"] == pytest.approx(88_000)   # 100k - 2k - 10%
        assert out.loc[1, "custo_ideal"] == pytest.approx(98_000)   # 100k - 2k - 0%
        assert out.loc[1, "paid_vs_ideal_pct"] == pytest.approx(1_000 / 98_000)
