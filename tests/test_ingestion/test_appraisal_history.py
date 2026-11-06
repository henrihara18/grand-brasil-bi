"""Tests for the appraisal history loader (ingestion/appraisal_history.py).

Covers:
- Column rename with accent/case tolerance
- Status filtering (UTILIZADO-only vs include AVALIADO)
- Outlier ratio filtering (< 0.40 and > 1.30 dropped)
- Invalid rows (missing FIPE, missing appraised value, missing year) dropped
- Weight assignment: UTILIZADO=1.0, REPASSE=1.0, AVALIADO=0.4
- Derived columns: ratio, model_red
- Date parsing (dd/mm/yyyy format)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import pytest
from openpyxl import Workbook

from grand_brasil.ingestion.appraisal_history import (
    STATUS_WEIGHTS,
    detect_layout,
    load_appraisal_history,
    merge_with_legacy,
)


# ── Fixture builder ──────────────────────────────────────────────────────────


def _write_excel(tmp_path: Path, rows: list[dict], filename: str = "appraisals.xlsx") -> Path:
    """Write a minimal appraisal Excel mimicking the real source format."""
    wb = Workbook()
    ws = wb.active
    headers = [
        "Data de Avaliação", "Status", "Marca", "Modelo", "Versão",
        "Ano Modelo", "KM", "Valor avaliado", "FIPE",
        "ref. AAV B2C", "ref. AAV B2B", "ref. Web",
        "Gasto previsto", "Finalidade", "Placa da Avaliação",
        "Lojas", "Avaliador", "Classificação", "Observações",
    ]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, None) for h in headers])
    path = tmp_path / filename
    wb.save(path)
    return path


def _row(
    status: str = "UTILIZADO",
    brand: str = "HYUNDAI",
    model: str = "CRETA",
    year: int = 2023,
    km: int = 30_000,
    valor: float = 85_000.0,
    fipe: float = 100_000.0,
    date: str = "15/03/2025 10:30:00",
    **extra,
) -> dict:
    base = {
        "Data de Avaliação": date,
        "Status": status,
        "Marca": brand,
        "Modelo": model,
        "Versão": "1.0 TGDI Flex Limited Aut",
        "Ano Modelo": year,
        "KM": km,
        "Valor avaliado": valor,
        "FIPE": fipe,
    }
    base.update(extra)
    return base


# ── Column normalization & basic load ────────────────────────────────────────


class TestColumnNormalization:
    def test_standard_columns_are_renamed(self, tmp_path):
        path = _write_excel(tmp_path, [_row()])
        df = load_appraisal_history(path)
        expected = {
            "appraisal_date", "status", "brand", "model", "version",
            "year_model", "km", "appraised_value", "fipe_value",
            "ratio", "model_red", "weight", "status_norm",
        }
        assert expected.issubset(df.columns)

    def test_derived_model_red_is_brand_plus_model_uppercase(self, tmp_path):
        path = _write_excel(tmp_path, [_row(brand="hyundai", model="creta")])
        df = load_appraisal_history(path)
        assert df.iloc[0]["model_red"] == "HYUNDAI CRETA"


# ── Status filtering ─────────────────────────────────────────────────────────


class TestStatusFiltering:
    def test_utilizado_only_excludes_avaliado(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(status="UTILIZADO"),
            _row(status="AVALIADO"),
            _row(status="UTILIZADO"),
        ])
        df = load_appraisal_history(path, utilizado_only=True)
        assert len(df) == 2
        assert set(df["status_norm"].unique()) == {"UTILIZADO"}

    def test_default_includes_avaliado(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(status="UTILIZADO"),
            _row(status="AVALIADO"),
            _row(status="REPASSE"),
        ])
        df = load_appraisal_history(path)  # default: include_avaliado=True
        assert len(df) == 3

    def test_desativado_is_always_excluded(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(status="UTILIZADO"),
            _row(status="DESATIVADO"),
            _row(status="AVALIADO"),
        ])
        df = load_appraisal_history(path)
        assert "DESATIVADO" not in df["status_norm"].unique()
        assert len(df) == 2


# ── Weight assignment ────────────────────────────────────────────────────────


class TestWeights:
    def test_utilizado_gets_weight_1(self, tmp_path):
        path = _write_excel(tmp_path, [_row(status="UTILIZADO")])
        df = load_appraisal_history(path)
        assert df.iloc[0]["weight"] == 1.0

    def test_repasse_gets_weight_1(self, tmp_path):
        path = _write_excel(tmp_path, [_row(status="REPASSE")])
        df = load_appraisal_history(path)
        assert df.iloc[0]["weight"] == 1.0

    def test_avaliado_gets_weight_0_4(self, tmp_path):
        path = _write_excel(tmp_path, [_row(status="AVALIADO")])
        df = load_appraisal_history(path)
        assert df.iloc[0]["weight"] == 0.4

    def test_status_weights_constant_matches_loader(self):
        # If we ever tune weights, this guards the contract
        assert STATUS_WEIGHTS["UTILIZADO"] == 1.0
        assert STATUS_WEIGHTS["REPASSE"] == 1.0
        assert STATUS_WEIGHTS["AVALIADO"] == 0.4


# ── Ratio computation & outlier filtering ───────────────────────────────────


class TestRatioAndOutliers:
    def test_ratio_is_appraised_over_fipe(self, tmp_path):
        path = _write_excel(tmp_path, [_row(valor=80_000, fipe=100_000)])
        df = load_appraisal_history(path)
        assert df.iloc[0]["ratio"] == pytest.approx(0.80, abs=0.001)

    def test_ratio_below_0_40_is_dropped(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(valor=85_000, fipe=100_000),   # 0.85, keep
            _row(valor=30_000, fipe=100_000),   # 0.30, drop
        ])
        df = load_appraisal_history(path)
        assert len(df) == 1

    def test_ratio_above_1_30_is_dropped(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(valor=85_000, fipe=100_000),    # 0.85, keep
            _row(valor=150_000, fipe=100_000),   # 1.50, drop
        ])
        df = load_appraisal_history(path)
        assert len(df) == 1


# ── Data cleanliness filters ─────────────────────────────────────────────────


class TestDataCleaning:
    def test_fipe_below_5k_is_dropped(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(valor=85_000, fipe=100_000),
            _row(valor=4_000, fipe=4_500),   # FIPE too low
        ])
        df = load_appraisal_history(path)
        assert len(df) == 1

    def test_missing_year_model_is_dropped(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(),
            _row(year=None),   # missing year
        ])
        df = load_appraisal_history(path)
        assert len(df) == 1

    def test_appraised_below_1k_is_dropped(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(valor=85_000, fipe=100_000),
            _row(valor=500, fipe=100_000),   # too low
        ])
        df = load_appraisal_history(path)
        assert len(df) == 1


# ── Date parsing ─────────────────────────────────────────────────────────────


class TestDateParsing:
    def test_dd_mm_yyyy_format_parsed(self, tmp_path):
        path = _write_excel(tmp_path, [_row(date="15/03/2025 10:30:00")])
        df = load_appraisal_history(path)
        date = df.iloc[0]["appraisal_date"]
        assert date.year == 2025
        assert date.month == 3
        assert date.day == 15

    def test_invalid_date_becomes_nat(self, tmp_path):
        path = _write_excel(tmp_path, [_row(date="not a date")])
        df = load_appraisal_history(path)
        # Row should still load, just with NaT for date
        assert len(df) == 1
        assert pd.isna(df.iloc[0]["appraisal_date"])


# ── Integration: realistic mixed set ─────────────────────────────────────────


class TestIntegration:
    def test_realistic_mix(self, tmp_path):
        path = _write_excel(tmp_path, [
            _row(status="UTILIZADO", valor=85_000, fipe=100_000),   # keep (ratio 0.85)
            _row(status="AVALIADO", valor=80_000, fipe=100_000),    # keep (ratio 0.80)
            _row(status="REPASSE", valor=78_000, fipe=100_000),     # keep
            _row(status="DESATIVADO", valor=85_000, fipe=100_000),  # drop (status)
            _row(status="UTILIZADO", valor=30_000, fipe=100_000),   # drop (ratio < 0.40)
            _row(status="UTILIZADO", valor=85_000, fipe=3_000),     # drop (FIPE < 5k)
        ])
        df = load_appraisal_history(path)

        assert len(df) == 3
        statuses = set(df["status_norm"].unique())
        assert statuses == {"UTILIZADO", "AVALIADO", "REPASSE"}
        # Each status gets the right weight
        for _, r in df.iterrows():
            expected_weight = 0.4 if r["status_norm"] == "AVALIADO" else 1.0
            assert r["weight"] == expected_weight


# ── V2 layout (appraisal-platform Google Sheets export) ──────────────────────


V2_HEADERS = [
    "ID", "Empresa", "Vendedor", "Status", "Classificação", "Finalidade", "Placa",
    "Marca", "Modelo", "Versão", "Ano Modelo", "km", "Custos", "Valor Avaliado",
    "Total Avaliado", "Data Avaliação", "Valor Mesa", "BLindado",
    "Valor Ref. Web", "Valor Ref. Fipe", "Valor Ref. Auto Avaliar", "Data de Criação", "Observações",
]


def _write_v2_excel(tmp_path: Path, rows: list[dict], blank_rows_above: int = 1) -> Path:
    wb = Workbook()
    ws = wb.active
    for _ in range(blank_rows_above):
        ws.append([])
    ws.append(V2_HEADERS)
    for r in rows:
        ws.append([r.get(h, None) for h in V2_HEADERS])
    path = tmp_path / "avaliacoes_v2.xlsx"
    wb.save(path)
    return path


def _v2_row(
    status: str = "Utilizado",
    brand: str = "HYUNDAI",
    model: str = "CRETA",
    year: int = 2023,
    km: float = 30_000.0,
    valor: str = "R$ 85.000,00",
    fipe: str = "R$ 100.000,00",
    created: str = "2026-03-15 10:30:00",
    appraised_at: Optional[str] = "2026-03-15",
    plate: str = "ABC1D23",
    **extra,
) -> dict:
    base = {
        "Empresa": "GRAND BAY BARUERI", "Status": status, "Placa": plate,
        "Marca": brand, "Modelo": model, "Versão": "1.0 TGDI FLEX LIMITED AUTOMÁTICO",
        "Ano Modelo": year, "km": km, "Custos": 1500.0, "Valor Avaliado": valor,
        "Data Avaliação": appraised_at, "Data de Criação": created, "BLindado": "Não",
        "Valor Ref. Web": "R$ 92.000,00", "Valor Ref. Fipe": fipe,
    }
    base.update(extra)
    return base


class TestV2Layout:
    def test_layout_detected_from_fipe_ref_column(self):
        assert detect_layout(V2_HEADERS) == "v2"
        assert detect_layout(["Data de Avaliação", "Status", "Marca", "FIPE"]) == "legacy"

    def test_brl_text_values_are_parsed(self, tmp_path):
        path = _write_v2_excel(tmp_path, [_v2_row()])
        df = load_appraisal_history(path)
        assert len(df) == 1
        assert df.loc[0, "appraised_value"] == 85_000.0
        assert df.loc[0, "fipe_value"] == 100_000.0
        assert df.loc[0, "ref_web"] == 92_000.0
        assert df.loc[0, "expected_repair_cost"] == 1500.0
        assert df.loc[0, "ratio"] == pytest.approx(0.85)
        assert df.loc[0, "model_red"] == "HYUNDAI CRETA"
        assert df.loc[0, "plate"] == "ABC1D23"
        assert df.loc[0, "store"] == "GRAND BAY BARUERI"
        assert bool(df.loc[0, "blindado_flag"]) is False

    def test_creation_date_is_primary_with_appraisal_date_fallback(self, tmp_path):
        rows = [
            _v2_row(created="2026-03-15 10:30:00", appraised_at="2026-03-20"),
            _v2_row(created=None, appraised_at="2026-04-02", plate="XYZ9A88"),
        ]
        df = load_appraisal_history(_write_v2_excel(tmp_path, rows))
        dates = sorted(df["appraisal_date"].dt.strftime("%Y-%m-%d"))
        assert dates == ["2026-03-15", "2026-04-02"]

    def test_status_values_are_case_insensitive_and_desativado_dropped(self, tmp_path):
        rows = [
            _v2_row(status="Utilizado"), _v2_row(status="Avaliado", plate="B"),
            _v2_row(status="Repasse", plate="C"), _v2_row(status="Desativado", plate="D"),
            _v2_row(status="Aguardando Mesa", plate="E"),
        ]
        df = load_appraisal_history(_write_v2_excel(tmp_path, rows))
        assert sorted(df["status_norm"]) == ["AVALIADO", "REPASSE", "UTILIZADO"]
        assert df.set_index("status_norm")["weight"].to_dict() == {
            "AVALIADO": 0.4, "REPASSE": 1.0, "UTILIZADO": 1.0,
        }

    def test_rows_without_brand_or_zero_values_are_dropped(self, tmp_path):
        rows = [
            _v2_row(),
            _v2_row(brand=None, model=None, valor="R$ 0,00", fipe="R$ 0,00", plate="Z"),
        ]
        df = load_appraisal_history(_write_v2_excel(tmp_path, rows))
        assert len(df) == 1

    def test_blindado_flag_sim(self, tmp_path):
        df = load_appraisal_history(_write_v2_excel(tmp_path, [_v2_row(BLindado="Sim")]))
        assert bool(df.loc[0, "blindado_flag"]) is True
        assert df.loc[0, "blindado_source"] == "coluna"

    @pytest.mark.parametrize("note,expected", [
        ("Blindado CARBON", True),
        ("Blindagem Endure\n Vidros AGP B33\n pequenas delaminações", True),
        ("sem garantia de blindagem, blindagem evolution", True),
        ("Revisões em dia / Sem blindagem", False),
        ("Tem manual, tem chave reserva. Não é blindado", False),
        ("Único dono, revisões em concessionária", False),
        (None, False),
    ])
    def test_blindado_read_from_notes_when_column_says_no(self, tmp_path, note, expected):
        df = load_appraisal_history(_write_v2_excel(tmp_path, [_v2_row(**{"Observações": note})]))
        assert bool(df.loc[0, "blindado_flag"]) is expected
        assert df.loc[0, "blindado_source"] == ("observacao" if expected else "")

    def test_blindado_from_notes_can_be_switched_off(self, tmp_path):
        df = load_appraisal_history(_write_v2_excel(tmp_path, [_v2_row(**{"Observações": "Blindado CARBON"})]), blindado_from_notes=False)
        assert bool(df.loc[0, "blindado_flag"]) is False

    def test_legacy_layout_without_column_reads_notes(self, tmp_path):
        df = load_appraisal_history(_write_excel(tmp_path, [_row(**{"Observações": "blindado Rino, vidros Anglo"}), _row()]))
        assert list(df["blindado_flag"]) == [True, False]


class TestMergeWithLegacy:
    def _frames(self, tmp_path):
        v2 = load_appraisal_history(_write_v2_excel(tmp_path, [
            _v2_row(created="2026-02-01 09:00:00", plate="NEW2026"),
            _v2_row(created="2025-12-20 09:00:00", plate="DUP2025"),
        ]))
        legacy = load_appraisal_history(_write_excel(tmp_path, [
            _row(date="10/06/2025 10:00:00", **{"Placa da Avaliação": "OLD2025"}),
            _row(date="20/12/2025 15:00:00", **{"Placa da Avaliação": "DUP2025"}),
            _row(date="05/01/2026 15:00:00", **{"Placa da Avaliação": "OLD2026"}),
        ], filename="legacy.xlsx"))
        return v2, legacy

    def test_legacy_rows_before_cutoff_are_appended(self, tmp_path):
        v2, legacy = self._frames(tmp_path)
        merged = merge_with_legacy(v2, legacy, "2026-01-01")
        assert sorted(merged["plate"]) == ["DUP2025", "NEW2026", "OLD2025"]

    def test_legacy_rows_after_cutoff_are_ignored(self, tmp_path):
        v2, legacy = self._frames(tmp_path)
        merged = merge_with_legacy(v2, legacy, "2026-01-01")
        assert "OLD2026" not in set(merged["plate"])

    def test_primary_wins_on_same_plate_year_day(self, tmp_path):
        v2, legacy = self._frames(tmp_path)
        merged = merge_with_legacy(v2, legacy, "2026-01-01")
        dup = merged[merged["plate"] == "DUP2025"]
        assert len(dup) == 1
        assert dup.iloc[0]["store"] == "GRAND BAY BARUERI"  # came from V2
