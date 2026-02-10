"""Grand Brasil BI — Main Streamlit application.

Entry point for the dashboard. Handles:
- Page configuration and custom CSS
- Sidebar navigation and file upload
- Routing to page modules
- Session state management
"""

import logging
from pathlib import Path

import streamlit as st

from grand_brasil.config import load_config
from grand_brasil.ingestion.ingestion_manager import IngestionManager

logger = logging.getLogger(__name__)

# ── Page Config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Grand Brasil - BI Estoque",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _load_css() -> None:
    """Load custom CSS theme."""
    css_path = Path(__file__).parent / "styles" / "theme.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def _show_welcome_page() -> None:
    """Show the welcome page when no data is loaded."""
    st.title("Grand Brasil - BI Estoque")
    st.markdown("---")

    st.markdown(
        """
        ### Bem-vindo ao sistema de Business Intelligence do Grand Brasil!

        **Como comecar:**
        1. Exporte o estoque do DealerUp em formato **CSV** ou **Excel**
        2. Use o botao **"Carregar dados do estoque"** na barra lateral
        3. O dashboard sera carregado automaticamente

        **Paginas disponiveis:**
        - **Visao Geral** — KPIs, distribuicao por marca, envelhecimento
        - **Envelhecimento** — Analise detalhada de tempo em estoque
        - **Reducao de Precos** — Sugestoes de reducao baseadas em regras configuraveis
        - **Candidatos B2B** — Pontuacao de veiculos para venda por atacado
        """
    )

    st.info(
        "As regras de negocio (faixas de envelhecimento, reducao de precos, "
        "pesos do B2B) podem ser ajustadas no arquivo **config.yaml**."
    )


def main() -> None:
    """Main application entry point."""
    _load_css()

    # ── Sidebar ──
    st.sidebar.title("Grand Brasil")
    st.sidebar.markdown("**Business Intelligence - Estoque**")
    st.sidebar.divider()

    # Navigation
    page = st.sidebar.radio(
        "Navegacao",
        [
            "Visao Geral",
            "Envelhecimento",
            "Reducao de Precos",
            "Candidatos B2B",
        ],
        index=0,
    )

    st.sidebar.divider()

    # File upload
    uploaded_file = st.sidebar.file_uploader(
        "Carregar dados do estoque",
        type=["csv", "xlsx", "xls"],
        help="Exporte o estoque do DealerUp em CSV ou Excel e faca upload aqui.",
    )

    # Load config
    config = load_config()

    # Process uploaded file
    if uploaded_file is not None:
        # Only re-process if file changed
        file_key = f"{uploaded_file.name}_{uploaded_file.size}"
        if st.session_state.get("_file_key") != file_key:
            try:
                with st.spinner("Processando arquivo..."):
                    manager = IngestionManager()
                    vehicles = manager.load_data(source=uploaded_file)

                st.session_state["vehicles"] = vehicles
                st.session_state["_file_key"] = file_key

                st.sidebar.success(
                    f"{len(vehicles)} veiculos carregados com sucesso!"
                )
            except Exception as e:
                st.sidebar.error(f"Erro ao processar arquivo: {e}")
                logger.exception("Error processing uploaded file")

    # ── Info in sidebar ──
    if "vehicles" in st.session_state:
        vehicles = st.session_state["vehicles"]
        st.sidebar.divider()
        st.sidebar.markdown(f"**Veiculos carregados:** {len(vehicles)}")

        from grand_brasil.models.enums import VehicleStatus
        in_stock = sum(1 for v in vehicles if v.status == VehicleStatus.IN_STOCK)
        st.sidebar.markdown(f"**Em estoque:** {in_stock}")
    else:
        _show_welcome_page()
        return

    # ── Route to page ──
    if page == "Visao Geral":
        from grand_brasil.dashboard.pages.visao_geral import render
        render(vehicles, config)
    elif page == "Envelhecimento":
        from grand_brasil.dashboard.pages.envelhecimento import render
        render(vehicles, config)
    elif page == "Reducao de Precos":
        from grand_brasil.dashboard.pages.reducao_precos import render
        render(vehicles, config)
    elif page == "Candidatos B2B":
        from grand_brasil.dashboard.pages.candidatos_b2b import render
        render(vehicles, config)


if __name__ == "__main__":
    main()
