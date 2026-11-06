"""Tests for appraisal feedback CSV logger."""

from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from grand_brasil.ingestion.appraisal_feedback import (
    FEEDBACK_FIELDS,
    FeedbackEntry,
    append_feedback,
    build_entry_from_suggestion,
)
from grand_brasil.models.appraisal import AppraisalSuggestion


@pytest.fixture
def suggestion() -> AppraisalSuggestion:
    """A minimal AppraisalSuggestion populated with the fields used in feedback."""
    return AppraisalSuggestion(
        brand="HYUNDAI",
        model_red="HYUNDAI HB20",
        year_model=2022,
        km=45_000,
        fipe_code="004278-1",
        fipe_model_name="HB20 1.0",
        purpose="auto",
        loja_max_trade_value=Decimal("60000"),
        revenda_max_trade_value=Decimal("48000"),
        blended_max_trade_value=Decimal("54000"),
        buy_ratio_price=Decimal("55500"),
        p_revenda=0.5,
        brand_tier="SAFE",
        confidence="alta",
    )


class TestAppendFeedback:
    def test_creates_file_with_header_on_first_write(self, tmp_path: Path) -> None:
        log = tmp_path / "feedback.csv"
        entry = FeedbackEntry(
            timestamp=datetime(2026, 4, 28, 10, 0).isoformat(),
            plate="ABC1D23",
            brand="HYUNDAI",
            deal_closed="fechado",
            paid_real=55_000,
        )
        path = append_feedback(entry, path=log)
        assert path == log
        assert log.exists()

        with log.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["plate"] == "ABC1D23"
        assert rows[0]["brand"] == "HYUNDAI"
        assert rows[0]["paid_real"] == "55000"

    def test_appends_subsequent_writes_without_duplicating_header(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "feedback.csv"
        for plate in ("AAA1A11", "BBB2B22", "CCC3C33"):
            append_feedback(
                FeedbackEntry(timestamp="2026-04-28T10:00", plate=plate),
                path=log,
            )

        with log.open(encoding="utf-8-sig") as f:
            content = f.read()

        # Header appears exactly once
        assert content.count("timestamp,plate") == 1
        with log.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert [r["plate"] for r in rows] == ["AAA1A11", "BBB2B22", "CCC3C33"]

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        log = tmp_path / "nested" / "subdir" / "feedback.csv"
        append_feedback(FeedbackEntry(timestamp="2026-04-28T10:00"), path=log)
        assert log.exists()

    def test_none_values_become_empty_strings(self, tmp_path: Path) -> None:
        log = tmp_path / "feedback.csv"
        entry = FeedbackEntry(
            timestamp="2026-04-28T10:00",
            plate="XYZ",
            paid_real=None,
            km=None,
        )
        append_feedback(entry, path=log)
        with log.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["paid_real"] == ""
        assert rows[0]["km"] == ""

    def test_all_fields_in_header(self, tmp_path: Path) -> None:
        log = tmp_path / "feedback.csv"
        append_feedback(FeedbackEntry(timestamp="2026-04-28T10:00"), path=log)
        with log.open(encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        assert tuple(header) == FEEDBACK_FIELDS


class TestBuildEntryFromSuggestion:
    def test_basic_mapping(self, suggestion: AppraisalSuggestion) -> None:
        entry = build_entry_from_suggestion(
            suggestion=suggestion,
            plate="abc1d23",
            deal_closed="fechado",
            channel_real="Loja",
            paid_real=55_000.0,
            observation="cliente comparou com Webmotors",
            fipe_price=85_000.0,
            timestamp=datetime(2026, 4, 28, 10, 0),
        )
        assert entry.plate == "ABC1D23"  # uppercased + stripped
        assert entry.brand == "HYUNDAI"
        assert entry.model_red == "HYUNDAI HB20"
        assert entry.year_model == 2022
        assert entry.km == 45_000
        assert entry.fipe_price == 85_000.0
        assert entry.fipe_code == "004278-1"
        assert entry.purpose == "auto"
        assert entry.suggested_blended == 54_000.0
        assert entry.suggested_buy_ratio == 55_500.0
        assert entry.suggested_loja == 60_000.0
        assert entry.suggested_revenda == 48_000.0
        assert entry.p_revenda == 0.5
        assert entry.brand_tier == "SAFE"
        assert entry.confidence == "alta"
        assert entry.deal_closed == "fechado"
        assert entry.channel_real == "Loja"
        assert entry.paid_real == 55_000.0
        assert entry.observation == "cliente comparou com Webmotors"
        assert entry.timestamp == "2026-04-28T10:00:00"

    def test_decimal_values_converted_to_float(
        self, suggestion: AppraisalSuggestion
    ) -> None:
        entry = build_entry_from_suggestion(
            suggestion=suggestion,
            plate="",
            deal_closed="nao_fechado",
            channel_real="",
            paid_real=None,
            observation="",
        )
        assert isinstance(entry.suggested_blended, float)
        assert isinstance(entry.suggested_loja, float)
        assert isinstance(entry.suggested_revenda, float)
        assert entry.paid_real is None

    def test_missing_optional_fields_default_to_empty(
        self, suggestion: AppraisalSuggestion
    ) -> None:
        # Strip the suggestion of optional fields
        suggestion.fipe_code = None
        suggestion.fipe_model_name = None
        suggestion.brand_tier = None
        entry = build_entry_from_suggestion(
            suggestion=suggestion,
            plate="",
            deal_closed="fechado",
            channel_real="Loja",
            paid_real=10_000.0,
            observation="",
        )
        assert entry.fipe_code == ""
        assert entry.fipe_model_name == ""
        assert entry.brand_tier == ""

    def test_round_trip_through_csv(
        self, suggestion: AppraisalSuggestion, tmp_path: Path
    ) -> None:
        log = tmp_path / "feedback.csv"
        entry = build_entry_from_suggestion(
            suggestion=suggestion,
            plate="ABC1D23",
            deal_closed="fechado",
            channel_real="Loja",
            paid_real=55_000.0,
            observation="ok",
            fipe_price=85_000.0,
        )
        append_feedback(entry, path=log)

        with log.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        row = rows[0]
        assert row["plate"] == "ABC1D23"
        assert row["suggested_blended"] == "54000.0"
        assert row["paid_real"] == "55000.0"
        assert row["channel_real"] == "Loja"
