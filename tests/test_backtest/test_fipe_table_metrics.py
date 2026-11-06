"""Tests for the offline FIPE table and the metric helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from grand_brasil.backtest.fipe_table import FipeTable, TableFipeClient
from grand_brasil.backtest.metrics import add_errors, breakdown, summarize


def _appr_rows():
    return pd.DataFrame([
        {"model_red": "HYUNDAI CRETA", "year_model": 2022, "appraisal_date": pd.Timestamp("2026-03-10"), "fipe_value": 100_000.0},
        {"model_red": "HYUNDAI CRETA", "year_model": 2022, "appraisal_date": pd.Timestamp("2026-03-20"), "fipe_value": 102_000.0},
        {"model_red": "HYUNDAI CRETA", "year_model": 2022, "appraisal_date": pd.Timestamp("2026-06-01"), "fipe_value": 98_000.0},
        {"model_red": "HYUNDAI CRETA", "year_model": 2020, "appraisal_date": pd.Timestamp("2026-03-01"), "fipe_value": 80_000.0},
    ])


class TestFipeTable:
    def test_median_per_model_year_month(self):
        t = FipeTable(_appr_rows())
        assert t.lookup("HYUNDAI CRETA", 2022, pd.Period("2026-03", "M")) == 101_000.0
        assert t.lookup("hyundai creta ", 2020, pd.Period("2026-03", "M")) == 80_000.0

    def test_nearest_month_within_three(self):
        t = FipeTable(_appr_rows())
        assert t.lookup("HYUNDAI CRETA", 2022, pd.Period("2026-05", "M")) == 98_000.0   # June is 1 away, March 2
        assert t.lookup("HYUNDAI CRETA", 2022, pd.Period("2026-10", "M")) is None

    def test_client_raises_on_miss_and_counts(self):
        c = TableFipeClient(FipeTable(_appr_rows()))
        assert c.get_reference_code_for_date(pd.Timestamp("2026-03-15")) == "2026-03"
        price = c.get_historical_price("HYUNDAI", "HYUNDAI CRETA", "2022", "2026-03")
        assert float(price.value) == 101_000.0 and c.hits == 1
        with pytest.raises(KeyError):
            c.get_historical_price("HYUNDAI", "FIAT UNO", "2022", "2026-03")
        assert c.misses == 1


class TestMetrics:
    def _df(self):
        return pd.DataFrame({
            "pred": [100.0, 110.0, np.nan, 95.0],
            "custo_ideal": [100.0, 100.0, 100.0, 100.0],
            "sale_price": [120.0, 120.0, 120.0, 120.0],
            "taxes": [2.0, 2.0, 2.0, 2.0],
            "km": [10_000, 30_000, 60_000, 150_000],
            "year_model": [2016, 2020, 2023, 2024],
            "model_volume_train": [0, 10, 30, 100],
            "sale_channel": ["Loja", "Loja", "Revenda", "Revenda"],
        })

    def test_errors_and_summary(self):
        df = add_errors(self._df())
        s = summarize(df)
        assert s["n"] == 4 and s["n_pred"] == 3 and s["coverage"] == pytest.approx(0.75)
        assert s["mape"] == pytest.approx((0 + 0.10 + 0.05) / 3)
        assert s["within_5"] == pytest.approx(2 / 3)
        assert df.loc[0, "margin_if_paid_pred"] == pytest.approx((120 - 2 - 100) / 120)
        assert list(df["km_band"]) == ["<=20k", "20-50k", "50-100k", ">100k"]
        assert list(df["year_band"]) == ["<=2017", "2018-2022", "2023+", "2023+"]
        assert list(df["volume_band"]) == ["0-4", "5-19", "20-49", "50+"]

    def test_breakdown_respects_min_n(self):
        df = add_errors(self._df())
        assert breakdown(df, "sale_channel", min_n=3).empty
        t = breakdown(df, "sale_channel", min_n=2)
        assert set(t.index) == {"Loja", "Revenda"}
