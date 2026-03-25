"""FIPE API client with disk-based caching.

Uses the parallelum v1 API (https://parallelum.com.br/fipe/api/v1).
Cache lives in project_root/.cache/fipe/ and is refreshed automatically:
  - brands, models, years: 30-day TTL
  - prices: refreshed monthly (FIPE updates prices each month)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from grand_brasil.models.fipe import FipeBrand, FipeModel, FipePrice, FipeYear

logger = logging.getLogger(__name__)

_BASE_URL = "https://parallelum.com.br/fipe/api/v1"
_TIMEOUT = 10  # seconds
_CATALOG_TTL_DAYS = 30  # brands, models, years


class FipeApiError(Exception):
    """Raised when the FIPE API is unreachable or returns unexpected data."""


def _default_cache_dir() -> Path:
    """Return the default cache directory (project_root/.cache/fipe)."""
    return Path(__file__).resolve().parent.parent.parent / ".cache" / "fipe"


class FipeClient:
    """Client for the FIPE parallelum API with transparent disk caching."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir or _default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Public methods ──────────────────────────────────────────────

    def get_brands(self) -> list[FipeBrand]:
        """Return all car brands from FIPE, sorted by name."""
        cache_path = self.cache_dir / "brands.json"
        raw = self._load_or_fetch(cache_path, f"{_BASE_URL}/carros/marcas")
        brands = [FipeBrand.model_validate(d) for d in raw]
        return sorted(brands, key=lambda b: b.name)

    def get_models(self, brand_code: str) -> list[FipeModel]:
        """Return all models for a brand, sorted by name."""
        cache_path = self.cache_dir / f"models_{brand_code}.json"
        url = f"{_BASE_URL}/carros/marcas/{brand_code}/modelos"
        raw = self._load_or_fetch(cache_path, url, extract_key="modelos")
        models = [FipeModel.model_validate(d) for d in raw]
        return sorted(models, key=lambda m: m.name)

    def get_years(self, brand_code: str, model_code: str) -> list[FipeYear]:
        """Return available year/versions for a model, sorted descending by year."""
        cache_path = self.cache_dir / f"years_{brand_code}_{model_code}.json"
        url = f"{_BASE_URL}/carros/marcas/{brand_code}/modelos/{model_code}/anos"
        raw = self._load_or_fetch(cache_path, url)
        years = [FipeYear.model_validate(d) for d in raw]
        # Filter out "zero km" entries (year_int == 0) and very old/invalid
        years = [y for y in years if y.year_int > 1990]
        return sorted(years, key=lambda y: y.year_int, reverse=True)

    def get_price(self, brand_code: str, model_code: str, year_code: str) -> FipePrice:
        """Fetch the FIPE price for a specific brand/model/year variant.

        Cached per calendar month (FIPE updates prices monthly).
        """
        safe_year = year_code.replace("/", "_")
        cache_path = self.cache_dir / f"price_{brand_code}_{model_code}_{safe_year}.json"

        cached = self._safe_load_cache(cache_path)
        if cached and not self._is_price_stale(cached):
            data = cached["data"]
        else:
            url = f"{_BASE_URL}/carros/marcas/{brand_code}/modelos/{model_code}/anos/{year_code}"
            data = self._fetch(url)
            self._write_cache(cache_path, data)

        return self._parse_price(data, year_code)

    # ── Cache helpers ───────────────────────────────────────────────

    def _load_or_fetch(
        self,
        cache_path: Path,
        url: str,
        extract_key: Optional[str] = None,
    ) -> list[dict]:
        """Load from disk cache if fresh, otherwise fetch from API and cache."""
        cached = self._safe_load_cache(cache_path)
        if cached and not self._is_catalog_stale(cached):
            return cached["data"]

        raw = self._fetch(url)
        data = raw[extract_key] if extract_key and isinstance(raw, dict) else raw
        self._write_cache(cache_path, data)
        return data

    def _safe_load_cache(self, path: Path) -> Optional[dict]:
        """Load a cache file, returning None on any read/parse error."""
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Cache corrompido em {path}, sera ignorado: {e}")
            return None

    def _is_catalog_stale(self, envelope: dict) -> bool:
        """Return True if catalog cache (brands/models/years) is older than 30 days."""
        try:
            fetched_at = datetime.fromisoformat(envelope["fetched_at"])
            return (datetime.now() - fetched_at).days > _CATALOG_TTL_DAYS
        except Exception:
            return True

    def _is_price_stale(self, envelope: dict) -> bool:
        """Return True if price cache is from a previous calendar month."""
        try:
            fetched_at = datetime.fromisoformat(envelope["fetched_at"])
            now = datetime.now()
            return fetched_at.month != now.month or fetched_at.year != now.year
        except Exception:
            return True

    def _write_cache(self, path: Path, data: object) -> None:
        """Write data to cache with a timestamp envelope."""
        envelope = {
            "fetched_at": datetime.now().isoformat(),
            "data": data,
        }
        try:
            path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Nao foi possivel gravar cache em {path}: {e}")

    # ── Network ─────────────────────────────────────────────────────

    def _fetch(self, url: str) -> object:
        """Perform a GET request and return parsed JSON."""
        logger.debug(f"FIPE API GET: {url}")
        try:
            response = requests.get(url, timeout=_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise FipeApiError(
                f"Tempo limite excedido ao consultar a API FIPE ({url}). "
                "Verifique sua conexao com a internet."
            )
        except requests.exceptions.RequestException as e:
            raise FipeApiError(
                f"Erro ao consultar a API FIPE: {e}. "
                "Verifique sua conexao com a internet."
            )
        except ValueError as e:
            raise FipeApiError(f"API FIPE retornou dados inesperados em {url}: {e}")

    # ── Parsing ─────────────────────────────────────────────────────

    def _parse_price(self, data: dict, year_code: str) -> FipePrice:
        """Parse a FIPE price API response dict into a FipePrice model."""
        try:
            raw_value = data.get("Valor", "")
            value = FipePrice.parse_brl_value(raw_value)
            year_model = int(str(year_code).split("-")[0])
            return FipePrice(
                fipe_code=data.get("CodigoFipe", ""),
                value=value,
                brand=data.get("Marca", ""),
                model=data.get("Modelo", ""),
                fuel=data.get("Combustivel", ""),
                reference_month=data.get("MesReferencia", ""),
                year_model=year_model,
            )
        except (KeyError, ValueError) as e:
            raise FipeApiError(f"Formato de resposta FIPE inesperado: {e}. Dados: {data}")
