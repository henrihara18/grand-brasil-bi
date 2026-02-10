"""Shared test fixtures for the Grand Brasil BI test suite."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from grand_brasil.config import (
    AgingThresholds,
    AppConfig,
    B2BScoringWeights,
    PriceReductionRule,
    Settings,
)
from grand_brasil.models.enums import VehicleStatus
from grand_brasil.models.vehicle import Vehicle


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_vehicle() -> Vehicle:
    """A single sample vehicle for unit tests."""
    return Vehicle(
        brand="CHEVROLET",
        model="ONIX 1.0 FLEX PLUS LT MANUAL",
        year_model=2021,
        transmission="MANUAL",
        plate="ABC1D23",
        color="PRETO",
        fuel_type="FLEX",
        mileage=137408,
        days_in_stock=50,
        asking_price=Decimal("50000.00"),
        purchase_cost=Decimal("46820.00"),
        bonus_value=Decimal("2000.00"),
        operational_expense=Decimal("1170.00"),
        status=VehicleStatus.IN_STOCK,
    )


@pytest.fixture
def sample_vehicles() -> list[Vehicle]:
    """A list of diverse vehicles for batch analysis tests."""
    return [
        Vehicle(
            brand="CHEVROLET",
            model="ONIX 1.0 FLEX PLUS LT",
            year_model=2021,
            days_in_stock=15,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("45000.00"),
        ),
        Vehicle(
            brand="CHEVROLET",
            model="ONIX 1.0 FLEX PLUS LT",
            year_model=2021,
            days_in_stock=45,
            asking_price=Decimal("48000.00"),
            purchase_cost=Decimal("44000.00"),
        ),
        Vehicle(
            brand="CHEVROLET",
            model="ONIX 1.0 FLEX PLUS LT",
            year_model=2022,
            days_in_stock=95,
            asking_price=Decimal("55000.00"),
            purchase_cost=Decimal("52000.00"),
        ),
        Vehicle(
            brand="TOYOTA",
            model="COROLLA XEI 2.0 FLEX",
            year_model=2023,
            days_in_stock=30,
            asking_price=Decimal("130000.00"),
            purchase_cost=Decimal("115000.00"),
        ),
        Vehicle(
            brand="VOLKSWAGEN",
            model="GOL 1.0 MPI",
            year_model=2020,
            days_in_stock=120,
            asking_price=Decimal("38000.00"),
            purchase_cost=Decimal("35000.00"),
            fipe_price=Decimal("36000.00"),
        ),
        Vehicle(
            brand="HYUNDAI",
            model="HB20 1.0 COMFORT",
            year_model=2022,
            days_in_stock=65,
            asking_price=Decimal("62000.00"),
            purchase_cost=Decimal("58000.00"),
        ),
        Vehicle(
            brand="FIAT",
            model="ARGO 1.0 DRIVE",
            year_model=2023,
            days_in_stock=10,
            asking_price=Decimal("68000.00"),
            purchase_cost=Decimal("60000.00"),
        ),
    ]


@pytest.fixture
def default_config() -> Settings:
    """Default application configuration for tests."""
    return Settings(
        app=AppConfig(
            aging=AgingThresholds(
                green_max_days=30,
                yellow_max_days=60,
                orange_max_days=90,
            ),
            price_reduction_rules=[
                PriceReductionRule(
                    days_threshold=45,
                    reduction_percent=5.0,
                    min_margin_percent=3.0,
                ),
                PriceReductionRule(
                    days_threshold=60,
                    reduction_percent=10.0,
                    min_margin_percent=2.0,
                ),
                PriceReductionRule(
                    days_threshold=90,
                    reduction_percent=15.0,
                    min_margin_percent=1.0,
                ),
            ],
            b2b_scoring=B2BScoringWeights(
                aging_weight=0.4,
                concentration_weight=0.4,
                margin_weight=0.2,
                score_threshold=7.0,
                concentration_limit=3,
            ),
        )
    )


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return FIXTURES_DIR
