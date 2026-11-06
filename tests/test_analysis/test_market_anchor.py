"""Anchor M: sale/FIPE of our own sales, similarity-weighted."""

from decimal import Decimal

import pandas as pd
import pytest

from grand_brasil.analysis.market_anchor import RATIO_COL, compute_market_anchor, fit_slopes, prepare_sales_ratios
from grand_brasil.config import MarketAnchorConfig


class _Table:
    """Minimal FipeTable stand-in: 100k for every (model, year, month) except one gap."""

    def lookup(self, model_red, year_model, month, max_shift=3):
        if model_red == "SEM TABELA":
            return None
        return 100_000.0


def _sales(n=12, model="HYUNDAI CRETA", year=2022, ratio=0.80, km=40_000, channel="Loja", start="2026-01-01", **extra):
    dates = pd.date_range(start, periods=n, freq="15D")
    return pd.DataFrame({
        "brand": model.split()[0], "model_red": model, "year_model": year, "km": km,
        "sale_price": 100_000.0 * ratio, "sale_date": dates, "sale_channel": channel, **extra,
    })


REF = pd.Timestamp("2026-10-01")


def test_prepare_sales_ratios_uses_table_then_erp_fallback():
    df = pd.concat([_sales(3), _sales(2, model="SEM TABELA", FIPE=[90_000.0, 90_000.0])], ignore_index=True)
    out = prepare_sales_ratios(df, _Table())
    assert out.loc[0, RATIO_COL] == pytest.approx(0.80)
    assert out.loc[3, RATIO_COL] == pytest.approx(80_000 / 90_000)   # ERP FIPE filled the gap
    assert out.loc[0, "age_at_sale"] == 4


def test_prepare_sales_ratios_drops_implausible_and_without_fipe():
    df = pd.concat([_sales(1, ratio=0.80), _sales(1, ratio=2.0), _sales(1, model="SEM TABELA")], ignore_index=True)
    out = prepare_sales_ratios(df, _Table())
    assert list(out[RATIO_COL].notna()) == [True, False, False]


def test_kernel_tier_reads_the_model_ratio():
    df = prepare_sales_ratios(_sales(10, ratio=0.82), _Table())
    res = compute_market_anchor("HYUNDAI CRETA", "HYUNDAI", 2022, 40_000, Decimal("120000"), df, REF, MarketAnchorConfig())
    assert res is not None and res.tier == "kernel" and res.n == 10
    assert res.ratio == pytest.approx(0.82, abs=0.01)
    assert res.estimated_sale == pytest.approx(Decimal("98400"), abs=1500)


def test_closer_comparables_weigh_more():
    close = _sales(4, ratio=0.80, km=40_000)
    far = _sales(4, ratio=0.70, km=150_000, start="2026-02-01")
    df = prepare_sales_ratios(pd.concat([close, far], ignore_index=True), _Table())
    cfg = MarketAnchorConfig()
    res = compute_market_anchor("HYUNDAI CRETA", "HYUNDAI", 2022, 40_000, Decimal("100000"), df, REF, cfg, slopes=(0.0, 0.0))
    assert res.ratio == pytest.approx(0.80, abs=0.02)   # the 150k-km sales barely count for a 40k-km car


def test_km_slope_moves_the_ratio_toward_the_requested_km():
    df = prepare_sales_ratios(_sales(8, ratio=0.80, km=20_000), _Table())
    cfg = MarketAnchorConfig()
    low = compute_market_anchor("HYUNDAI CRETA", "HYUNDAI", 2022, 20_000, Decimal("100000"), df, REF, cfg, slopes=(-0.01, 0.0))
    high = compute_market_anchor("HYUNDAI CRETA", "HYUNDAI", 2022, 80_000, Decimal("100000"), df, REF, cfg, slopes=(-0.01, 0.0))
    assert low.ratio == pytest.approx(0.80, abs=0.005)
    assert high.ratio == pytest.approx(0.80 - 0.06, abs=0.005)   # 6 x 10k km x -0.01


def test_brand_age_fallback_when_model_unknown():
    df = prepare_sales_ratios(_sales(8, model="HYUNDAI HB20", ratio=0.78), _Table())
    res = compute_market_anchor("HYUNDAI IX35", "HYUNDAI", 2022, 40_000, Decimal("100000"), df, REF, MarketAnchorConfig())
    assert res is not None and res.tier == "brand_age"
    assert res.ratio == pytest.approx(0.78, abs=0.01)


def test_none_without_ratios_or_comparables():
    assert compute_market_anchor("X", "Y", 2022, 1, Decimal("100000"), pd.DataFrame({"a": [1]}), REF, MarketAnchorConfig()) is None
    df = prepare_sales_ratios(_sales(2, model="FIAT UNO", ratio=0.8), _Table())
    assert compute_market_anchor("HYUNDAI CRETA", "HYUNDAI", 2022, 1, Decimal("100000"), df, REF, MarketAnchorConfig()) is None


def test_only_the_configured_channel_is_read():
    loja = _sales(6, ratio=0.85, channel="Loja")
    rev = _sales(6, ratio=0.70, channel="Revenda", start="2026-02-01")
    df = prepare_sales_ratios(pd.concat([loja, rev], ignore_index=True), _Table())
    res = compute_market_anchor("HYUNDAI CRETA", "HYUNDAI", 2022, 40_000, Decimal("100000"), df, REF, MarketAnchorConfig(), slopes=(0.0, 0.0))
    assert res.ratio == pytest.approx(0.85, abs=0.01)


def test_fit_slopes_defaults_on_thin_pool_and_are_non_positive():
    df = prepare_sales_ratios(_sales(5), _Table())
    km_s, age_s = fit_slopes(df)
    assert km_s <= 0 and age_s <= 0


def test_config_defaults_loaded_from_yaml():
    from grand_brasil.config import load_config
    cfg = load_config().app.appraisal
    assert cfg.market_anchor.enabled is True
    assert cfg.ensemble_partner == "market"
