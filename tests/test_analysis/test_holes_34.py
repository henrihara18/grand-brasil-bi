"""Tests for hole fixes 3-4: piecewise KM slope, KM-out-of-range signal, purpose-aware comparables."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.confidence import Signals, km_out_of_range, signals_from_row
from grand_brasil.analysis.purchase_ratio import _km_delta, compute_buy_ratio, compute_km_slope_piecewise
from grand_brasil.config import BuyRatioConfig


def _row(model_red, year, km, ratio, status="UTILIZADO", purpose="SHOWROOM", plate=None):
    return {"model_red": model_red, "brand": "HYUNDAI", "year_model": year, "km": km, "ratio": ratio,
            "status_norm": status, "weight": 1.0 if status != "AVALIADO" else 0.25, "fipe_value": 100_000.0,
            "appraised_value": ratio * 100_000.0, "purpose": purpose, "plate": plate or f"P{abs(hash((model_red, year, km, ratio, purpose))) % 10**7}",
            "appraisal_date": pd.Timestamp("2026-01-15")}


class TestPiecewiseKm:
    def test_band_slopes_and_integration(self):
        rows = []
        for model in ("A", "B", "C"):
            for i in range(8):                       # 0-80k: -0.01 per 10k
                rows.append(_row(model, 2022, i * 10_000, 0.90 - 0.01 * i))
            for i in range(8, 30):                   # 80k-300k: -0.03 per 10k (steeper)
                rows.append(_row(model, 2022, i * 10_000, 0.90 - 0.08 - 0.03 * (i - 8)))
        df = pd.DataFrame(rows)
        pw = compute_km_slope_piecewise(df, breaks=[100_000], min_band_rows=20)
        assert pw["breaks"] == [100_000] and len(pw["slopes"]) == 2
        assert pw["slopes"][1] < pw["slopes"][0] < 0               # high-KM band steeper
        # going from 50k to 250k: 5 bands of 10k at slope[0] + 15 at slope[1]
        d = _km_delta(50_000, 250_000, pw)
        assert d == pytest.approx(5 * pw["slopes"][0] + 15 * pw["slopes"][1], abs=1e-9)
        assert _km_delta(250_000, 50_000, pw) == pytest.approx(-d)
        assert _km_delta(50_000, 70_000, -0.01) == pytest.approx(-0.02)   # linear still works

    def test_engine_records_km_range_of_comparables(self):
        rows = [_row("HYUNDAI X", 2022, km, 0.80) for km in (40_000, 55_000, 70_000, 90_000, 120_000)]
        r = compute_buy_ratio("HYUNDAI X", 2022, 300_000, pd.DataFrame(rows), config=BuyRatioConfig())
        assert r.tier == "same_year" and (r.km_min_used, r.km_max_used) == (40_000, 120_000)


class TestKmOutSignal:
    def test_out_of_range_flag_and_label(self):
        assert km_out_of_range(300_000, 40_000, 120_000) is True
        assert km_out_of_range(130_000, 40_000, 120_000) is False            # within the 25k margin
        assert km_out_of_range(10_000, 40_000, 120_000) is True
        assert km_out_of_range(None, 40_000, 120_000) is False
        s = signals_from_row(pd.Series({"buy_ratio_tier": "same_year", "km": 300_000, "buy_ratio_km_min": 40_000,
                                        "buy_ratio_km_max": 120_000, "anchor_divergence_pct": 0.02,
                                        "buy_ratio_low": 0.7, "buy_ratio_high": 0.74, "buy_ratio_price": 0.72, "buy_ratio_closed_n": 5}))
        assert s.tier == "same_year|km_fora"
        inside = signals_from_row(pd.Series({"buy_ratio_tier": "same_year", "km": 80_000, "buy_ratio_km_min": 40_000, "buy_ratio_km_max": 120_000}))
        assert inside.tier == "same_year"


class TestPurposeAware:
    def _base(self):
        rows = [_row("HYUNDAI X", 2022, 50_000, 0.88, purpose="SHOWROOM") for _ in range(8)]
        rows += [_row("HYUNDAI X", 2022, 50_000, 0.80, purpose="REPASSE") for _ in range(6)]
        return pd.DataFrame(rows)

    def test_revenda_prefers_repasse_comparables(self):
        df = self._base()
        off = compute_buy_ratio("HYUNDAI X", 2022, 50_000, df, config=BuyRatioConfig(), prefer_purpose=None)
        on = compute_buy_ratio("HYUNDAI X", 2022, 50_000, df, config=BuyRatioConfig(), prefer_purpose="REPASSE")
        assert off.ratio_median == pytest.approx(0.88) and off.purpose_filtered is False
        assert on.ratio_median == pytest.approx(0.80) and on.purpose_filtered is True and "REPASSE" in on.description

    def test_falls_back_to_all_when_too_few_of_that_purpose(self):
        df = self._base()
        few = df[~((df.purpose == "REPASSE") & (df.index >= 10))]      # only 2 REPASSE rows left
        on = compute_buy_ratio("HYUNDAI X", 2022, 50_000, few, config=BuyRatioConfig(), prefer_purpose="REPASSE")
        assert on.purpose_filtered is False and on.ratio_median == pytest.approx(0.88)
