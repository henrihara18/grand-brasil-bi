"""Empirical calibration of armored-vehicle (blindado) premium by year.

There is no explicit 'blindado' flag in our sales data — armored cars are
detected as statistical outliers on sale_price. This script:

    1. Groups sales by (brand, model_red, year_model) with >= 6 rows.
    2. Within each group, computes an 'anchor' = median of the bottom 75%
       (same heuristic used in `_blindado.py::remove_blindados`).
    3. Flags rows whose sale_price - anchor exceeds a floor (R$ 8k) and
       whose z-score is high — these are blindado candidates.
    4. For each flagged row, records its premium = sale_price - anchor.
    5. Aggregates premiums by year_model and reports:
         - N candidates detected
         - Median, P25, P75 premium
         - Current config value (from BlindadoConfig defaults)
         - Suggested calibration (rounded to nearest 5k)

Run with:
    py -3.12 -m tests.backtests.analyze_blindado_premium

Not a pytest test (slow, I/O-heavy, investigative tool).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from grand_brasil.analysis._blindado import _DEFAULT_BLINDADO_SALE_PREMIUM
from grand_brasil.ingestion.sales_history import load_sales_history


# ── Detection parameters ─────────────────────────────────────────────────────
MIN_GROUP_SIZE = 6            # Skip (brand, model, year) groups smaller than this
PREMIUM_FLOOR_BRL = 8_000     # Minimum price delta above anchor to flag candidate
MIN_Z_SCORE = 1.5             # Stats: candidate must be N std devs above anchor
MAX_PREMIUM_BRL = 200_000     # Upper sanity bound — exclude absurd outliers (data errors)


def detect_blindado_candidates(sales_df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of rows flagged as likely blindados, with computed premium.

    Columns added:
        anchor_price  : median of bottom 75% in the group
        premium_brl   : sale_price - anchor_price
        group_n       : group size (useful for weighting)
        z_score       : how many std devs the row is above the group median

    The 'sale_channel' column is preserved so callers can break the result
    down by Loja vs Revenda.
    """
    needed = ["sale_price", "year_model", "model_red"]
    keep = sales_df.dropna(subset=needed).copy()
    keep = keep[keep["sale_price"] > 0]

    out_frames = []
    for (brand, model, year), grp in keep.groupby(["brand", "model_red", "year_model"]):
        if len(grp) < MIN_GROUP_SIZE:
            continue

        prices = grp["sale_price"].astype(float)
        p75 = prices.quantile(0.75)
        lower = prices[prices <= p75]
        if len(lower) < 3:
            continue
        anchor = float(lower.median())
        std = float(lower.std(ddof=0))
        if std <= 0:
            continue

        candidates = grp.copy()
        candidates["anchor_price"] = anchor
        candidates["premium_brl"] = candidates["sale_price"].astype(float) - anchor
        candidates["group_n"] = len(grp)
        candidates["z_score"] = (
            candidates["sale_price"].astype(float) - anchor
        ) / std

        flagged = candidates[
            (candidates["premium_brl"] >= PREMIUM_FLOOR_BRL)
            & (candidates["premium_brl"] <= MAX_PREMIUM_BRL)
            & (candidates["z_score"] >= MIN_Z_SCORE)
        ]
        if len(flagged) > 0:
            out_frames.append(flagged)

    if not out_frames:
        return pd.DataFrame()
    return pd.concat(out_frames, ignore_index=True)


def summarize_by_year(flagged: pd.DataFrame) -> pd.DataFrame:
    """Aggregate detected blindados by year_model."""
    if flagged.empty:
        return pd.DataFrame()

    rows = []
    for year, grp in flagged.groupby("year_model"):
        year_int = int(year)
        premiums = grp["premium_brl"].astype(float)
        config_value = _DEFAULT_BLINDADO_SALE_PREMIUM.get(year_int)
        median_premium = float(premiums.median())
        # Round suggestion to nearest 5k (business-friendly)
        suggested = int(round(median_premium / 5_000) * 5_000)

        rows.append({
            "year_model": year_int,
            "n_candidates": len(grp),
            "median_premium": median_premium,
            "p25_premium": float(premiums.quantile(0.25)),
            "p75_premium": float(premiums.quantile(0.75)),
            "current_config": config_value,
            "suggested_5k": suggested,
            "delta_vs_config": (
                suggested - config_value if config_value is not None else None
            ),
        })

    return pd.DataFrame(rows).sort_values("year_model", ascending=False)


