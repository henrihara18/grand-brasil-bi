import pandas as pd
import numpy as np
import re
from tagger import Tagger

UP = "/mnt/user-data/uploads/"
tg = Tagger(UP + "Tag_Modelos.xlsx")

MARCA_FIX = {"BMW AUTOS": "BMW", "KIAMOTORS": "KIA", "MERCEDES-BENZ": "MERCEDES"}
FILIAL_FIX = {
    "21 - TOY NACOES 01::21": "Toyota Nações",
    "22 - TOY MORUMBI 25::22": "Toyota Morumbi",
    "31 - BYD IBIRAPUERA": "BYD Ibirapuera",
    "32 - BYD ALPHAVILLE": "BYD Alphaville",
    "35 - DENZA ALPHAVILLE": "Denza Alphaville",
    "71 - HYU BARRA FUNDA": "Hyundai Barra Funda",
    "72 - HYU GUARULHOS": "Hyundai Guarulhos",
    "75 - HYU PATIO BARRA FUNDA": "Hyundai Barra Funda",
    "2 - BMW ALPHAVILLE": "BMW Alphaville",
}


def norm_filial(x):
    s = str(x).strip()
    s = re.sub(r"^(TOYOTA|BYD|HYUNDAI|DENZA|BMW)\s*-\s*", "", s)
    return FILIAL_FIX.get(s, s)


# ---------------- VENDAS ----------------
def load_vendas(path, sheet=0):
    v = pd.read_excel(path, sheet_name=sheet, header=1)
    v = v.drop(columns=[c for c in v.columns if str(c).startswith("Unnamed")], errors="ignore")
    v = v.dropna(subset=["Modelo"])
    # layout alternativo (planilha de trabalho ja enriquecida)
    if "Valor Fipe" not in v.columns and "FIPE" in v.columns:
        v = v.rename(columns={"FIPE": "Valor Fipe"})
    for c in ["Loja Venda", "Situação NBS"]:
        if c not in v.columns:
            v[c] = np.nan
    v["Marca"] = (v["Família"].str.replace("^VU-", "", regex=True).str.strip()
                  .replace(MARCA_FIX))
    v["Shortname"] = tg.apply(v["Modelo"])
    v["Filial_N"] = v["Filial"].map(norm_filial)
    v["Loja_N"] = v["Loja Venda"].astype(str).str.strip().replace({"BYD Moema": "BYD Ibirapuera"})
    v["Ano"] = pd.to_numeric(v["Ano Modelo"].astype(str).str.split("/").str[-1], errors="coerce")
    v["Margem"] = v["Vl Venda"] - v["Vl Impostos"] - v["Custo Ajustado"]
    v["Blindado"] = v["Situação NBS"].astype(str).str.upper().eq("BLINDADO")
    v["Faixa_KM"] = pd.cut(v["KM"], [-1, 20000, 50000, 100000, 10**9],
                           labels=["Até 20 mil", "20–50 mil", "50–100 mil", "+100 mil"])
    v["Faixa_Ano"] = pd.cut(v["Ano"], [-1, 2017, 2022, 3000],
                            labels=["Até 2017", "2018–2022", "2023+"])
    return v


def agg(df, by):
    g = df.groupby(by, observed=True).agg(
        Vol=("Vl Venda", "size"),
        Faturamento=("Vl Venda", "sum"),
        Custo=("Custo Ajustado", "sum"),
        Margem=("Margem", "sum"),
    )
    # %FIPE so considera linhas com FIPE valida (blindados/importados vem com FIPE=0)
    f = df[df["Valor Fipe"] > 0]
    gf = f.groupby(by, observed=True).agg(V=("Vl Venda", "sum"), F=("Valor Fipe", "sum"))
    g["%FIPE"] = (gf["V"] / gf["F"] * 100).reindex(g.index)
    g["Margem %"] = g["Margem"] / g["Faturamento"] * 100
    g["Margem/carro"] = g["Margem"] / g["Vol"]
    return g.sort_values("Vol", ascending=False)


def total_row(df):
    fat = df["Vl Venda"].sum(); mg = df["Margem"].sum(); n = len(df)
    return dict(Vol=n, Faturamento=fat, Margem=mg,
                **{"Margem %": mg / fat * 100, "Margem/carro": mg / n})


def fmt(g, cols=None):
    d = g.copy()
    for c in ["Faturamento", "Custo", "Margem", "Margem/carro"]:
        if c in d: d[c] = d[c].map(lambda x: f"{x:,.0f}".replace(",", "."))
    for c in ["Margem %", "%FIPE"]:
        if c in d: d[c] = d[c].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
    keep = cols or ["Vol", "Faturamento", "Margem", "Margem %", "Margem/carro", "%FIPE"]
    return d[[c for c in keep if c in d]]


# ---------------- ESTOQUE ----------------
def load_estoque(path):
    e = pd.read_excel(path, header=1).drop(columns=["Unnamed: 0"], errors="ignore")
    e = e.dropna(subset=["MODELO"])
    e["Marca"] = e["MARCA"].str.strip().replace(MARCA_FIX)
    e["Shortname"] = tg.apply(e["MODELO"])
    e["Filial_N"] = e["FILIAL"].map(norm_filial)
    e["Ano"] = pd.to_numeric(e["A/M"].astype(str).str.split("/").str[-1], errors="coerce")
    e["Custo"] = e["CUSTO AJUSTADO"]
    e["Bucket"] = pd.cut(e["D.E"], [-1, 30, 60, 90, 10**6],
                         labels=["0–30", "31–60", "61–90", "90+"])
    return e
