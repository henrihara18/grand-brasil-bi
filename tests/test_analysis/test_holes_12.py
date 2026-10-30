"""Tests for the hole fixes: sparse year-profile cells, plate dedupe, paid reconciliation, ratio floors."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.purchase_ratio import _dedupe_by_plate, compute_buy_ratio, compute_year_ratio_profile
from grand_brasil.config import BuyRatioConfig
from grand_brasil.ingestion.appraisal_history import drop_implausible_ratios, reconcile_with_sales


def _row(model_red, year, km, ratio, status="UTILIZADO", plate="AAA1111", date="2026-03-01", brand="HYUNDAI"):
    return {"model_red": model_red, "brand": brand, "year_model": year, "km": km, "ratio": ratio, "status_norm": status,
            "weight": 1.0 if status != "AVALIADO" else 0.25, "fipe_value": 100_000.0, "appraised_value": ratio * 100_000.0,
            "plate": plate, "appraisal_date": pd.Timestamp(date)}


class TestYearProfileMinRows:
    def test_sparse_cell_is_ignored(self):
        rows = [_row("X", 2026, 10_000, 0.87, plate=f"P{i}") for i in range(40)] + [_row("X", 2027, 500, 0.67, plate="Q1"), _row("X", 2027, 500, 0.68, plate="Q2")]
        df = pd.DataFrame(rows)
        assert 2027 in compute_year_ratio_profile(df)                 # legacy: 2 rows define the cell
        assert 2027 not in compute_year_ratio_profile(df, min_rows=30)

    def test_no_adjustment_when_target_year_cell_missing(self):
        rows = [_row("HYUNDAI X", 2026, 3_000, 0.88, plate=f"P{i}") for i in range(6)]
        rows += [_row("HYUNDAI Y", 2027, 500, 0.67, plate="Q1"), _row("HYUNDAI Y", 2027, 500, 0.68, plate="Q2")]
        rows += [_row("HYUNDAI Z", 2026, 3_000, 0.88, plate=f"R{i}") for i in range(30)]
        df = pd.DataFrame(rows)
        legacy = compute_buy_ratio("HYUNDAI X", 2027, 400, df, config=BuyRatioConfig(year_profile_min_rows=1))
        fixed = compute_buy_ratio("HYUNDAI X", 2027, 400, df, config=BuyRatioConfig(year_profile_min_rows=30))
        assert legacy.tier == fixed.tier == "year_pm1_km12k"
        assert legacy.ratio_median < 0.75                               # the −0.20 artefact
        assert fixed.ratio_median == pytest.approx(0.88)                # no delta without a reliable 2027 cell


class TestDedupeByPlate:
    def test_closed_row_wins_then_latest(self):
        df = pd.DataFrame([
            _row("X", 2023, 30_000, 0.80, "AVALIADO", "ABC1D23", "2026-01-10"),
            _row("X", 2023, 30_000, 0.85, "UTILIZADO", "ABC-1D23", "2026-01-15"),
            _row("X", 2023, 30_000, 0.78, "AVALIADO", "ZZZ9Z99", "2026-02-01"),
            _row("X", 2023, 30_000, 0.79, "AVALIADO", "ZZZ9Z99", "2026-02-20"),
            _row("X", 2023, 30_000, 0.70, "AVALIADO", None, "2026-02-20"),
        ])
        out = _dedupe_by_plate(df)
        assert len(out) == 3
        kept = out.set_index("ratio")
        assert 0.85 in kept.index and 0.79 in kept.index and 0.70 in kept.index

    def test_engine_toggle(self):
        # Three distinct closed deals at 0.90 + the same car closed three times at 0.60
        rows = [_row("X", 2023, 30_000, 0.90, "UTILIZADO", f"P{i}") for i in range(3)]
        rows += [_row("X", 2023, 30_000, 0.60, "REPASSE", "DUP0001", f"2026-01-0{d}") for d in (1, 3, 5)]
        df = pd.DataFrame(rows)
        off = compute_buy_ratio("X", 2023, 30_000, df, config=BuyRatioConfig(dedupe_by_plate=False))
        on = compute_buy_ratio("X", 2023, 30_000, df, config=BuyRatioConfig(dedupe_by_plate=True))
        assert off.sample_size == 6 and off.ratio_median == pytest.approx(0.60)   # duplicates drag the median
        assert on.sample_size == 4 and on.ratio_median == pytest.approx(0.90)


class TestReconcileWithSales:
    def test_replaces_only_when_off_by_more_than_tolerance(self):
        appr = pd.DataFrame([
            _row("X", 2023, 30_000, 0.85, plate="AAA1111", date="2026-01-10"),   # paid 85k, sale cost 131k -> fixed
            _row("X", 2023, 30_000, 0.86, plate="BBB2222", date="2026-01-10"),   # paid 86k, cost 87k -> kept
            _row("X", 2023, 30_000, 0.50, "AVALIADO", "CCC3333", "2026-01-10"), # offer, untouched
        ])
        sales = pd.DataFrame([
            {"plate": "AAA-1111", "sale_date": pd.Timestamp("2026-02-20"), "adjusted_cost": 131_000.0},
            {"plate": "BBB2222", "sale_date": pd.Timestamp("2026-02-20"), "adjusted_cost": 87_000.0},
        ])
        out = reconcile_with_sales(appr, sales, tolerance=0.05)
        a = out.set_index("plate")
        assert a.loc["AAA1111", "appraised_value"] == 131_000.0 and a.loc["AAA1111", "ratio"] == pytest.approx(1.31)
        assert a.loc["AAA1111", "paid_source"] == "venda"
        assert a.loc["BBB2222", "appraised_value"] == 86_000.0 and a.loc["BBB2222", "paid_source"] == "confirmado"
        assert a.loc["CCC3333", "ratio"] == 0.50 and a.loc["CCC3333", "paid_source"] == "avaliacao"


class TestRatioFloor:
    def test_floor_by_age_drops_only_closed_rows(self):
        floors = {0: 0.70, 1: 0.65, 3: 0.65, 6: 0.58, 10: 0.50, 99: 0.40}
        df = pd.DataFrame([
            _row("X", 2026, 1_000, 0.60, plate="A"),                 # age 0, below 0.70 -> dropped
            _row("X", 2023, 30_000, 0.58, plate="B"),                # age 3, below 0.65 -> dropped
            _row("X", 2023, 30_000, 0.66, plate="C"),                # age 3, ok
            _row("X", 2015, 150_000, 0.45, plate="D"),               # age 11, floor 0.40 -> ok
            _row("X", 2023, 30_000, 0.30, "AVALIADO", "E"),          # offer -> never dropped
        ])
        out = drop_implausible_ratios(df, floors)
        assert sorted(out["plate"]) == ["C", "D", "E"]

    def test_confirmed_extreme_deal_is_kept(self):
        floors = {0: 0.70, 1: 0.65, 3: 0.65, 6: 0.58, 10: 0.50, 99: 0.40}
        df = pd.DataFrame([
            {**_row("X", 2022, 309_000, 0.46, plate="A"), "paid_source": "confirmado"},   # real: 309k km at 46% of FIPE
            {**_row("X", 2023, 30_000, 0.58, plate="B"), "paid_source": "venda"},         # corrected by the sale -> trusted
            {**_row("X", 2023, 30_000, 0.58, plate="C"), "paid_source": "avaliacao"},     # unconfirmed -> dropped
        ])
        assert sorted(drop_implausible_ratios(df, floors)["plate"]) == ["A", "B"]

    def test_empty_table_is_noop(self):
        df = pd.DataFrame([_row("X", 2023, 30_000, 0.30)])
        assert len(drop_implausible_ratios(df, {})) == 1
