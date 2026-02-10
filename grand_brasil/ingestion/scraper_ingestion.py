"""Web scraper ingestion strategy — placeholder for future DealerUp scraping."""

from pathlib import Path
from typing import Optional

import pandas as pd

from grand_brasil.ingestion.base import IngestionStrategy


class ScraperIngestionStrategy(IngestionStrategy):
    """Scrapes DealerUp stock page using Playwright.

    Status: PLACEHOLDER — requires DealerUp credentials and
    reverse-engineering of the Vue.js SPA DOM structure.
    """

    def __init__(
        self,
        username: str = "",
        password: str = "",
        headless: bool = True,
    ):
        self._username = username
        self._password = password
        self._headless = headless

    @property
    def strategy_name(self) -> str:
        return "Web Scraper (DealerUp)"

    def validate_source(self, source: Optional[Path] = None) -> bool:
        """Test login credentials and page accessibility."""
        return False  # Not yet implemented

    def ingest(self, source: Optional[Path] = None) -> pd.DataFrame:
        """Scrape DealerUp stock data.

        Raises:
            NotImplementedError: This strategy is not yet implemented.
        """
        raise NotImplementedError(
            "A estrategia de scraping ainda nao foi implementada. "
            "Use o upload de CSV/Excel como metodo principal de importacao."
        )
