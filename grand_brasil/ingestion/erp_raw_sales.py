"""ERP RAW sales report → processed sales history.

The ERP exports "Relatório - <timestamp>.xls", which is an HTML page with a
single <table> (not a real Excel file). Numbers come as Brazilian text
("20.700,00"), dates as dd/mm/yyyy, one row per invoiced car.

Pipeline:
    parse_erp_html()       HTML → DataFrame (regex over <th>/<td>; pd.read_html
                           would mangle the decimal commas)
    normalize_erp_sales()  RAW columns → the layout read by sales_history.py
                           (Marca, Shortname, MODELO RED, Situação, faixas…)
    build_sales_history()  RAW rows for the current year + rows kept from the
                           previous processed workbook (older years, and
                           current-year rows of filiais absent from the RAW)
    write_sales_history()  xlsx with the blank first row / column the loader expects

Business rules (validated line by line against the ERP):
    • Vendedor "JULIO CESAR SILVEIRA" → Revenda (B2B); anyone else → Loja.
    • Marca = Família without the "VU-" prefix; BMW AUTOS→BMW, KIAMOTORS→KIA…
    • "VU-BMW MOTOS" rows are motorcycles and are dropped.
    • Marg. Ini. == Vl Venda − Vl Impostos − Custo Ajustado (checked on load).
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from grand_brasil.utils.model_tagger import Tagger, clean

logger = logging.getLogger(__name__)

REPASSE_SELLER = "JULIO CESAR SILVEIRA"

BRAND_FIX: dict[str, str] = {
    "BMW AUTOS": "BMW",
    "KIAMOTORS": "KIA",
    "HONDA AUTOS": "HONDA",
    "GAC MOTOR": "GAC",
}
MOTORCYCLE_FAMILIES = {"VU-BMW MOTOS"}

NUMERIC_COLUMNS = [
    "KM", "D.E", "Vl Venda", "Despesa Operacional", "% DV", "Vl Bônus", "Vl Impostos",
    "Custo", "Custo Ajustado", "Marg. Ini.", "% MI", "O. Custo", "Margem Final", "% MF",
    "Diferença Fipe", "Valor Fipe",
]
DATE_COLUMNS = ["Dt Venda", "Dt. placa"]
REQUIRED_RAW_COLUMNS = [
    "Família", "Modelo", "Vendedor", "Placa", "KM", "Ano Modelo", "Dt Venda", "D.E",
    "Vl Venda", "Vl Impostos", "Custo", "Custo Ajustado", "Marg. Ini.", "Filial",
    "Nr NF/Série", "Valor Fipe",
]

# Column order of the processed workbook (what sales_history.py maps)
OUTPUT_COLUMNS = [
    "Família", "Marca", "Modelo", "Shortname", "MODELO RED", "Cor", "Vendedor", "Veículo",
    "Placa", "KM", "Km Range", "Ano Modelo", "Modelo(year)", "range ano", "Chassi", "Tipo",
    "Dt Venda", "Mês", "Ano", "D.E", "Vl Venda", "Range Valor Venda", "Despesa Operacional",
    "% DV", "Vl Bônus", "Vl Impostos", "Custo", "Custo Ajustado", "Marg. Ini.", "% MI",
    "O. Custo", "Margem Final", "% MF", "Filial", "Filial(2)", "Nr NF/Série", "Situação",
    "FIPE", "Situação NBS", "Proposta", "Dt. placa", "Origem",
]

KM_BINS = [-1, 19_999.99, 49_999.99, 99_999.99, 1e12]
KM_LABELS = ["Até 20k", "20k - 50k", "50k - 100k", "Mais de 100k"]
YEAR_BINS = [0, 2017, 2022, 9999]
YEAR_LABELS = ["Até 2017", "2018 - 2022", "2023+"]


@dataclass
class BuildReport:
    """What went into the processed workbook — for the hand-off summary."""
    raw_rows: int = 0
    duplicate_invoices: int = 0
    motorcycles_dropped: int = 0
    fipe_zero_rows: int = 0
    margin_mismatches: int = 0
    odd_families: dict[str, int] = field(default_factory=dict)
    raw_filiais: dict[str, int] = field(default_factory=dict)
    kept_previous_years: int = 0
    kept_previous_other_filiais: dict[str, int] = field(default_factory=dict)
    dropped_previous_same_filial: pd.DataFrame = field(default_factory=pd.DataFrame)
    new_models: dict[str, str] = field(default_factory=dict)
    total_rows: int = 0


# ── 1) Parse ────────────────────────────────────────────────────────────────

def parse_erp_html(source: Union[str, Path]) -> pd.DataFrame:
    """Read the ERP's HTML-disguised .xls into a typed DataFrame."""
    raw_bytes = Path(source).read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin1")

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I)
    if not rows:
        raise ValueError(f"Nenhuma tabela encontrada em {source}")

    def cells(row: str) -> list[str]:
        return [
            html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S | re.I)
        ]

    header = cells(rows[0])
    data = [r for r in (cells(x) for x in rows[1:]) if len(r) == len(header) and any(r)]
    df = pd.DataFrame(data, columns=header)

    missing = [c for c in REQUIRED_RAW_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas ausentes no RAW: {missing}")

    df = df[~df["Família"].str.strip().str.lower().isin({"", "total"})].copy()

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = df[col].map(_parse_br_number)
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    if df["Vl Venda"].fillna(0).sum() == 0:
        raise ValueError("Conversao numerica falhou (soma de Vl Venda = 0)")

    logger.info(f"RAW ERP parsed: {len(df)} rows, {len(header)} columns")
    return df.reset_index(drop=True)


def _parse_br_number(value: str) -> float:
    s = str(value).strip().replace(".", "").replace(",", ".")
    return pd.to_numeric(s, errors="coerce")


# ── 2) Normalize ────────────────────────────────────────────────────────────

def brand_from_familia(familia: str) -> str:
    f = str(familia).strip().upper()
    if f.startswith("VU-"):
        brand = f[3:]
    elif f.startswith("TOY ") or f == "COROLLA CROSS":
        brand = "TOYOTA"
    elif f.startswith("HYUNDAI"):
        brand = "HYUNDAI"
    else:
        brand = f
    return BRAND_FIX.get(brand, brand)


def sale_channel(vendedor: str) -> str:
    return "Revenda" if str(vendedor).strip().upper() == REPASSE_SELLER else "Loja"


def normalize_erp_sales(
    raw: pd.DataFrame,
    tagger: Optional[Tagger] = None,
    origem: str = "RAW ERP",
    report: Optional[BuildReport] = None,
) -> pd.DataFrame:
    """Turn a parsed RAW frame into the processed-workbook layout."""
    tagger = tagger or Tagger()
    rep = report or BuildReport()
    df = raw.copy()

    rep.raw_rows += len(df)
    rep.duplicate_invoices += int(df["Nr NF/Série"].duplicated().sum())
    rep.fipe_zero_rows += int((df["Valor Fipe"].fillna(0) == 0).sum())
    margin_check = (df["Vl Venda"] - df["Vl Impostos"] - df["Custo Ajustado"] - df["Marg. Ini."]).abs()
    rep.margin_mismatches += int((margin_check >= 1).sum())

    moto = df["Família"].str.strip().str.upper().isin(MOTORCYCLE_FAMILIES)
    rep.motorcycles_dropped += int(moto.sum())
    df = df[~moto].copy()

    odd = df[~df["Família"].str.upper().str.startswith("VU-")]["Família"].value_counts()
    for fam, n in odd.items():
        rep.odd_families[fam] = rep.odd_families.get(fam, 0) + int(n)

    df["Marca"] = df["Família"].map(brand_from_familia)
    df["Shortname"] = tagger.apply(df["Modelo"])
    df["MODELO RED"] = df["Marca"] + " " + df["Shortname"]
    df["Situação"] = df["Vendedor"].map(sale_channel)
    df["Placa"] = df["Placa"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    df["Modelo(year)"] = pd.to_numeric(
        df["Ano Modelo"].astype(str).str.split("/").str[-1], errors="coerce"
    ).astype("Int64")
    df["Km Range"] = pd.cut(df["KM"], KM_BINS, labels=KM_LABELS).astype(str)
    df["range ano"] = pd.cut(df["Modelo(year)"].astype(float), YEAR_BINS, labels=YEAR_LABELS).astype(str)
    df["Mês"] = df["Dt Venda"].dt.month
    df["Ano"] = df["Dt Venda"].dt.year
    df["FIPE"] = df["Valor Fipe"].where(df["Valor Fipe"] > 0)
    df["Range Valor Venda"] = np.nan
    df["Filial(2)"] = np.nan
    df["Origem"] = origem

    for fam, n in df["Filial"].value_counts().items():
        rep.raw_filiais[fam] = rep.raw_filiais.get(fam, 0) + int(n)
    rep.new_models.update(tagger.novos)

    return df.reindex(columns=OUTPUT_COLUMNS)


# ── 3) Merge with the previous processed workbook ──────────────────────────

def build_sales_history(
    raw_frames: list[pd.DataFrame],
    previous: Optional[pd.DataFrame],
    raw_year: int,
    report: Optional[BuildReport] = None,
) -> pd.DataFrame:
    """Combine normalized RAW frames with the previous workbook.

    Rules:
      • RAW rows are authoritative for `raw_year` in the filiais they cover.
        Several RAW exports (e.g. one per group of filiais) are concatenated
        and de-duplicated on plate + sale date.
      • From `previous`: every row dated before `raw_year` is kept untouched;
        rows of `raw_year` are kept only for filiais that no RAW covers (and
        are flagged in `Origem`).
    """
    rep = report or BuildReport()
    raw = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    raw = raw.drop_duplicates(subset=["Placa", "Dt Venda"], keep="first")
    raw_filiais = set(raw["Filial"].dropna().unique())

    parts = [raw]
    if previous is not None and len(previous):
        prev = previous.copy()
        prev["Dt Venda"] = pd.to_datetime(prev["Dt Venda"], errors="coerce")
        if "Origem" not in prev.columns:
            prev["Origem"] = np.nan
        prev["Origem"] = prev["Origem"].fillna("planilha anterior")

        older = prev[prev["Dt Venda"].dt.year < raw_year]
        same_year = prev[prev["Dt Venda"].dt.year == raw_year]
        other_filiais = same_year[~same_year["Filial"].isin(raw_filiais)].copy()
        other_filiais["Origem"] = "planilha anterior (filial fora do RAW)"
        covered = same_year[same_year["Filial"].isin(raw_filiais)]

        key = lambda d: d["Placa"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True) + "|" + d["Dt Venda"].dt.strftime("%Y%m%d")
        rep.dropped_previous_same_filial = covered[~key(covered).isin(set(key(raw)))]
        rep.kept_previous_years = len(older)
        rep.kept_previous_other_filiais = other_filiais["Filial"].value_counts().to_dict()

        parts = [older.reindex(columns=OUTPUT_COLUMNS), other_filiais.reindex(columns=OUTPUT_COLUMNS), raw]

    out = pd.concat([p for p in parts if len(p)], ignore_index=True)
    out = out.sort_values("Dt Venda").reset_index(drop=True)
    out["Nr NF/Série"] = out["Nr NF/Série"].astype(str)
    rep.total_rows = len(out)
    return out


def write_sales_history(df: pd.DataFrame, out_path: Union[str, Path]) -> Path:
    """Write the workbook in the layout sales_history.py reads (header on row 2, column A blank)."""
    out_path = Path(out_path)
    body = df.copy()
    body.insert(0, " ", np.nan)
    with pd.ExcelWriter(out_path, engine="openpyxl", datetime_format="yyyy-mm-dd") as writer:
        pd.DataFrame([[None] * body.shape[1]]).to_excel(
            writer, sheet_name="Relatório", index=False, header=False, startrow=0
        )
        body.to_excel(writer, sheet_name="Relatório", index=False, startrow=1)
    logger.info(f"Sales history written: {len(df)} rows -> {out_path}")
    return out_path


def read_previous_workbook(path: Union[str, Path]) -> pd.DataFrame:
    """Read a processed workbook (ours or the earlier Google Sheets export)."""
    df = pd.read_excel(path, sheet_name=0, header=1)
    return df.drop(columns=[c for c in df.columns if str(c).startswith("Unnamed")], errors="ignore")


def new_models_table(report: BuildReport, raw_frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Models resolved by rule (not in Tag_Modelos), with their frequency, for review."""
    if not report.new_models:
        return pd.DataFrame(columns=["Modelo", "Shortname atribuido", "n"])
    counts = pd.concat([f["Modelo"] for f in raw_frames]).map(clean).value_counts()
    table = pd.DataFrame({
        "Modelo": list(report.new_models.keys()),
        "Shortname atribuido": list(report.new_models.values()),
    })
    table["n"] = table["Modelo"].map(lambda m: int(counts.get(m, 0)))
    return table.sort_values("n", ascending=False).reset_index(drop=True)
