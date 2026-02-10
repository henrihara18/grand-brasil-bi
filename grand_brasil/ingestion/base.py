"""Abstract base class for data ingestion strategies."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import pandas as pd


class IngestionStrategy(ABC):
    """Abstract base for all data ingestion strategies.

    Implementations must:
    1. Read data from a source (file, API, scraper)
    2. Return a pandas DataFrame with standardized column names
    """

    @abstractmethod
    def ingest(self, source: Optional[Path] = None) -> pd.DataFrame:
        """Extract raw data and return a standardized DataFrame.

        Args:
            source: File path for file-based strategies, None for API/scraper.

        Returns:
            DataFrame with columns normalized by field_mapping.
        """
        ...

    @abstractmethod
    def validate_source(self, source: Optional[Path] = None) -> bool:
        """Check if the source is available and valid.

        Args:
            source: Source to validate.

        Returns:
            True if the source can be ingested.
        """
        ...

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Human-readable strategy name for logging/UI."""
        ...
