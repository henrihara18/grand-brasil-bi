"""Tests for fipe_matcher — especially cross-model contamination guards."""

import pandas as pd
import pytest

from grand_brasil.utils.fipe_matcher import (
    _score_row,
    extract_model_tokens,
    find_comparables,
)


# ── extract_model_tokens ────────────────────────────────────────────────────

def test_polo_highline_tokens():
    tokens = extract_model_tokens("Polo 200 TSI Highline (Aut)")
    assert "POLO" in tokens
    assert "HIGHLINE" in tokens
    assert "TSI" not in tokens
    assert "200" not in tokens
    assert "AUT" not in tokens


def test_tcross_highline_tokens():
    tokens = extract_model_tokens("T-Cross 200 TSI Highline (Aut)")
    assert "T-CROSS" in tokens
    assert "HIGHLINE" in tokens


def test_hrv_ex_tokens():
    tokens = extract_model_tokens("HR-V 1.8 EX FlexOne 16V 5p Aut.")
    assert "HR-V" in tokens
    assert "EX" in tokens
    assert "FLEX" not in tokens
    assert "FLEXONE" not in tokens


# ── _score_row — cross-model guard ─────────────────────────────────────────

def _row(model_red: str, model_trim: str | None = None) -> pd.Series:
    return pd.Series({"model_red": model_red, "model_trim": model_trim})


def test_polo_highline_matches_polo_highline_row():
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN POLO", "VOLKSWAGEN POLO HIGHLINE")
    assert _score_row(row, tokens) == 1.0


def test_polo_highline_does_not_match_tcross():
    """Critical: 'POLO HIGHLINE' must score 0 against any T-Cross row."""
    tokens = ["POLO", "HIGHLINE"]
    # T-Cross Highline — shares "HIGHLINE" trim but different model
    row = _row("VOLKSWAGEN T-CROSS", "VOLKSWAGEN T-CROSS HIGHLINE")
    assert _score_row(row, tokens) == 0.0


def test_polo_highline_does_not_match_tcross_no_trim():
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN T-CROSS", None)
    assert _score_row(row, tokens) == 0.0


def test_polo_highline_does_not_match_nivus():
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN NIVUS", "VOLKSWAGEN NIVUS HIGHLINE")
    assert _score_row(row, tokens) == 0.0


def test_polo_highline_matches_polo_no_trim_with_base_score():
    """When model_red matches but trim data is absent, score >= threshold (0.65)."""
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN POLO", None)          # no trim info
    assert _score_row(row, tokens) >= 0.6


def test_polo_highline_matches_polo_base_trim():
    """model_trim == model_red (trim=BASE) → treat as no trim info."""
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN POLO", "VOLKSWAGEN POLO")   # trim = BASE fallback
    assert _score_row(row, tokens) >= 0.6


def test_polo_highline_does_not_match_polo_comfortline():
    """Comfortline row with proper trim should NOT match Highline tokens."""
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN POLO", "VOLKSWAGEN POLO COMFORTLINE")
    score = _score_row(row, tokens)
    assert score < 0.6


def test_polo_model_only_token():
    """Single model token matches any Polo row."""
    tokens = ["POLO"]
    row = _row("VOLKSWAGEN POLO", "VOLKSWAGEN POLO COMFORTLINE")
    assert _score_row(row, tokens) >= 0.6


def test_nan_string_in_model_trim_treated_as_absent():
    """Pandas NaN stringified as 'nan' must not block model_red matching."""
    tokens = ["POLO", "HIGHLINE"]
    row = _row("VOLKSWAGEN POLO", "nan")
    score = _score_row(row, tokens)
    assert score >= 0.6


# ── find_comparables integration ────────────────────────────────────────────

def _make_sales_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"brand": "VOLKSWAGEN", "model_red": "VOLKSWAGEN POLO",
         "model_trim": "VOLKSWAGEN POLO HIGHLINE", "year_model": 2023,
         "sale_price": 90000, "purchase_cost": 75000, "adjusted_cost": 74000,
         "sale_channel": "Loja", "days_in_stock": 30, "margin_percent": 15.0},
        {"brand": "VOLKSWAGEN", "model_red": "VOLKSWAGEN POLO",
         "model_trim": "VOLKSWAGEN POLO COMFORTLINE", "year_model": 2023,
         "sale_price": 85000, "purchase_cost": 70000, "adjusted_cost": 69000,
         "sale_channel": "Loja", "days_in_stock": 25, "margin_percent": 14.0},
        {"brand": "VOLKSWAGEN", "model_red": "VOLKSWAGEN T-CROSS",
         "model_trim": "VOLKSWAGEN T-CROSS HIGHLINE", "year_model": 2023,
         "sale_price": 120000, "purchase_cost": 100000, "adjusted_cost": 99000,
         "sale_channel": "Loja", "days_in_stock": 20, "margin_percent": 15.0},
    ])


