"""Backtest cases: closed appraisals linked to the car's subsequent sale.

A case is one UTILIZADO/REPASSE appraisal whose plate shows up in the sales
history with a sale date on or after the appraisal date. The target is the
cost that would have delivered the target margin on that real sale:

    custo_ideal = sale_price − taxes − margin_target × sale_price

    margin_target  Loja    = realized median margin (after taxes) of the
                             price band, measured on sales before the test
                             period (so the target never looks at test data)
                   Revenda = 0 (break even after taxes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PRICE_BAND_EDGES = [0, 60_000, 90_000, 120_000, 160_000, 220_000, np.inf]
PRICE_BAND_LABELS = ["<=60k", "60-90k", "90-120k", "120-160k", "160-220k", ">220k"]

CLOSED_STATUSES = {"UTILIZADO", "REPASSE"}


def normalize_plate(series: pd.Series) -> pd.Series:
    return series.astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def price_band(prices: pd.Series) -> pd.Series:
    return pd.cut(prices, PRICE_BAND_EDGES, labels=PRICE_BAND_LABELS, include_lowest=True).astype(str)


@dataclass(frozen=True)
class MarginTargets:
    loja_by_band: dict[str, float]      # band label -> margin on sale (0-1), after taxes
    revenda: float = 0.0

    def for_sale(self, channel: str, sale_price: float) -> float:
        if str(channel).strip().lower() == "revenda":
            return self.revenda
        band = price_band(pd.Series([sale_price])).iloc[0]
        return self.loja_by_band[band]


def realized_margin(df: pd.DataFrame) -> pd.Series:
    """Marg. Ini. / Vl Venda: (venda − impostos − custo ajustado) / venda."""
    taxes = df["taxes"].fillna(0.0) if "taxes" in df.columns else 0.0
    return (df["sale_price"] - taxes - df["adjusted_cost"]) / df["sale_price"]


def loja_margin_targets(sales: pd.DataFrame, until: pd.Timestamp, revenda: float = 0.0) -> MarginTargets:
    """Median realized Loja margin per price band, using only sales before `until`."""
    loja = sales[(sales["sale_channel"].str.lower() == "loja") & (sales["sale_date"] < until)].copy()
    loja["band"] = price_band(loja["sale_price"])
    loja["margin"] = realized_margin(loja)
    medians = loja.groupby("band")["margin"].median()
    by_band = {b: float(medians.get(b, medians.median())) for b in PRICE_BAND_LABELS}
    logger.info(f"Loja margin targets (sales < {until:%Y-%m-%d}): {by_band}")
    return MarginTargets(loja_by_band=by_band, revenda=revenda)


def link_cases(
    appraisals: pd.DataFrame,
    sales: pd.DataFrame,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    max_lag_days: int = 365,
) -> pd.DataFrame:
    """Closed appraisals in [test_start, test_end) joined to their next sale by plate."""
    a = appraisals[appraisals["status_norm"].isin(CLOSED_STATUSES)].copy()
    a = a[a["appraisal_date"].notna() & a["plate"].notna()]
    a["plate_norm"] = normalize_plate(a["plate"])
    a = a[(a["appraisal_date"] >= test_start) & (a["appraisal_date"] < test_end)]
    a = a[a["plate_norm"].str.len() >= 6]

    s = sales[sales["sale_date"].notna() & sales["plate"].notna()].copy()
    s["plate_norm"] = normalize_plate(s["plate"])
    s = s.rename(columns={
        "brand": "sale_brand", "model_red": "sale_model_red", "model_trim": "sale_model_trim",
        "year_model": "sale_year_model", "km": "sale_km",
    })
    keep = ["plate_norm", "sale_date", "sale_price", "taxes", "adjusted_cost", "purchase_cost",
            "sale_channel", "Filial", "days_in_stock", "sale_brand", "sale_model_red",
            "sale_model_trim", "sale_year_model", "sale_km"]
    s = s[[c for c in keep if c in s.columns]].sort_values("sale_date")

    a = a.sort_values("appraisal_date")
    linked = pd.merge_asof(
        a, s, left_on="appraisal_date", right_on="sale_date", by="plate_norm",
        direction="forward", tolerance=pd.Timedelta(days=max_lag_days),
    )
    linked = linked[linked["sale_date"].notna()].copy()
    # Same car appraised twice (closed) before one sale: keep the appraisal closest to the sale
    linked = linked.sort_values("appraisal_date").drop_duplicates(["plate_norm", "sale_date"], keep="last")
    linked["lag_days"] = (linked["sale_date"] - linked["appraisal_date"]).dt.days
    logger.info(f"Linked {len(linked)} closed appraisals to a later sale (of {len(a)})")
    return linked.reset_index(drop=True)


def add_targets(cases: pd.DataFrame, targets: MarginTargets) -> pd.DataFrame:
    df = cases.copy()
    df["price_band"] = price_band(df["sale_price"])
    is_rev = df["sale_channel"].str.lower() == "revenda"
    df["margin_target"] = np.where(is_rev, targets.revenda, df["price_band"].map(targets.loja_by_band))
    df["custo_ideal"] = df["sale_price"] - df["taxes"].fillna(0.0) - df["margin_target"] * df["sale_price"]
    df["margin_realized"] = realized_margin(df)
    df["paid_vs_ideal_pct"] = (df["appraised_value"] - df["custo_ideal"]) / df["custo_ideal"]
    return df
