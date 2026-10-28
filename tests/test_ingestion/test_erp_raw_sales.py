"""Tests for the ERP RAW sales ingestion (ingestion/erp_raw_sales.py)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from grand_brasil.ingestion.erp_raw_sales import (
    BuildReport,
    brand_from_familia,
    build_sales_history,
    normalize_erp_sales,
    parse_erp_html,
    sale_channel,
    write_sales_history,
)
from grand_brasil.ingestion.sales_history import load_sales_history

HEADER = [
    "Família", "Modelo", "Cor", "Vendedor", "Veículo", "Placa", "KM", "Ano Modelo", "Chassi", "Tipo",
    "Dt Venda", "D.E", "Vl Venda", "Despesa Operacional", "% DV", "Vl Bônus", "Vl Impostos", "Custo",
    "Custo Ajustado", "Marg. Ini.", "% MI", "O. Custo", "Margem Final", "% MF", "Filial", "Nr NF/Série",
    "Proposta", "Cor Interna", "Nome", "Situação NBS", "Dt. placa", "Diferença Fipe", "Valor Fipe",
]


def _row(**over) -> list[str]:
    base = {
        "Família": "VU-HYUNDAI", "Modelo": "CRETA 1.0 TGDI FLEX LIMITED AUTOMÁTICO", "Cor": "PRETO",
        "Vendedor": "RAFAEL FRANCO IZIDORO", "Veículo": "131055", "Placa": "ABC-1D23", "KM": "35.120",
        "Ano Modelo": "2023/2024", "Chassi": "9BH1", "Tipo": "VU", "Dt Venda": "17/07/2026", "D.E": "12",
        "Vl Venda": "120.000,00", "Despesa Operacional": "0,00", "% DV": "0,00", "Vl Bônus": "0,00",
        "Vl Impostos": "2.500,00", "Custo": "105.000,00", "Custo Ajustado": "105.000,00",
        "Marg. Ini.": "12.500,00", "% MI": "10,42", "O. Custo": "800,00", "Margem Final": "11.700,00",
        "% MF": "9,75", "Filial": "72 - HYU GUARULHOS", "Nr NF/Série": "1001/1", "Proposta": "77",
        "Cor Interna": "PRETO", "Nome": "CLIENTE", "Situação NBS": "NORMAL", "Dt. placa": "10/01/2024",
        "Diferença Fipe": "5.000,00", "Valor Fipe": "115.000,00",
    }
    base.update(over)
    return [base[h] for h in HEADER]


def _write_html(tmp_path: Path, rows: list[list[str]]) -> Path:
    def tr(cells, tag):
        return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
    body = tr(HEADER, "th") + "".join(tr(r, "td") for r in rows)
    body += "<tr>" + "<td>Total</td>" + "<td></td>" * (len(HEADER) - 1) + "</tr>"
    path = tmp_path / "relatorio.xls"
    path.write_text(f"<html><body><table><tbody>{body}</tbody></table></body></html>", encoding="utf-8")
    return path


@pytest.fixture
def raw_df(tmp_path) -> pd.DataFrame:
    rows = [
        _row(),
        _row(**{"Vendedor": "JULIO CESAR SILVEIRA", "Placa": "XYZ9A88", "Nr NF/Série": "1002/1",
                "Família": "VU-BMW AUTOS", "Modelo": "X1 2.0 16V TURBO ACTIVEFLEX SDRIVE20I",
                "KM": "104.859", "Ano Modelo": "2016/2017", "Valor Fipe": "0,00",
                "Filial": "32 - BYD ALPHAVILLE"}),
        _row(**{"Família": "VU-BMW MOTOS", "Modelo": "S 1000 RR", "Placa": "MOT0001", "Nr NF/Série": "1003/1"}),
    ]
    return parse_erp_html(_write_html(tmp_path, rows))


class TestParse:
    def test_brazilian_numbers_and_dates_are_typed(self, raw_df):
        assert len(raw_df) == 3  # footer "Total" dropped
        assert raw_df.loc[0, "Vl Venda"] == 120_000.0
        assert raw_df.loc[0, "% MI"] == pytest.approx(10.42)
        assert raw_df.loc[0, "KM"] == 35_120
        assert raw_df.loc[0, "Dt Venda"] == pd.Timestamp("2026-07-17")

    def test_missing_required_column_raises(self, tmp_path):
        path = tmp_path / "bad.xls"
        path.write_text("<table><tr><th>Família</th></tr><tr><td>VU-X</td></tr></table>", encoding="utf-8")
        with pytest.raises(ValueError):
            parse_erp_html(path)


class TestRules:
    @pytest.mark.parametrize("familia,brand", [
        ("VU-HYUNDAI", "HYUNDAI"), ("VU-BMW AUTOS", "BMW"), ("VU-KIAMOTORS", "KIA"),
        ("VU-MERCEDES-BENZ", "MERCEDES-BENZ"), ("TOY COROLLA", "TOYOTA"), ("COROLLA CROSS", "TOYOTA"),
        ("HYUNDAI HB20", "HYUNDAI"),
    ])
    def test_brand_from_familia(self, familia, brand):
        assert brand_from_familia(familia) == brand

    def test_channel_rule(self):
        assert sale_channel("JULIO CESAR SILVEIRA") == "Revenda"
        assert sale_channel(" julio cesar silveira ") == "Revenda"
        assert sale_channel("RAFAEL FRANCO IZIDORO") == "Loja"


class TestNormalize:
    def test_output_layout_and_derived_columns(self, raw_df):
        report = BuildReport()
        out = normalize_erp_sales(raw_df, report=report, origem="RAW teste")
        assert len(out) == 2 and report.motorcycles_dropped == 1
        creta = out[out["Placa"] == "ABC1D23"].iloc[0]
        assert creta["Marca"] == "HYUNDAI"
        assert creta["Shortname"] == "CRETA LIMITED"
        assert creta["MODELO RED"] == "HYUNDAI CRETA LIMITED"
        assert creta["Situação"] == "Loja"
        assert creta["Modelo(year)"] == 2024
        assert creta["Km Range"] == "20k - 50k" and creta["range ano"] == "2023+"
        assert creta["FIPE"] == 115_000.0 and creta["Origem"] == "RAW teste"
        bmw = out[out["Placa"] == "XYZ9A88"].iloc[0]
        assert bmw["Marca"] == "BMW" and bmw["Situação"] == "Revenda"
        assert bmw["Km Range"] == "Mais de 100k" and bmw["range ano"] == "Até 2017"
        assert pd.isna(bmw["FIPE"]) and report.fipe_zero_rows == 1
        assert report.margin_mismatches == 0 and report.duplicate_invoices == 0


class TestBuild:
    def _previous(self) -> pd.DataFrame:
        cols = ["Dt Venda", "Marca", "MODELO RED", "Placa", "Filial", "Nr NF/Série", "Situação", "Vl Venda",
                "Custo", "Custo Ajustado", "Modelo(year)"]
        rows = [
            ["2025-05-10", "TOYOTA", "TOYOTA COROLLA", "OLD2025", "21 - TOY NACOES", "9/1", "Loja", 90000, 80000, 80000, 2022],
            ["2026-03-01", "AUDI", "AUDI Q3", "BMW2026", "3 - BMW GASTAO", "8/1", "Loja", 150000, 130000, 130000, 2021],
            ["2026-07-17", "HYUNDAI", "HYUNDAI CRETA LIMITED", "ABC1D23", "72 - HYU GUARULHOS", "1001/1", "Loja", 120000, 105000, 105000, 2024],
            ["2026-02-02", "FIAT", "FIAT PULSE", "GONE2026", "72 - HYU GUARULHOS", "5/1", "Loja", 70000, 60000, 60000, 2023],
        ]
        return pd.DataFrame(rows, columns=cols)

    def test_merge_rules(self, raw_df):
        report = BuildReport()
        out = build_sales_history([normalize_erp_sales(raw_df, report=report)], self._previous(), 2026, report=report)
        plates = set(out["Placa"])
        assert {"OLD2025", "BMW2026", "ABC1D23", "XYZ9A88"} <= plates
        assert "GONE2026" not in plates  # same filial as RAW, not in RAW -> dropped
        assert report.kept_previous_years == 1
        assert report.kept_previous_other_filiais == {"3 - BMW GASTAO": 1}
        assert list(report.dropped_previous_same_filial["Placa"]) == ["GONE2026"]
        assert out[out["Placa"] == "BMW2026"].iloc[0]["Origem"] == "planilha anterior (filial fora do RAW)"
        assert (out[out["Placa"] == "ABC1D23"]["Origem"] == "RAW ERP").all()

    def test_duplicate_raw_rows_across_exports_are_collapsed(self, raw_df):
        a = normalize_erp_sales(raw_df); b = normalize_erp_sales(raw_df)
        out = build_sales_history([a, b], None, 2026)
        assert len(out) == 2

    def test_roundtrip_through_sales_loader(self, raw_df, tmp_path):
        out = build_sales_history([normalize_erp_sales(raw_df)], self._previous(), 2026)
        path = write_sales_history(out, tmp_path / "vendas.xlsx")
        loaded = load_sales_history(path)
        assert len(loaded) == 4
        assert set(loaded["sale_channel"]) == {"Loja", "Revenda"}
        assert "HYUNDAI CRETA LIMITED" in set(loaded["model_red"])
        assert loaded["sale_date"].min().year == 2025
