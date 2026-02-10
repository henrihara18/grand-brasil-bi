"""Brazilian Real (BRL) currency formatting and parsing utilities."""

import re
from decimal import Decimal, InvalidOperation


def format_brl(value: Decimal | float | int) -> str:
    """Format a numeric value as Brazilian Real currency.

    Examples:
        >>> format_brl(Decimal("85000.00"))
        'R$ 85.000,00'
        >>> format_brl(1234.5)
        'R$ 1.234,50'
        >>> format_brl(0)
        'R$ 0,00'
    """
    value = Decimal(str(value))
    # Format with 2 decimal places
    formatted = f"{value:,.2f}"
    # Swap commas and periods for Brazilian format
    # "85,000.00" -> "85.000,00"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def parse_brl(text: str) -> Decimal:
    """Parse a Brazilian currency string into a Decimal.

    Handles formats:
        - "R$ 85.000,00"
        - "85.000,00"
        - "85000,00"
        - "85000.00" (fallback US format)
        - "85000"

    Args:
        text: Currency string to parse.

    Returns:
        Parsed Decimal value.

    Raises:
        ValueError: If the string cannot be parsed as a currency value.
    """
    if not text or not str(text).strip():
        return Decimal("0")

    original = str(text).strip()

    # Remove "R$" prefix and whitespace
    cleaned = re.sub(r"R\$\s*", "", original).strip()

    # Remove any non-numeric characters except . , - +
    cleaned = re.sub(r"[^\d.,-]", "", cleaned)

    if not cleaned:
        return Decimal("0")

    # Detect Brazilian format: has dot as thousands separator, comma as decimal
    # e.g., "85.000,00"
    if "," in cleaned and "." in cleaned:
        # Brazilian format: dots are thousands, comma is decimal
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned and "." not in cleaned:
        # Only comma: treat as decimal separator ("85000,00")
        cleaned = cleaned.replace(",", ".")
    # else: US format or no decimal ("85000.00" or "85000")

    try:
        return Decimal(cleaned)
    except InvalidOperation as e:
        raise ValueError(
            f"Nao foi possivel converter '{original}' para valor numerico"
        ) from e


def format_percent(value: float, decimals: int = 1) -> str:
    """Format a float as a percentage string.

    Examples:
        >>> format_percent(15.5)
        '15,5%'
        >>> format_percent(0.0)
        '0,0%'
    """
    formatted = f"{value:.{decimals}f}".replace(".", ",")
    return f"{formatted}%"
