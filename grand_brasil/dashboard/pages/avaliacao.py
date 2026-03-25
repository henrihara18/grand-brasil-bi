"""Avaliacao (Trade-In Appraisal) page — suggest trade values for cars being appraised.

The user selects brand → model → year/version from the FIPE API catalog.
The FIPE price is auto-fetched and used as the primary pricing anchor.
Historical DealerUp sales are cross-referenced for KM adjustment and market context.
"""

import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from grand_brasil.analysis.appraisal import appraise
from grand_brasil.config import Settings
from grand_brasil.ingestion.fipe_client import FipeApiError, FipeClient
from grand_brasil.ingestion.sales_history import load_sales_history
from grand_brasil.models.appraisal import AppraisalRequest
from grand_brasil.models.fipe import FipeBrand, FipeModel, FipeYear
from grand_brasil.utils.currency import format_brl
from grand_brasil.utils.fipe_matcher import find_comparables as fipe_find_comparables

logger = logging.getLogger(__name__)


def render(config: Settings) -> None:
    """Render the Avaliacao (Appraisal) page."""
    st.title("Avaliacao de Troca")
    st.markdown(
        "Selecione o veiculo pela tabela FIPE para obter uma sugestao de valor de troca "
        "baseada no preco FIPE e no historico de vendas."
    )

    # ── Load sales history ──
    sales_df = _load_sales_data(config)
    if sales_df is None:
        return

    appraisal_cfg = config.app.appraisal

    # ── FIPE Client ──
    fipe_client = _get_fipe_client()

    # ── FIPE Identification Form ──
    st.divider()
    st.subheader("Identificacao do Veiculo (FIPE)")

    col1, col2 = st.columns(2)

    # Brand selection
    with col1:
        brands = _load_fipe_brands(fipe_client)
        brand_names = [b.name for b in brands]
        brand_key = "fipe_brand_idx"
        brand_idx = st.selectbox(
            "Marca FIPE",
            options=range(len(brand_names)),
            format_func=lambda i: brand_names[i],
            index=None,
            placeholder="Selecione a marca...",
            key=brand_key,
        )
        selected_brand: FipeBrand | None = brands[brand_idx] if brand_idx is not None else None

    # Model selection
    with col2:
        selected_model: FipeModel | None = None
        if selected_brand:
            models = _load_fipe_models(fipe_client, selected_brand.code)
            model_names = [m.name for m in models]
            model_key = f"fipe_model_idx_{selected_brand.code}"
            model_idx = st.selectbox(
                "Modelo FIPE",
                options=range(len(model_names)),
                format_func=lambda i: model_names[i],
                index=None,
                placeholder="Selecione o modelo...",
                key=model_key,
            )
            selected_model = models[model_idx] if model_idx is not None else None
        else:
            st.selectbox(
                "Modelo FIPE", options=[], placeholder="Selecione a marca primeiro...", disabled=True
            )

    # Year/version selection
    selected_year: FipeYear | None = None
    if selected_brand and selected_model:
        years = _load_fipe_years(fipe_client, selected_brand.code, selected_model.code)
        if years:
            year_names = [y.name for y in years]
            year_key = f"fipe_year_idx_{selected_brand.code}_{selected_model.code}"
            year_idx = st.selectbox(
                "Ano / Versao",
                options=range(len(year_names)),
                format_func=lambda i: year_names[i],
                index=None,
                placeholder="Selecione o ano e versao...",
                key=year_key,
            )
            selected_year = years[year_idx] if year_idx is not None else None
        else:
            st.warning("Nenhum ano disponivel para este modelo.")

    # FIPE price auto-fetch
    fipe_price_data = None
    if selected_brand and selected_model and selected_year:
        fipe_price_data = _fetch_fipe_price(
            fipe_client,
            selected_brand.code,
            selected_model.code,
            selected_year.code,
        )
        if fipe_price_data:
            col_val, col_ref = st.columns([2, 1])
            with col_val:
                st.metric(
                    "Valor FIPE",
                    format_brl(fipe_price_data.value),
                    help=f"Codigo FIPE: {fipe_price_data.fipe_code} | {fipe_price_data.fuel}",
                )
            with col_ref:
                st.caption(f"Referencia: {fipe_price_data.reference_month}")

    # ── Vehicle details ──
    st.divider()
    st.subheader("Dados do Veiculo")

    col3, col4 = st.columns(2)
    with col3:
        km = st.number_input(
            "Quilometragem (KM)",
            min_value=0,
            max_value=500_000,
            value=50_000,
            step=5_000,
        )
    with col4:
        repair_cost = st.number_input(
            "Custo Estimado de Reparo (R$)",
            min_value=0,
            max_value=100_000,
            value=0,
            step=500,
            help="Valor estimado para consertar problemas do veiculo.",
        )

    st.markdown("")
    avaliar_btn = st.button(
        "Avaliar Veiculo",
        type="primary",
        use_container_width=True,
        disabled=(fipe_price_data is None),
    )

    # ── Stale result invalidation ──
    current_selection = (
        st.session_state.get("fipe_brand_idx"),
        st.session_state.get(f"fipe_model_idx_{selected_brand.code}" if selected_brand else "_"),
        st.session_state.get(
            f"fipe_year_idx_{selected_brand.code}_{selected_model.code}"
            if selected_brand and selected_model
            else "_"
        ),
    )
    if st.session_state.get("_fipe_last_selection") != current_selection:
        st.session_state.pop("appraisal_result", None)
        st.session_state["_fipe_last_selection"] = current_selection

    # ── Run Appraisal ──
    if avaliar_btn and fipe_price_data and selected_brand and selected_model and selected_year:
        year_model_int = selected_year.year_int

        # Cross-reference FIPE selection against DealerUp history
        with st.spinner("Buscando vendas comparaveis..."):
            comp_df = fipe_find_comparables(
                fipe_brand=selected_brand.name,
                fipe_model=selected_model.name,
                year_model=year_model_int,
                sales_df=sales_df,
                year_tolerance=appraisal_cfg.year_tolerance,
            )

        # Derive DealerUp brand/model keys from matches (or fall back to FIPE names)
        if len(comp_df) > 0:
            req_brand = str(comp_df["brand"].value_counts().index[0])
            req_model_red = str(comp_df["model_red"].value_counts().index[0])
        else:
            req_brand = selected_brand.name.upper()
            req_model_red = f"{selected_brand.name.upper()} {selected_model.name}"

        request = AppraisalRequest(
            brand=req_brand,
            model_red=req_model_red,
            model_trim=None,
            year_model=year_model_int,
            km=km,
            estimated_repair_cost=Decimal(str(repair_cost)),
            fipe_price=fipe_price_data.value,
            fipe_code=fipe_price_data.fipe_code,
            fipe_reference_month=fipe_price_data.reference_month,
            fipe_model_name=selected_model.name,
        )

        with st.spinner("Calculando avaliacao..."):
            result = appraise(
                request=request,
                sales_df=sales_df,
                year_tolerance=appraisal_cfg.year_tolerance,
                loja_target_margin=appraisal_cfg.loja_target_margin,
                revenda_target_margin=appraisal_cfg.revenda_target_margin,
                min_comparables=appraisal_cfg.min_comparables,
                km_pct_per_10k=appraisal_cfg.km_pct_per_10k,
                recency_halflife_days=appraisal_cfg.recency_halflife_days,
                year_pct_per_year=appraisal_cfg.year_pct_per_year,
            )

        st.session_state["appraisal_result"] = result

    # ── Display Result ──
    if "appraisal_result" in st.session_state:
        result = st.session_state["appraisal_result"]
        st.divider()
        _render_result(result)


