"""KPI metric card components for the Streamlit dashboard."""

from decimal import Decimal

import streamlit as st

from grand_brasil.utils.currency import format_brl, format_percent


def render_kpi_row(
    total_vehicles: int,
    total_value: Decimal,
    avg_margin: float,
    avg_days: float,
    vehicles_over_90: int = 0,
) -> None:
    """Render a row of KPI metric cards.

    Args:
        total_vehicles: Total number of vehicles in stock.
        total_value: Total asking price value of inventory.
        avg_margin: Average margin percentage across inventory.
        avg_days: Average days in stock.
        vehicles_over_90: Count of vehicles over 90 days.
    """
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            label="Total Veiculos",
            value=f"{total_vehicles}",
        )

    with col2:
        st.metric(
            label="Valor Estoque",
            value=format_brl(total_value),
        )

    with col3:
        st.metric(
            label="Margem Media",
            value=format_percent(avg_margin),
        )

    with col4:
        st.metric(
            label="Dias Medios Estoque",
            value=f"{avg_days:.0f} dias",
        )

    with col5:
        st.metric(
            label="Veiculos +90 dias",
            value=f"{vehicles_over_90}",
        )
