"""Aging visualization components — treemap and scatter plot."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from grand_brasil.models.analysis import AgingResult
from grand_brasil.models.enums import AgingBracket


# Consistent color map for aging brackets
BRACKET_COLORS: dict[str, str] = {
    AgingBracket.GREEN.value: "#2ecc71",
    AgingBracket.YELLOW.value: "#f1c40f",
    AgingBracket.ORANGE.value: "#e67e22",
    AgingBracket.RED.value: "#e74c3c",
}

BRACKET_LABELS: dict[str, str] = {
    AgingBracket.GREEN.value: "Verde (0-30d)",
    AgingBracket.YELLOW.value: "Amarelo (31-60d)",
    AgingBracket.ORANGE.value: "Laranja (61-90d)",
    AgingBracket.RED.value: "Vermelho (90+d)",
}


def render_aging_pie_chart(distribution: dict[str, int]) -> None:
    """Render a pie chart showing the aging bracket distribution.

    Args:
        distribution: Dict of bracket value -> count.
    """
    labels = []
    values = []
    colors = []

    for bracket_val, count in distribution.items():
        if count > 0:
            labels.append(BRACKET_LABELS.get(bracket_val, bracket_val))
            values.append(count)
            colors.append(BRACKET_COLORS.get(bracket_val, "#95a5a6"))

    if not values:
        st.info("Nenhum veiculo para exibir.")
        return

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors),
                hole=0.4,
                textinfo="label+value+percent",
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title="Distribuicao por Faixa de Envelhecimento",
        showlegend=True,
        height=400,
        margin=dict(t=60, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_aging_scatter(results: list[AgingResult]) -> None:
    """Scatter plot: days_in_stock (x) vs asking_price (y), colored by bracket.

    Args:
        results: List of AgingResult from aging analysis.
    """
    if not results:
        st.info("Nenhum veiculo para exibir.")
        return

    data = {
        "Dias em Estoque": [r.days_in_stock for r in results],
        "Preco de Venda (R$)": [float(r.asking_price) for r in results],
        "Modelo": [f"{r.brand} {r.model}" for r in results],
        "Faixa": [BRACKET_LABELS.get(r.bracket.value, r.bracket.value) for r in results],
        "Cor": [BRACKET_COLORS.get(r.bracket.value, "#95a5a6") for r in results],
    }

    fig = px.scatter(
        data,
        x="Dias em Estoque",
        y="Preco de Venda (R$)",
        color="Faixa",
        hover_data=["Modelo"],
        color_discrete_map={
            label: color
            for label, color in zip(
                BRACKET_LABELS.values(), BRACKET_COLORS.values()
            )
        },
    )
    fig.update_layout(
        title="Envelhecimento vs Preco de Venda",
        xaxis_title="Dias em Estoque",
        yaxis_title="Preco de Venda (R$)",
        height=450,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_aging_bar_chart(distribution: dict[str, int]) -> None:
    """Horizontal bar chart showing count by aging bracket.

    Args:
        distribution: Dict of bracket value -> count.
    """
    labels = []
    values = []
    colors = []

    bracket_order = [
        AgingBracket.GREEN.value,
        AgingBracket.YELLOW.value,
        AgingBracket.ORANGE.value,
        AgingBracket.RED.value,
    ]

    for bracket_val in bracket_order:
        count = distribution.get(bracket_val, 0)
        labels.append(BRACKET_LABELS.get(bracket_val, bracket_val))
        values.append(count)
        colors.append(BRACKET_COLORS.get(bracket_val, "#95a5a6"))

    fig = go.Figure(
        data=[
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                marker_color=colors,
                text=values,
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title="Veiculos por Faixa de Envelhecimento",
        xaxis_title="Quantidade",
        height=300,
        margin=dict(t=60, b=20, l=150, r=40),
    )
    st.plotly_chart(fig, use_container_width=True)
