"""Deep analysis: where does trim segregation actually succeed or fail?

Follow-up to analyze_trim_matching.py. That script flagged big spreads
per model_red — but many of those are already handled correctly because
the trim IS embedded in model_red (e.g. "HYUNDAI CRETA LIMITED"). This
script drills into WHY each model_red has a spread:

    Category A — GENERATION/BODY splits already in model_red
        → No action needed (e.g. CRETA variants each have own model_red)

    Category B — HIDDEN GENERATIONS (same model_red, different body/gen)
        → Need split at ingestion (e.g. TIGUAN vs TIGUAN ALLSPACE)

    Category C — TRIM-LEVEL within same model (EX vs EXL vs TOURING)
        → Check if model_trim is actually segregating the price

Output tells us for each high-spread model:
    • How many distinct model_trims exist
    • Median price per trim (showing if trims are well-separated)
    • Whether the DealerUp `modelo_full` contains the generation hint
      that we should promote (ALLSPACE, T-GDI, CROSS, GT, etc.)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from grand_brasil.ingestion.sales_history import load_sales_history


# Models to investigate (high-spread from previous analysis + user's request)
MODELS_TO_INVESTIGATE = [
    "VOLKSWAGEN TIGUAN",
    "HYUNDAI TUCSON",
    "HYUNDAI HB20",
    "NISSAN VERSA",
    "VOLKSWAGEN VIRTUS",
    "CHEVROLET ONIX",
    "HONDA CIVIC",      # user's case
    "HONDA HR-V",
    "HONDA CITY",
    "TOYOTA COROLLA",
    "VOLKSWAGEN POLO",
    "VOLKSWAGEN GOL",
    "JEEP COMPASS",
    "JEEP RENEGADE",
    "NISSAN KICKS",
    "TOYOTA COROLLA CROSS",
    "TOYOTA YARIS",
    "HYUNDAI HB20S",
    "CHEVROLET TRACKER",
    "CHEVROLET EQUINOX",
    "FORD ECOSPORT",
    "MITSUBISHI OUTLANDER",
    "MITSUBISHI ASX",
]


def _load_sales() -> pd.DataFrame:
    for fname in ("Relatorio vendas 20255 processado.xlsx",
                  "Relatorio vendas 2025 processado.xlsx"):
        p = Path(fname)
        if p.exists():
            return load_sales_history(p)
    raise FileNotFoundError("Sales file not found")


def analyze_model(df: pd.DataFrame, model_red: str) -> None:
    sub = df[df["model_red"].str.upper() == model_red.upper()].copy()
    if len(sub) < 5:
        return
    print("\n" + "=" * 85)
    print(f"  {model_red}  —  n={len(sub)}  (median R$ {sub['sale_price'].median():,.0f})")
    print("=" * 85)

    # Trim level breakdown
    trim_stats = (
        sub.groupby("model_trim")
        .agg(n=("sale_price", "size"),
             median=("sale_price", "median"),
             p25=("sale_price", lambda s: s.quantile(0.25)),
             p75=("sale_price", lambda s: s.quantile(0.75)))
        .sort_values("median")
        .reset_index()
    )
    print(f"  {'model_trim':<45} {'n':>4} {'median':>12} {'p25':>10} {'p75':>10}")
    print("  " + "-" * 83)
    for _, r in trim_stats.iterrows():
        flag = " ⚠" if r["n"] >= 3 and (r["p75"] / max(r["p25"], 1)) > 1.40 else ""
        trim_disp = r["model_trim"] if len(r["model_trim"]) < 45 else r["model_trim"][:42] + "..."
        print(f"  {trim_disp:<45} {int(r['n']):>4} R$ {r['median']:>9,.0f} "
              f"R$ {r['p25']:>7,.0f} R$ {r['p75']:>7,.0f}{flag}")

    # Sample modelo_full strings to see what info is available in source
    uniq_modelo = sub["modelo_full"].dropna().unique()[:8] if "modelo_full" in sub.columns else []
    if len(uniq_modelo) > 0:
        print(f"  📄 Sample modelo_full from DealerUp:")
        for m in uniq_modelo[:6]:
            print(f"     • {m}")


def find_generation_hints(df: pd.DataFrame) -> dict:
    """Look for tokens in modelo_full that suggest generation/body-style splits
    the system is currently missing.

    Focus on models where model_trim == model_red (fallback cases) AND
    where the modelo_full contains distinguishing tokens.
    """
    if "modelo_full" not in df.columns:
        return {}

    # Models where trim extraction failed (fallback rows)
    fallback_rows = df[df["model_trim"].str.upper() == df["model_red"].str.upper()].copy()

    hints: dict[str, set[str]] = {}
    # Tokens known to indicate major variations (body, generation, engine family)
    gen_tokens = [
        "ALLSPACE", "COMFORT", "SAFETY", "SPACE", "COUPE", "SW",
        "T-GDI", "T-GDI", "TGDI",
        "GTI", "GT", "GTS",
        "XLS", "XLT", "XR", "XRS",
        "R-DYNAMIC", "R-LINE", "RL",
        "HYBRID", "HIBRIDO",
        "LOUNGE", "ACTION", "FIRST", "EDITION",
        "SPORT",  # only matters when joined with another word
    ]

    for model, sub in fallback_rows.groupby("model_red"):
        if len(sub) < 5:
            continue
        for mf in sub["modelo_full"].dropna().astype(str):
            mf_u = mf.upper()
            for tok in gen_tokens:
                if tok in mf_u:
                    hints.setdefault(model, set()).add(tok)

    return hints


def main() -> None:
    print("Carregando vendas...")
    df = _load_sales()
    print(f"  {len(df):,} vendas carregadas")

    print("\n\n" + "=" * 85)
    print("  PARTE 1 — ANÁLISE DETALHADA POR MODELO")
    print("=" * 85)
    for model in MODELS_TO_INVESTIGATE:
        analyze_model(df, model)

    # Part 2: hint discovery
    print("\n\n" + "=" * 85)
    print("  PARTE 2 — DICAS DE GERAÇÃO NÃO EXPLORADAS (no modelo_full)")
    print("=" * 85)
    print("Modelos onde model_trim == model_red (fallback) MAS o modelo_full")
    print("contém tokens que indicam variações importantes:\n")
    hints = find_generation_hints(df)
    for model, tokens in sorted(hints.items(), key=lambda x: -len(x[1])):
        sub = df[df["model_red"] == model]
        n = len(sub)
        if n < 5:
            continue
        print(f"  {model:<40} n={n:<4} tokens encontrados: {sorted(tokens)}")


if __name__ == "__main__":
    main()
