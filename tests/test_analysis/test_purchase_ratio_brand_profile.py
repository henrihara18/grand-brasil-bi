"""Tests for the per-brand year profile of the buy-ratio engine."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.purchase_ratio import compute_brand_year_profile, compute_buy_ratio
from grand_brasil.config import BuyRatioConfig


def _row(model_red, brand, year, km, ratio):
    return {
        "model_red": model_red, "brand": brand, "year_model": year, "km": km, "ratio": ratio,
        "status_norm": "UTILIZADO", "weight": 1.0, "fipe_value": 100_000.0,
        "appraised_value": ratio * 100_000.0, "appraisal_date": pd.Timestamp("2026-01-15"),
    }


def _base() -> pd.DataFrame:
    rows = []
    # BYD: steep curve (2022 -> 2023 = +0.20), 15 rows per cell; TOYOTA: flat (+0.02),
    # 40 rows per cell so the GLOBAL curve is dominated by Toyota (delta ~ +0.02).
    for brand, r22, r23, n in (("BYD", 0.60, 0.80, 15), ("TOYOTA", 0.84, 0.86, 40)):
        for year, ratio in ((2022, r22), (2023, r23)):
            rows += [_row(f"{brand} X", brand, year, 30_000, ratio) for _ in range(n)]
    return pd.DataFrame(rows)


def test_brand_profile_only_for_cells_with_enough_rows():
    prof = compute_brand_year_profile(_base(), min_rows=15)
    assert prof["BYD"][2023] - prof["BYD"][2022] == pytest.approx(0.20)
    assert prof["TOYOTA"][2023] - prof["TOYOTA"][2022] == pytest.approx(0.02)
    prof16 = compute_brand_year_profile(_base(), min_rows=16)
    assert "BYD" not in prof16 and "TOYOTA" in prof16


def test_adjacent_year_adjustment_uses_brand_curve_when_enabled():
    df = _base()
    # Remove BYD X 2023 so the target falls back to year +-1 (the 2022 rows),
    # but keep a BYD 2023 cell from another model so the brand curve exists.
    df = df[~((df["brand"] == "BYD") & (df["year_model"] == 2023))]
    extra = pd.DataFrame([_row("BYD Y", "BYD", 2023, 90_000, 0.80) for _ in range(15)])
    df = pd.concat([df, extra], ignore_index=True)

    off = compute_buy_ratio("BYD X", 2023, 30_000, df, config=BuyRatioConfig(year_profile_by_brand=False))
    on = compute_buy_ratio("BYD X", 2023, 30_000, df, config=BuyRatioConfig(year_profile_by_brand=True))
    assert off.tier == on.tier == "year_pm1_km12k"
    assert on.ratio_median == pytest.approx(0.80, abs=1e-6)   # 0.60 + 0.20 from the BYD curve
    assert off.ratio_median < on.ratio_median                 # global curve (mixed with Toyota) under-adjusts


def test_falls_back_to_global_curve_when_brand_cell_missing():
    df = _base()
    df = df[~((df["brand"] == "BYD") & (df["year_model"] == 2023))]   # no BYD 2023 anywhere
    on = compute_buy_ratio("BYD X", 2023, 30_000, df, config=BuyRatioConfig(year_profile_by_brand=True))
    off = compute_buy_ratio("BYD X", 2023, 30_000, df, config=BuyRatioConfig(year_profile_by_brand=False))
    assert on.ratio_median == pytest.approx(off.ratio_median)
