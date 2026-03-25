"""Pydantic models for FIPE API data."""

from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import BaseModel, model_validator


def _normalise_api_dict(data: object) -> object:
    """Map raw FIPE API keys (codigo/nome) to internal keys (code/name).

    Handles both the raw API format and already-normalised dicts so that
    model_validate() works regardless of the source (API response or disk cache).
    """
    if not isinstance(data, dict):
        return data
    if "codigo" in data and "code" not in data:
        data["code"] = str(data["codigo"])
    if "nome" in data and "name" not in data:
        data["name"] = str(data["nome"])
    # Always ensure code is a string (API may return int for model codes)
    if "code" in data:
        data["code"] = str(data["code"])
    return data


class FipeBrand(BaseModel):
    """A vehicle brand from the FIPE catalog."""

    code: str   # e.g. "59"
    name: str   # e.g. "VW - VolksWagen"

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: object) -> object:
        return _normalise_api_dict(data)


class FipeModel(BaseModel):
    """A vehicle model from the FIPE catalog."""

    code: str   # e.g. "5940"
    name: str   # e.g. "HR-V 1.8 EX FlexOne 16V 5p Aut."

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: object) -> object:
        return _normalise_api_dict(data)


class FipeYear(BaseModel):
    """A year/version entry from the FIPE catalog."""

    code: str       # e.g. "2022-1"
    name: str       # e.g. "2022 Flex"
    year_int: int   # extracted from code: int("2022-1".split("-")[0]) = 2022

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: object) -> object:
        data = _normalise_api_dict(data)
        if isinstance(data, dict) and "year_int" not in data and "code" in data:
            try:
                data["year_int"] = int(str(data["code"]).split("-")[0])
            except (ValueError, IndexError):
                data["year_int"] = 0
        return data


class FipePrice(BaseModel):
    """Price result from the FIPE API for a specific brand/model/year."""

    fipe_code: str          # e.g. "004278-1"
    value: Decimal          # e.g. Decimal("85000.00")
    brand: str              # e.g. "Honda"
    model: str              # e.g. "HR-V 1.8 EX FlexOne 16V 5p Aut."
    fuel: str               # e.g. "Flex", "Gasolina"
    reference_month: str    # e.g. "abril de 2026"
    year_model: int         # e.g. 2022

    @classmethod
    def parse_brl_value(cls, raw: str) -> Decimal:
        """Parse a Brazilian currency string to Decimal.

        Handles formats like "R$ 85.000,00" or "85.000,00".
        Raises ValueError if the format is unexpected.
        """
        cleaned = raw.strip()
        if cleaned.startswith("R$"):
            cleaned = cleaned[2:].strip()
        # Brazilian format: dots as thousands separator, comma as decimal
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return Decimal(cleaned)
        except InvalidOperation as e:
            raise ValueError(f"Formato de valor FIPE inesperado: '{raw}'") from e
