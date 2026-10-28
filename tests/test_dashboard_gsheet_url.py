"""URL handling for Google Sheets sources (share links and published links)."""

import pytest

from grand_brasil.dashboard.pages._avaliacao.loaders import gsheet_export_url


def test_share_link_becomes_export_url():
    url = "https://docs.google.com/spreadsheets/d/1AbC_dEf/edit?usp=sharing"
    assert gsheet_export_url(url) == "https://docs.google.com/spreadsheets/d/1AbC_dEf/export?format=xlsx"


def test_published_link_becomes_pub_output_xlsx():
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-abc123/pubhtml"
    assert gsheet_export_url(url) == "https://docs.google.com/spreadsheets/d/e/2PACX-abc123/pub?output=xlsx"


def test_invalid_url_raises():
    with pytest.raises(ValueError):
        gsheet_export_url("https://example.com/not-a-sheet")