# ── FIPE client helpers ──────────────────────────────────────────────────────

def _get_fipe_client() -> FipeClient:
    if "_fipe_client" not in st.session_state:
        st.session_state["_fipe_client"] = FipeClient()
    return st.session_state["_fipe_client"]


def _load_fipe_brands(client: FipeClient) -> list[FipeBrand]:
    key = "_fipe_brands"
    if key not in st.session_state:
        try:
            with st.spinner("Carregando marcas FIPE..."):
                st.session_state[key] = client.get_brands()
        except FipeApiError as e:
            st.error(f"Erro ao carregar marcas FIPE: {e}")
            return []
    return st.session_state[key]


def _load_fipe_models(client: FipeClient, brand_code: str) -> list[FipeModel]:
    key = f"_fipe_models_{brand_code}"
    if key not in st.session_state:
        try:
            with st.spinner("Carregando modelos..."):
                st.session_state[key] = client.get_models(brand_code)
        except FipeApiError as e:
            st.error(f"Erro ao carregar modelos FIPE: {e}")
            return []
    return st.session_state[key]


def _load_fipe_years(client: FipeClient, brand_code: str, model_code: str) -> list[FipeYear]:
    key = f"_fipe_years_{brand_code}_{model_code}"
    if key not in st.session_state:
        try:
            with st.spinner("Carregando anos/versoes..."):
                st.session_state[key] = client.get_years(brand_code, model_code)
        except FipeApiError as e:
            st.error(f"Erro ao carregar anos FIPE: {e}")
            return []
    return st.session_state[key]


