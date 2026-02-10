"""Enumerations used across the Grand Brasil BI system."""

from enum import Enum


class AgingBracket(str, Enum):
    """Color-coded aging classification for vehicles in stock."""

    GREEN = "verde"       # 0 to green_max_days
    YELLOW = "amarelo"    # green_max_days+1 to yellow_max_days
    ORANGE = "laranja"    # yellow_max_days+1 to orange_max_days
    RED = "vermelho"      # orange_max_days+1 and above


class FuelType(str, Enum):
    """Vehicle fuel types commonly found in the Brazilian market."""

    FLEX = "flex"
    GASOLINE = "gasolina"
    ETHANOL = "etanol"
    DIESEL = "diesel"
    ELECTRIC = "eletrico"
    HYBRID = "hibrido"


class VehicleStatus(str, Enum):
    """Current status of a vehicle in the dealership inventory."""

    IN_STOCK = "estoque"
    RESERVED = "reservado"
    SOLD = "vendido"