def _fmt_brl(v) -> str:
    if pd.isna(v) or v is None:
        return "      —"
    return f"R$ {int(v):>8,}"


def _print_summary(summary: pd.DataFrame) -> None:
    header = (
        f"{'Ano':>5} {'N':>4} | {'Mediana':>12} {'P25':>12} {'P75':>12} |"
        f" {'Config':>12} {'Sugestão':>12} {'Δ':>10}"
    )
    print(header)
    print("-" * len(header))
    for _, row in summary.iterrows():
        delta = row["delta_vs_config"]
        delta_str = "—" if delta is None or pd.isna(delta) else f"{int(delta):+,}"
        print(
            f"{int(row['year_model']):>5} "
            f"{int(row['n_candidates']):>4} | "
            f"{_fmt_brl(row['median_premium'])} "
            f"{_fmt_brl(row['p25_premium'])} "
            f"{_fmt_brl(row['p75_premium'])} | "
            f"{_fmt_brl(row['current_config'])} "
            f"{_fmt_brl(row['suggested_5k'])} "
            f"{delta_str:>10}"
        )


def _print_recommendation(summary: pd.DataFrame) -> None:
    if summary.empty:
        return
    print("\n" + "─" * 80)
    print("Leitura rápida:")
    within_10k = summary[
        (summary["delta_vs_config"].abs() <= 10_000) & summary["current_config"].notna()
    ]
    off = summary[
        (summary["delta_vs_config"].abs() > 10_000) & summary["current_config"].notna()
    ]
    new_years = summary[summary["current_config"].isna()]

    print(f"  • {len(within_10k)} ano(s) dentro de ±R$ 10k do config (OK).")
    if len(off) > 0:
        print(f"  • {len(off)} ano(s) com desvio > R$ 10k — revisar:")
        for _, row in off.iterrows():
            print(
                f"      {int(row['year_model'])}: "
                f"config {_fmt_brl(row['current_config'])}, "
                f"empirico {_fmt_brl(row['suggested_5k'])} "
                f"({int(row['delta_vs_config']):+,})"
            )
    if len(new_years) > 0:
        anos = ", ".join(str(int(y)) for y in new_years["year_model"])
        print(f"  • {len(new_years)} ano(s) sem entry no config: {anos}")

    # Robustness caveat
    small_n = summary[summary["n_candidates"] < 5]
    if len(small_n) > 0:
        anos = ", ".join(str(int(y)) for y in small_n["year_model"])
        print(f"\n  ⚠️ Anos com amostra pequena (<5 candidatos), resultado ruidoso: {anos}")