def _fetch_fipe_price(client: FipeClient, brand_code: str, model_code: str, year_code: str):
    key = f"_fipe_price_{brand_code}_{model_code}_{year_code}"
    if key not in st.session_state:
        try:
            with st.spinner("Consultando valor FIPE..."):
                st.session_state[key] = client.get_price(brand_code, model_code, year_code)
        except FipeApiError as e:
            st.error(f"Erro ao consultar preco FIPE: {e}")
            return None
    return st.session_state[key]


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_sales_data(config: Settings) -> pd.DataFrame | None:
    """Load sales history from Google Drive URL (cloud) or local file (dev)."""
    if "sales_history_df" in st.session_state:
        return st.session_state["sales_history_df"]

    url: str | None = None
    try:
        url = st.secrets.get("SALES_HISTORY_URL")
    except Exception:
        pass

    if url:
        try:
            with st.spinner("Carregando historico de vendas..."):
                df = _load_from_gdrive(url)
                st.session_state["sales_history_df"] = df
                return df
        except Exception as e:
            st.error(f"Erro ao carregar historico do Google Drive: {e}")
            logger.exception("Failed to load sales history from Google Drive URL")
            return None

    sales_file = config.app.appraisal.sales_history_file
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    file_path = project_root / sales_file

    if not file_path.exists():
        st.error(
            f"Arquivo de historico nao encontrado: **{sales_file}**. "
            "Configure **SALES_HISTORY_URL** nos secrets do Streamlit ou "
            "verifique o caminho em config.yaml."
        )
        return None

    try:
        with st.spinner("Carregando historico de vendas..."):
            df = load_sales_history(file_path)
            st.session_state["sales_history_df"] = df
            return df
    except Exception as e:
        st.error(f"Erro ao carregar historico: {e}")
        logger.exception("Failed to load sales history")
        return None


def _load_from_gdrive(url: str) -> pd.DataFrame:
    """Download Excel from a Google Sheets shareable link."""
    import io
    import os
    import re
    import tempfile

    import requests

    sheets_match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if sheets_match:
        sheet_id = sheets_match.group(1)
        download_url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        )
        response = requests.get(download_url, timeout=60)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        try:
            return load_sales_history(Path(tmp_path))
        finally:
            os.unlink(tmp_path)

    raise ValueError(
        "URL invalida. Use o link de compartilhamento do Google Sheets "
        "(docs.google.com/spreadsheets/d/...)."
    )


