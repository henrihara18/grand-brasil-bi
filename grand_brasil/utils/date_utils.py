"""Brazilian date parsing and formatting utilities."""

from datetime import date, datetime
from typing import Optional


# Common Brazilian date formats
BR_DATE_FORMATS = [
    "%d/%m/%Y",    # 26/01/2026
    "%d/%m/%y",    # 26/01/26
    "%d-%m-%Y",    # 26-01-2026
    "%d-%m-%y",    # 26-01-26
    "%Y-%m-%d",    # 2026-01-26 (ISO format, sometimes used in exports)
]


def parse_br_date(text: str) -> Optional[date]:
    """Parse a Brazilian date string into a date object.

    Tries multiple common formats. Returns None if no format matches.

    Args:
        text: Date string to parse (e.g., "26/01/2026" or "2026-01-26").

    Returns:
        Parsed date or None if parsing fails.
    """
    if not text or not str(text).strip():
        return None

    cleaned = str(text).strip()

    for fmt in BR_DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


def format_br_date(d: date) -> str:
    """Format a date as Brazilian dd/mm/yyyy.

    Args:
        d: Date to format.

    Returns:
        Formatted date string, e.g., "26/01/2026".
    """
    return d.strftime("%d/%m/%Y")


def parse_year_model(am_text: str) -> int:
    """Extract the model year from an A/M (Ano/Modelo) string.

    DealerUp format: "2020/2021" where 2020 = manufacture year, 2021 = model year.
    We extract the second (model year) as it's the relevant one.

    Args:
        am_text: Year string, e.g., "2020/2021" or "2021".

    Returns:
        Model year as integer.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    cleaned = str(am_text).strip()

    if "/" in cleaned:
        parts = cleaned.split("/")
        # Take the second part (model year)
        try:
            return int(parts[1].strip())
        except (IndexError, ValueError) as e:
            raise ValueError(
                f"Formato A/M invalido: '{am_text}'. Esperado: 'AAAA/AAAA'"
            ) from e

    # Single year
    try:
        return int(cleaned)
    except ValueError as e:
        raise ValueError(
            f"Formato de ano invalido: '{am_text}'"
        ) from e
