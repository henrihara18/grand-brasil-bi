"""Avaliacao (Trade-In Appraisal) page.

Flow from the user's perspective:
  1) Pick brand → model → year/version from the FIPE API catalog
  2) Inform KM, estimated repair cost, and whether the car is armored
  3) Click "Avaliar" → two anchors are displayed:

       PRIMARY — "Valor Sugerido de Compra"
         Comes from the buy-ratio engine (analysis/purchase_ratio.py).
         Based on what Grand Brasil actually paid for similar cars historically
         (appraisal database, UTILIZADO + AVALIADO with tiered weights).
         This is the number the appraiser should use for the trade.

       SECONDARY — "Validação cruzada com histórico de vendas"
         Loja and Revenda cards built from recent sales data (margin-based).
         Useful as a sanity check — divergence above 8% triggers a warning.

Data sources (loaded once per session, refreshed via "Atualizar dados"):
  • Sales history — load_sales_history (CSV/Excel or Google Sheets)
  • Appraisal history — load_appraisal_history (Excel or Google Sheets)
  • FIPE catalog & prices — FipeClient (live API, cached per brand/model/year)
  • WebMotors reference — optional, requires ScraperAPI key (standby)

Module layout:
  avaliacao.py           — this file: form, submit, orchestration (thin)
  _avaliacao/loaders.py  — all FIPE/sales/appraisal loaders + gdrive plumbing
  _avaliacao/result.py   — rendering of the full appraisal result
  _avaliacao/webmotors.py — Webmotors reference section
"""

from __future__ import annotations

import logging
from decimal import Decimal

import streamlit as st

from grand_brasil.analysis.appraisal import appraise
from grand_brasil.config import Settings
from grand_brasil.models.appraisal import AppraisalRequest
from grand_brasil.models.fipe import FipeBrand, FipeModel, FipeYear
from grand_brasil.utils.currency import format_brl
from grand_brasil.utils.fipe_matcher import find_comparables as fipe_find_comparables

from grand_brasil.dashboard.pages._avaliacao.loaders import (
    fetch_fipe_price,
    get_fipe_client,
    get_brand_year_profile,
    get_confidence_model,
    get_km_slope,
    get_year_profile,
    load_appraisal_data,
    load_fipe_brands,
    load_fipe_models,
    load_fipe_years,
    load_sales_data,
)
from grand_brasil.dashboard.pages._avaliacao.result import render_result
from grand_brasil.dashboard.pages._avaliacao.webmotors import render_webmotors

logger = logging.getLogger(__name__)


def render(config: Settings) -> None:
    """Render the Avaliacao (Appraisal) page."""
    st.title("Avaliacao de Troca")

    appraisal_cfg = config.app.appraisal

    # ── Top bar: info + reload button ──
    col_info, col_btn = st.columns([6, 1])
    with col_btn:
        if st.button(
            "🔄 Atualizar dados",
            help="Recarrega historico de vendas E base de avaliacoes (Google Sheets ou Excel local)",
        ):
            for key in (
                "sales_history_df",
                "appraisal_df",
                "appraisal_year_profile",
                "appraisal_result",
            ):
                st.session_state.pop(key, None)
            st.rerun()

    # ── Load data ──
    if "sales_history_df" not in st.session_state:
        sales_df = load_sales_data(config)
        if sales_df is None:
            return
    else:
        sales_df = st.session_state["sales_history_df"]

    br_cfg = appraisal_cfg.buy_ratio
    status_weights = {
        "UTILIZADO": br_cfg.utilizado_weight,
        "REPASSE": br_cfg.repasse_weight,
        "AVALIADO": br_cfg.avaliado_weight,
    }
    appraisal_df = load_appraisal_data(status_weights, config)
    appraisal_year_profile = get_year_profile(appraisal_df)
    appraisal_km_slope = get_km_slope(appraisal_df, config)
    appraisal_brand_profile = get_brand_year_profile(appraisal_df, config)
    confidence_model = get_confidence_model(config)

    with col_info:
        caption = f"✅ {len(sales_df):,} vendas carregadas"
        if appraisal_df is not None:
            caption += f" | {len(appraisal_df):,} avaliações UTILIZADO"
        caption += "."
        st.caption(caption)

    # ── FIPE form ──
    fipe_client = get_fipe_client()
    selected_brand, selected_model, selected_year, fipe_price_data = _render_fipe_form(
        fipe_client
    )

    # ── Vehicle details ──
    km, repair_cost, blindado, purpose = _render_vehicle_details()

    # ── Submit button ──
    historico_ausente = len(sales_df) == 0
    avaliar_btn = st.button(
        "Avaliar Veiculo",
        type="primary",
        use_container_width=True,
        disabled=(fipe_price_data is None),
        help=(
            "Carregue o historico de vendas para incluir comparaveis na analise."
            if historico_ausente else None
        ),
    )

    # ── Invalidate stale result if selection changed ──
    _invalidate_stale_result(selected_brand, selected_model, blindado, purpose)

    # ── Run appraisal ──
    if avaliar_btn and fipe_price_data and selected_brand and selected_model and selected_year:
        _run_appraisal(
            selected_brand=selected_brand,
            selected_model=selected_model,
            selected_year=selected_year,
            fipe_price_data=fipe_price_data,
            km=km,
            repair_cost=repair_cost,
            blindado=blindado,
            purpose=purpose,
            sales_df=sales_df,
            appraisal_df=appraisal_df,
            appraisal_year_profile=appraisal_year_profile,
            appraisal_cfg=appraisal_cfg,
            fipe_client=fipe_client,
            km_slope=appraisal_km_slope,
            brand_year_profile=appraisal_brand_profile,
            confidence_model=confidence_model,
        )

    # ── Display result ──
    if "appraisal_result" in st.session_state:
        result = st.session_state["appraisal_result"]
        st.divider()
        render_result(result)

        if "wm_search_params" in st.session_state:
            st.divider()
            render_webmotors(st.session_state["wm_search_params"])


