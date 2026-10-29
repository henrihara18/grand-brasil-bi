"""Temporal backtest of the appraisal engine.

Uso:
    py -3.12 scripts/backtest.py --label baseline
    py -3.12 scripts/backtest.py --label baseline --test-start 2026-01-01 --test-end 2026-11-01

Entradas (default): Vendas 2025-2026 processado.xlsx, Avaliacoes plataforma.xlsx (export da
planilha) mesclado com o Excel legado do config. Saidas em backtest_results/<label>_*.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from grand_brasil.backtest.dataset import add_targets, link_cases, loja_margin_targets  # noqa: E402
from grand_brasil.backtest.fipe_table import FipeTable, TableFipeClient  # noqa: E402
from grand_brasil.backtest.metrics import add_errors, all_breakdowns, fmt_summary, summarize, table_md  # noqa: E402
from grand_brasil.backtest.runner import RunOptions, run_backtest  # noqa: E402
from grand_brasil.config import load_config  # noqa: E402
from grand_brasil.ingestion.appraisal_history import (  # noqa: E402
    drop_implausible_ratios,
    load_appraisal_history,
    merge_with_legacy,
    reconcile_with_sales,
)
from grand_brasil.ingestion.sales_history import load_sales_history  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    ap.add_argument("--sales", default=None, help="xlsx processado (default: config sales_history_file)")
    ap.add_argument("--appraisals", default="Avaliacoes plataforma.xlsx")
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--test-end", default="2026-11-01")
    ap.add_argument("--max-lag-days", type=int, default=365)
    ap.add_argument("--targets-until", default=None,
                    help="margens-alvo Loja a partir das vendas anteriores a esta data (default: --test-start)")
    ap.add_argument("--purpose", default="auto", choices=["auto", "loja", "revenda", "from_case"],
                    help="from_case = Revenda quando a avaliacao foi lancada como REPASSE (o que o avaliador escolheria na tela)")
    ap.add_argument("--keep-same-plate", action="store_true", help="nao excluir avaliacoes anteriores do mesmo carro")
    ap.add_argument("--limit", type=int, default=None, help="rodar so os N primeiros casos (debug)")
    ap.add_argument("--out", default="backtest_results")
    ap.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                    help="override de config, ex.: --set buy_ratio.tier_order=km_first --set buy_ratio.km_adjust=true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for name in ("grand_brasil.analysis", "grand_brasil.ingestion", "grand_brasil.utils"):
        logging.getLogger(name).setLevel(logging.ERROR)

    settings = load_config()
    cfg = settings.app.appraisal
    for item in args.set:
        path, value = item.split("=", 1)
        target, attr = cfg, path
        if "." in path:
            parent, attr = path.rsplit(".", 1)
            for part in parent.split("."):
                target = getattr(target, part)
        current = getattr(target, attr)
        if isinstance(current, bool) or value.lower() in ("true", "false"):
            parsed = value.lower() == "true"
        elif value.lower() in ("none", "null"):
            parsed = None
        elif isinstance(current, int) and not isinstance(current, bool):
            parsed = int(value)
        elif isinstance(current, float) or current is None:
            parsed = float(value)
        elif isinstance(current, dict):
            import json
            parsed = {int(k) if str(k).lstrip("-").isdigit() else k: v for k, v in json.loads(value).items()}
        else:
            parsed = value
        setattr(target, attr, parsed)
        print(f"config override: {path} = {parsed!r}")
    weights = {"UTILIZADO": cfg.buy_ratio.utilizado_weight, "REPASSE": cfg.buy_ratio.repasse_weight,
               "AVALIADO": cfg.buy_ratio.avaliado_weight}

    t0 = time.time()
    sales = load_sales_history(ROOT / (args.sales or cfg.sales_history_file))
    appr = load_appraisal_history(ROOT / args.appraisals, status_weights=weights)
    legacy = ROOT / cfg.appraisal_legacy_file
    if legacy.exists():
        appr = merge_with_legacy(appr, load_appraisal_history(legacy, status_weights=weights), cfg.appraisal_legacy_until)
    if cfg.reconcile_paid_with_sales:
        appr = reconcile_with_sales(appr, sales, cfg.reconcile_tolerance)
        print(f"  reconciliacao com custo da venda: {int((appr['paid_source'] == 'venda').sum())} valores corrigidos")
    appr_cases = appr   # evaluation cases keep every closed deal (with reconciled paid values)
    if cfg.ratio_floor_by_age:
        before = len(appr); appr = drop_implausible_ratios(appr, cfg.ratio_floor_by_age)
        print(f"  ratios implausiveis removidos da base de comparaveis: {before - len(appr)}")
    print(f"dados: {len(sales)} vendas, {len(appr)} avaliacoes ({time.time() - t0:.0f}s)")

    test_start, test_end = pd.Timestamp(args.test_start), pd.Timestamp(args.test_end)
    targets = loja_margin_targets(sales, until=pd.Timestamp(args.targets_until) if args.targets_until else test_start)
    cases = add_targets(link_cases(appr_cases, sales, test_start, test_end, args.max_lag_days), targets)
    if args.limit:
        cases = cases.head(args.limit)
    print(f"casos: {len(cases)} avaliacoes fechadas em [{test_start:%d/%m/%Y}, {test_end:%d/%m/%Y}) com venda posterior")
    print("margem-alvo Loja por faixa (realizada antes do teste):", {k: f"{v:.1%}" for k, v in targets.loja_by_band.items()}, "| Revenda:", f"{targets.revenda:.0%}")

    fipe = TableFipeClient(FipeTable(appr))
    print(f"tabela FIPE: {fipe.table.size} combinacoes modelo x ano x mes")

    t1 = time.time()
    res = run_backtest(cases, sales, appr, cfg, fipe, RunOptions(purpose=args.purpose, exclude_same_plate=not args.keep_same_plate))
    res = add_errors(res)
    print(f"motor rodou {len(res)} casos em {time.time() - t1:.0f}s | FIPE hist: {fipe.hits} hits, {fipe.misses} misses")

    out_dir = ROOT / args.out
    out_dir.mkdir(exist_ok=True)
    res.to_csv(out_dir / f"{args.label}_predictions.csv", index=False, sep=";", encoding="utf-8-sig")

    overall = summarize(res)
    lines = [f"# Backtest `{args.label}`", "",
             f"Teste: avaliacoes fechadas de {test_start:%d/%m/%Y} a {test_end:%d/%m/%Y} com venda posterior (lag <= {args.max_lag_days} d). "
             f"Treino: tudo anterior ao mes da avaliacao{' (sem o proprio carro)' if not args.keep_same_plate else ''}. Finalidade: {args.purpose}.",
             "", "**Geral:** " + fmt_summary(overall), ""]
    for title, t in all_breakdowns(res).items():
        lines += [f"## Por {title}", "", table_md(t), ""]
    (out_dir / f"{args.label}_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\nGERAL:", fmt_summary(overall))
    print(f"\nresumo: {out_dir / (args.label + '_summary.md')}")


if __name__ == "__main__":
    main()
