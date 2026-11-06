"""Offline stand-in for the FIPE API, built from FIPE values observed in the appraisal base.

Production asks the FIPE API for the price of (model, year) in the month each
comparable was sold. In a backtest with thousands of appraisals that is not
feasible, so this table reproduces it from the appraisal base itself: every
appraisal records the FIPE value of (family, year_model) on its date, which is
the same public number the API would return for that month.

Keyed by (family model_red, year_model, "YYYY-MM"); when a month is missing the
nearest month within ±3 is used. Lookups that fail raise, which the engine
treats exactly like a failed API call (the comparable is skipped).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pandas as pd

from grand_brasil.models.fipe import FipePrice


class FipeTable:
    def __init__(self, appraisals: pd.DataFrame):
        df = appraisals.dropna(subset=["fipe_value", "appraisal_date", "year_model"]).copy()
        df = df[df["fipe_value"] > 0]
        df["ym"] = df["appraisal_date"].dt.to_period("M")
        grouped = df.groupby(["model_red", "year_model", "ym"])["fipe_value"].median()
        self._table: dict[tuple[str, int, pd.Period], float] = {
            (str(k[0]), int(k[1]), k[2]): float(v) for k, v in grouped.items()
        }
        self.size = len(self._table)

    def lookup(self, model_red: str, year_model: int, month: pd.Period, max_shift: int = 3) -> Optional[float]:
        key = (model_red.strip().upper(), int(year_model), month)
        if key in self._table:
            return self._table[key]
        for shift in range(1, max_shift + 1):
            for cand in (month - shift, month + shift):
                k = (key[0], key[1], cand)
                if k in self._table:
                    return self._table[k]
        return None


class TableFipeClient:
    """Duck-types the two FipeClient methods used by the spread computation."""

    def __init__(self, table: FipeTable):
        self.table = table
        self.hits = 0
        self.misses = 0

    def get_reference_code_for_date(self, sale_date: object) -> Optional[str]:
        if sale_date is None or pd.isna(sale_date):
            return None
        ts = pd.Timestamp(sale_date)
        return f"{ts.year}-{ts.month:02d}"

    def get_historical_price(self, brand_code: str, model_code: str, year_code: str, reference_code: str) -> FipePrice:
        month = pd.Period(reference_code, freq="M")
        value = self.table.lookup(model_code, int(year_code), month)
        if value is None:
            self.misses += 1
            raise KeyError(f"FIPE indisponivel: {model_code} {year_code} {reference_code}")
        self.hits += 1
        return FipePrice(
            fipe_code="backtest", value=Decimal(str(round(value, 2))), brand=brand_code,
            model=model_code, fuel="-", reference_month=reference_code, year_model=int(year_code),
        )
