"""appraise() uses the calibrated confidence when a model is supplied."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from grand_brasil.analysis.appraisal import appraise
from grand_brasil.analysis.confidence import ConfidenceModel
from grand_brasil.config import AppraisalConfig
from grand_brasil.models.appraisal import AppraisalRequest


def _sales(n=12):
    return pd.DataFrame([{
        "brand": "HYUNDAI", "model_red": "HYUNDAI CRETA", "model_trim": "HYUNDAI CRETA", "modelo_full": "CRETA",
        "year_model": 2022, "km": 30_000 + i * 1000, "sale_price": 100_000.0 + i * 500, "purchase_cost": 85_000.0,
        "adjusted_cost": 85_000.0, "days_in_stock": 20, "sale_channel": "Loja" if i % 2 else "Revenda",
        "margin_percent": 10.0, "plate": f"P{i}", "sale_date": pd.Timestamp("2025-10-01") + pd.Timedelta(days=i),
    } for i in range(n)])


def _appraisals(n=8):
    return pd.DataFrame([{
        "model_red": "HYUNDAI CRETA", "brand": "HYUNDAI", "year_model": 2022, "km": 30_000 + i * 500,
        "ratio": 0.85 + 0.002 * i, "status_norm": "UTILIZADO", "weight": 1.0, "fipe_value": 100_000.0,
        "appraised_value": 85_000.0, "appraisal_date": pd.Timestamp("2025-11-01"), "plate": f"A{i}",
    } for i in range(n)])


def _model():
    rows = [{"buy_ratio_tier": "same_year_km6k", "anchor_divergence_pct": 0.01, "buy_ratio_low": 0.84,
             "buy_ratio_high": 0.86, "buy_ratio_price": 0.85, "buy_ratio_closed_n": 8,
             "abs_err_pct": abs(np.random.default_rng(i).normal(0, 0.03))} for i in range(60)]
    return ConfidenceModel(min_group=40).fit(pd.DataFrame(rows))


def test_without_model_confidence_is_count_based():
    req = AppraisalRequest(brand="HYUNDAI", model_red="HYUNDAI CRETA", year_model=2022, km=31_000, fipe_price=Decimal("100000"))
    s = appraise(req, _sales(), appraisal_df=_appraisals(), appraisal_config=AppraisalConfig())
    assert s.confidence_source == "contagem" and s.confidence in ("alta", "media", "baixa")


def test_with_model_confidence_is_calibrated():
    req = AppraisalRequest(brand="HYUNDAI", model_red="HYUNDAI CRETA", year_model=2022, km=31_000, fipe_price=Decimal("100000"))
    s = appraise(req, _sales(), appraisal_df=_appraisals(), appraisal_config=AppraisalConfig(), confidence_model=_model())
    assert s.buy_ratio_available and s.buy_ratio_tier == "same_year_km6k"
    assert s.confidence_source == "calibrada"
    assert s.confidence == "alta" and 0 < s.confidence_q90 < 0.10 and s.confidence_n == 60
    assert "avaliações passadas" in s.confidence_reason
