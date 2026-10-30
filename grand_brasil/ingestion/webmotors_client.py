"""
webmotors_api.py — Módulo de integração Webmotors
Expõe uma função pública limpa para consumo externo.

Dependências: apenas stdlib + requests (sem instalações extras)
Compatível com Python 3.10+

Uso rápido:
    from webmotors_api import search_webmotors

    listings = search_webmotors("Hyundai", "HB20", 2024)
    for l in listings:
        print(l["price"], l["km"], l["url"])

Configuração opcional (via variável de ambiente ou parâmetro):
    SCRAPERAPI_KEY=sua_chave  →  rotas via proxy anti-bot (recomendado)
    Sem chave               →  requisição direta (pode ser bloqueada)
"""

import hashlib
import json
import os
import random
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ── Configuração ──────────────────────────────────────────────────────────────

_BASE_URL       = "https://www.webmotors.com.br"
_API_SEARCH_URL = "https://www.webmotors.com.br/api/search/car"
_SCRAPERAPI_URL = "https://api.scraperapi.com"
_CACHE_DIR      = Path(__file__).resolve().parent.parent.parent / ".cache" / "webmotors"
_CACHE_TTL_H    = 24          # horas até expirar o cache
_RESULTS_PER_PAGE = 24
_MAX_PAGES        = 3         # máx 72 anúncios — suficiente para métricas

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


# ── Cache em disco ────────────────────────────────────────────────────────────

def _cache_key(brand: str, model: str, year: int) -> str:
    raw = f"{brand}|{model}|{year}".lower()
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(exist_ok=True)
    return _CACHE_DIR / f"{key}.json"


def _cache_read(key: str) -> Optional[list[dict]]:
    """Lê cache do disco se existir e ainda estiver válido (TTL 24h)."""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data["cached_at"])
        if datetime.now() - cached_at > timedelta(hours=_CACHE_TTL_H):
            return None          # expirado
        return data["listings"]
    except Exception:
        return None


def _cache_write(key: str, listings: list[dict]) -> None:
    """Salva resultados no cache com timestamp."""
    path = _cache_path(key)
    payload = {"cached_at": datetime.now().isoformat(), "listings": listings}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Helpers internos ──────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[\s./\\]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    return re.sub(r"-+", "-", text).strip("-")


def _build_listing_url(brand: str, model: str, version: str, year: int, uid: int) -> str:
    """Monta URL direta no formato /comprar/carro/marca/modelo/versao/ano/cod-ID."""
    return (
        f"{_BASE_URL}/comprar/carro"
        f"/{_slugify(brand)}/{_slugify(model)}/{_slugify(version)}/{year}/cod-{uid}"
    )


def _parse_state(raw: str) -> str:
    """Extrai sigla UF de strings como 'São Paulo (SP)'."""
    m = re.search(r"\(([A-Z]{2})\)", str(raw))
    return m.group(1) if m else raw[:2].upper()


def _parse_item(item: dict, brand: str, model: str) -> Optional[dict]:
    """
    Converte um item bruto da API Webmotors para o formato público.
    Retorna None se campos obrigatórios estiverem ausentes.
    """
    try:
        spec   = item.get("Specification", {})
        prices = item.get("Prices", {})
        seller = item.get("Seller", {})
        photos = item.get("Media", {}).get("Photos", [])

        price = prices.get("Price") or prices.get("SearchPrice")
        km    = spec.get("Odometer") or spec.get("Mileage")
        uid   = item.get("UniqueId")

        if not price or km is None or not uid:
            return None

        version = spec.get("Version", {}).get("Value", "")
        year    = int(spec.get("YearModel") or spec.get("YearFabrication") or 0)
        city    = seller.get("City", "")
        state   = _parse_state(seller.get("State", ""))

        foto_path = (photos[0].get("PhotoPath", "").replace("\\", "/")) if photos else ""
        photo_url = f"https://img.webmotors.com.br/producao/{foto_path}" if foto_path else ""

        return {
            "price":   float(price),
            "year":    year,
            "km":      int(km),
            "version": version,
            "url":     _build_listing_url(brand, model, version, year, int(uid)),
            "city":    f"{city} - {state}" if city else "",
            # campos extras úteis (ignorar se não precisar)
            "photo_url":      photo_url,
            "advertiser_type": (
                "Concessionaria" if "concession" in
                seller.get("AdType", {}).get("Value", "").lower()
                else ("Pessoa Fisica" if seller.get("SellerType", "").upper() == "PF"
                      else "Loja")
            ),
            "advertiser_name": seller.get("FantasyName", ""),
        }
    except Exception:
        return None


