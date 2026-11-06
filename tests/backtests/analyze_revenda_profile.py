"""Empirical analysis of the Revenda (wholesale B2B) car profile.

The user's hypothesis is that certain vehicle profiles are much more likely
to end up in Revenda rather than Loja (varejo / B2C), and that the team is
intuitively more aggressive on "safe" brands (Toyota/Honda/Hyundai) and
more conservative on "risky" ones (old Ford/Peugeot/Renault/Citroen/Jeep).

This script validates those intuitions with data and finds:

    1. REVENDA SHARE BY SEGMENT
       - Brand, age, km — which segments flow disproportionately to wholesale?

    2. THRESHOLDS
       - Where in the km distribution does Revenda share spike? (e.g. 100k+?)
       - Where in the age distribution does it spike? (e.g. 8+ years?)

    3. MARGIN / RATIO BY SEGMENT
       - When we send a car to Revenda, are we actually paying less
         relative to FIPE? (vs when it goes to Loja)
       - By brand: are "safe" brands priced more aggressively (higher ratio)?

    4. REVENDA-TYPICAL CANDIDATES CURRENTLY GOING TO LOJA
       - Cars that match the Revenda profile but ended up on the showroom
         floor — these might be the hardest-to-sell inventory later.

    5. ACTIONABLE INSIGHTS
       - Concrete recommendations: e.g. "cars with brand X and age>8 have
         Revenda share Y and we pay margin Z less — consider lowering
         trade-in offer by W% for similar future appraisals."

Run:
    py -3.12 -m tests.backtests.analyze_revenda_profile
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.ingestion.sales_history import load_sales_history


# Brands the user mentioned explicitly as "safer" / "riskier"
SAFE_BRANDS = {"TOYOTA", "HONDA", "HYUNDAI"}
RISKY_BRANDS = {"FORD", "PEUGEOT", "RENAULT", "CITROEN", "JEEP"}


def _load_sales() -> pd.DataFrame:
    for fname in ("Relatorio vendas 20255 processado.xlsx",
                  "Relatorio vendas 2025 processado.xlsx"):
        p = Path(fname)
        if p.exists():
            return load_sales_history(p)
    raise FileNotFoundError("Sales file not found")


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add age, brand_tier, channel_bucket, km bucket."""
    df = df.copy()

    # Sale year -> age
    df["sale_year"] = pd.to_datetime(df["sale_date"], errors="coerce").dt.year
    df["sale_year"] = df["sale_year"].fillna(2025).astype(int)
    df["age"] = (df["sale_year"] - df["year_model"].astype(int)).clip(lower=0, upper=30)

    # Brand tier
    def tier(b: str) -> str:
        bu = str(b).upper().strip()
        if bu in SAFE_BRANDS:
            return "SAFE"
        if bu in RISKY_BRANDS:
            return "RISKY"
        return "NEUTRAL"
    df["brand_tier"] = df["brand"].map(tier)

    # Channel bucket (Loja/Revenda)
    def chan(raw: str) -> str:
        s = str(raw).upper()
        if "REVENDA" in s or "ATACADO" in s or "REPASSE" in s:
            return "Revenda"
        if "LOJA" in s or "VAREJO" in s:
            return "Loja"
        return "Other"
    df["channel"] = df["sale_channel"].apply(chan)

    # KM bucket
    df["km"] = pd.to_numeric(df["km"], errors="coerce")
    km_bins = [0, 30_000, 60_000, 90_000, 120_000, 150_000, 10_000_000]
    km_labels = ["0-30k", "30-60k", "60-90k", "90-120k", "120-150k", "150k+"]
    df["km_bucket"] = pd.cut(df["km"], bins=km_bins, labels=km_labels, right=False)

    # Age bucket
    age_bins = [0, 3, 5, 8, 12, 30]
    age_labels = ["0-2", "3-4", "5-7", "8-11", "12+"]
    df["age_bucket"] = pd.cut(df["age"], bins=age_bins, labels=age_labels, right=False)

    return df


