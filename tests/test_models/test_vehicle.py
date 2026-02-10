"""Tests for the Vehicle Pydantic model."""

from decimal import Decimal

from grand_brasil.models.enums import VehicleStatus
from grand_brasil.models.vehicle import Vehicle


class TestVehicle:
    """Tests for Vehicle model creation and computed fields."""

    def test_create_basic_vehicle(self) -> None:
        """Vehicle can be created with minimal required fields."""
        vehicle = Vehicle(
            brand="CHEVROLET",
            model="ONIX 1.0",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("45000.00"),
        )
        assert vehicle.brand == "CHEVROLET"
        assert vehicle.model == "ONIX 1.0"
        assert vehicle.year_model == 2021
        assert vehicle.status == VehicleStatus.IN_STOCK

    def test_margin_percent_calculation(self) -> None:
        """Margin percentage is correctly computed."""
        vehicle = Vehicle(
            brand="CHEVROLET",
            model="ONIX",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("45000.00"),
        )
        # (50000 - 45000) / 45000 * 100 = 11.11%
        assert abs(vehicle.margin_percent - 11.11) < 0.01

    def test_margin_percent_zero_cost(self) -> None:
        """Margin is 0 when purchase cost is 0."""
        vehicle = Vehicle(
            brand="CHEVROLET",
            model="ONIX",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("0"),
        )
        assert vehicle.margin_percent == 0.0

    def test_computed_adjusted_cost(self) -> None:
        """Adjusted cost = purchase_cost + operational_expense - bonus_value."""
        vehicle = Vehicle(
            brand="CHEVROLET",
            model="ONIX",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("46820.00"),
            operational_expense=Decimal("1170.00"),
            bonus_value=Decimal("2000.00"),
        )
        # 46820 + 1170 - 2000 = 45990
        assert vehicle.computed_adjusted_cost == Decimal("45990.00")

    def test_fipe_delta_percent_above(self) -> None:
        """FIPE delta is positive when asking price is above FIPE."""
        vehicle = Vehicle(
            brand="CHEVROLET",
            model="ONIX",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("55000.00"),
            purchase_cost=Decimal("45000.00"),
            fipe_price=Decimal("50000.00"),
        )
        # (55000 - 50000) / 50000 * 100 = 10%
        assert vehicle.fipe_delta_percent is not None
        assert abs(vehicle.fipe_delta_percent - 10.0) < 0.01

    def test_fipe_delta_percent_none_when_no_fipe(self) -> None:
        """FIPE delta is None when no FIPE price is set."""
        vehicle = Vehicle(
            brand="CHEVROLET",
            model="ONIX",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("45000.00"),
        )
        assert vehicle.fipe_delta_percent is None

    def test_model_key(self) -> None:
        """Model key combines brand and model in uppercase."""
        vehicle = Vehicle(
            brand="Chevrolet",
            model="Onix 1.0 Flex",
            year_model=2021,
            days_in_stock=30,
            asking_price=Decimal("50000.00"),
            purchase_cost=Decimal("45000.00"),
        )
        assert vehicle.model_key == "CHEVROLET ONIX 1.0 FLEX"

    def test_vehicle_with_all_fields(self, sample_vehicle: Vehicle) -> None:
        """Vehicle fixture has all expected fields populated."""
        assert sample_vehicle.brand == "CHEVROLET"
        assert sample_vehicle.transmission == "MANUAL"
        assert sample_vehicle.plate == "ABC1D23"
        assert sample_vehicle.days_in_stock == 50