# ── Form helpers ────────────────────────────────────────────────────────────


def _render_fipe_form(
    fipe_client,
) -> tuple["FipeBrand | None", "FipeModel | None", "FipeYear | None", object | None]:
    """Render the brand/model/year cascading selectors and fetch the FIPE price.

    Returns (brand, model, year, price_data). Any field that isn't selected
    yet comes back as None.
    """
    st.divider()
    st.subheader("Identificacao do Veiculo (FIPE)")

    col1, col2 = st.columns(2)

    selected_brand: FipeBrand | None = None
    with col1:
        brands = load_fipe_brands(fipe_client)
        brand_names = [b.name for b in brands]
        brand_idx = st.selectbox(
            "Marca FIPE",
            options=range(len(brand_names)),
            format_func=lambda i: brand_names[i],
            index=None,
            placeholder="Selecione a marca...",
            key="fipe_brand_idx",
        )
        if brand_idx is not None:
            selected_brand = brands[brand_idx]

    selected_model: FipeModel | None = None
    with col2:
        if selected_brand:
            models = load_fipe_models(fipe_client, selected_brand.code)
            model_names = [m.name for m in models]
            model_idx = st.selectbox(
                "Modelo FIPE",
                options=range(len(model_names)),
                format_func=lambda i: model_names[i],
                index=None,
                placeholder="Selecione o modelo...",
                key=f"fipe_model_idx_{selected_brand.code}",
            )
            if model_idx is not None:
                selected_model = models[model_idx]
        else:
            st.selectbox(
                "Modelo FIPE", options=[],
                placeholder="Selecione a marca primeiro...", disabled=True,
            )

    selected_year: FipeYear | None = None
    if selected_brand and selected_model:
        years = load_fipe_years(fipe_client, selected_brand.code, selected_model.code)
        if years:
            year_names = [y.name for y in years]
            year_idx = st.selectbox(
                "Ano / Versao",
                options=range(len(year_names)),
                format_func=lambda i: year_names[i],
                index=None,
                placeholder="Selecione o ano e versao...",
                key=f"fipe_year_idx_{selected_brand.code}_{selected_model.code}",
            )
            if year_idx is not None:
                selected_year = years[year_idx]
        else:
            st.warning("Nenhum ano disponivel para este modelo.")

    fipe_price_data = None
    if selected_brand and selected_model and selected_year:
        fipe_price_data = fetch_fipe_price(
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

    return selected_brand, selected_model, selected_year, fipe_price_data


def _render_vehicle_details() -> tuple[int, int, bool, str]:
    """Render KM / repair cost / blindado / finalidade inputs.

    Returns (km, repair_cost, blindado, purpose).
    """
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

    col5, col6 = st.columns(2)
    with col5:
        purpose_label = st.radio(
            "Finalidade",
            options=["Automatico", "Loja (B2C)", "Revenda (B2B)"],
            horizontal=True,
            help=(
                "Automatico: usa P(Revenda) para misturar Loja/Revenda. "
                "Selecione um canal especifico para forcar."
            ),
        )
        purpose_map = {
            "Automatico": "auto",
            "Loja (B2C)": "loja",
            "Revenda (B2B)": "revenda",
        }
        purpose = purpose_map[purpose_label]
    with col6:
        blindado = st.checkbox(
            "🛡️ Veiculo Blindado",
            value=False,
            help=(
                "Marque se o veiculo possui blindagem. Adiciona um premio ao "
                "preco estimado de venda Loja e Revenda."
            ),
        )
    st.markdown("")
    return km, repair_cost, blindado, purpose


def _invalidate_stale_result(
    selected_brand: FipeBrand | None,
    selected_model: FipeModel | None,
    blindado: bool,
    purpose: str,
) -> None:
    """Drop the cached result if any dropdown/blindado/purpose changed since last run."""
    current_selection = (
        st.session_state.get("fipe_brand_idx"),
        st.session_state.get(
            f"fipe_model_idx_{selected_brand.code}" if selected_brand else "_"
        ),
        st.session_state.get(
            f"fipe_year_idx_{selected_brand.code}_{selected_model.code}"
            if selected_brand and selected_model
            else "_"
        ),
        blindado,
        purpose,
    )
    if st.session_state.get("_fipe_last_selection") != current_selection:
        st.session_state.pop("appraisal_result", None)
        st.session_state["_fipe_last_selection"] = current_selection


def _run_appraisal(
    *,
    selected_brand: FipeBrand,
    selected_model: FipeModel,
    selected_year: FipeYear,
    fipe_price_data,
    km: int,
    repair_cost: int,
    blindado: bool,
    purpose: str,
    sales_df,
    appraisal_df,
    appraisal_year_profile,
    appraisal_cfg,
    fipe_client,
    km_slope=None,
    brand_year_profile=None,
    confidence_model=None,
) -> None:
    """Build the AppraisalRequest, run appraise(), store the result in session state."""
    year_model_int = selected_year.year_int

    # Cross-reference FIPE selection against DealerUp history to pick brand/model keys
    with st.spinner("Buscando vendas comparaveis..."):
        comp_df = fipe_find_comparables(
            fipe_brand=selected_brand.name,
            fipe_model=selected_model.name,
            year_model=year_model_int,
            sales_df=sales_df,
            year_tolerance=appraisal_cfg.year_tolerance,
        )

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
        blindado=blindado,
        purpose=purpose,
    )

    with st.spinner("Calculando avaliacao (buscando FIPE historica)..."):
        result = appraise(
            request=request,
            sales_df=sales_df,
            year_tolerance=appraisal_cfg.year_tolerance,
            loja_target_margin=appraisal_cfg.loja_target_margin,
            revenda_target_margin=appraisal_cfg.revenda_target_margin,
            min_comparables=appraisal_cfg.min_comparables,
            recency_halflife_days=appraisal_cfg.recency_halflife_days,
            year_pct_per_year=appraisal_cfg.year_pct_per_year,
            fipe_client=fipe_client,
            fipe_brand_code=selected_brand.code,
            fipe_model_code=selected_model.code,
            fipe_year_code=selected_year.code,
            appraisal_df=appraisal_df,
            year_profile=appraisal_year_profile,
            appraisal_config=appraisal_cfg,
            km_slope=km_slope,
            brand_year_profile=brand_year_profile,
            confidence_model=confidence_model,
        )

    st.session_state["appraisal_result"] = result
    # Store FIPE price separately for the feedback log (not on the suggestion)
    st.session_state["appraisal_fipe_price"] = float(fipe_price_data.value)
    # Webmotors params (used 24h cache downstream)
    wm_model = selected_model.name.split()[0].strip("()")
    st.session_state["wm_search_params"] = {
        "brand": selected_brand.name,
        "model": wm_model,
        "year_model": year_model_int,
        "km": km,
    }
