"""Reducao de Precos (Price Reduction) page — recommendations table + filters."""

from decimal import Decimal

import pandas as pd
import streamlit as st

from grand_brasil.analysis.pricing import recommend_prices_batch
from grand_brasil.config import Settings
from grand_brasil.dashboard.components.data_table import render_csv_download
from grand_brasil.models.vehicle import Vehicle
from grand_brasil.utils.currency import format_brl, format_percent


def render(vehicles: list[Vehicle], config: Settings) -> None:
    """Render the Reducao de Precos (Price Reduction) page.

    Shows:
    - Summary: total vehicles with recommendations, potential revenue impact
    - Filters: by brand, minimum days, minimum margin
    - Recommendation table: modelo, preco atual, preco sugerido, reducao %,
      dias, margem atual/projetada, FIPE reference
    - CSV export

    Args:
        vehicles: Full list of vehicles in stock.
        config: Application configuration.
    """
    st.title("Recomendacoes de Reducao de Preco")

    if not vehicles:
        st.warning("Nenhum veiculo carregado. Faca upload de um arquivo na barra lateral.")
        return

    recommendations = recommend_prices_batch(
        vehicles, config.app.price_reduction_rules
    )

    if not recommendations:
        st.success(
            "Nenhum veiculo necessita de reducao de preco com as regras atuais. "
            "Ajuste os parametros em config.yaml se necessario."
        )
        return

    # ── Summary Metrics ──
    total_current = sum(r.current_price for r in recommendations)
    total_recommended = sum(r.recommended_price for r in recommendations)
    total_impact = total_current - total_recommended

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Veiculos com Sugestao", f"{len(recommendations)}")
    with col2:
        st.metric("Valor Atual Total", format_brl(total_current))
    with col3:
        st.metric("Valor Sugerido Total", format_brl(total_recommended))
    with col4:
        st.metric("Impacto Total", f"-{format_brl(total_impact)}")

    st.divider()

    # ── Filters ──
    st.subheader("Filtros")
    col_f1, col_f2, col_f3 = st.columns(3)

    with col_f1:
        brands = sorted(set(r.brand for r in recommendations))
        selected_brands = st.multiselect(
            "Marca",
            brands,
            default=[],
            key="price_brand_filter",
        )

    with col_f2:
        min_days = st.number_input(
            "Dias Minimos em Estoque",
            min_value=0,
            value=0,
            step=10,
            key="price_min_days",
        )

    with col_f3:
        max_margin = st.number_input(
            "Margem Atual Maxima (%)",
            min_value=0.0,
            value=100.0,
            step=1.0,
            key="price_max_margin",
        )

    # Apply filters
    filtered = recommendations
    if selected_brands:
        filtered = [r for r in filtered if r.brand in selected_brands]
    if min_days > 0:
        filtered = [r for r in filtered if r.days_in_stock >= min_days]
    if max_margin < 100.0:
        filtered = [r for r in filtered if r.current_margin_percent <= max_margin]

    st.divider()

    # ── Recommendations Table ──
    st.subheader(f"Recomendacoes ({len(filtered)} veiculos)")

    if not filtered:
        st.info("Nenhuma recomendacao com os filtros aplicados.")
        return

    table_data = []
    for r in filtered:
        row = {
            "Marca": r.brand,
            "Modelo": r.model,
            "Ano": r.year_model,
            "Dias Estoque": r.days_in_stock,
            "Preco Atual": format_brl(r.current_price),
            "Preco Sugerido": format_brl(r.recommended_price),
            "Reducao": format_percent(r.reduction_percent),
            "Margem Atual": format_percent(r.current_margin_percent),
            "Margem Projetada": format_percent(r.projected_margin_percent),
            "FIPE": format_brl(r.fipe_price) if r.fipe_price else "-",
            "Justificativa": r.rationale,
        }
        table_data.append(row)

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Current Rules Display ──
    with st.expander("Regras de Reducao Atuais (config.yaml)"):
        for rule in config.app.price_reduction_rules:
            st.markdown(
                f"- **{rule.days_threshold}+ dias**: "
                f"Reducao de {rule.reduction_percent}% "
                f"(margem minima: {rule.min_margin_percent}%)"
            )

    # ── CSV Export ──
    render_csv_download(
        df,
        filename="recomendacoes_preco.csv",
        label="Exportar Recomendacoes",
    )
