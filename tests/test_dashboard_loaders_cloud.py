"""Appraisal base loading in the cloud: no local Excel, both bases via Google Sheets URLs."""

from pathlib import Path

import pytest
import streamlit as st

import grand_brasil.dashboard.pages._avaliacao.loaders as loaders
from grand_brasil.config import load_config
from tests.test_ingestion.test_appraisal_history import _row, _v2_row, _write_excel, _write_v2_excel

V2_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-PRIMARY/pubhtml"
LEGACY_URL = "https://docs.google.com/spreadsheets/d/LEGACY123/edit"


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    """Empty project root (no local Excel) and fake downloads per URL."""
    (tmp_path / "v2").mkdir()
    (tmp_path / "legacy").mkdir()
    v2 = _write_v2_excel(tmp_path / "v2", [_v2_row(plate="AAA1A11"), _v2_row(plate="BBB2B22")])
    legacy = _write_excel(tmp_path / "legacy", [_row(date="15/03/2025 10:30:00"), _row(date="10/02/2026 10:30:00")])
    files = {V2_URL: v2, LEGACY_URL: legacy}
    downloaded: list[str] = []

    def fake_download(url: str) -> str:
        downloaded.append(url)
        import shutil, tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False).name
        shutil.copy(files[url], tmp)
        return tmp

    empty_root = tmp_path / "root"
    empty_root.mkdir()
    monkeypatch.setattr(loaders, "_project_root", lambda: empty_root)
    monkeypatch.setattr(loaders, "_download_gsheet_xlsx", fake_download)
    st.session_state.clear()
    yield downloaded
    st.session_state.clear()


def _secrets(monkeypatch, **values):
    monkeypatch.setattr(loaders, "_get_secret", lambda key: values.get(key))


def test_legacy_comes_from_url_when_no_local_file(cloud, monkeypatch):
    _secrets(monkeypatch, APPRAISAL_HISTORY_URL=V2_URL, APPRAISAL_LEGACY_URL=LEGACY_URL)
    df = loaders.load_appraisal_data(config=load_config())
    assert sorted(cloud) == sorted([V2_URL, LEGACY_URL])
    # 2 primary rows + only the legacy row dated before appraisal_legacy_until (2026-01-01)
    assert len(df) == 3
    assert (df["appraisal_date"] < "2026-01-01").sum() == 1


def test_without_legacy_url_primary_alone_is_used(cloud, monkeypatch):
    _secrets(monkeypatch, APPRAISAL_HISTORY_URL=V2_URL)
    df = loaders.load_appraisal_data(config=load_config())
    assert cloud == [V2_URL]
    assert len(df) == 2


def test_legacy_url_alone_when_primary_missing(cloud, monkeypatch):
    _secrets(monkeypatch, APPRAISAL_LEGACY_URL=LEGACY_URL)
    df = loaders.load_appraisal_data(config=load_config())
    assert cloud == [LEGACY_URL]
    assert len(df) == 2  # no merge cutoff without a primary base


def test_sales_from_url_follow_trim_rules_switch(monkeypatch):
    seen = {}

    def fake_download(url: str) -> str:
        return "ignored.xlsx"

    def fake_load(path: Path, trim_rules: bool = True):
        seen["trim_rules"] = trim_rules
        import pandas as pd
        return pd.DataFrame({"a": [1]})

    monkeypatch.setattr(loaders, "_download_gsheet_xlsx", fake_download)
    monkeypatch.setattr(loaders, "load_sales_history", fake_load)
    monkeypatch.setattr(loaders.os, "unlink", lambda p: None)
    monkeypatch.setattr(loaders, "_get_secret", lambda key: "https://docs.google.com/spreadsheets/d/SALES/edit" if key == "SALES_HISTORY_URL" else None)
    st.session_state.clear()
    cfg = load_config()
    loaders.load_sales_data(cfg)
    assert seen["trim_rules"] == cfg.app.appraisal.trim_rules_enabled
    st.session_state.clear()