def _print_channel_breakdown(flagged: pd.DataFrame) -> None:
    """Per-channel premium analysis (Loja vs Revenda)."""
    if flagged.empty or "sale_channel" not in flagged.columns:
        return

    print("\n" + "=" * 80)
    print("BREAKDOWN POR CANAL — Loja (B2C) vs Revenda (B2B)")
    print("=" * 80)

    by_channel = flagged.groupby("sale_channel").size().to_dict()
    print(f"\nDistribuicao dos candidatos: {by_channel}\n")

    rows = []
    for (year, channel), grp in flagged.groupby(["year_model", "sale_channel"]):
        premiums = grp["premium_brl"].astype(float)
        rows.append({
            "year_model": int(year),
            "channel": channel,
            "n": len(grp),
            "median": float(premiums.median()),
            "p25": float(premiums.quantile(0.25)),
            "p75": float(premiums.quantile(0.75)),
        })
    df = pd.DataFrame(rows)

    # Pivot for side-by-side comparison
    pivot = df.pivot(index="year_model", columns="channel",
                     values=["n", "median", "p25", "p75"])
    pivot = pivot.sort_index(ascending=False)

    header = (
        f"{'Ano':>5} | "
        f"{'Loja N':>7} {'Loja med':>11} {'Loja P25':>11} {'Loja P75':>11} | "
        f"{'Rev N':>6} {'Rev med':>11} {'Rev P25':>11} {'Rev P75':>11} | "
        f"{'Δ med':>10}"
    )
    print(header)
    print("-" * len(header))

    for year in pivot.index:
        loja_n = pivot.get(("n", "Loja"), pd.Series()).get(year, np.nan)
        loja_med = pivot.get(("median", "Loja"), pd.Series()).get(year, np.nan)
        loja_p25 = pivot.get(("p25", "Loja"), pd.Series()).get(year, np.nan)
        loja_p75 = pivot.get(("p75", "Loja"), pd.Series()).get(year, np.nan)
        rev_n = pivot.get(("n", "Revenda"), pd.Series()).get(year, np.nan)
        rev_med = pivot.get(("median", "Revenda"), pd.Series()).get(year, np.nan)
        rev_p25 = pivot.get(("p25", "Revenda"), pd.Series()).get(year, np.nan)
        rev_p75 = pivot.get(("p75", "Revenda"), pd.Series()).get(year, np.nan)

        delta = (loja_med - rev_med) if not (pd.isna(loja_med) or pd.isna(rev_med)) else np.nan
        delta_str = "—" if pd.isna(delta) else f"{int(delta):+,}"

        def fmt_n(v):
            return "  —" if pd.isna(v) else f"{int(v):>3}"
        def fmt_b(v):
            return "         —" if pd.isna(v) else f"R$ {int(v):>7,}"

        print(
            f"{int(year):>5} | "
            f"{fmt_n(loja_n):>7} {fmt_b(loja_med):>11} {fmt_b(loja_p25):>11} {fmt_b(loja_p75):>11} | "
            f"{fmt_n(rev_n):>6} {fmt_b(rev_med):>11} {fmt_b(rev_p25):>11} {fmt_b(rev_p75):>11} | "
            f"{delta_str:>10}"
        )

    # Aggregate hypothesis: is Loja systematically higher than Revenda?
    print("\n" + "─" * 80)
    print("Teste agregado (Loja vs Revenda, todos anos):")
    overall = flagged.groupby("sale_channel")["premium_brl"].agg(["count", "median", "mean"])
    print(overall.to_string())

    if "Loja" in overall.index and "Revenda" in overall.index:
        loja_med_all = overall.loc["Loja", "median"]
        rev_med_all = overall.loc["Revenda", "median"]
        diff_pct = (loja_med_all - rev_med_all) / rev_med_all * 100
        print(
            f"\n  → Mediana Loja:    R$ {loja_med_all:>8,.0f}\n"
            f"  → Mediana Revenda: R$ {rev_med_all:>8,.0f}\n"
            f"  → Loja eh {diff_pct:+.1f}% maior que Revenda."
        )


def main(sales_path: Optional[Path] = None) -> None:
    if sales_path is None:
        root = Path(__file__).resolve().parents[2]
        sales_path = root / "Relatorio vendas 20255 processado.xlsx"

    if not sales_path.exists():
        print(f"ERRO: {sales_path} nao encontrado.")
        return

    print("=" * 80)
    print("CALIBRAÇÃO EMPÍRICA — Prêmio de Blindagem (R$) por Ano Modelo")
    print("=" * 80)

    sales_df = load_sales_history(sales_path)
    print(f"\nBase de vendas: {len(sales_df)} linhas")

    flagged = detect_blindado_candidates(sales_df)
    total_groups = sales_df.groupby(["brand", "model_red", "year_model"]).size()
    n_groups_used = (total_groups >= MIN_GROUP_SIZE).sum()
    print(
        f"Grupos (marca×modelo×ano) com ≥{MIN_GROUP_SIZE} vendas: "
        f"{n_groups_used}/{len(total_groups)}"
    )
    print(
        f"Candidatos a blindado detectados (z≥{MIN_Z_SCORE}, "
        f"premium≥R${PREMIUM_FLOOR_BRL:,}, ≤R${MAX_PREMIUM_BRL:,}): "
        f"{len(flagged)} venda(s)\n"
    )

    if flagged.empty:
        print("Nenhum candidato detectado. Ajuste os limiares em detect_blindado_candidates().")
        return

    summary = summarize_by_year(flagged)
    _print_summary(summary)
    _print_recommendation(summary)
    _print_channel_breakdown(flagged)


if __name__ == "__main__":
    main()
