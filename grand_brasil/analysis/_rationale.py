"""Rationale builder — converts an `AppraisalSuggestion` into a human-readable
sentence in PT-BR for display in the dashboard and logs.

Kept separate from the orchestrator so changes in phrasing don't require
touching the pricing logic.
"""

from __future__ import annotations

from grand_brasil.models.appraisal import AppraisalSuggestion


def build_rationale(suggestion: AppraisalSuggestion, year_tolerance: int) -> str:
    """Compose a legible summary of how the suggestion was derived.

    The narrative is structured as separate sentences that are joined with a
    single space. Sections are included only when they contribute information
    (no empty headers).
    """
    display_name = (
        suggestion.fipe_model_name
        or suggestion.model_trim
        or suggestion.model_red
    )
    match_level = "versao especifica" if suggestion.used_trim_level else "modelo geral"
    median_method = (
        "ponderada (recencia)" if suggestion.used_weighted_median else "simples"
    )

    parts: list[str] = []

    # ── FIPE vs historical anchor ──
    if suggestion.fipe_used_as_anchor:
        ref = (
            f" ({suggestion.fipe_reference_month})"
            if suggestion.fipe_reference_month
            else ""
        )
        code = f" — codigo {suggestion.fipe_code}" if suggestion.fipe_code else ""
        parts.append(f"Preco FIPE{ref}{code} usado como ancora principal.")

        if suggestion.loja_fipe_spread_pct is not None:
            loja_dir = "acima" if suggestion.loja_fipe_spread_pct >= 0 else "abaixo"
            loja_pct = abs(suggestion.loja_fipe_spread_pct * 100)
            parts.append(
                f"Historico Loja: vendemos em media {loja_pct:.1f}% {loja_dir} da FIPE "
                f"({suggestion.loja_spread_sample_size} vendas com FIPE historica)."
            )
        if suggestion.revenda_fipe_spread_pct is not None:
            rev_dir = "acima" if suggestion.revenda_fipe_spread_pct >= 0 else "abaixo"
            rev_pct = abs(suggestion.revenda_fipe_spread_pct * 100)
            parts.append(
                f"Historico Revenda: vendemos em media {rev_pct:.1f}% {rev_dir} da FIPE "
                f"({suggestion.revenda_spread_sample_size} vendas com FIPE historica)."
            )
        if (
            suggestion.loja_fipe_spread_pct is None
            and suggestion.revenda_fipe_spread_pct is None
            and not suggestion.revenda_used_fallback_spread
            and not suggestion.loja_used_fallback_spread
        ):
            parts.append("Sem historico de spreads vs FIPE disponivel para este modelo.")

        if suggestion.revenda_used_fallback_spread and suggestion.revenda_fallback_ratio:
            parts.append(
                f"Revenda sem historico suficiente: usando referencia padrao B2B "
                f"(FIPE x {suggestion.revenda_fallback_ratio:.2f})."
            )
        if suggestion.loja_used_fallback_spread and suggestion.loja_fallback_ratio:
            parts.append(
                f"Loja sem historico suficiente: usando referencia padrao "
                f"(FIPE x {suggestion.loja_fallback_ratio:.2f})."
            )
    else:
        parts.append(
            f"Avaliacao baseada em {suggestion.total_comparables} vendas comparaveis "
            f"de {display_name} ({suggestion.year_range_used}). "
            f"Nivel de comparacao: {match_level}. Mediana {median_method}."
        )

    # ── Buy-ratio anchor (primary — historical Grand Brasil purchases) ──
    if suggestion.buy_ratio_available and suggestion.buy_ratio_price is not None:
        ratio_pct = (suggestion.buy_ratio_median or 0) * 100
        tier_lbl = suggestion.buy_ratio_tier or "—"
        closed_n = suggestion.buy_ratio_closed_deal_count
        offered_n = suggestion.buy_ratio_offered_count
        samples_txt = (
            f"{closed_n} vendas fechadas"
            + (f" + {offered_n} avaliacoes c/ peso 0.25" if offered_n > 0 else "")
        )
        parts.append(
            f"Base de compra historica: mediana em {ratio_pct:.1f}% da FIPE "
            f"(preco sugerido R$ {suggestion.buy_ratio_price:,.0f}), "
            f"{samples_txt}, tier '{tier_lbl}'."
        )
        if (
            suggestion.buy_ratio_low is not None
            and suggestion.buy_ratio_high is not None
        ):
            # Share each bound as percentage delta from the median for quick context.
            median_brl = float(suggestion.buy_ratio_price)
            low_brl = float(suggestion.buy_ratio_low)
            high_brl = float(suggestion.buy_ratio_high)
            low_delta = (low_brl / median_brl - 1) * 100 if median_brl else 0.0
            high_delta = (high_brl / median_brl - 1) * 100 if median_brl else 0.0
            parts.append(
                f"Faixa segura P25-P75: R$ {low_brl:,.0f} a R$ {high_brl:,.0f} "
                f"({low_delta:+.1f}% a {high_delta:+.1f}% da mediana). "
                f"Valores fora desta faixa pedem justificativa."
            )

    # ── Outliers ──
    if suggestion.outliers_removed > 0:
        parts.append(
            f"{suggestion.outliers_removed} venda(s) removida(s) como outlier "
            f"(ex: blindados, vendas atipicas)."
        )

    # ── KM adjustment per channel ──
    if (
        suggestion.km_referencia is not None
        and suggestion.loja_km_adjustment_pct is not None
    ):
        km_ref = suggestion.km_referencia
        loja_pct = suggestion.loja_km_adjustment_pct * 100
        rev_pct = (suggestion.revenda_km_adjustment_pct or 0) * 100
        loja_sign = "+" if loja_pct >= 0 else ""
        rev_sign = "+" if rev_pct >= 0 else ""
        parts.append(
            f"Ajuste de KM: Loja {loja_sign}{loja_pct:.1f}% / Revenda {rev_sign}{rev_pct:.1f}% "
            f"(referencia para {suggestion.year_model}: {km_ref:,} km | "
            f"fator Loja: {(suggestion.fator_km_loja or 0)*100:.1f}%/10k, "
            f"Revenda: {(suggestion.fator_km_revenda or 0)*100:.1f}%/10k)."
        )

    # ── Per-channel outputs ──
    if suggestion.loja_comparables_count > 0:
        parts.append(
            f"Loja (B2C): {suggestion.loja_comparables_count} vendas, "
            f"preco estimado R$ {suggestion.loja_estimated_sale_price:,.0f}, "
            f"media {suggestion.loja_avg_days_in_stock:.0f} dias em estoque."
        )
    if suggestion.revenda_comparables_count > 0:
        parts.append(
            f"Revenda (B2B): {suggestion.revenda_comparables_count} vendas, "
            f"preco estimado R$ {suggestion.revenda_estimated_sale_price:,.0f}, "
            f"media {suggestion.revenda_avg_days_in_stock:.0f} dias em estoque."
        )

    # ── Brand tier (Alavanca B) ──
    if suggestion.brand_tier and suggestion.brand_tier_adjustment_pp != 0.0:
        sign = "+" if suggestion.brand_tier_adjustment_pp > 0 else ""
        parts.append(
            f"Perfil de marca {suggestion.brand_tier}: ajuste de "
            f"{sign}{suggestion.brand_tier_adjustment_pp:.1f}pp na margem-alvo "
            f"(Loja e Revenda)."
        )

    # ── Channel probability (Alavanca A) ──
    if suggestion.p_revenda is not None:
        pct = suggestion.p_revenda * 100
        profile_tag = " — perfil Revenda" if suggestion.is_revenda_profile else ""
        parts.append(
            f"Probabilidade de Revenda estimada: {pct:.0f}% "
            f"(tier {suggestion.channel_profile_tier}, idade {suggestion.channel_age_bucket}, "
            f"KM {suggestion.channel_km_bucket}){profile_tag}."
        )

    # ── Blended single price ──
    if suggestion.blended_max_trade_value is not None:
        purpose_lbl = {
            "auto": "automatica",
            "loja": "Loja forcada",
            "revenda": "Revenda forcada",
        }.get((suggestion.purpose or "auto").lower(), suggestion.purpose or "auto")
        parts.append(
            f"Valor unico recomendado: R$ {suggestion.blended_max_trade_value:,.0f} "
            f"(finalidade {purpose_lbl}, fonte: {suggestion.blended_source})."
        )

    # ── Modifiers ──
    if suggestion.loja_margin_base_pct is not None:
        parts.append(_format_dynamic_margin_line(suggestion))

    if suggestion.estimated_repair_cost > 0:
        parts.append(
            f"Custo de reparo estimado de R$ {suggestion.estimated_repair_cost:,.0f} ja descontado."
        )

    if suggestion.blindado and suggestion.blindado_premium_applied:
        parts.append(
            f"Veiculo blindado: premio de R$ {suggestion.blindado_premium_applied:,.0f} "
            f"adicionado ao preco estimado de venda Loja e Revenda (ano {suggestion.year_model})."
        )

    parts.append(f"Confianca: {suggestion.confidence}.")

    return " ".join(parts)


def _format_dynamic_margin_line(suggestion: AppraisalSuggestion) -> str:
    """One-line summary of the dynamic-margin decomposition (Loja-focused)."""
    base = suggestion.loja_margin_base_pct or 0
    speed = suggestion.loja_margin_speed_adj_pp
    vol = suggestion.loja_margin_volatility_adj_pp
    final = suggestion.loja_target_margin_percent

    pieces = [f"Margem dinamica Loja: base {base:.1f}%"]
    if speed > 0:
        pieces.append(f"+ velocidade {speed:.1f}pp")
    if vol > 0:
        pieces.append(f"+ volatilidade {vol:.1f}pp")
    tail = f"= {final:.1f}%"
    if suggestion.loja_margin_capped:
        tail += " (cap)"
    if suggestion.model_sample_size_for_margin:
        n = suggestion.model_sample_size_for_margin
        days = suggestion.model_median_days_in_stock
        std = suggestion.model_margin_std_pp
        tail += f" — base de {n} vendas ({days:.0f}d med., std {std:.1f}pp)."
    else:
        tail += "."
    return " ".join(pieces) + " " + tail