def test_find_comparables_polo_highline_excludes_tcross():
    df = _make_sales_df()
    result = find_comparables("VW - VolksWagen", "Polo 200 TSI Highline (Aut)", 2023, df)
    assert len(result) > 0, "Deveria encontrar vendas de Polo"
    assert not any("T-CROSS" in str(r).upper() for r in result["model_red"]), \
        "T-Cross nao deve aparecer nos comparaveis de Polo"


def test_find_comparables_polo_returns_polo_rows():
    df = _make_sales_df()
    result = find_comparables("VW - VolksWagen", "Polo 200 TSI Highline (Aut)", 2023, df)
    assert all("POLO" in m for m in result["model_red"])


# ── Tiered selection: exact match preferred over no-trim fallback ───────────

def _make_song_plus_df() -> pd.DataFrame:
    """Song Plus and Song Plus Premium rows — both share model_red 'BYD SONG PLUS'."""
    return pd.DataFrame([
        # Song Plus Premium (trim extracted correctly)
        {"brand": "BYD", "model_red": "BYD SONG PLUS",
         "model_trim": "BYD SONG PLUS PREMIUM", "year_model": 2024,
         "sale_price": 185000, "purchase_cost": 155000, "adjusted_cost": 153000,
         "sale_channel": "Loja", "days_in_stock": 20, "margin_percent": 14.0},
        {"brand": "BYD", "model_red": "BYD SONG PLUS",
         "model_trim": "BYD SONG PLUS PREMIUM", "year_model": 2024,
         "sale_price": 188000, "purchase_cost": 158000, "adjusted_cost": 156000,
         "sale_channel": "Loja", "days_in_stock": 18, "margin_percent": 14.5},
        # Song Plus (non-premium, no trim extracted → model_trim == model_red)
        {"brand": "BYD", "model_red": "BYD SONG PLUS",
         "model_trim": "BYD SONG PLUS", "year_model": 2024,
         "sale_price": 160000, "purchase_cost": 135000, "adjusted_cost": 133000,
         "sale_channel": "Loja", "days_in_stock": 25, "margin_percent": 13.0},
    ])


def test_song_plus_premium_excludes_regular_song_plus():
    """When Premium rows exist (score 1.0), regular Song Plus (score 0.65) must be excluded."""
    df = _make_song_plus_df()
    result = find_comparables("BYD", "Song Plus Premium DM-i 110km (Aut)", 2024, df)
    assert len(result) > 0, "Deveria encontrar vendas de Song Plus Premium"
    assert all("PREMIUM" in str(m) for m in result["model_trim"]), \
        "Apenas rows de Song Plus Premium devem ser retornados"
    # The non-premium row (price 160k) must not appear
    assert not any(float(r) == 160000 for r in result["sale_price"]), \
        "Venda do Song Plus sem premium nao deve aparecer"


def test_song_plus_no_trim_data_fallback():
    """When NO Premium rows exist (all model_trim == model_red), include them as fallback."""
    df = pd.DataFrame([
        # All Song Plus rows without trim data
        {"brand": "BYD", "model_red": "BYD SONG PLUS",
         "model_trim": "BYD SONG PLUS", "year_model": 2024,
         "sale_price": 160000, "purchase_cost": 135000, "adjusted_cost": 133000,
         "sale_channel": "Loja", "days_in_stock": 25, "margin_percent": 13.0},
        {"brand": "BYD", "model_red": "BYD SONG PLUS",
         "model_trim": "BYD SONG PLUS", "year_model": 2024,
         "sale_price": 162000, "purchase_cost": 136000, "adjusted_cost": 134000,
         "sale_channel": "Revenda", "days_in_stock": 15, "margin_percent": 10.0},
    ])
    result = find_comparables("BYD", "Song Plus Premium DM-i 110km (Aut)", 2024, df)
    # Should fall back to model-level matches since no trim data exists
    assert len(result) == 2, "Deve retornar as vendas de Song Plus como fallback de modelo"
