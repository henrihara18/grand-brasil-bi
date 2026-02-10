"""Envelhecimento (Aging) page — heatmap, scatter plot, aged vehicle table."""

import pandas as pd
import streamlit as st

from grand_brasil.analysis.aging import analyze_aging_batch, aging_distribution
from grand_brasil.config import Settings
from grand_brasil.dashboard.components.aging_heatmap import (
    BRACKET_LABELS,
    render_aging_bar_chart,
    render_aging_scatter,
)
from grand_brasil.dashboard.components.data_table import render_csv_download
from grand_brasil.models.enums import AgingBracket
from grand_brasil.models.vehicle import Vehicle
from grand_brasil.utils.currency import format_brl


def render(vehicles: list[Vehicle], config: Settings) -> None:
    """Render the Envelhecimento (Aging) page.

    Shows:
    - Summary stats: avg age, oldest vehicle, count per bracket
    - Color-coded bar chart of aging distribution
    - Scatter plot: days in stock vs price
    - Filterable table of aged vehicles
    - CSV export

    Args:
        vehicles: Full list of vehicles in stock.
        config: Application configuration.
    """
    st.title("Analise de Envelhecimento")

    if not vehicles:
        st.warning("Nenhum veiculo carregado. Faca upload de um arquivo na barra lateral.")
        return

    aging_results = analyze_aging_batch(vehicles, config.app.aging)
    distribution = aging_distribution(aging_results)

    # ── Summary Metrics ──
    if aging_results:
        oldest = aging_results[0]  # Already sorted by days desc
        avg_days = sum(r.days_in_stock for r in aging_results) / len(aging_results)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Media de Dias", f"{avg_days:.0f}")
        with col2:
            st.metric("Veiculo Mais Antigo", f"{oldest.days_in_stock} dias")
        with col3:
            st.metric(
                "Mais Antigo",
                f"{oldest.brand} {oldest.model}",
            )
        with col4:
            st.metric(
                "Veiculos Criticos (90+d)",
                f"{distribution.get(AgingBracket.RED.value, 0)}",
            )

    st.divider()

    # ── Charts ──
    col_left, col_right = st.columns(2)

    with col_left:
        render_aging_bar_chart(distribution)

    with col_right:
        render_aging_scatter(aging_results)

    st.divider()

    # ── Filterable Table ──
    st.subheader("Detalhamento por Veiculo")

    # Bracket filter
    bracket_options = {
        "Todos": None,
        "Verde (0-30d)": AgingBracket.GREEN,
        "Amarelo (31-60d)": AgingBracket.YELLOW,
        "Laranja (61-90d)": AgingBracket.ORANGE,
        "Vermelho (90+d)": AgingBracket.RED,
    }

    selected = st.selectbox(
        "Filtrar por Faixa",
        list(bracket_options.keys()),
        index=0,
    )

    filtered_results = aging_results
    if bracket_options[selected] is not None:
        filtered_results = [
            r for r in aging_results
            if r.bracket == bracket_options[selected]
        ]

    if filtered_results:
        table_data = []
        for r in filtered_results:
            table_data.append({
                "Marca": r.brand,
                "Modelo": r.model,
                "Ano": r.year_model,
                "Dias Estoque": r.days_in_stock,
                "Faixa": BRACKET_LABELS.get(r.bracket.value, r.bracket.value),
                "Preco Venda": format_brl(r.asking_price),
                "Placa": r.plate or "-",
            })

        df = pd.DataFrame(table_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # CSV export
        render_csv_download(
            df,
            filename="envelhecimento_estoque.csv",
            label="Exportar Envelhecimento",
        )
    else:
        st.info("Nenhum veiculo na faixa selecionada.")
