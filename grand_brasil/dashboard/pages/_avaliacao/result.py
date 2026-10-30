"""Result rendering for the Avaliacao page.

Displays the full appraisal output, structured top-to-bottom as:

  1. Header (model + year)
  2. PRIMARY anchor — buy-ratio card (if available)
  3. FIPE info + historical spreads (contextual)
  4. Confidence badge
  5. SECONDARY — Loja / Revenda cards (validation)
  6. Blindado notice
  7. KM adjustment details
  8. Comparables chart + table
  9. Details expander (rationale, config)
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from grand_brasil.dashboard.pages._avaliacao.feedback import render_feedback_form
from grand_brasil.utils.currency import format_brl


def render_result(result) -> None:
    """Entry-point for the result section. Dispatches to the helpers below."""
    display_name = result.fipe_model_name or result.model_trim or result.model_red
    st.subheader(f"Resultado: {display_name} {result.year_model}")

    _render_blended_headline(result)
    _render_price_mode(result)

    if result.buy_ratio_available:
        _render_primary_buy_ratio(result)

    _render_fipe_context(result)
    _render_confidence_badge(result)
    _render_profile_badges(result)

    if result.total_comparables == 0 and not result.fipe_used_as_anchor:
        st.warning(result.rationale)
        return

    _render_secondary_cards(result)
    _render_modifiers(result)

    if result.loja_comparables or result.revenda_comparables:
        st.divider()
        _render_comparables_chart(result)
        st.divider()
        _render_comparables_table(result)

    _render_details_expander(result)

    # ── Feedback form (Fase 3 — calibração contínua) ──
    st.divider()
    fipe_price = st.session_state.get("appraisal_fipe_price")
    render_feedback_form(result, fipe_price=fipe_price)


# ── Individual sections ─────────────────────────────────────────────────────


def _render_blended_headline(result) -> None:
    """Single recommended buy value at the top of the result.

    The engine picks the number (`recommended_value`): the 70/30 ensemble of the
    two anchors in `headline_mode: ensemble`, or anchor A first in the legacy mode.
    """
    blended = result.blended_max_trade_value
    if blended is None or blended <= 0:
        return

    purpose = (result.purpose or "auto").lower()
    purpose_label = {
        "auto": "Automático",
        "loja": "Loja (B2C) — forçado",
        "revenda": "Revenda (B2B) — forçado",
    }.get(purpose, purpose)

    # Headline comes from the engine (buy_ratio_first or ensemble); legacy fallback below
    source = result.recommended_source
    use_buy_ratio = source == "buy_ratio" or (
        source is None and result.buy_ratio_available and result.buy_ratio_price is not None and result.buy_ratio_price > 0
    )
    if result.recommended_value is not None and result.recommended_value > 0:
        headline_value = result.recommended_value
    else:
        headline_value = result.buy_ratio_price if use_buy_ratio else blended
    headline_label = {
        "ensemble": "💰 Valor Recomendado (compra + vendas)",
        "buy_ratio": "💰 Valor Recomendado (histórico de compra)",
    }.get(source, "💰 Valor Recomendado (histórico de compra)" if use_buy_ratio else "💰 Valor Recomendado de Compra")

    if result.price_mode == "sugestao":
        headline_label = "💡 Sugestão de Valor — não é preço oficial"

    main_col, alt_col = st.columns([3, 2])
    with main_col:
        st.metric(
            headline_label,
            format_brl(headline_value),
            help=(
                "Valor único de compra ponderado pela probabilidade de canal "
                "(Loja vs Revenda). Use este número como referência principal."
            ),
        )
        if source == "ensemble" and result.recommended_reason:
            st.caption(f"ℹ️ {result.recommended_reason}")
        if result.blended_reason:
            st.caption(f"ℹ️ Finalidade: **{purpose_label}** — {result.blended_reason}")
        if result.above_fipe_alert:
            st.warning(result.above_fipe_alert)

    with alt_col:
        if use_buy_ratio:
            # Show blended as alternative
            st.metric(
                "Análise por canal (mistura)",
                format_brl(blended),
                help=(
                    "Valor obtido pela mistura ponderada Loja/Revenda. "
                    "Comparativo ao histórico de compra ao lado."
                ),
            )
        else:
            # Show channel weights composition
            if (
                result.blended_weight_loja is not None
                and result.blended_weight_revenda is not None
                and result.blended_source == "blend"
            ):
                wl = result.blended_weight_loja * 100
                wr = result.blended_weight_revenda * 100
                st.caption(
                    f"**Composição:** {wl:.0f}% Loja + {wr:.0f}% Revenda"
                )

    st.divider()


def _render_price_mode(result) -> None:
    """Official price (inside the gate) or suggestion for the desk (outside), with the reasons."""
    if result.price_mode == "oficial":
        st.success(
            "✅ **Preço oficial** — perfil dentro do portão: confiança alta ou média, idade e KM dentro "
            "dos limites, marca com base. Na régua de 2026, 87% desses casos ficam a ±10% do ideal."
        )
    elif result.price_mode == "sugestao":
        reasons = "; ".join(result.price_mode_reasons) or "fora do portão"
        st.warning(
            f"💡 **Sugestão, não é preço oficial.** Motivo: {reasons}. "
            "Use como referência e feche o valor com a mesa."
        )


def _render_primary_buy_ratio(result) -> None:
    """Headline metric + confidence band + divergence alert."""
    main_col, band_col = st.columns([3, 2])

    with main_col:
        st.metric(
            "💰 Valor Sugerido de Compra",
            format_brl(result.buy_ratio_price),
            help=(
                "Baseado em quanto a Grand Brasil realmente pagou em carros "
                "similares (mesmo modelo, ano e faixa de KM). "
                "Este é o número principal para a decisão de compra."
            ),
        )
        ratio_pct = result.buy_ratio_median * 100
        tier_label = {
            "same_year_km6k": "✅ Mesmo ano, KM ±6k",
            "same_year_km12k": "✅ Mesmo ano, KM ±12k",
            "same_year": "⚠️ Mesmo ano (sem KM)",
            "year_pm1_km12k": "⚠️ Ano ±1 (ajustado), KM ±12k",
            "year_pm2_km24k": "⚠️ Ano ±2 (ajustado), KM ±24k",
            "model_fallback": "⚠️ Fallback por modelo",
        }.get(result.buy_ratio_tier, result.buy_ratio_tier or "")

        avaliados_extra = (
            f" + **{result.buy_ratio_offered_count}** avaliações"
            if result.buy_ratio_offered_count and result.buy_ratio_offered_count > 0
            else ""
        )
        st.caption(
            f"**{ratio_pct:.1f}%** da FIPE · "
            f"**{result.buy_ratio_closed_deal_count}** vendas fechadas{avaliados_extra} · "
            f"{tier_label}"
        )

    with band_col:
        if result.buy_ratio_low is not None and result.buy_ratio_high is not None:
            st.metric(
                "Faixa (P25 – P75)",
                f"{format_brl(result.buy_ratio_low)} – {format_brl(result.buy_ratio_high)}",
                help=(
                    "Intervalo entre o 25º e 75º percentil dos valores "
                    "historicamente pagos. Valores dentro desta faixa "
                    "são seguros; fora, requerem justificativa."
                ),
            )
            p25 = result.buy_ratio_p25 * 100
            p75 = result.buy_ratio_p75 * 100
            st.caption(f"{p25:.1f}% – {p75:.1f}% da FIPE")

    if result.buy_ratio_description:
        st.caption(f"ℹ️ {result.buy_ratio_description}")

    _render_divergence_alert(result)


def _render_divergence_alert(result) -> None:
    """Green/amber/red alert comparing primary anchor to the Loja max-trade value."""
    if result.anchor_divergence_pct is None or not result.loja_max_trade_value:
        return

    div = result.anchor_divergence_pct * 100
    sales_value = format_brl(result.loja_max_trade_value)
    buy_value = format_brl(result.buy_ratio_price)

    if abs(div) < 3:
        st.success(
            f"✅ Convergência com a análise de vendas (diferença {div:+.1f}%). "
            f"Alta confiança."
        )
    elif abs(div) < 8:
        st.info(
            f"ℹ️ Divergência moderada ({div:+.1f}%) entre histórico de compra "
            f"({buy_value}) e análise de vendas ({sales_value})."
        )
    else:
        direction = "acima" if div > 0 else "abaixo"
        st.warning(
            f"⚠️ Divergência alta ({div:+.1f}%): histórico de compra está "
            f"{abs(div):.1f}% {direction} da análise de vendas. "
            f"Vendas sugerem {sales_value}, histórico indica {buy_value}. "
            f"Vale revisar manualmente antes de fechar."
        )


def _render_fipe_context(result) -> None:
    """FIPE reference line + per-channel historical spreads (small, contextual)."""
    if not result.fipe_used_as_anchor:
        if result.used_trim_level:
            st.caption(f"Comparacao por versao especifica: **{result.model_trim}**")
        elif result.model_trim:
            st.caption(
                f"Versao {result.model_trim} com poucos dados — "
                f"usando modelo geral: **{result.model_red}**"
            )
        return

    ref = (
        f" — referencia {result.fipe_reference_month}"
        if result.fipe_reference_month
        else ""
    )
    code = f" (cod. {result.fipe_code})" if result.fipe_code else ""
    st.caption(f"📊 FIPE{code}{ref} — âncora usada para aplicar o ratio histórico.")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if result.loja_fipe_spread_pct is not None:
            loja_pct = result.loja_fipe_spread_pct * 100
            loja_dir = "acima" if loja_pct >= 0 else "abaixo"
            st.metric(
                f"Spread Loja vs FIPE ({result.loja_spread_sample_size} vendas)",
                f"{'+' if loja_pct >= 0 else ''}{loja_pct:.1f}%",
                help=f"Vendemos em media {abs(loja_pct):.1f}% {loja_dir} da FIPE historica no canal Loja.",
            )
        elif result.loja_used_fallback_spread and result.loja_fallback_ratio:
            st.metric(
                "Spread Loja vs FIPE (fallback)",
                f"{(result.loja_fallback_ratio - 1) * 100:+.0f}%",
                help=(
                    f"Sem historico suficiente. Usando referencia padrao: "
                    f"FIPE x {result.loja_fallback_ratio:.2f}."
                ),
            )
        else:
            st.caption("Sem historico de spread Loja com FIPE disponivel.")
    with col_s2:
        if result.revenda_fipe_spread_pct is not None:
            rev_pct = result.revenda_fipe_spread_pct * 100
            rev_dir = "acima" if rev_pct >= 0 else "abaixo"
            st.metric(
                f"Spread Revenda vs FIPE ({result.revenda_spread_sample_size} vendas)",
                f"{'+' if rev_pct >= 0 else ''}{rev_pct:.1f}%",
                help=f"Vendemos em media {abs(rev_pct):.1f}% {rev_dir} da FIPE historica no canal Revenda.",
            )
        elif result.revenda_used_fallback_spread and result.revenda_fallback_ratio:
            st.metric(
                "Spread Revenda vs FIPE (fallback)",
                f"{(result.revenda_fallback_ratio - 1) * 100:+.0f}%",
                help=(
                    f"Sem historico suficiente (< {3} vendas). Usando referencia "
                    f"padrao de mercado B2B: FIPE x {result.revenda_fallback_ratio:.2f}."
                ),
            )
        else:
            st.caption("Sem historico de spread Revenda com FIPE disponivel.")


def _render_profile_badges(result) -> None:
    """Show brand-tier and channel-probability side-by-side (when available)."""
    if result.brand_tier is None and result.p_revenda is None:
        return

    col_tier, col_channel = st.columns(2)

    with col_tier:
        if result.brand_tier is not None:
            tier = result.brand_tier
            emoji = {"SAFE": "🟢", "NEUTRAL": "⚪", "RISKY": "🟠"}.get(tier, "•")
            adj = result.brand_tier_adjustment_pp
            if adj > 0:
                adj_txt = f"margem +{adj:.1f}pp (mais conservador)"
            elif adj < 0:
                adj_txt = f"margem {adj:.1f}pp (mais agressivo)"
            else:
                adj_txt = "sem ajuste"
            st.markdown(f"**Perfil da marca:** {emoji} **{tier}** — {adj_txt}")
            if result.brand_tier_reason:
                st.caption(result.brand_tier_reason)

    with col_channel:
        if result.p_revenda is not None:
            pct = result.p_revenda * 100
            if result.is_revenda_profile:
                badge = "🔴 Perfil Revenda"
            elif pct < 30:
                badge = "🔵 Perfil Loja"
            else:
                badge = "⚫ Perfil misto"
            st.markdown(
                f"**{badge}** — P(Revenda) ≈ **{pct:.0f}%** "
                f"(tier {result.channel_profile_tier}, "
                f"{result.channel_age_bucket}a, {result.channel_km_bucket})"
            )
            if result.is_revenda_profile:
                st.caption(
                    "Use prioritariamente o cenário Revenda abaixo — "
                    "este carro tende a não ser vendido no showroom."
                )


def _render_confidence_badge(result) -> None:
    colors = {"alta": "green", "media": "orange", "baixa": "red", "sem dados": "red"}
    color = colors.get(result.confidence, "gray")
    outlier_text = (
        f" | {result.outliers_removed} outlier(s) removido(s)"
        if result.outliers_removed > 0
        else ""
    )
    if result.confidence_source == "calibrada" and result.confidence_q90 is not None:
        st.markdown(
            f"**Confianca:** :{color}[{result.confidence.upper()}] — 9 em 10 casos com este perfil "
            f"ficam dentro de **±{result.confidence_q90:.0%}** (metade dentro de ±{result.confidence_q50:.0%}; "
            f"{result.confidence_n} avaliações passadas)"
        )
        if result.confidence_reason:
            st.caption(result.confidence_reason + f" {result.total_comparables} vendas comparaveis{outlier_text}.")
        return
    st.markdown(
        f"**Confianca:** :{color}[{result.confidence.upper()}] "
        f"({result.total_comparables} vendas comparaveis{outlier_text})"
    )


def _render_secondary_cards(result) -> None:
    """Loja / Revenda cards as secondary validation of the primary anchor."""
    st.divider()
    if result.buy_ratio_available:
        st.markdown("### 🔍 Validação cruzada — Cenários Loja / Revenda")
        st.caption(
            "Valores teóricos derivados das vendas recentes (preço estimado de "
            "venda × margem-alvo). Use para comparar com o valor principal acima: "
            "convergência indica alta confiança, divergência sugere revisão."
        )
    else:
        st.markdown("### Análise por Cenário (Loja / Revenda)")

    col_loja, col_revenda = st.columns(2)

    with col_loja:
        st.markdown("#### Cenário Loja (B2C)")
        if result.loja_max_trade_value is not None:
            st.metric(
                "Valor de compra — Loja",
                format_brl(result.loja_max_trade_value),
                help=(
                    "Maximo que podemos pagar mantendo a margem-alvo Loja "
                    "ao revender no showroom. Derivado do preco estimado de "
                    "venda menos a margem-alvo."
                ),
            )
            if (
                result.loja_max_trade_low is not None
                and result.loja_max_trade_high is not None
            ):
                st.caption(
                    f"📏 Faixa P25–P75: "
                    f"**{format_brl(result.loja_max_trade_low)} – "
                    f"{format_brl(result.loja_max_trade_high)}**"
                )
            details = (
                f"Preco estimado venda: {format_brl(result.loja_estimated_sale_price)} | "
                f"Margem alvo: {result.loja_target_margin_percent}%"
            )
            if result.loja_avg_days_in_stock:
                details += f" | Media estoque: {result.loja_avg_days_in_stock:.0f} dias"
            if result.loja_comparables_count:
                details += f" | {result.loja_comparables_count} comparaveis"
            st.caption(details)
        else:
            st.info("Sem vendas Loja comparaveis.")

    with col_revenda:
        st.markdown("#### Cenário Revenda (B2B)")
        if result.revenda_max_trade_value is not None:
            st.metric(
                "Valor de compra — Revenda",
                format_brl(result.revenda_max_trade_value),
                help=(
                    "Maximo que podemos pagar mantendo a margem-alvo Revenda "
                    "ao repassar para outra concessionaria. Derivado do preco "
                    "estimado de venda B2B menos a margem-alvo."
                ),
            )
            if (
                result.revenda_max_trade_low is not None
                and result.revenda_max_trade_high is not None
            ):
                st.caption(
                    f"📏 Faixa P25–P75: "
                    f"**{format_brl(result.revenda_max_trade_low)} – "
                    f"{format_brl(result.revenda_max_trade_high)}**"
                )
            details = (
                f"Preco estimado venda: {format_brl(result.revenda_estimated_sale_price)} | "
                f"Margem alvo: {result.revenda_target_margin_percent}%"
            )
            if result.revenda_avg_days_in_stock:
                details += f" | Media estoque: {result.revenda_avg_days_in_stock:.0f} dias"
            if result.revenda_comparables_count:
                details += f" | {result.revenda_comparables_count} comparaveis"
            st.caption(details)
            if result.revenda_used_fallback_spread and result.revenda_fallback_ratio:
                st.caption(
                    f"⚠️ Usando referencia padrao B2B (FIPE × {result.revenda_fallback_ratio:.2f}) "
                    f"— pouco historico do modelo."
                )
        else:
            st.info("Sem vendas Revenda comparaveis.")


def _render_modifiers(result) -> None:
    """Repair cost, blindado badge, and KM adjustment info."""
    if result.estimated_repair_cost > 0:
        st.info(
            f"Custo de reparo de {format_brl(result.estimated_repair_cost)} "
            "ja descontado dos valores acima."
        )

    if result.blindado:
        if result.blindado_premium_applied and result.blindado_premium_applied > 0:
            st.success(
                f"🛡️ **Veiculo Blindado** — premio de "
                f"**{format_brl(result.blindado_premium_applied)}** adicionado ao preco "
                f"estimado de venda Loja e Revenda (referencia ano {result.year_model})."
            )
        else:
            st.info("🛡️ Veiculo Blindado — sem premio aplicavel para este ano modelo.")

    if result.km_referencia is not None and result.loja_km_adjustment_pct is not None:
        car_km = result.km or 0
        km_ref = result.km_referencia
        delta_km = car_km - km_ref
        direction = "a mais" if delta_km > 0 else "a menos"

        loja_pct = result.loja_km_adjustment_pct * 100
        rev_pct = (result.revenda_km_adjustment_pct or 0) * 100
        loja_sign = "+" if loja_pct >= 0 else ""
        rev_sign = "+" if rev_pct >= 0 else ""

        fator_loja_pct = (result.fator_km_loja or 0) * 100
        fator_rev_pct = (result.fator_km_revenda or 0) * 100

        st.info(
            f"**Ajuste de KM** — referencia para {result.year_model}: **{km_ref:,} km**  \n"
            f"Seu veiculo: **{car_km:,} km** ({abs(delta_km):,} km {direction} do referencial)  \n"
            f"Loja: **{loja_sign}{loja_pct:.1f}%** (fator {result.brand}: {fator_loja_pct:.1f}%/10k) | "
            f"Revenda: **{rev_sign}{rev_pct:.1f}%** (fator {fator_rev_pct:.1f}%/10k)"
        )


def _render_comparables_chart(result) -> None:
    """Scatter plot of all comparables with trade-value reference lines."""
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
    """Full table of comparable sales used (inside an expander)."""
    all_comps = result.loja_comparables + result.revenda_comparables
    if not all_comps:
        return

    with st.expander(f"Tabela de Comparaveis ({len(all_comps)} vendas)", expanded=False):
        data = [
            {
                "Placa": c.plate or "-",
                "Modelo RED": c.model_red or "-",
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


def _render_details_expander(result) -> None:
    """Rationale + run metadata (mode, year range, margins) in a collapsed panel."""
    with st.expander("Detalhes da Analise"):
        st.markdown(result.rationale)
        if result.year_range_used:
            st.markdown(f"**Faixa de ano utilizada:** {result.year_range_used}")
        modo = (
            "FIPE como ancora"
            if result.fipe_used_as_anchor
            else (
                "Mediana ponderada por recencia"
                if result.used_weighted_median
                else "Mediana simples"
            )
        )
        st.markdown(f"**Modo de calculo:** {modo}")
        st.markdown(
            f"**Configuracao:** Margem Loja: {result.loja_target_margin_percent}% | "
            f"Margem Revenda: {result.revenda_target_margin_percent}%"
        )