# ── Result rendering ─────────────────────────────────────────────────────────

def _render_result(result) -> None:
    """Render the appraisal result with cards, charts, and comparables table."""

    # ── FIPE anchor banner ──
    display_name = result.fipe_model_name or result.model_trim or result.model_red
    st.subheader(f"Resultado: {display_name} {result.year_model}")

    if result.fipe_used_as_anchor:
        ref = f" — referencia {result.fipe_reference_month}" if result.fipe_reference_month else ""
        code = f" (cod. {result.fipe_code})" if result.fipe_code else ""
        st.info(
            f"Calculo baseado no **valor FIPE**{code}{ref}. "
            "Vendas historicas usadas para ajuste de KM e contexto de mercado."
        )
        if result.fipe_historical_spread_pct is not None:
            spread_pct = result.fipe_historical_spread_pct * 100
            direction = "acima" if spread_pct >= 0 else "abaixo"
            st.caption(
                f"Historico de vendas comparaveis: {abs(spread_pct):.1f}% {direction} da FIPE "
                f"({result.total_comparables} vendas encontradas)"
            )
    else:
        # Historical mode
        if result.used_trim_level:
            st.caption(f"Comparacao por versao especifica: **{result.model_trim}**")
        elif result.model_trim:
            st.caption(
                f"Versao {result.model_trim} com poucos dados — "
                f"usando modelo geral: **{result.model_red}**"
            )

    # ── Confidence badge ──
    confidence_colors = {"alta": "green", "media": "orange", "baixa": "red", "sem dados": "red"}
    color = confidence_colors.get(result.confidence, "gray")
    outlier_text = f" | {result.outliers_removed} outlier(s) removido(s)" if result.outliers_removed > 0 else ""
    st.markdown(
        f"**Confianca:** :{color}[{result.confidence.upper()}] "
        f"({result.total_comparables} vendas comparaveis{outlier_text})"
    )

    if result.total_comparables == 0 and not result.fipe_used_as_anchor:
        st.warning(result.rationale)
        return

    # ── Value Cards ──
    col_loja, col_revenda = st.columns(2)

    with col_loja:
        st.markdown("### Loja (B2C)")
        if result.loja_max_trade_value is not None:
            st.metric("Valor Maximo de Troca", format_brl(result.loja_max_trade_value))
            details = f"Preco estimado: {format_brl(result.loja_estimated_sale_price)} | Margem: {result.loja_target_margin_percent}%"
            if result.loja_avg_days_in_stock:
                details += f" | Media estoque: {result.loja_avg_days_in_stock:.0f} dias"
            if result.loja_comparables_count:
                details += f" | {result.loja_comparables_count} comparaveis"
            st.caption(details)
        else:
            st.info("Sem vendas Loja comparaveis.")

    with col_revenda:
        st.markdown("### Revenda (B2B)")
        if result.revenda_max_trade_value is not None:
            st.metric("Valor Maximo de Troca", format_brl(result.revenda_max_trade_value))
            details = f"Preco estimado: {format_brl(result.revenda_estimated_sale_price)} | Margem: {result.revenda_target_margin_percent}%"
            if result.revenda_avg_days_in_stock:
                details += f" | Media estoque: {result.revenda_avg_days_in_stock:.0f} dias"
            if result.revenda_comparables_count:
                details += f" | {result.revenda_comparables_count} comparaveis"
            st.caption(details)
        else:
            st.info("Sem vendas Revenda comparaveis.")

    if result.estimated_repair_cost > 0:
        st.info(
            f"Custo de reparo de {format_brl(result.estimated_repair_cost)} "
            "ja descontado dos valores acima."
        )

    # ── KM Adjustment ──
    if result.km_adjustment_pct is not None and result.comparables_median_km is not None:
        pct = result.km_adjustment_pct * 100
        car_km = result.km or 0
        delta_km = result.comparables_median_km - car_km
        direction = "a menos" if delta_km > 0 else "a mais"
        sign = "+" if pct >= 0 else ""
        st.info(
            f"**Ajuste de KM:** {sign}{pct:.1f}% aplicado  "
            f"(seu veiculo tem **{abs(delta_km):,} km {direction}** "
            f"que a mediana dos comparaveis: {result.comparables_median_km:,} km)"
        )

    # ── Comparables Chart ──
    if result.loja_comparables or result.revenda_comparables:
        st.divider()
        _render_comparables_chart(result)
        st.divider()
        _render_comparables_table(result)

    # ── Details expander ──
    with st.expander("Detalhes da Analise"):
        st.markdown(result.rationale)
        if result.year_range_used:
            st.markdown(f"**Faixa de ano utilizada:** {result.year_range_used}")
        modo = "FIPE como ancora" if result.fipe_used_as_anchor else (
            "Mediana ponderada por recencia" if result.used_weighted_median else "Mediana simples"
        )
        st.markdown(f"**Modo de calculo:** {modo}")
        st.markdown(
            f"**Configuracao:** Margem Loja: {result.loja_target_margin_percent}% | "
            f"Margem Revenda: {result.revenda_target_margin_percent}%"
        )


