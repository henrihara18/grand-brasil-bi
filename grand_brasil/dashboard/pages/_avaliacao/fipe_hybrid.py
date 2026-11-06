"""FIPE client for the dashboard appraisal: offline table first, live API as fallback.

The legacy spread anchor asks for the FIPE value of EVERY comparable sale at its sale
month. Against the live API that is one HTTP call per sale month, throttled by the
API's rate limit (one answer every ~30 s after a 429), so a high-volume model such as
the HB20 took many minutes to appraise. The appraisal base already carries the FIPE of
each model, year and month (the same table the backtest uses), so historical prices
are read from it and the API is only asked for months the table does not have. The
live client keeps serving the catalog (brands, models, years) and the current price.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

import pandas as pd

from grand_brasil.backtest.fipe_table import FipeTable
from grand_brasil.models.fipe import FipePrice

logger = logging.getLogger(__name__)


class HybridFipeClient:
    """Duck-types the two FipeClient methods the spread computation uses."""

    def __init__(self, live_client, table: Optional[FipeTable], model_red: str):
        self.live = live_client
        self.table = table
        self.model_red = str(model_red).upper()
        self.table_hits = 0
        self.live_calls = 0

    def get_reference_code_for_date(self, sale_date: object) -> Optional[str]:
        if sale_date is None or pd.isna(sale_date):
            return None
        ts = pd.Timestamp(sale_date)
        return f"{ts.year}-{ts.month:02d}"

    def get_historical_price(self, brand_code: str, model_code: str, year_code: str, reference_code: str) -> FipePrice:
        year = int(str(year_code).split("-")[0])
        if self.table is not None:
            value = self.table.lookup(self.model_red, year, pd.Period(reference_code, freq="M"))
            if value:
                self.table_hits += 1
                return FipePrice(
                    fipe_code="tabela", value=Decimal(str(round(float(value), 2))), brand=brand_code,
                    model=self.model_red, fuel="-", reference_month=reference_code, year_model=year,
                )
        # Fallback: the live API wants its own reference code for that month
        self.live_calls += 1
        live_ref = self.live.get_reference_code_for_date(pd.Period(reference_code, freq="M").to_timestamp())
        if live_ref is None:
            raise KeyError(f"FIPE indisponivel para {reference_code}")
        return self.live.get_historical_price(brand_code, model_code, year_code, live_ref)

    def __getattr__(self, name):
        # Everything else (catalog, current price) goes to the live client
        return getattr(self.live, name)
