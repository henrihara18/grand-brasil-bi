"""Direct API ingestion strategy — placeholder for future DealerUp API."""

from pathlib import Path
from typing import Optional

import pandas as pd

from grand_brasil.ingestion.base import IngestionStrategy


class ApiIngestionStrategy(IngestionStrategy):
    """Calls DealerUp API endpoints directly.

    Status: PLACEHOLDER — requires discovery of API endpoints
    by inspecting network requests in the browser dev tools.
    """

    def __init__(self, base_url: str = "", token: str = ""):
        self._base_url = base_url
        self._token = token

    @property
    def strategy_name(self) -> str:
        return "API Direta (DealerUp)"

    def validate_source(self, source: Optional[Path] = None) -> bool:
        """Test API connectivity and authentication."""
        return False  # Not yet implemented

    def ingest(self, source: Optional[Path] = None) -> pd.DataFrame:
        """Call DealerUp API and return stock data.

        Raises:
            NotImplementedError: This strategy is not yet implemented.
        """
        raise NotImplementedError(
            "A estrategia de API ainda nao foi implementada. "
            "Inspecione as requisicoes de rede do DealerUp para "
            "descobrir os endpoints disponiveis."
        )