def _render_comparables_chart(result) -> None:
    """Render a scatter chart of comparable sales."""
    all_comps = result.loja_comparables + result.revenda_comparables
    if not all_comps:
        return

    st.subheader("Distribuicao dos Comparaveis")
    data = [
        {
            "Preco Venda": float(c.sale_price),
            "Custo": float(c.purchase_cost),
            "Ano": c.year_model,
            "KM": c.km if c.km else 0,
            "Dias Estoque": c.days_in_stock,
            "Canal": c.sale_channel,
            "Margem %": c.margin_percent,
        }
        for c in all_comps
    ]
    df = pd.DataFrame(data)

    fig = px.scatter(
        df,
        x="Ano",
        y="Preco Venda",
        color="Canal",
        size="Dias Estoque",
        hover_data=["Custo", "KM", "Margem %"],
        color_discrete_map={"Loja": "#2196F3", "Revenda": "#FF9800"},
        labels={"Preco Venda": "Preco de Venda (R$)", "Ano": "Ano Modelo"},
        title="Vendas Comparaveis por Ano e Preco",
    )
    if result.loja_max_trade_value:
        fig.add_hline(
            y=float(result.loja_max_trade_value),
            line_dash="dash",
            line_color="#2196F3",
            annotation_text=f"Troca Loja: {format_brl(result.loja_max_trade_value)}",
            annotation_position="top left",
        )
    if result.revenda_max_trade_value:
        fig.add_hline(
            y=float(result.revenda_max_trade_value),
            line_dash="dash",
            line_color="#FF9800",
            annotation_text=f"Troca Revenda: {format_brl(result.revenda_max_trade_value)}",
            annotation_position="bottom left",
        )
    fig.update_layout(height=450, margin=dict(t=60, b=20))
    st.plotly_chart(fig, use_container_width=True)


def _render_comparables_table(result) -> None:
    """Render a table of all comparables used."""
    all_comps = result.loja_comparables + result.revenda_comparables
    if not all_comps:
        return

    with st.expander(f"Tabela de Comparaveis ({len(all_comps)} vendas)", expanded=False):
        data = [
            {
                "Canal": c.sale_channel,
                "Ano": c.year_model,
                "KM": f"{c.km:,}".replace(",", ".") if c.km else "-",
                "Preco Venda": format_brl(c.sale_price),
                "Custo": format_brl(c.purchase_cost),
                "Custo Ajust.": format_brl(c.adjusted_cost),
                "Margem %": f"{c.margin_percent:.1f}%",
                "Dias Estoque": c.days_in_stock,
            }
            for c in all_comps
        ]
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
