"""Data-loading helpers for the Avaliacao page.

All functions here read from (or write to) Streamlit session state as a cache,
so navigating tabs or re-running the appraisal doesn't re-fetch FIPE / data.

Responsibilities split:
  • FIPE catalog/prices (brands, models, years, price)   — cached by key
  • Sales history (local Excel or Google Sheets URL)     — cached as `sales_history_df`
  • Appraisal history (same pattern, with status weights)
  • Year-ratio profile derived from appraisal history
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import streamlit as st

from grand_brasil.analysis.confidence import ConfidenceModel
from grand_brasil.analysis.purchase_ratio import (
    compute_brand_year_profile,
    compute_km_slope,
    compute_km_slope_piecewise,
    compute_year_ratio_profile,
)
from grand_brasil.config import Settings
from grand_brasil.ingestion.appraisal_history import (
    drop_implausible_ratios,
    load_appraisal_history,
    merge_with_legacy,
    reconcile_with_sales,
)
from grand_brasil.ingestion.fipe_client import FipeApiError, FipeClient
from grand_brasil.ingestion.sales_history import load_sales_history
from grand_brasil.models.fipe import FipeBrand, FipeModel, FipeYear

logger = logging.getLogger(__name__)


# ── FIPE client + catalog ───────────────────────────────────────────────────

def get_fipe_client() -> FipeClient:
    if "_fipe_client" not in st.session_state:
        st.session_state["_fipe_client"] = FipeClient()
    return st.session_state["_fipe_client"]


def load_fipe_brands(client: FipeClient) -> list[FipeBrand]:
    key = "_fipe_brands"
    if key not in st.session_state:
        try:
            with st.spinner("Carregando marcas FIPE..."):
                st.session_state[key] = client.get_brands()
        except FipeApiError as e:
            st.error(f"Erro ao carregar marcas FIPE: {e}")
            return []
    return st.session_state[key]


def load_fipe_models(client: FipeClient, brand_code: str) -> list[FipeModel]:
    key = f"_fipe_models_{brand_code}"
    if key not in st.session_state:
        try:
            with st.spinner("Carregando modelos..."):
                st.session_state[key] = client.get_models(brand_code)
        except FipeApiError as e:
            st.error(f"Erro ao carregar modelos FIPE: {e}")
            return []
    return st.session_state[key]


def load_fipe_years(client: FipeClient, brand_code: str, model_code: str) -> list[FipeYear]:
    key = f"_fipe_years_{brand_code}_{model_code}"
    if key not in st.session_state:
        try:
            with st.spinner("Carregando anos/versoes..."):
                st.session_state[key] = client.get_years(brand_code, model_code)
        except FipeApiError as e:
            st.error(f"Erro ao carregar anos FIPE: {e}")
            return []
    return st.session_state[key]


def fetch_fipe_price(client: FipeClient, brand_code: str, model_code: str, year_code: str):
    key = f"_fipe_price_{brand_code}_{model_code}_{year_code}"
    if key not in st.session_state:
        try:
            with st.spinner("Consultando valor FIPE..."):
                st.session_state[key] = client.get_price(brand_code, model_code, year_code)
        except FipeApiError as e:
            st.error(f"Erro ao consultar preco FIPE: {e}")
            return None
    return st.session_state[key]


# ── Sales history loader ────────────────────────────────────────────────────

def load_sales_data(config: Settings) -> Optional[pd.DataFrame]:
    """Load sales history from Google Sheets (secret) or local file."""
    if "sales_history_df" in st.session_state:
        return st.session_state["sales_history_df"]

    url = _get_secret("SALES_HISTORY_URL")

    if url:
        try:
            with st.spinner("Carregando historico de vendas..."):
                df = _load_sales_from_gdrive(url)
                st.session_state["sales_history_df"] = df
                return df
        except Exception as e:
            st.error(f"Erro ao carregar historico do Google Drive: {e}")
            logger.exception("Failed to load sales history from Google Drive URL")
            return None

    sales_file = config.app.appraisal.sales_history_file
    project_root = _project_root()
    file_path = project_root / sales_file

    if not file_path.exists():
        st.error(
            f"Arquivo de historico nao encontrado: **{sales_file}**. "
            "Configure **SALES_HISTORY_URL** nos secrets do Streamlit ou "
            "verifique o caminho em config.yaml."
        )
        return None

    try:
        with st.spinner("Carregando historico de vendas..."):
            df = load_sales_history(file_path, trim_rules=config.app.appraisal.trim_rules_enabled)
            st.session_state["sales_history_df"] = df
            return df
    except Exception as e:
        st.error(f"Erro ao carregar historico: {e}")
        logger.exception("Failed to load sales history")
        return None


def _load_sales_from_gdrive(url: str) -> pd.DataFrame:
    tmp_path = _download_gsheet_xlsx(url)
    try:
        return load_sales_history(Path(tmp_path))
    finally:
        os.unlink(tmp_path)


# ── Appraisal history loader ────────────────────────────────────────────────

def load_appraisal_data(
    status_weights: Optional[dict[str, float]] = None,
    config: Optional[Settings] = None,
) -> Optional[pd.DataFrame]:
    """Load the historical appraisal database with session cache.

    Primary source is APPRAISAL_HISTORY_URL (Google Sheets, V2 layout). When
    the legacy Excel configured in `appraisal_legacy_file` exists locally, its
    rows dated before `appraisal_legacy_until` are appended (the V2 export only
    covers 2026 onwards). Without the URL, the legacy file alone is used.
    """
    if "appraisal_df" in st.session_state:
        return st.session_state["appraisal_df"]

    project_root = _project_root()
    appraisal_cfg = config.app.appraisal if config is not None else None
    legacy_name = appraisal_cfg.appraisal_legacy_file if appraisal_cfg else "Avaliações 2025 e 2026.xlsx"
    legacy_until = appraisal_cfg.appraisal_legacy_until if appraisal_cfg else "2026-01-01"
    legacy_path = next(
        (p for p in (project_root / legacy_name, project_root / _strip_accents(legacy_name)) if p.exists()),
        None,
    )

    # Same switches as the backtest, so the screen prices with the measured stack
    load_kw = {
        "status_weights": status_weights,
        "trim_rules": appraisal_cfg.trim_rules_enabled if appraisal_cfg else False,
        "blindado_from_notes": appraisal_cfg.blindado_from_notes if appraisal_cfg else True,
    }

    url = _get_secret("APPRAISAL_HISTORY_URL")
    df: Optional[pd.DataFrame] = None

    if url:
        try:
            with st.spinner("Carregando base de avaliacoes historicas..."):
                df = _load_appraisals_from_gdrive(url, **load_kw)
                if legacy_path is not None:
                    legacy_df = load_appraisal_history(legacy_path, **load_kw)
                    df = merge_with_legacy(df, legacy_df, legacy_until)
        except Exception as e:
            logger.exception("Failed to load appraisal base from Google Drive")
            st.warning(f"Nao foi possivel carregar base de avaliacoes: {e}")
    elif legacy_path is not None:
        try:
            with st.spinner("Carregando base de avaliacoes historicas..."):
                df = load_appraisal_history(legacy_path, **load_kw)
        except Exception as e:
            logger.exception("Failed to load appraisal base")
            st.warning(f"Nao foi possivel carregar base de avaliacoes: {e}")

    st.session_state["appraisal_df"] = df
    return df


def _load_appraisals_from_gdrive(url: str, **load_kw) -> pd.DataFrame:
    tmp_path = _download_gsheet_xlsx(url)
    try:
        return load_appraisal_history(Path(tmp_path), **load_kw)
    finally:
        os.unlink(tmp_path)


def apply_appraisal_hygiene(appraisal_df: Optional[pd.DataFrame], sales_df: Optional[pd.DataFrame], config: Settings) -> Optional[pd.DataFrame]:
    """Reconcile 'valor avaliado' with sale costs and drop implausible ratios (config-gated, cached)."""
    if appraisal_df is None:
        return None
    if st.session_state.get("appraisal_hygiene_done"):
        return st.session_state["appraisal_df"]
    cfg = config.app.appraisal
    df = appraisal_df
    if cfg.reconcile_paid_with_sales and sales_df is not None:
        df = reconcile_with_sales(df, sales_df, cfg.reconcile_tolerance)
    if cfg.ratio_floor_by_age:
        df = drop_implausible_ratios(df, cfg.ratio_floor_by_age)
    st.session_state["appraisal_df"] = df
    st.session_state["appraisal_hygiene_done"] = True
    return df


def get_year_profile(appraisal_df: Optional[pd.DataFrame], config: Optional[Settings] = None) -> Optional[dict]:
    """Cache the per-year ratio profile (avoids recomputing each request)."""
    if appraisal_df is None:
        return None
    if "appraisal_year_profile" in st.session_state:
        return st.session_state["appraisal_year_profile"]
    min_rows = config.app.appraisal.buy_ratio.year_profile_min_rows if config is not None else 1
    profile = compute_year_ratio_profile(appraisal_df, min_rows=min_rows)
    st.session_state["appraisal_year_profile"] = profile
    return profile


def get_km_slope(appraisal_df: Optional[pd.DataFrame], config: Settings) -> Optional[float]:
    """Pooled ratio-vs-KM slope, only when buy_ratio.km_adjust is on (cached per session)."""
    if appraisal_df is None or not config.app.appraisal.buy_ratio.km_adjust:
        return None
    if "appraisal_km_slope" not in st.session_state:
        br = config.app.appraisal.buy_ratio
        st.session_state["appraisal_km_slope"] = (
            compute_km_slope_piecewise(appraisal_df, list(br.km_piecewise_breaks))
            if br.km_adjust_mode == "piecewise" else compute_km_slope(appraisal_df)
        )
    return st.session_state["appraisal_km_slope"]


def get_brand_year_profile(appraisal_df: Optional[pd.DataFrame], config: Settings) -> Optional[dict]:
    if appraisal_df is None or not config.app.appraisal.buy_ratio.year_profile_by_brand:
        return None
    if "appraisal_brand_profile" not in st.session_state:
        st.session_state["appraisal_brand_profile"] = compute_brand_year_profile(appraisal_df)
    return st.session_state["appraisal_brand_profile"]


def get_confidence_model(config: Settings) -> Optional[ConfidenceModel]:
    """Calibrated confidence table from disk; None when the file is missing."""
    if "confidence_model" not in st.session_state:
        path = _project_root() / config.app.appraisal.confidence_calibration_file
        try:
            st.session_state["confidence_model"] = ConfidenceModel.from_json(path) if path.exists() else None
        except Exception:
            logger.exception("Failed to load confidence calibration")
            st.session_state["confidence_model"] = None
    return st.session_state["confidence_model"]


# ── Shared plumbing ─────────────────────────────────────────────────────────

def _get_secret(key: str) -> Optional[str]:
    try:
        return st.secrets.get(key)
    except Exception:
        return None


def _project_root() -> Path:
    # loaders.py lives at grand_brasil/dashboard/pages/_avaliacao/loaders.py
    # project root is 5 parents up
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _strip_accents(name: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")


def gsheet_export_url(url: str) -> str:
    """Turn a Google Sheets share or published link into an xlsx export URL.

    Supports both `/spreadsheets/d/<id>/...` (share link) and
    `/spreadsheets/d/e/<id>/pub...` (File > Share > Publish to web).
    """
    published = re.search(r"/spreadsheets/d/e/([^/?#]+)", url)
    if published:
        return f"https://docs.google.com/spreadsheets/d/e/{published.group(1)}/pub?output=xlsx"
    shared = re.search(r"/spreadsheets/d/([^/?#]+)", url)
    if shared:
        return f"https://docs.google.com/spreadsheets/d/{shared.group(1)}/export?format=xlsx"
    raise ValueError(
        "URL invalida. Use o link de compartilhamento ou de publicacao do Google Sheets "
        "(docs.google.com/spreadsheets/d/...)."
    )


def _download_gsheet_xlsx(url: str) -> str:
    """Download a Google Sheets share/published URL as xlsx; return the temp file path."""
    response = requests.get(gsheet_export_url(url), timeout=120)
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(response.content)
        return tmp.name
