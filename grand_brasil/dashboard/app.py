"""Grand Brasil - Avaliacao de Troca.

Dashboard focado em avaliacao de veiculos para troca.
"""

import logging
from pathlib import Path

import streamlit as st

from grand_brasil.config import load_config

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Grand Brasil - Avaliacao de Troca",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _load_css() -> None:
    css_path = Path(__file__).parent / "styles" / "theme.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def _check_password() -> bool:
    """Show password gate if APP_PASSWORD is configured in secrets."""
    try:
        correct_password = st.secrets.get("APP_PASSWORD")
    except Exception:
        correct_password = None

    # No password configured → allow access (local dev without secrets)
    if not correct_password:
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("Grand Brasil - Avaliacao de Troca")
    st.markdown("---")

    col, _ = st.columns([1, 2])
    with col:
        password = st.text_input("Senha de acesso", type="password")
        if st.button("Entrar", use_container_width=True):
            if password == correct_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Senha incorreta.")

    return False


def main() -> None:
    _load_css()

    if not _check_password():
        return

    config = load_config()

    from grand_brasil.dashboard.pages.avaliacao import render as render_avaliacao
    render_avaliacao(config)


if __name__ == "__main__":
    main()