def _revenda_share(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    pivot = (
        df.groupby(by + ["channel"])
        .size()
        .unstack(fill_value=0)
    )
    # Ensure all channel columns exist
    for c in ["Loja", "Revenda", "Other"]:
        if c not in pivot.columns:
            pivot[c] = 0
    pivot["total"] = pivot.sum(axis=1)
    pivot["revenda_pct"] = 100.0 * pivot["Revenda"] / pivot["total"].replace(0, np.nan)
    return pivot.reset_index()


def _print_section(title: str) -> None:
    print("\n" + "=" * 90)
    print(f"  {title}")
    print("=" * 90)


def main() -> None:
    print("Carregando vendas...")
    raw = _load_sales()
    df = _enrich(raw)
    print(f"  {len(df):,} vendas, {df['brand'].nunique()} marcas, "
          f"{df['channel'].value_counts().to_dict()}")

    # ── 1. Revenda share por marca (overall) ────────────────────────────
    _print_section("1. REVENDA SHARE POR MARCA")
    by_brand = _revenda_share(df, ["brand"]).sort_values("revenda_pct", ascending=False)
    by_brand = by_brand[by_brand["total"] >= 10]  # only brands with meaningful volume
    print(f"{'Marca':<20} {'n':>5} {'Loja':>6} {'Revenda':>8} {'%Rev':>6}  {'tier':>8}")
    print("-" * 60)
    for _, r in by_brand.iterrows():
        brand_u = str(r["brand"]).upper()
        t = "SAFE" if brand_u in SAFE_BRANDS else ("RISKY" if brand_u in RISKY_BRANDS else "")
        print(f"{r['brand']:<20} {int(r['total']):>5} {int(r['Loja']):>6} "
              f"{int(r['Revenda']):>8} {r['revenda_pct']:>5.1f}%  {t:>8}")

    # ── 2. Revenda share por tier x idade ────────────────────────────────
    _print_section("2. REVENDA SHARE POR TIER × IDADE")
    tier_age = _revenda_share(df, ["brand_tier", "age_bucket"])
    pivot = tier_age.pivot(index="brand_tier", columns="age_bucket", values="revenda_pct")
    n_pivot = tier_age.pivot(index="brand_tier", columns="age_bucket", values="total")
    print("\nRevenda % por tier × idade:")
    print(pivot.to_string(float_format="%.1f"))
    print("\n(n) amostras por célula:")
    print(n_pivot.to_string())

    # ── 3. Revenda share por tier x KM ───────────────────────────────────
    _print_section("3. REVENDA SHARE POR TIER × KM")
    tier_km = _revenda_share(df, ["brand_tier", "km_bucket"])
    pivot_km = tier_km.pivot(index="brand_tier", columns="km_bucket", values="revenda_pct")
    n_km = tier_km.pivot(index="brand_tier", columns="km_bucket", values="total")
    print("\nRevenda % por tier × km:")
    print(pivot_km.to_string(float_format="%.1f"))
    print("\n(n) amostras por célula:")
    print(n_km.to_string())

    # ── 4. Margem e dias em estoque por tier x canal ─────────────────────
    _print_section("4. MARGEM REAL E DIAS EM ESTOQUE POR TIER × CANAL")
    mg = (
        df[df["channel"].isin(["Loja", "Revenda"])]
        .groupby(["brand_tier", "channel"])
        .agg(
            n=("sale_price", "size"),
            margin_median=("margin_percent", "median"),
            margin_p25=("margin_percent", lambda s: s.quantile(0.25)),
            margin_p75=("margin_percent", lambda s: s.quantile(0.75)),
            days_median=("days_in_stock", "median"),
            price_median=("sale_price", "median"),
        )
    )
    print(mg.to_string(float_format="%.2f"))

    # ── 5. Thresholds: onde KM/idade estouram p/ Revenda ─────────────────
    _print_section("5. THRESHOLDS — onde o Revenda share dispara?")
    for tier_name in ["SAFE", "NEUTRAL", "RISKY"]:
        sub = df[df["brand_tier"] == tier_name]
        if len(sub) < 20:
            continue
        # KM
        km_share = _revenda_share(sub, ["km_bucket"])
        print(f"\n  TIER = {tier_name}")
        print(f"  {'km_bucket':<12} {'n':>4} {'%Revenda':>9}")
        for _, r in km_share.iterrows():
            print(f"  {str(r['km_bucket']):<12} {int(r['total']):>4} {r['revenda_pct']:>8.1f}%")

    # ── 6. Idade × brand — concentração de marcas riskier em idades altas ──
    _print_section("6. MARCAS RISKY POR IDADE — Revenda share")
    risky_df = df[df["brand_tier"] == "RISKY"]
    if len(risky_df) > 0:
        r_age = _revenda_share(risky_df, ["brand", "age_bucket"])
        # Only show brand+age combos with >=5 rows
        r_age = r_age[r_age["total"] >= 5].sort_values(["brand", "age_bucket"])
        print(f"{'brand':<14} {'age':>6} {'n':>4} {'Loja':>5} {'Revenda':>8} {'%Rev':>6}")
        print("-" * 50)
        for _, r in r_age.iterrows():
            print(f"{r['brand']:<14} {str(r['age_bucket']):>6} {int(r['total']):>4} "
                  f"{int(r['Loja']):>5} {int(r['Revenda']):>8} {r['revenda_pct']:>5.1f}%")

    # ── 7. Preço de compra relativo ao de venda (proxy de agressividade) ─
    _print_section("7. PROXY DE AGRESSIVIDADE — purchase/sale ratio")
    df["purchase_ratio"] = df["adjusted_cost"] / df["sale_price"]
    valid = df[(df["purchase_ratio"] > 0.3) & (df["purchase_ratio"] < 1.1)]
    print("\nMaior = mais agressivo (pagamos mais perto do preço de venda).\n"
          "Separado por tier × canal:")
    pr = (
        valid.groupby(["brand_tier", "channel"])["purchase_ratio"]
        .agg(["median", "mean", "size"])
        .round(3)
    )
    print(pr.to_string())

    # ── 8. Insights & recomendações ──────────────────────────────────────
    _print_section("8. INSIGHTS & RECOMENDAÇÕES CONCRETAS")

    # Find brands where Revenda share is high AND margin is low
    brand_chan = df[df["channel"].isin(["Loja", "Revenda"])].groupby(
        ["brand", "channel"]).agg(
        n=("sale_price", "size"),
        margin_median=("margin_percent", "median"),
        price_median=("sale_price", "median"),
    ).reset_index()

    # Brand-level Revenda share
    brand_total = df[df["channel"].isin(["Loja", "Revenda"])].groupby("brand").size()
    brand_rev = df[df["channel"] == "Revenda"].groupby("brand").size()
    brand_rev_pct = (brand_rev / brand_total * 100).fillna(0).sort_values(ascending=False)

    # Only brands with meaningful volume
    top_rev = brand_rev_pct[brand_total >= 15].head(10)
    print("\nMarcas com MAIOR % Revenda (n >= 15):")
    for b, pct in top_rev.items():
        tot = int(brand_total[b])
        print(f"  {b:<20} {pct:>5.1f}% Revenda   (n={tot})")

    print("\nMarcas com MENOR % Revenda (n >= 15):")
    bot_rev = brand_rev_pct[brand_total >= 15].tail(10)
    for b, pct in bot_rev.items():
        tot = int(brand_total[b])
        print(f"  {b:<20} {pct:>5.1f}% Revenda   (n={tot})")

    # ── 9. Revenda-suspect cars currently at Loja ────────────────────────
    _print_section("9. CARROS QUE FORAM P/ LOJA MAS TINHAM PERFIL REVENDA")
    # Heuristic: RISKY brand + age >= 8 + km >= 120k AND went to Loja
    suspect = df[
        (df["channel"] == "Loja")
        & (df["brand_tier"] == "RISKY")
        & (df["age"] >= 8)
        & (df["km"] >= 120_000)
    ].copy()
    print(f"\n{len(suspect)} carros casaram o perfil (RISKY + 8+ anos + 120k+ km) e foram p/ Loja")
    if len(suspect) > 0:
        print(f"  margem real mediana: {suspect['margin_percent'].median():.2f}%")
        print(f"  dias em estoque mediana: {suspect['days_in_stock'].median():.0f}")
        print(f"  vs comparaveis Revenda SAFE 3-7 anos:")
        baseline = df[
            (df["channel"] == "Revenda")
            & (df["brand_tier"] == "SAFE")
            & (df["age"].between(3, 7))
        ]
        if len(baseline) > 0:
            print(f"    margem: {baseline['margin_percent'].median():.2f}%, "
                  f"dias: {baseline['days_in_stock'].median():.0f}")


if __name__ == "__main__":
    main()
