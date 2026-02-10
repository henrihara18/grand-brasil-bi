"""Candidatos B2B page — B2B wholesale candidate scoring and ranking."""

from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st

from grand_brasil.analysis.b2b_scoring import identify_b2b_candidates, score_all_vehicles
from grand_brasil.config import Settings
from grand_brasil.dashboard.components.data_table import render_csv_download
from grand_brasil.models.vehicle import Vehicle
from grand_brasil.utils.currency import format_brl, format_percent


def render(vehicles: list[Vehicle], config: Settings) -> None:
    """Render the Candidatos B2B page.

    Shows:
    - Adjustable threshold slider
    - Summary: total candidates, avg score
    - Model concentration bar chart
    - Ranked table with score breakdown
    - CSV export

    Args:
        vehicles: Full list of vehicles in stock.
        config: Application configuration.
    """
    st.title("Candidatos B2B (Venda por Atacado)")

    if not vehicles:
        st.warning("Nenhum veiculo carregado. Faca upload de um arquivo na barra lateral.")
        return

    # ── Threshold Slider ──
    st.markdown(
        "Ajuste o limiar de pontuacao para identificar candidatos B2B. "
        "Veiculos acima deste valor sao sugeridos para venda por atacado."
    )

    threshold = st.slider(
        "Limiar de Pontuacao B2B",
        min_value=0.0,
        max_value=10.0,
        value=config.app.b2b_scoring.score_threshold,
        step=0.5,
        key="b2b_threshold",
    )

    # Score all vehicles
    all_scored = score_all_vehicles(
        vehicles, config.app.b2b_scoring, config.app.aging
    )

    # Filter by dynamic threshold
    candidates = [c for c in all_scored if c.score >= threshold]

    # ── Summary Metrics ──
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Candidatos", f"{len(candidates)}")
    with col2:
        avg_score = (
            sum(c.score for c in candidates) / len(candidates)
            if candidates
            else 0
        )
        st.metric("Score Medio", f"{avg_score:.1f}")
    with col3:
        st.metric("% do Estoque", format_percent(
            len(candidates) / len(vehicles) * 100 if vehicles else 0
        ))
    with col4:
        total_value = sum(c.asking_price for c in candidates)
        st.metric("Valor Total B2B", format_brl(total_value))

    st.divider()

    # ── Model Concentration Chart ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Concentracao por Modelo")
        model_counts = Counter(v.model_key for v in vehicles)
        # Show only models with > 1 unit
        concentrated = {
            k: v for k, v in model_counts.items() if v > 1
        }

        if concentrated:
            sorted_models = sorted(
                concentrated.items(), key=lambda x: x[1], reverse=True
            )
            fig = px.bar(
                x=[m[1] for m in sorted_models],
                y=[m[0] for m in sorted_models],
                orientation="h",
                labels={"x": "Quantidade", "y": "Modelo"},
                color=[m[1] for m in sorted_models],
                color_continuous_scale="Reds",
            )
            fig.update_layout(
                height=max(300, len(sorted_models) * 35 + 100),
                showlegend=False,
                coloraxis_showscale=False,
                margin=dict(t=20, b=20, l=200, r=20),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhum modelo com mais de 1 unidade em estoque.")

    with col_right:
        st.subheader("Composicao do Score")
        st.markdown(
            f"- **Envelhecimento**: peso {config.app.b2b_scoring.aging_weight:.0%}\n"
            f"- **Concentracao**: peso {config.app.b2b_scoring.concentration_weight:.0%}\n"
            f"- **Margem (inverso)**: peso {config.app.b2b_scoring.margin_weight:.0%}\n"
            f"- **Limiar configurado**: {config.app.b2b_scoring.score_threshold}\n"
            f"- **Limite concentracao**: {config.app.b2b_scoring.concentration_limit}+ unidades"
        )

        if candidates:
            # Score component averages
            avg_aging = sum(c.aging_score_component for c in candidates) / len(candidates)
            avg_conc = sum(c.concentration_score_component for c in candidates) / len(candidates)
            avg_margin = sum(c.margin_score_component for c in candidates) / len(candidates)

            fig = px.bar(
                x=[avg_aging, avg_conc, avg_margin],
                y=["Envelhecimento", "Concentracao", "Margem"],
                orientation="h",
                labels={"x": "Score Medio (0-10)", "y": "Componente"},
                color_discrete_sequence=["#e74c3c", "#e67e22", "#3498db"],
            )
            fig.update_layout(
                height=200,
                showlegend=False,
                margin=dict(t=20, b=20, l=120, r=20),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Candidates Table ──
    st.subheader(f"Ranking de Candidatos ({len(candidates)} veiculos)")

    if not candidates:
        st.info(
            f"Nenhum veiculo atingiu o limiar de {threshold:.1f}. "
            "Reduza o limiar no slider acima."
        )
        return

    table_data = []
    for i, c in enumerate(candidates, 1):
        table_data.append({
            "#": i,
            "Marca": c.brand,
            "Modelo": c.model,
            "Ano": c.year_model,
            "Dias Estoque": c.days_in_stock,
            "Score Total": f"{c.score:.1f}",
            "Score Envelh.": f"{c.aging_score_component:.1f}",
            "Score Conc.": f"{c.concentration_score_component:.1f}",
            "Score Margem": f"{c.margin_score_component:.1f}",
            "Unid. Modelo": c.same_model_count,
            "Preco": format_brl(c.asking_price),
            "Custo": format_brl(c.purchase_cost),
            "Justificativa": c.rationale,
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── CSV Export ──
    render_csv_download(
        df,
        filename="candidatos_b2b.csv",
        label="Exportar Candidatos B2B",
    )
