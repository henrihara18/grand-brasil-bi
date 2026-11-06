"""Dashboard FIPE client: offline table first, live API only for months the table lacks."""

from decimal import Decimal

import pandas as pd
import pytest

from grand_brasil.dashboard.pages._avaliacao.fipe_hybrid import HybridFipeClient
from grand_brasil.models.fipe import FipePrice


class _Table:
    def __init__(self, known):
        self.known = known

    def lookup(self, model_red, year_model, month, max_shift=3):
        return self.known.get((model_red, year_model, str(month)))


class _Live:
    def __init__(self):
        self.calls = []

    def get_reference_code_for_date(self, sale_date):
        return "r330"

    def get_historical_price(self, brand_code, model_code, year_code, reference_code):
        self.calls.append((brand_code, model_code, year_code, reference_code))
        return FipePrice(fipe_code="api", value=Decimal("70000"), brand=brand_code, model=model_code,
                         fuel="-", reference_month=reference_code, year_model=int(year_code.split("-")[0]))

    def get_brands(self):
        return ["catalogo"]


def test_table_answers_without_touching_the_api():
    live = _Live()
    hybrid = HybridFipeClient(live, _Table({("HYUNDAI HB20", 2024, "2026-03"): 75000.0}), "Hyundai HB20")
    ref = hybrid.get_reference_code_for_date(pd.Timestamp("2026-03-15"))
    assert ref == "2026-03"
    price = hybrid.get_historical_price("26", "10778", "2024-5", ref)
    assert price.value == Decimal("75000") and price.fipe_code == "tabela"
    assert live.calls == [] and hybrid.table_hits == 1


def test_api_fills_months_the_table_lacks():
    live = _Live()
    hybrid = HybridFipeClient(live, _Table({}), "HYUNDAI HB20")
    price = hybrid.get_historical_price("26", "10778", "2024-5", "2025-11")
    assert price.value == Decimal("70000")
    assert live.calls == [("26", "10778", "2024-5", "r330")] and hybrid.live_calls == 1


def test_catalog_methods_go_to_the_live_client():
    hybrid = HybridFipeClient(_Live(), None, "X")
    assert hybrid.get_brands() == ["catalogo"]


def test_missing_sale_date_gives_no_reference():
    hybrid = HybridFipeClient(_Live(), None, "X")
    assert hybrid.get_reference_code_for_date(None) is None
    assert hybrid.get_reference_code_for_date(pd.NaT) is None
