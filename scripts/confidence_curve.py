"""Walk-forward calibration of the confidence layer + coverage × precision curve.

Uso:
    py -3.12 scripts/confidence_curve.py --predictions backtest_results/final_predictions.csv \
        --test-start 2026-01-01 [--out data/confidence_calibration.json]

Para cada caso do período de teste, o modelo de confiança é ajustado só com os
casos cuja VENDA aconteceu antes do mês da avaliação (nada do futuro). Reporta a
cobertura real de cada nível (alta / média / baixa) e a curva "liberando X % das
avaliações, Y % ficam dentro de ±5 % / ±10 %". No fim, ajusta com tudo e grava a
tabela de calibração usada em produção.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from grand_brasil.analysis.confidence import ConfidenceModel, signals_from_row  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--min-group", type=int, default=40)
    ap.add_argument("--high-q90", type=float, default=0.10)
    ap.add_argument("--medium-q90", type=float, default=0.15)
    ap.add_argument("--out", default=None, help="json de calibração (ajustado com todos os casos)")
    args = ap.parse_args()

    df = pd.read_csv(ROOT / args.predictions, sep=";", parse_dates=["appraisal_date", "sale_date"])
    df = df[df["pred"].notna()].copy()
    test_start = pd.Timestamp(args.test_start)
    test = df[df["appraisal_date"] >= test_start].copy()
    print(f"casos: {len(df)} no total, {len(test)} no teste (>= {test_start:%d/%m/%Y})")

    rows = []
    for month, cases in test.groupby(test["appraisal_date"].dt.to_period("M")):
        cutoff = month.start_time
        calib = df[df["sale_date"] < cutoff]
        model = ConfidenceModel(args.min_group, args.high_q90, args.medium_q90).fit(calib)
        for idx, r in cases.iterrows():
            v = model.verdict(signals_from_row(r))
            rows.append({"idx": idx, "level": v.level, "q90": v.q90, "q50": v.q50, "key_len": len(v.key), "calib_n": len(calib)})
    out = test.join(pd.DataFrame(rows).set_index("idx"))

    print("\n== cobertura real por nível (walk-forward) ==")
    print("| nível | casos | % do total | MAPE | ±5% | ±10% | q90 previsto (mediana) |")
    print("|---|---|---|---|---|---|---|")
    for lvl in ("alta", "media", "baixa"):
        g = out[out["level"] == lvl]
        if g.empty:
            continue
        e = g["abs_err_pct"]
        print(f"| {lvl} | {len(g)} | {len(g) / len(out):.0%} | {e.mean():.1%} | {(e <= .05).mean():.0%} | {(e <= .10).mean():.0%} | {g['q90'].median():.1%} |")

    print("\n== curva cobertura × precisão (ordenando pela faixa prevista q90, da mais estreita para a mais larga) ==")
    ranked = out.sort_values("q90").reset_index(drop=True)
    print("| libera | ±3% | ±5% | ±10% | MAPE | q90 máx. no corte |")
    print("|---|---|---|---|---|---|")
    for share in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        k = max(1, int(round(share * len(ranked))))
        e = ranked["abs_err_pct"].iloc[:k]
        print(f"| {share:.0%} | {(e <= .03).mean():.0%} | {(e <= .05).mean():.0%} | {(e <= .10).mean():.0%} | {e.mean():.1%} | {ranked['q90'].iloc[k - 1]:.1%} |")

    print("\n== calibração: q90 previsto vs. realizado por faixa de q90 ==")
    out["q90_bin"] = pd.cut(out["q90"], [0, .06, .08, .10, .12, .15, .20, 1.0])
    g = out.groupby("q90_bin", observed=True)["abs_err_pct"].agg(n="size", within_q90=lambda e: np.nan)
    for b, grp in out.groupby("q90_bin", observed=True):
        within = (grp["abs_err_pct"] <= grp["q90"]).mean()
        print(f"  q90 {b}: n={len(grp)}  realizado dentro da própria faixa: {within:.0%}  (alvo 90%)")

    print("\nespecificidade da chave usada (4 = tier×div×largura×n):", out["key_len"].value_counts().sort_index().to_dict())

    if args.out:
        final = ConfidenceModel(args.min_group, args.high_q90, args.medium_q90).fit(df)
        final.to_json(ROOT / args.out)
        print(f"\ncalibração gravada: {args.out} ({len(final.table)} chaves)")


if __name__ == "__main__":
    main()
