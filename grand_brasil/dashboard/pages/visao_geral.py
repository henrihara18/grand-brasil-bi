"""Visao Geral (Overview) page — KPIs, brand distribution, aging pie chart."""

import plotly.express as px
import streamlit as st

from grand_brasil.analysis.aging import analyze_aging_batch, aging_distribution
from grand_brasil.analysis.b2b_scoring import identify_b2b_candidates
from grand_brasil.analysis.inventory_summary import compute_summary
from grand_brasil.config import Settings
from grand_brasil.dashboard.components.aging_heatmap import render_aging_pie_chart
from grand_brasil.dashboard.components.data_table import render_vehicle_table
from grand_brasil.dashboard.components.metric_cards import render_kpi_row
from grand_brasil.models.vehicle import Vehicle


def render(vehicles: list[Vehicle], config: Settings) -> None:
    """Render the Visao Geral (Overview) page.

    Shows:
    - KPI cards: total vehicles, stock value, average margin, avg days, 90+ count
    - Aging bracket pie chart
    - Brand distribution bar chart
    - Full sortable inventory table

    Args:
        vehicles: Full list of vehicles in stock.
        config: Application configuration.
    """
    st.title("Visao Geral do Estoque")

    if not vehicles:
        st.warning("Nenhum veiculo carregado. Faca upload de um arquivo na barra lateral.")
        return

    # Run analysis
    aging_results = analyze_aging_batch(vehicles, config.app.aging)
    distribution = aging_distribution(aging_results)
    b2b_candidates = identify_b2b_candidates(
        vehicles, config.app.b2b_scoring, config.app.aging
    )
    summary = compute_summary(vehicles, aging_results, len(b2b_candidates))

    # ── KPI Cards ──
    render_kpi_row(
        total_vehicles=summary.total_vehicles,
        total_value=summary.total_stock_value,
        avg_margin=summary.average_margin_percent,
        avg_days=summary.average_days_in_stock,
        vehicles_over_90=summary.vehicles_over_90_days,
    )

    st.divider()

    # ── Charts Row ──
    col_left, col_right = st.columns(2)

    with col_left:
        render_aging_pie_chart(distribution)

    with col_right:
        # Brand distribution bar chart
        if summary.count_by_brand:
            sorted_brands = sorted(
                summary.count_by_brand.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            brands = [b[0] for b in sorted_brands]
            counts = [b[1] for b in sorted_brands]

            fig = px.bar(
                x=counts,
                y=brands,
                orientation="h",
                labels={"x": "Quantidade", "y": "Marca"},
                title="Distribuicao por Marca",
                color=counts,
                color_continuous_scale="Blues",
            )
            fig.update_layout(
                height=400,
                showlegend=False,
                coloraxis_showscale=False,
                margin=dict(t=60, b=20, l=120, r=20),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Inventory Table ──
    render_vehicle_table(vehicles, title="Estoque Completo")
