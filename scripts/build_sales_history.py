"""Rebuild the processed sales workbook from ERP RAW report(s).

Uso:
    py -3.12 scripts/build_sales_history.py \
        --raw "C:/Users/henri/Downloads/Relatório - 2026-10-26T181239.418.xls" \
        [--raw "<outro RAW, ex. filiais BMW/JLR>"] \
        --previous "Vendas 2025-2026 processado.xlsx" \
        --year 2026 \
        --out "Vendas 2025-2026 processado.xlsx"

Regras: linhas do RAW mandam no ano informado; do arquivo anterior ficam os anos
antigos e, no ano do RAW, só as filiais que nenhum RAW cobre. Modelos que não
estão em Tag_Modelos.xlsx saem em --novos para confirmação.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from grand_brasil.ingestion.erp_raw_sales import (  # noqa: E402
    BuildReport,
    build_sales_history,
    new_models_table,
    normalize_erp_sales,
    parse_erp_html,
    read_previous_workbook,
    write_sales_history,
)
from grand_brasil.ingestion.sales_history import load_sales_history  # noqa: E402
from grand_brasil.utils.model_tagger import Tagger  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", action="append", required=True, help="RAW do ERP (.xls/HTML); repita para varios")
    ap.add_argument("--previous", help="planilha processada anterior (anos antigos / filiais fora do RAW)")
    ap.add_argument("--year", type=int, required=True, help="ano coberto pelos RAWs")
    ap.add_argument("--out", required=True, help="xlsx de saida (layout lido pelo app)")
    ap.add_argument("--novos", help="csv com modelos resolvidos por regra, para confirmacao")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    report = BuildReport()
    tagger = Tagger()
    raw_frames = [parse_erp_html(p) for p in args.raw]
    normalized = [
        normalize_erp_sales(f, tagger, origem=f"RAW ERP {Path(p).name}", report=report)
        for f, p in zip(raw_frames, args.raw)
    ]
    previous = read_previous_workbook(args.previous) if args.previous else None

    out = build_sales_history(normalized, previous, args.year, report=report)
    write_sales_history(out, args.out)
    loaded = load_sales_history(args.out)

    if args.novos:
        new_models_table(report, raw_frames).to_csv(args.novos, index=False, sep=";", encoding="utf-8-sig")

    print(f"RAW: {report.raw_rows} linhas lidas | NF duplicadas: {report.duplicate_invoices} | "
          f"Marg.Ini. divergente: {report.margin_mismatches} | Valor Fipe = 0: {report.fipe_zero_rows} | "
          f"motos descartadas: {report.motorcycles_dropped}")
    print(f"Filiais no RAW: {report.raw_filiais}")
    if report.odd_families:
        print(f"Familias sem prefixo VU- (mapeadas por regra): {report.odd_families}")
    if previous is not None:
        print(f"Do arquivo anterior: {report.kept_previous_years} linhas de anos anteriores a {args.year}; "
              f"{sum(report.kept_previous_other_filiais.values())} de {args.year} em filiais fora do RAW "
              f"{report.kept_previous_other_filiais}")
        if len(report.dropped_previous_same_filial):
            cols = [c for c in ["Dt Venda", "Marca", "MODELO RED", "Placa", "Filial", "Nr NF/Série", "Vl Venda"] if c in report.dropped_previous_same_filial.columns]
            print(f"ATENCAO: {len(report.dropped_previous_same_filial)} vendas de {args.year} estavam no arquivo "
                  f"anterior mas nao no RAW (descartadas):")
            print(report.dropped_previous_same_filial[cols].to_string(index=False))
    print(f"Saida: {report.total_rows} linhas -> {args.out} | loader carregou {len(loaded)} vendas validas")
    print("Por mes:", loaded["sale_date"].dt.to_period("M").value_counts().sort_index().to_dict())
    print("Canal:", loaded["sale_channel"].value_counts().to_dict())
    print(f"Modelos fora da base Tag_Modelos: {len(report.new_models)}" + (f" -> {args.novos}" if args.novos else ""))


if __name__ == "__main__":
    main()
