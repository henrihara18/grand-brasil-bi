"""Tests for ratio shrinkage toward a prior and the year-adjustment scale."""

from __future__ import annotations

import pandas as pd
import pytest

from grand_brasil.analysis.purchase_ratio import compute_buy_ratio
from grand_brasil.config import BuyRatioConfig


def _row(model_red, year, km, ratio, brand="HYUNDAI"):
    return {"model_red": model_red, "brand": brand, "year_model": year, "km": km, "ratio": ratio,
            "status_norm": "UTILIZADO", "weight": 1.0, "fipe_value": 100_000.0,
            "appraised_value": ratio * 100_000.0, "appraisal_date": pd.Timestamp("2026-01-15")}


def test_shrink_pulls_small_sample_toward_global_year_prior():
    rows = [_row("HYUNDAI CRETA", 2023, 30_000, 0.95) for _ in range(5)]           # local median 0.95, n=5
    rows += [_row("TOYOTA COROLLA", 2023, 30_000, 0.80, "TOYOTA") for _ in range(50)]  # prior for 2023 ≈ 0.80
    df = pd.DataFrame(rows)
    off = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df, config=BuyRatioConfig(shrink_k=0.0))
    on = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df, config=BuyRatioConfig(shrink_k=5.0))
    assert off.ratio_median == pytest.approx(0.95) and off.shrink_weight is None
    assert on.shrink_weight == pytest.approx(0.5)                       # 5 / (5 + 5)
    assert on.ratio_median == pytest.approx(0.5 * 0.95 + 0.5 * on.prior_ratio)
    assert on.ratio_p75 - on.ratio_p25 == pytest.approx(off.ratio_p75 - off.ratio_p25)   # band keeps its width
    assert "referencia" in on.description


def test_shrink_uses_brand_curve_when_available():
    rows = [_row("HYUNDAI CRETA", 2023, 30_000, 0.95) for _ in range(5)]
    rows += [_row("HYUNDAI HB20", 2023, 30_000, 0.90) for _ in range(20)]            # Hyundai 2023 ≈ 0.90
    rows += [_row("TOYOTA COROLLA", 2023, 30_000, 0.80, "TOYOTA") for _ in range(50)]
    df = pd.DataFrame(rows)
    on = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df,
                           config=BuyRatioConfig(shrink_k=5.0, year_profile_by_brand=True))
    assert on.prior_ratio == pytest.approx(0.90)


def test_year_adjust_scale_zero_disables_the_year_delta():
    rows = [_row("HYUNDAI CRETA", 2022, 30_000, 0.70) for _ in range(5)]            # only 2022 rows
    rows += [_row("HYUNDAI HB20", 2023, 30_000, 0.90) for _ in range(20)]            # makes 2023 - 2022 delta ≈ +0.20
    df = pd.DataFrame(rows)
    full = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df, config=BuyRatioConfig(year_adjust_scale=1.0))
    half = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df, config=BuyRatioConfig(year_adjust_scale=0.5))
    none = compute_buy_ratio("HYUNDAI CRETA", 2023, 30_000, df, config=BuyRatioConfig(year_adjust_scale=0.0))
    assert full.tier == "year_pm1_km12k"
    assert none.ratio_median == pytest.approx(0.70)
    assert half.ratio_median == pytest.approx((full.ratio_median + none.ratio_median) / 2)
