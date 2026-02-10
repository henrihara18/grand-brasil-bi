"""Sortable, filterable data table components for Streamlit."""

import io
from decimal import Decimal

import pandas as pd
import streamlit as st

from grand_brasil.models.vehicle import Vehicle
from grand_brasil.utils.currency import format_brl, format_percent


def vehicles_to_dataframe(vehicles: list[Vehicle]) -> pd.DataFrame:
    """Convert a list of Vehicle models to a display-ready DataFrame.

    Args:
        vehicles: List of Vehicle instances.

    Returns:
        DataFrame with formatted columns for display.
    """
    rows = []
    for v in vehicles:
        rows.append({
            "Marca": v.brand,
            "Modelo": v.model,
            "Ano": v.year_model,
            "Cor": v.color or "-",
            "KM": f"{v.mileage:,}".replace(",", ".") if v.mileage else "-",
            "Dias Estoque": v.days_in_stock,
            "Preco Venda": format_brl(v.asking_price),
            "Custo": format_brl(v.purchase_cost),
            "Margem %": format_percent(v.margin_percent),
            "Status": v.status.value.capitalize(),
            "Filial": v.branch or "-",
        })
    return pd.DataFrame(rows)


def render_vehicle_table(
    vehicles: list[Vehicle],
    title: str = "Estoque de Veiculos",
    show_filters: bool = True,
) -> list[Vehicle]:
    """Render a filterable vehicle table.

    Args:
        vehicles: Vehicles to display.
        title: Table title.
        show_filters: Whether to show brand/status filters.

    Returns:
        Filtered list of vehicles (after applying user filters).
    """
    st.subheader(title)

    filtered = vehicles

    if show_filters and vehicles:
        col1, col2 = st.columns(2)

        with col1:
            brands = sorted(set(v.brand for v in vehicles))
            selected_brands = st.multiselect(
                "Filtrar por Marca",
                brands,
                default=[],
                key=f"brand_filter_{title}",
            )

        with col2:
            statuses = sorted(set(v.status.value for v in vehicles))
            selected_statuses = st.multiselect(
                "Filtrar por Status",
                statuses,
                default=[],
                key=f"status_filter_{title}",
            )

        if selected_brands:
            filtered = [v for v in filtered if v.brand in selected_brands]
        if selected_statuses:
            filtered = [v for v in filtered if v.status.value in selected_statuses]

    if not filtered:
        st.info("Nenhum veiculo encontrado com os filtros selecionados.")
        return filtered

    df = vehicles_to_dataframe(filtered)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(400, 35 * len(df) + 38),
    )

    return filtered


def render_csv_download(
    data: pd.DataFrame | list[dict],
    filename: str = "dados.csv",
    label: str = "Baixar CSV",
) -> None:
    """Render a CSV download button.

    Args:
        data: DataFrame or list of dicts to export.
        filename: Name of the downloaded file.
        label: Button label text.
    """
    if isinstance(data, list):
        df = pd.DataFrame(data)
    else:
        df = data

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, sep=";", decimal=",")

    st.download_button(
        label=f"📥 {label}",
        data=csv_buffer.getvalue(),
        file_name=filename,
        mime="text/csv",
    )
