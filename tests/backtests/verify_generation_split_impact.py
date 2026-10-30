"""Verify the impact of the generation-split rules on real data.

Reports how many rows got reclassified, the new median-price separation
of the split models, and whether the buy-ratio tier matching now sees
meaningfully different cohorts.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from grand_brasil.ingestion.appraisal_history import load_appraisal_history
from grand_brasil.ingestion.sales_history import load_sales_history


SPLIT_MODELS_NEW = [
    "VOLKSWAGEN TIGUAN",
    "VOLKSWAGEN TIGUAN ALLSPACE",
    "HYUNDAI TUCSON",
    "HYUNDAI TUCSON T-GDI",
    "TOYOTA YARIS",
    "TOYOTA YARIS SEDAN",
    "MITSUBISHI OUTLANDER",
    "MITSUBISHI OUTLANDER SPORT",
]


def main():
    print("=" * 85)
    print("  VERIFICAÇÃO DO IMPACTO — GENERATION SPLIT RULES")
    print("=" * 85)

    # ── Vendas ──
    print("\n## Base de VENDAS")
    sales_path = Path("Relatorio vendas 20255 processado.xlsx")
    sales = load_sales_history(sales_path)
    print(f"  Total: {len(sales):,} linhas\n")

    for m in SPLIT_MODELS_NEW:
        sub = sales[sales["model_red"] == m]
        if len(sub) == 0:
            continue
        median = sub["sale_price"].median()
        p25 = sub["sale_price"].quantile(0.25)
        p75 = sub["sale_price"].quantile(0.75)
        print(f"  {m:<38} n={len(sub):>3}   "
              f"mediana R$ {median:>9,.0f}   P25 R$ {p25:>9,.0f}   P75 R$ {p75:>9,.0f}")

    # ── Avaliações ──
    print("\n## Base de AVALIAÇÕES")
    appr_path = Path("Avaliações 2025 e 2026.xlsx")
    appr = load_appraisal_history(appr_path)
    print(f"  Total: {len(appr):,} linhas\n")

    for m in SPLIT_MODELS_NEW:
        sub = appr[appr["model_red"] == m]
        if len(sub) == 0:
            continue
        median_ratio = sub["ratio"].median()
        median_fipe = sub["fipe_value"].median()
        print(f"  {m:<38} n={len(sub):>4}   "
              f"ratio mediana {median_ratio:.3f}   FIPE mediana R$ {median_fipe:>9,.0f}")

    # ── Ratio comparison: does the split change the ratio meaningfully? ──
    print("\n## Comparação de RATIO entre variantes (base de avaliações)")
    pairs = [
        ("VOLKSWAGEN TIGUAN", "VOLKSWAGEN TIGUAN ALLSPACE"),
        ("HYUNDAI TUCSON", "HYUNDAI TUCSON T-GDI"),
        ("TOYOTA YARIS", "TOYOTA YARIS SEDAN"),
        ("MITSUBISHI OUTLANDER", "MITSUBISHI OUTLANDER SPORT"),
    ]
    for base, new in pairs:
        b = appr[appr["model_red"] == base]
        n = appr[appr["model_red"] == new]
        if len(b) == 0 or len(n) == 0:
            print(f"  {base:<28} vs {new:<40}  (uma das variantes sem dados)")
            continue
        br = b["ratio"].median()
        nr = n["ratio"].median()
        diff = (nr - br) * 100
        fipe_diff = n["fipe_value"].median() - b["fipe_value"].median()
        print(f"  {base:<28} ratio={br:.3f} (n={len(b)})")
        print(f"    vs {new:<26} ratio={nr:.3f} (n={len(n)})"
              f"   Δratio={diff:+.1f}pp   ΔFIPE=R$ {fipe_diff:+,.0f}")


if __name__ == "__main__":
    main()