def _fetch_page(search_url: str, page: int, scraperapi_key: str) -> Optional[dict]:
    """Faz uma requisição à API interna do Webmotors, com ou sem proxy."""
    params_api = {
        "url":            search_url,
        "actualPage":     page,
        "displayPerPage": _RESULTS_PER_PAGE,
        "showMenu":       "false",
        "suggestions":    "false",
        "testAB":         "",
        "returnUrl":      "false",
    }
    api_url = f"{_API_SEARCH_URL}?{urllib.parse.urlencode(params_api)}"

    for attempt in range(3):
        try:
            if scraperapi_key:
                resp = requests.get(
                    _SCRAPERAPI_URL,
                    params={"api_key": scraperapi_key, "url": api_url,
                            "render": "false", "country_code": "br"},
                    timeout=60,
                )
            else:
                resp = requests.get(
                    api_url,
                    headers={
                        "User-Agent": random.choice(_USER_AGENTS),
                        "Accept": "application/json, text/plain, */*",
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Referer": "https://www.webmotors.com.br/",
                        "Origin": "https://www.webmotors.com.br",
                        "Connection": "keep-alive",
                    },
                    timeout=30,
                )
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.json()
        except requests.Timeout:
            if attempt == 2:
                return None
            time.sleep(5 * (attempt + 1))
        except Exception:
            return None

    return None


# ── Função pública ────────────────────────────────────────────────────────────

def search_webmotors(
    brand: str,
    model: str,
    year_model: int,
    max_results: int = 20,
    scraperapi_key: str = "",
    use_cache: bool = True,
) -> list[dict]:
    """
    Busca anúncios de um modelo/ano no Webmotors e retorna lista padronizada.

    Parâmetros
    ----------
    brand          : Marca do veículo. Ex: "Hyundai", "Toyota"
    model          : Modelo do veículo. Ex: "HB20", "Corolla"
    year_model     : Ano do modelo. Ex: 2024
    max_results    : Máximo de anúncios a retornar (default 20)
    scraperapi_key : Chave ScraperAPI para proxy anti-bot.
                     Se vazio, usa a variável de ambiente SCRAPERAPI_KEY.
                     Se nenhuma, faz requisição direta (pode ser bloqueada).
    use_cache      : Se True (default), usa cache em disco com TTL de 24h.

    Retorno
    -------
    Lista de dicts com os campos:
        price           (float) — preço anunciado em R$
        year            (int)   — ano modelo
        km              (int)   — quilometragem
        version         (str)   — versão/trim
        url             (str)   — link direto para o anúncio
        city            (str)   — cidade e UF do anunciante
        photo_url       (str)   — URL da foto principal
        advertiser_type (str)   — "Concessionária" | "Loja" | "Pessoa Física"
        advertiser_name (str)   — nome do anunciante

    Exemplo
    -------
        listings = search_webmotors("Hyundai", "HB20", 2024, max_results=50)
        df = pd.DataFrame(listings)
    """
    # Resolve chave ScraperAPI
    key = scraperapi_key or os.environ.get("SCRAPERAPI_KEY", "")

    # Verifica cache
    cache_k = _cache_key(brand, model, year_model)
    if use_cache:
        cached = _cache_read(cache_k)
        if cached is not None:
            return cached[:max_results]

    # Monta URL de busca — usa o formato slug que a API interna reconhece
    search_url = (
        f"{_BASE_URL}/comprar/carro/{_slugify(brand)}/{_slugify(model)}/"
        f"?AnoMin={year_model}&AnoMax={year_model}"
    )

    listings: list[dict] = []

    for page in range(1, _MAX_PAGES + 1):
        if page > 1:
            time.sleep(random.uniform(2, 4))

        data = _fetch_page(search_url, page, key)
        if not data:
            break

        results = data.get("SearchResults", [])
        if not results:
            break

        for item in results:
            parsed = _parse_item(item, brand, model)
            if parsed:
                listings.append(parsed)

        # Verifica paginação
        total  = data.get("TotalCount", 0)
        seen   = page * _RESULTS_PER_PAGE
        if (total and seen >= total) or len(results) < _RESULTS_PER_PAGE:
            break

        # Para cedo se já temos resultados suficientes para o cache
        if len(listings) >= max(max_results, 100):
            break

    # Filtra por ano (tolerância ±1 para não ficar vazio)
    exact = [l for l in listings if l["year"] == year_model]
    if exact:
        listings = exact
    else:
        listings = [l for l in listings if abs(l["year"] - year_model) <= 1]

    # Ordena por preço e salva cache com todos os resultados
    listings.sort(key=lambda x: x["price"])
    if use_cache and listings:
        _cache_write(cache_k, listings)

    return listings[:max_results]


# ── Execução direta (teste rápido) ────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    brand = sys.argv[1] if len(sys.argv) > 1 else "Hyundai"
    model = sys.argv[2] if len(sys.argv) > 2 else "HB20"
    year  = int(sys.argv[3]) if len(sys.argv) > 3 else 2024

    print(f"\nBuscando {brand} {model} {year}...\n")
    results = search_webmotors(brand, model, year, max_results=10)
    print(f"{len(results)} anúncios encontrados:\n")
    for r in results:
        print(f"  R$ {r['price']:,.0f}  |  {r['km']:,} km  |  {r['version']}")
        print(f"  {r['city']}  |  {r['advertiser_type']}  |  {r['url']}\n")
