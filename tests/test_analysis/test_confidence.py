"""Tests for the calibrated confidence layer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from grand_brasil.analysis.confidence import (
    ConfidenceModel,
    Signals,
    closed_bucket,
    divergence_bucket,
    signals_from_row,
    width_bucket,
)


def _residuals(n_tight=60, n_loose=60):
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(n_tight):   # km6k, converging anchors, narrow band -> small errors
        rows.append({"buy_ratio_tier": "same_year_km6k", "anchor_divergence_pct": 0.01, "buy_ratio_low": 95.0,
                     "buy_ratio_high": 98.0, "buy_ratio_price": 96.5, "buy_ratio_closed_n": 12,
                     "abs_err_pct": abs(rng.normal(0, 0.03))})
    for _ in range(n_loose):   # fallback tier -> big errors
        rows.append({"buy_ratio_tier": "model_fallback", "anchor_divergence_pct": 0.12, "buy_ratio_low": 80.0,
                     "buy_ratio_high": 100.0, "buy_ratio_price": 90.0, "buy_ratio_closed_n": 3,
                     "abs_err_pct": abs(rng.normal(0, 0.12))})
    return pd.DataFrame(rows)


def test_buckets():
    assert divergence_bucket(None) == "none" and divergence_bucket(-0.02) == "<=3%" and divergence_bucket(0.2) == ">8%"
    assert width_bucket(95, 98, 96.5) == "<=4%" and width_bucket(80, 100, 90) == ">8%" and width_bucket(None, 1, 1) == "none"
    assert closed_bucket(None) == "0" and closed_bucket(4) == "<5" and closed_bucket(7) == "5-9" and closed_bucket(10) == "10+"


def test_fit_builds_hierarchy_and_levels():
    m = ConfidenceModel(min_group=40).fit(_residuals())
    tight = m.verdict(Signals("same_year_km6k", "<=3%", "<=4%", "10+"))
    loose = m.verdict(Signals("model_fallback", ">8%", ">8%", "<5"))
    assert tight.level == "alta" and len(tight.key) == 4 and tight.n == 60
    assert loose.level == "baixa" and loose.q90 > 0.15
    assert "60 avaliações" in tight.reason


def test_falls_back_to_less_specific_key_then_global():
    m = ConfidenceModel(min_group=40).fit(_residuals())
    unseen_combo = m.verdict(Signals("same_year_km6k", ">8%", ">8%", "<5"))   # tier seen, combo not
    assert unseen_combo.key == ("same_year_km6k",)
    unseen_tier = m.verdict(Signals("year_pm2_km24k", "none", "none", "0"))
    assert unseen_tier.key == () and unseen_tier.n == 120


def test_json_roundtrip(tmp_path):
    m = ConfidenceModel(min_group=40, high_max_q90=0.09).fit(_residuals())
    m.to_json(tmp_path / "c.json")
    back = ConfidenceModel.from_json(tmp_path / "c.json")
    assert back.high_max_q90 == 0.09 and back.table == m.table


def test_signals_from_row_handles_nans():
    r = pd.Series({"buy_ratio_tier": None, "anchor_divergence_pct": np.nan, "buy_ratio_low": np.nan,
                   "buy_ratio_high": np.nan, "buy_ratio_price": np.nan, "buy_ratio_closed_n": np.nan})
    s = signals_from_row(r)
    assert s == Signals("none", "none", "none", "0")
