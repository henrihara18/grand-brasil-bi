"""Analise: quanto a equipe Grand Brasil costuma avaliar vs o que o
AutoAvaliar/Webmotors sugeririam para o mesmo carro.

Comparacao por linha das colunas:
    appraised_value  - valor que pagamos / oferecemos
    ref_aav_b2c      - referencia AutoAvaliar B2C (Loja)
    ref_aav_b2b      - referencia AutoAvaliar B2B (Revenda)
    ref_web          - media Webmotors

Reporta delta absoluto, delta %, MAPE e bias por:
  - Status do negocio (UTILIZADO / REPASSE / AVALIADO)
  - Faixa de FIPE
  - Marca
  - Tier de marca (SAFE / NEUTRAL / RISKY)
  - Idade do carro

Saida: estatisticas em texto (cp1252-safe).

Run:
    py -3.12 -m tests.backtests.analyze_vs_autoavaliar
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from grand_brasil.ingestion.appraisal_history import load_appraisal_history
from grand_brasil.utils.brand_tier import BrandTierConfig


def _classify_tier(brand: str) -> str:
    cfg = BrandTierConfig()
    safe = {x.upper() for x in cfg.safe_brands}
    risky = {x.upper() for x in cfg.risky_brands}
    bu = str(brand).upper().strip()
    if bu in safe:
        return "SAFE"
    if bu in risky:
        return "RISKY"
    return "NEUTRAL"


def _stats(series: pd.Series) -> dict[str, float]:
    s = series.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": float("nan"), "median": float("nan"),
                "p25": float("nan"), "p75": float("nan"), "std": float("nan")}
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "std": float(s.std()),
    }


def _delta_metrics(label: str, df: pd.DataFrame, ref_col: str) -> str:
    """Compute mean/median delta of appraised vs ref. Returns formatted line."""
    sub = df[df[ref_col].notna() & (df[ref_col] > 0)].copy()
    if len(sub) == 0:
        return f"  {label:<20} (sem dados em {ref_col})"
    sub["delta_brl"] = sub["appraised_value"] - sub[ref_col]
    sub["delta_pct"] = (sub["appraised_value"] - sub[ref_col]) / sub[ref_col] * 100

    n = len(sub)
    bias_brl = sub["delta_brl"].mean()
    median_brl = sub["delta_brl"].median()
    bias_pct = sub["delta_pct"].mean()
    median_pct = sub["delta_pct"].median()
    mape = sub["delta_pct"].abs().mean()

    sign_b = "+" if bias_brl >= 0 else ""
    sign_p = "+" if bias_pct >= 0 else ""
    sign_m = "+" if median_pct >= 0 else ""

    return (
        f"  {label:<20} n={n:>5}  "
        f"bias R$ {sign_b}{bias_brl:>+8,.0f}  "
        f"({sign_p}{bias_pct:+5.2f}%)  "
        f"median {sign_m}{median_pct:+5.2f}%  "
        f"MAPE {mape:5.2f}%"
    ).replace(",", ".")


def _section(title: str) -> None:
    print()
    print("=" * 90)
    print(f"  {title}")
    print("=" * 90)


def _breakdown(df: pd.DataFrame, group_col: str, ref_col: str,
               min_n: int = 30) -> None:
    """Print per-group delta metrics, sorted by group key."""
    groups = df.groupby(group_col)
    rows = []
    for key, sub in groups:
        if len(sub[sub[ref_col].notna()]) < min_n:
            continue
        s = sub[sub[ref_col].notna() & (sub[ref_col] > 0)].copy()
        if len(s) == 0:
            continue
        s["delta_pct"] = (s["appraised_value"] - s[ref_col]) / s[ref_col] * 100
        rows.append({
            "key": str(key),
            "n": len(s),
            "bias_pct": s["delta_pct"].mean(),
            "median_pct": s["delta_pct"].median(),
            "mape": s["delta_pct"].abs().mean(),
        })
    if not rows:
        print(f"  (sem grupos com n >= {min_n})")
        return
    rows.sort(key=lambda r: r["key"])
    print(f"  {'GRUPO':<25} {'N':>6}  {'BIAS %':>8}  {'MEDIAN %':>9}  {'MAPE %':>8}")
    print(f"  {'-'*25} {'-'*6}  {'-'*8}  {'-'*9}  {'-'*8}")
    for r in rows:
        bias_sign = "+" if r['bias_pct'] >= 0 else ""
        med_sign = "+" if r['median_pct'] >= 0 else ""
        print(
            f"  {r['key']:<25} {r['n']:>6}  "
            f"{bias_sign}{r['bias_pct']:>7.2f}  "
            f"{med_sign}{r['median_pct']:>8.2f}  "
            f"{r['mape']:>7.2f}"
        )


def run() -> None:
    root = Path(__file__).resolve().parents[2]
    appr_path = root / "Avaliacoes 2025 e 2026.xlsx"
    if not appr_path.exists():
        # Fallback to encoded filename
        appr_path = root / "Avaliações 2025 e 2026.xlsx"
    if not appr_path.exists():
        print("ERRO: arquivo de avaliacoes nao encontrado.")
        return

    print("=" * 90)
    print("  ANALISE: GRAND BRASIL vs AUTOAVALIAR / WEBMOTORS")
    print("=" * 90)
    print()
    print("Carregando avaliacoes (UTILIZADO + REPASSE + AVALIADO)...")
    df = load_appraisal_history(appr_path)
    print(f"  Total de linhas validas: {len(df):,}".replace(",", "."))

    # Cobertura das colunas de referencia
    n_b2c = df["ref_aav_b2c"].notna().sum()
    n_b2b = df["ref_aav_b2b"].notna().sum()
    n_web = df["ref_web"].notna().sum() if "ref_web" in df.columns else 0
    print()
    print("Cobertura das colunas de referencia:")
    print(f"  ref_aav_b2c (Loja):    {n_b2c:>6,} linhas ({n_b2c/len(df)*100:.1f}%)".replace(",", "."))
    print(f"  ref_aav_b2b (Revenda): {n_b2b:>6,} linhas ({n_b2b/len(df)*100:.1f}%)".replace(",", "."))
    print(f"  ref_web (Webmotors):   {n_web:>6,} linhas ({n_web/len(df)*100:.1f}%)".replace(",", "."))

    # Distribuicao geral
    _section("DISTRIBUICAO GERAL DOS VALORES")
    print()
    print("  Valor avaliado (Grand Brasil):")
    s = _stats(df["appraised_value"])
    print(f"    media R$ {s['mean']:>10,.0f}  mediana R$ {s['median']:>10,.0f}  "
          f"P25 {s['p25']:>10,.0f}  P75 {s['p75']:>10,.0f}".replace(",", "."))

    print()
    print("  AutoAvaliar B2C (Loja):")
    s = _stats(df["ref_aav_b2c"])
    print(f"    media R$ {s['mean']:>10,.0f}  mediana R$ {s['median']:>10,.0f}  "
          f"P25 {s['p25']:>10,.0f}  P75 {s['p75']:>10,.0f}".replace(",", "."))

    print()
    print("  AutoAvaliar B2B (Revenda):")
    s = _stats(df["ref_aav_b2b"])
    print(f"    media R$ {s['mean']:>10,.0f}  mediana R$ {s['median']:>10,.0f}  "
          f"P25 {s['p25']:>10,.0f}  P75 {s['p75']:>10,.0f}".replace(",", "."))

    if n_web > 0:
        print()
        print("  Webmotors:")
        s = _stats(df["ref_web"])
        print(f"    media R$ {s['mean']:>10,.0f}  mediana R$ {s['median']:>10,.0f}  "
              f"P25 {s['p25']:>10,.0f}  P75 {s['p75']:>10,.0f}".replace(",", "."))

    # Comparacao GLOBAL: Grand Brasil vs cada referencia
    _section("DELTA: GRAND BRASIL - REFERENCIA  (todos os status)")
    print(_delta_metrics("vs AAV B2C (Loja)",     df, "ref_aav_b2c"))
    print(_delta_metrics("vs AAV B2B (Revenda)",  df, "ref_aav_b2b"))
    if n_web > 0:
        print(_delta_metrics("vs Webmotors",      df, "ref_web"))

    # Por status
    _section("POR STATUS DO NEGOCIO")
    for status in ["UTILIZADO", "REPASSE", "AVALIADO"]:
        sub = df[df["status_norm"] == status]
        if len(sub) < 30:
            continue
        print()
        print(f"  -- {status} (n={len(sub)}) --")
        print(_delta_metrics("vs AAV B2C", sub, "ref_aav_b2c"))
        print(_delta_metrics("vs AAV B2B", sub, "ref_aav_b2b"))

    # Por tier de marca
    _section("POR TIER DE MARCA")
    df["tier"] = df["brand"].apply(_classify_tier)
    print()
    print("  vs AAV B2C (Loja):")
    _breakdown(df, "tier", "ref_aav_b2c", min_n=30)
    print()
    print("  vs AAV B2B (Revenda):")
    _breakdown(df, "tier", "ref_aav_b2b", min_n=30)

    # Por marca (top 10)
    _section("TOP 10 MARCAS (por volume)")
    top_brands = df["brand"].value_counts().head(10).index.tolist()
    df_top = df[df["brand"].isin(top_brands)].copy()
    print()
    print("  vs AAV B2C (Loja):")
    _breakdown(df_top, "brand", "ref_aav_b2c", min_n=30)
    print()
    print("  vs AAV B2B (Revenda):")
    _breakdown(df_top, "brand", "ref_aav_b2b", min_n=30)

    # Por faixa de FIPE
    _section("POR FAIXA DE FIPE")
    df["fipe_band"] = pd.cut(
        df["fipe_value"],
        bins=[0, 60_000, 90_000, 120_000, 160_000, 220_000, 1e9],
        labels=["00-60k", "60-90k", "90-120k", "120-160k", "160-220k", "220k+"],
    )
    print()
    print("  vs AAV B2C (Loja):")
    _breakdown(df, "fipe_band", "ref_aav_b2c", min_n=30)
    print()
    print("  vs AAV B2B (Revenda):")
    _breakdown(df, "fipe_band", "ref_aav_b2b", min_n=30)

    # Por idade
    _section("POR IDADE DO CARRO")
    ref_year = pd.Timestamp.now().year
    df["age"] = ref_year - df["year_model"].astype(float)
    df["age_band"] = pd.cut(
        df["age"],
        bins=[-0.5, 2, 4, 7, 11, 99],
        labels=["0-2 anos", "3-4 anos", "5-7 anos", "8-11 anos", "12+ anos"],
    )
    print()
    print("  vs AAV B2C (Loja):")
    _breakdown(df, "age_band", "ref_aav_b2c", min_n=30)
    print()
    print("  vs AAV B2B (Revenda):")
    _breakdown(df, "age_band", "ref_aav_b2b", min_n=30)

    # Quantil de subdeduzir / sobreduzir
    _section("QUEM ESTA MAIS PROXIMO DE QUEM")
    sub = df[df["ref_aav_b2c"].notna() & df["ref_aav_b2b"].notna()].copy()
    if len(sub) > 0:
        # Mais proximo de qual? (em percentual absoluto)
        sub["dist_b2c"] = (sub["appraised_value"] - sub["ref_aav_b2c"]).abs() / sub["ref_aav_b2c"]
        sub["dist_b2b"] = (sub["appraised_value"] - sub["ref_aav_b2b"]).abs() / sub["ref_aav_b2b"]
        closer_b2c = (sub["dist_b2c"] < sub["dist_b2b"]).sum()
        closer_b2b = (sub["dist_b2b"] < sub["dist_b2c"]).sum()
        ties = len(sub) - closer_b2c - closer_b2b
        print()
        print(f"  Linhas com ambas referencias: {len(sub):,}".replace(",", "."))
        print(f"    Mais proxima do AAV B2C (Loja):    {closer_b2c:>5} ({closer_b2c/len(sub)*100:.1f}%)")
        print(f"    Mais proxima do AAV B2B (Revenda): {closer_b2b:>5} ({closer_b2b/len(sub)*100:.1f}%)")
        print(f"    Empate:                             {ties:>5}")

        # Posicao relativa: avaliado entre B2B e B2C?
        between = (
            (sub["appraised_value"] >= sub[["ref_aav_b2c", "ref_aav_b2b"]].min(axis=1)) &
            (sub["appraised_value"] <= sub[["ref_aav_b2c", "ref_aav_b2b"]].max(axis=1))
        ).sum()
        below = (sub["appraised_value"] < sub[["ref_aav_b2c", "ref_aav_b2b"]].min(axis=1)).sum()
        above = (sub["appraised_value"] > sub[["ref_aav_b2c", "ref_aav_b2b"]].max(axis=1)).sum()
        print()
        print("  Posicao do valor avaliado em relacao ao corredor B2B-B2C:")
        print(f"    DENTRO do corredor (entre B2B e B2C):  {between:>5} ({between/len(sub)*100:.1f}%)")
        print(f"    ABAIXO do menor (mais agressivo):      {below:>5} ({below/len(sub)*100:.1f}%)")
        print(f"    ACIMA do maior  (sobrepagamos):        {above:>5} ({above/len(sub)*100:.1f}%)")

    print()
    print("=" * 90)
    print("  Fim da analise.")
    print("=" * 90)


if __name__ == "__main__":
    run()
