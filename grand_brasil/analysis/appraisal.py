"""Appraisal engine — suggests trade-in and sale prices for a vehicle.

Two independent pricing anchors are produced for every appraisal:

1. PRIMARY — Buy-ratio anchor (see analysis/purchase_ratio.py)
   Computed from our historical appraisal database (ingestion/appraisal_history.py).
   Answers: "What did Grand Brasil actually pay for similar cars?"
   Formula: FIPE_today × weighted_median(ratio_paid_historically)

2. SECONDARY — Sales-based anchor (this module)
   Computed from recent sales data (Loja / Revenda split, margin on top).
   Answers: "What could we sell this car for, and what trade value keeps our margin?"
   Used as a validation check against the primary anchor.

Sales-based pipeline in appraise():
  a) Find comparables by model_red + year tolerance   (_comparable_selection)
  b) Remove blindado outliers via year-band premium    (_blindado)
  c) Split by sale_channel (Loja / Revenda)
  d) Compute an adjusted base price per channel
       FIPE mode:  base = FIPE × (1 + historical_spread_vs_fipe)   (_fipe_spread)
       Fallback:   base = weighted_median of year-adjusted historical prices
  e) Apply brand-specific KM factor (utils/fator_km_preco)
  f) Add blindado premium if applicable (Loja and Revenda)         (_blindado)
  g) Derive max_trade_value from target margin minus estimated repair cost
  h) Compute buy-ratio anchor from the appraisal database          (purchase_ratio)
  i) Build a human-readable rationale                              (_rationale)

Sub-modules:
    _blindado               — filter + sale-price premium helpers
    _comparable_selection   — find/build/weight comparables
    _fipe_spread            — spread vs historical FIPE + fipe_ratio metric
    _rationale              — builds the PT-BR narrative
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import pandas as pd

from grand_brasil.analysis._blindado import (
    blindado_sale_premium,
    remove_blindados,
)
from grand_brasil.analysis._comparable_selection import (
    build_comparables,
    compute_weights,
    find_comparables,
    weighted_median,
    year_adjusted_prices,
)  # `year_adjusted_prices` is reused by _resolve_target_margins
from grand_brasil.analysis._fipe_spread import (
    compute_fipe_spreads,
    fipe_ratio,
)
from grand_brasil.analysis._rationale import build_rationale
from grand_brasil.analysis.confidence import ConfidenceModel, signals_from_suggestion
from grand_brasil.analysis.dynamic_margin import (
    DynamicMarginResult,
    compute_target_margin,
)
from grand_brasil.analysis.purchase_ratio import (
    BuyRatioResult,
    compute_buy_ratio,
)
from grand_brasil.models.appraisal import (
    AppraisalRequest,
    AppraisalSuggestion,
)
from grand_brasil.utils.brand_tier import classify_brand
from grand_brasil.utils.channel_probability import predict_channel_probability
from grand_brasil.utils.fator_km_preco import (
    ajuste_km_pct as calc_ajuste_km_pct,
    get_fator_km,
    km_referencia as calc_km_referencia,
)

logger = logging.getLogger(__name__)


def appraise(
    request: AppraisalRequest,
    sales_df: pd.DataFrame,
    year_tolerance: int = 2,
    loja_target_margin: float = 15.0,
    revenda_target_margin: float = 5.5,
    min_comparables: int = 3,
    recency_halflife_days: float = 180.0,
    year_pct_per_year: float = 10.0,
    fipe_client=None,
    fipe_brand_code: Optional[str] = None,
    fipe_model_code: Optional[str] = None,
    fipe_year_code: Optional[str] = None,
    appraisal_df=None,
    year_profile: Optional[dict] = None,
    appraisal_config=None,
    reference_date: Optional[pd.Timestamp] = None,
    km_slope: Optional[float] = None,
    brand_year_profile: Optional[dict] = None,
    confidence_model: Optional[ConfidenceModel] = None,
) -> AppraisalSuggestion:
    """Generate a full trade-in appraisal.

    Produces both the primary buy-ratio anchor (from the appraisal history)
    and the secondary sales-based anchor (Loja/Revenda margin scenarios) in
    a single object. See the module docstring for the full pipeline.

    Args:
        request: The car being appraised.
        sales_df: Historical sales DataFrame (from load_sales_history).
        year_tolerance: How many years +/- to search for comparables.
        loja_target_margin, revenda_target_margin: Target gross margin %
            per channel (used in the secondary anchor).
        min_comparables: Minimum comps for "media" confidence.
        fipe_client, fipe_*_code: Optional FIPE API access for historical
            spread lookup.
        appraisal_df, year_profile, appraisal_config: Inputs that activate
            the primary buy-ratio anchor.
    """
    # ── 1) Find comparables (trim-level first, fallback to model_red) ──
    comparables_df, used_trim, match_key = _select_comparables(
        sales_df=sales_df,
        request=request,
        year_tolerance=year_tolerance,
        min_comparables=min_comparables,
    )

    # ── 2) Remove blindado outliers ──
    raw_count = len(comparables_df)
    comparables_df = remove_blindados(comparables_df, request.year_model)
    outliers_removed = raw_count - len(comparables_df)
    total_comps = len(comparables_df)

    # Split by channel
    loja_df = comparables_df[comparables_df["sale_channel"] == "Loja"]
    revenda_df = comparables_df[comparables_df["sale_channel"] == "Revenda"]

    # ── 3) Skeleton suggestion (will be enriched below) ──
    fipe_mode = request.fipe_price is not None and request.fipe_price > 0

    suggestion = AppraisalSuggestion(
        brand=request.brand.upper(),
        model_red=request.model_red.upper(),
        model_trim=match_key.upper() if used_trim else None,
        year_model=request.year_model,
        km=request.km,
        estimated_repair_cost=request.estimated_repair_cost,
        loja_target_margin_percent=loja_target_margin,
        revenda_target_margin_percent=revenda_target_margin,
        total_comparables=total_comps,
        outliers_removed=outliers_removed,
        used_trim_level=used_trim,
        fipe_code=request.fipe_code,
        fipe_reference_month=request.fipe_reference_month,
        fipe_model_name=request.fipe_model_name,
    )

    # Nothing to compute
    if total_comps == 0 and not fipe_mode:
        suggestion.confidence = "sem dados"
        suggestion.rationale = (
            f"Nenhuma venda comparavel encontrada para {match_key} "
            f"ano {request.year_model} (tolerancia: +/-{year_tolerance} anos)."
        )
        return suggestion

    # Year range (informational)
    if total_comps > 0:
        min_year = int(comparables_df["year_model"].min())
        max_year = int(comparables_df["year_model"].max())
        suggestion.year_range_used = f"{min_year} - {max_year}"

    # ── 4) Weighting setup ──
    has_sale_date = (
        "sale_date" in comparables_df.columns
        and comparables_df["sale_date"].notna().any()
    )
    suggestion.used_weighted_median = has_sale_date and not fipe_mode
    reference_date = pd.Timestamp.now()

    # ── 5) KM factor per channel (brand-specific) ──
    loja_km_pct, revenda_km_pct = _apply_km_factors(
        request, suggestion, appraisal_config=appraisal_config
    )

    # ── 6) FIPE historical spread per channel (+ fallback when scarce) ──
    loja_spread, revenda_spread = _apply_fipe_spreads(
        suggestion=suggestion,
        loja_df=loja_df,
        revenda_df=revenda_df,
        fipe_mode=fipe_mode,
        fipe_client=fipe_client,
        fipe_brand_code=fipe_brand_code,
        fipe_model_code=fipe_model_code,
        fipe_year_code=fipe_year_code,
        reference_date=reference_date,
        recency_halflife_days=recency_halflife_days,
        appraisal_config=appraisal_config,
    )

    # ── 7) Resolve effective target margins (fixed or dynamic) ──
    effective_loja_margin, effective_revenda_margin = _resolve_target_margins(
        suggestion=suggestion,
        request=request,
        fipe_mode=fipe_mode,
        loja_df=loja_df,
        revenda_df=revenda_df,
        sales_df=sales_df,
        loja_spread=loja_spread,
        revenda_spread=revenda_spread,
        year_pct_per_year=year_pct_per_year,
        loja_target_margin=loja_target_margin,
        revenda_target_margin=revenda_target_margin,
        appraisal_config=appraisal_config,
    )

    margin_basis = str(getattr(appraisal_config, "margin_basis", "markup")) if appraisal_config else "markup"
    tax_pct = float(getattr(appraisal_config, "sales_tax_pct", 0.0)) if appraisal_config else 0.0

    # ── 8) Compute Loja / Revenda estimated sale prices and trade values ──
    _compute_channel_prices(
        suggestion=suggestion,
        request=request,
        loja_df=loja_df,
        revenda_df=revenda_df,
        loja_km_pct=loja_km_pct,
        revenda_km_pct=revenda_km_pct,
        loja_spread=loja_spread,
        revenda_spread=revenda_spread,
        fipe_mode=fipe_mode,
        has_sale_date=has_sale_date,
        reference_date=reference_date,
        year_pct_per_year=year_pct_per_year,
        recency_halflife_days=recency_halflife_days,
        loja_target_margin=effective_loja_margin,
        revenda_target_margin=effective_revenda_margin,
        margin_basis=margin_basis,
        tax_pct=tax_pct,
    )

    # ── 9) Blindado premium (added to both channels) ──
    if request.blindado:
        _apply_blindado_premium(
            suggestion=suggestion,
            request=request,
            loja_target_margin=effective_loja_margin,
            revenda_target_margin=effective_revenda_margin,
            appraisal_config=appraisal_config,
            margin_basis=margin_basis,
            tax_pct=tax_pct,
        )

    if fipe_mode:
        suggestion.fipe_used_as_anchor = True

    # FIPE ratios (display metrics)
    suggestion.loja_fipe_ratio = fipe_ratio(
        suggestion.loja_estimated_sale_price, request.fipe_price
    )
    suggestion.revenda_fipe_ratio = fipe_ratio(
        suggestion.revenda_estimated_sale_price, request.fipe_price
    )

    # ── 9) PRIMARY anchor: buy-ratio from historical appraisals ──
    if (
        appraisal_df is not None
        and request.fipe_price is not None
        and request.fipe_price > 0
    ):
        _apply_buy_ratio(
            suggestion=suggestion,
            request=request,
            appraisal_df=appraisal_df,
            year_profile=year_profile,
            appraisal_config=appraisal_config,
            reference_date=reference_date,
            km_slope=km_slope,
            brand_year_profile=brand_year_profile,
        )

    # ── 10) Channel probability (Alavanca A) ──
    _apply_channel_probability(
        suggestion=suggestion,
        request=request,
        appraisal_config=appraisal_config,
    )

    # ── 11) Blended single price (Fase 2) ──
    _apply_blended_price(
        suggestion=suggestion,
        request=request,
    )

    # ── 11b) Headline: which number the UI shows ──
    _apply_recommendation(suggestion, appraisal_config)
    _apply_fipe_ratio_alert(suggestion, request, appraisal_config)

    # ── 12) Confidence + rationale ──
    suggestion.confidence = _assess_confidence(
        total=total_comps,
        loja_count=len(loja_df),
        revenda_count=len(revenda_df),
        min_comparables=min_comparables,
    )
    if confidence_model is not None:
        _apply_calibrated_confidence(suggestion, confidence_model)
    suggestion.rationale = build_rationale(suggestion, year_tolerance)

    # ── 13) Official price or suggestion ──
    _apply_official_gate(suggestion, request, appraisal_config, reference_date)

    return suggestion


def _apply_channel_probability(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    appraisal_config,
) -> None:
    """Predict P(Revenda) for the car profile and store it on the suggestion.

    Uses the calibrated brand_tier × km × age lookup table. The reference
    year is today's year (so age is current, not historical).
    """
    cp_cfg = getattr(appraisal_config, "channel_probability", None) if appraisal_config else None
    bt_cfg = getattr(appraisal_config, "brand_tier", None) if appraisal_config else None
    reference_year = pd.Timestamp.now().year

    info = predict_channel_probability(
        brand=request.brand,
        km=request.km,
        year_model=request.year_model,
        reference_year=reference_year,
        config=cp_cfg,
        brand_tier_config=bt_cfg,
    )

    suggestion.p_revenda = info.p_revenda
    suggestion.p_loja = info.p_loja
    suggestion.channel_profile_tier = info.tier
    suggestion.channel_km_bucket = info.km_bucket
    suggestion.channel_age_bucket = info.age_bucket
    suggestion.is_revenda_profile = info.is_revenda_profile
    suggestion.channel_probability_reason = info.reason


def _apply_blended_price(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
) -> None:
    """Produce a single recommended buy value from the channel scenarios.

    Logic:
      • purpose="loja":     use loja_max_trade_value     (force B2C)
      • purpose="revenda":  use revenda_max_trade_value  (force B2B)
      • purpose="auto":
          - If both channels priced and p_revenda is available:
                blended = (1-p)·loja + p·revenda
          - If only one channel priced: that one wins.
          - If neither: leave None.

    The buy-ratio anchor stays the *headline* value when it's available
    (it has its own confidence band and tends to be the most accurate
    single number). The blended figure is always populated as a
    secondary, channel-aware price for the cases when buy_ratio is
    unavailable or the user explicitly forced a channel.
    """
    purpose = (request.purpose or "auto").strip().lower()
    if purpose not in ("auto", "loja", "revenda"):
        purpose = "auto"
    suggestion.purpose = purpose

    loja = suggestion.loja_max_trade_value
    revenda = suggestion.revenda_max_trade_value

    if purpose == "loja":
        if loja is not None and loja > 0:
            suggestion.blended_max_trade_value = loja
            suggestion.blended_weight_loja = 1.0
            suggestion.blended_weight_revenda = 0.0
            suggestion.blended_source = "loja"
            suggestion.blended_reason = (
                "Finalidade Loja forçada — usando o máximo do cenário B2C."
            )
        return

    if purpose == "revenda":
        if revenda is not None and revenda > 0:
            suggestion.blended_max_trade_value = revenda
            suggestion.blended_weight_loja = 0.0
            suggestion.blended_weight_revenda = 1.0
            suggestion.blended_source = "revenda"
            suggestion.blended_reason = (
                "Finalidade Revenda forçada — usando o máximo do cenário B2B."
            )
        return

    # purpose == "auto"
    has_loja = loja is not None and loja > 0
    has_rev = revenda is not None and revenda > 0

    if not has_loja and not has_rev:
        return

    if has_loja and not has_rev:
        suggestion.blended_max_trade_value = loja
        suggestion.blended_weight_loja = 1.0
        suggestion.blended_weight_revenda = 0.0
        suggestion.blended_source = "loja"
        suggestion.blended_reason = "Sem cenário Revenda disponível — usando Loja."
        return

    if has_rev and not has_loja:
        suggestion.blended_max_trade_value = revenda
        suggestion.blended_weight_loja = 0.0
        suggestion.blended_weight_revenda = 1.0
        suggestion.blended_source = "revenda"
        suggestion.blended_reason = "Sem cenário Loja disponível — usando Revenda."
        return

    # Both channels available — blend by p_revenda
    p_rev = suggestion.p_revenda
    if p_rev is None:
        # Without channel probability, average them as a neutral fallback
        p_rev = 0.5

    p_rev = max(0.0, min(1.0, float(p_rev)))
    p_loja = 1.0 - p_rev

    blended = (
        Decimal(str(p_loja)) * loja + Decimal(str(p_rev)) * revenda
    )
    suggestion.blended_max_trade_value = _round_to_500(blended)
    suggestion.blended_weight_loja = p_loja
    suggestion.blended_weight_revenda = p_rev
    suggestion.blended_source = "blend"
    suggestion.blended_reason = (
        f"Mistura ponderada por P(Revenda)={p_rev:.0%}: "
        f"{p_loja:.0%}·Loja + {p_rev:.0%}·Revenda."
    )


def _apply_calibrated_confidence(suggestion: AppraisalSuggestion, model: ConfidenceModel) -> None:
    """Replace the count-based confidence with the calibrated error quantiles of similar past cases."""
    verdict = model.verdict(signals_from_suggestion(suggestion))
    if verdict.n == 0:
        return
    suggestion.confidence = verdict.level
    suggestion.confidence_source = "calibrada"
    suggestion.confidence_q50 = verdict.q50
    suggestion.confidence_q80 = verdict.q80
    suggestion.confidence_q90 = verdict.q90
    suggestion.confidence_n = verdict.n
    suggestion.confidence_reason = verdict.reason


def _apply_recommendation(suggestion: AppraisalSuggestion, appraisal_config) -> None:
    """Pick the headline value.

    buy_ratio_first (legacy): anchor A (historical buy ratio) whenever it
    exists, otherwise the channel blend (anchor B).
    ensemble: w·A + (1−w)·B when both exist. The two anchors come from
    different data (what we paid vs. what we sold for) and their errors are
    only partly correlated, so the mix beats either one alone in the backtest.
    """
    mode = getattr(appraisal_config, "headline_mode", "buy_ratio_first") if appraisal_config else "buy_ratio_first"
    a = suggestion.buy_ratio_price if suggestion.buy_ratio_available else None
    b = suggestion.blended_max_trade_value
    has_a = a is not None and a > 0
    has_b = b is not None and b > 0

    if mode == "ensemble" and has_a and has_b:
        w = float(getattr(appraisal_config, "ensemble_weight_buy_ratio", 0.7))
        by_tier = getattr(appraisal_config, "ensemble_weight_by_tier", None) or {}
        w = float(by_tier.get(suggestion.buy_ratio_tier or "", w))
        w = max(0.0, min(1.0, w))
        suggestion.recommended_value = _round_to_500(Decimal(str(w)) * a + Decimal(str(1 - w)) * b)
        suggestion.recommended_source = "ensemble"
        brl = lambda v: f"{v:,.0f}".replace(",", ".")
        suggestion.recommended_reason = (
            f"{w:.0%} histórico de compra ({brl(a)}) + {1 - w:.0%} análise de vendas ({brl(b)})."
        )
        return

    if has_a:
        suggestion.recommended_value = a
        suggestion.recommended_source = "buy_ratio"
        suggestion.recommended_reason = "Histórico de compra disponível para este modelo."
    elif has_b:
        suggestion.recommended_value = b
        suggestion.recommended_source = "blend"
        suggestion.recommended_reason = suggestion.blended_reason or "Sem histórico de compra — análise de vendas."


def _apply_fipe_ratio_alert(suggestion: AppraisalSuggestion, request: AppraisalRequest, appraisal_config) -> None:
    """Flag a headline that sits above `fipe_ratio_alert` × FIPE.

    Not an algorithm hole: the desk closes these deals (0 km or next model year
    taken as trade-in on a new-car sale), but in 2026 a third of the 78 closed
    deals above 95 % of FIPE ended with a negative margin (half in Hyundai/Toyota/BYD). The number stays; the
    screen warns.
    """
    fipe = request.fipe_price
    value = suggestion.recommended_value
    if fipe is None or fipe <= 0 or value is None or value <= 0:
        return
    ratio = float(value) / float(fipe)
    suggestion.recommended_fipe_ratio = ratio
    threshold = getattr(appraisal_config, "fipe_ratio_alert", None) if appraisal_config else None
    if threshold is None or ratio <= float(threshold):
        return
    suggestion.above_fipe_alert = (
        f"⚠️ Valor recomendado a {ratio:.0%} da FIPE (acima de {float(threshold):.0%}). "
        f"Nos fechamentos de 2026 nessa faixa — 0 km ou ano seguinte, em geral troca na venda de um "
        f"novo — um terço saiu com margem negativa. Confira a margem da venda antes de fechar."
    )


def _apply_official_gate(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    appraisal_config,
    reference_date: Optional[pd.Timestamp] = None,
) -> None:
    """Decide whether the headline is an official price or a suggestion for the desk.

    Henri's rule: hard cars (old, high KM, 0 km / next model year, brands without
    base, low confidence) still get a number, but not an official one. Every
    threshold lives in config.official_gate and was measured on the backtest.
    """
    cfg = getattr(appraisal_config, "official_gate", None) if appraisal_config else None
    if cfg is None or not cfg.enabled:
        return
    if suggestion.recommended_value is None or suggestion.recommended_value <= 0:
        suggestion.price_mode = "sugestao"
        suggestion.price_mode_reasons = ["sem valor recomendado"]
        return

    reasons: list[str] = []
    allowed = [str(c).lower() for c in (cfg.allowed_confidence or [])]
    if (suggestion.confidence or "").lower() not in allowed:
        reasons.append(f"confiança {suggestion.confidence} (preço oficial exige {' ou '.join(allowed)})")

    ref_year = (reference_date if reference_date is not None else pd.Timestamp.today()).year
    age = ref_year - int(request.year_model)
    if cfg.max_age_years is not None and age > cfg.max_age_years:
        reasons.append(f"{age} anos de idade (limite {cfg.max_age_years})")
    km = request.km
    if cfg.max_km is not None and km is not None and km > cfg.max_km:
        reasons.append(f"{km:,} km (limite {cfg.max_km:,})".replace(",", "."))
    if cfg.exclude_new and (age < 0 or (km is not None and km < cfg.new_km_threshold)):
        reasons.append("0 km / ano-modelo seguinte (a mesa paga acima do ideal nesses carros)")
    brand = (request.brand or "").strip().upper()
    if brand in {b.strip().upper() for b in cfg.exclude_brands}:
        reasons.append(f"marca {brand} sem base suficiente")
    model_key = (request.model_red or "").strip().upper()
    for prefix in cfg.exclude_models:
        if model_key.startswith(prefix.strip().upper()):
            reasons.append(f"modelo {prefix.strip().upper()} fora do portão")
            break
    if cfg.exclude_blindado and request.blindado:
        reasons.append("blindado (prêmio estimado, não medido)")
    closed = suggestion.buy_ratio_closed_deal_count or 0
    if cfg.min_closed_deals and closed < cfg.min_closed_deals:
        reasons.append(f"{closed} compras fechadas do modelo (mínimo {cfg.min_closed_deals})")

    suggestion.price_mode = "oficial" if not reasons else "sugestao"
    suggestion.price_mode_reasons = reasons


# ── Orchestration helpers ────────────────────────────────────────────────────

def _select_comparables(
    sales_df: pd.DataFrame,
    request: AppraisalRequest,
    year_tolerance: int,
    min_comparables: int,
) -> tuple[pd.DataFrame, bool, str]:
    """Trim-level match first; fall back to model_red if too few rows."""
    if request.model_trim and "model_trim" in sales_df.columns:
        trim_df = find_comparables(
            sales_df=sales_df,
            model_key=request.model_trim,
            match_column="model_trim",
            year_model=request.year_model,
            year_tolerance=year_tolerance,
        )
        if len(trim_df) >= min_comparables:
            logger.info(
                f"Using trim-level match: {request.model_trim} ({len(trim_df)} comparables)"
            )
            return trim_df, True, request.model_trim
        logger.info(
            f"Trim {request.model_trim} has only {len(trim_df)} comps, "
            f"falling back to {request.model_red}"
        )

    df = find_comparables(
        sales_df=sales_df,
        model_key=request.model_red,
        match_column="model_red",
        year_model=request.year_model,
        year_tolerance=year_tolerance,
    )
    tokens = request.model_red.strip().upper().split()
    while len(df) < min_comparables and len(tokens) > 2:
        tokens = tokens[:-1]
        family = " ".join(tokens)
        df = find_comparables(
            sales_df=sales_df, model_key=family, match_column="model_red",
            year_model=request.year_model, year_tolerance=year_tolerance, prefix=True,
        )
        if len(df) >= min_comparables:
            logger.info(f"{request.model_red}: {len(df)} comparables at family level {family}")
            return df, False, family
    return df, False, request.model_red


def _resolve_target_margins(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    fipe_mode: bool,
    loja_df: pd.DataFrame,
    revenda_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    loja_spread: Optional[float],
    revenda_spread: Optional[float],
    year_pct_per_year: float,
    loja_target_margin: float,
    revenda_target_margin: float,
    appraisal_config,
) -> tuple[float, float]:
    """Return the effective (Loja, Revenda) target margins in %.

    When `appraisal_config.dynamic_margin.enabled` is True, computes the target
    per-channel from the dynamic-margin engine, using the best available sale-price
    estimate to pick the price band:
        - FIPE mode → request.fipe_price × (1 + channel_spread)
        - Otherwise → median of year-adjusted historical prices for the channel
    If the dynamic config is unavailable or disabled, returns the static fallbacks.
    """
    dm_cfg = getattr(appraisal_config, "dynamic_margin", None) if appraisal_config else None
    if dm_cfg is None or not dm_cfg.enabled:
        # Even in the static-margin path, brand tier may adjust the target.
        loja_final, revenda_final = _apply_brand_tier_adjustment(
            suggestion=suggestion,
            request=request,
            loja_margin=loja_target_margin,
            revenda_margin=revenda_target_margin,
            appraisal_config=appraisal_config,
        )
        suggestion.loja_target_margin_percent = loja_final
        suggestion.revenda_target_margin_percent = revenda_final
        return loja_final, revenda_final

    loja_ref_price = _estimate_sale_price_for_margin(
        fipe_mode=fipe_mode,
        fipe_price=float(request.fipe_price) if request.fipe_price else None,
        channel_spread=loja_spread,
        channel_df=loja_df,
        target_year=request.year_model,
        year_pct_per_year=year_pct_per_year,
    )
    revenda_ref_price = _estimate_sale_price_for_margin(
        fipe_mode=fipe_mode,
        fipe_price=float(request.fipe_price) if request.fipe_price else None,
        channel_spread=revenda_spread,
        channel_df=revenda_df,
        target_year=request.year_model,
        year_pct_per_year=year_pct_per_year,
    )

    loja_margin, revenda_margin = loja_target_margin, revenda_target_margin

    if loja_ref_price is not None:
        dm_loja: DynamicMarginResult = compute_target_margin(
            sale_price=loja_ref_price,
            channel="Loja",
            model_red=request.model_red,
            sales_df=sales_df,
            config=dm_cfg,
        )
        loja_margin = dm_loja.target_pct
        suggestion.loja_margin_base_pct = dm_loja.base_pct
        suggestion.loja_margin_speed_adj_pp = dm_loja.speed_adjustment_pp
        suggestion.loja_margin_volatility_adj_pp = dm_loja.volatility_adjustment_pp
        suggestion.loja_margin_capped = dm_loja.capped
        suggestion.model_sample_size_for_margin = dm_loja.model_sample_size
        suggestion.model_median_days_in_stock = dm_loja.model_median_days
        suggestion.model_margin_std_pp = dm_loja.model_margin_std

    if revenda_ref_price is not None:
        dm_rev: DynamicMarginResult = compute_target_margin(
            sale_price=revenda_ref_price,
            channel="Revenda",
            model_red=request.model_red,
            sales_df=sales_df,
            config=dm_cfg,
        )
        revenda_margin = dm_rev.target_pct
        suggestion.revenda_margin_base_pct = dm_rev.base_pct
        suggestion.revenda_margin_speed_adj_pp = dm_rev.speed_adjustment_pp
        suggestion.revenda_margin_volatility_adj_pp = dm_rev.volatility_adjustment_pp
        suggestion.revenda_margin_capped = dm_rev.capped

    # Apply brand-tier aggressiveness adjustment on top of the band/speed/vol result
    loja_margin, revenda_margin = _apply_brand_tier_adjustment(
        suggestion=suggestion,
        request=request,
        loja_margin=loja_margin,
        revenda_margin=revenda_margin,
        appraisal_config=appraisal_config,
    )

    # Update the display fields so the UI shows the effective targets
    suggestion.loja_target_margin_percent = loja_margin
    suggestion.revenda_target_margin_percent = revenda_margin

    return loja_margin, revenda_margin


def _apply_brand_tier_adjustment(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    loja_margin: float,
    revenda_margin: float,
    appraisal_config,
) -> tuple[float, float]:
    """Shift target margins by the brand-tier adjustment (SAFE/NEUTRAL/RISKY).

    SAFE brands (Toyota/Honda/Hyundai) carry a negative pp (lower margin
    required → more aggressive trade offer). RISKY brands carry positive pp.
    Applied to BOTH channels. Records the tier info on the suggestion.
    """
    bt_cfg = getattr(appraisal_config, "brand_tier", None) if appraisal_config else None
    info = classify_brand(request.brand, bt_cfg)

    suggestion.brand_tier = info.tier
    suggestion.brand_tier_adjustment_pp = info.adjustment_pp
    suggestion.brand_tier_reason = info.reason

    if info.adjustment_pp == 0.0:
        return loja_margin, revenda_margin

    return loja_margin + info.adjustment_pp, revenda_margin + info.adjustment_pp


def _estimate_sale_price_for_margin(
    fipe_mode: bool,
    fipe_price: Optional[float],
    channel_spread: Optional[float],
    channel_df: pd.DataFrame,
    target_year: int,
    year_pct_per_year: float,
) -> Optional[float]:
    """Best-effort sale-price estimate for picking a margin band.

    Note: this is the SAME formula used downstream in `_compute_channel_prices`;
    we just need it early for band lookup. Keeping it as a separate helper
    avoids coupling the two stages.
    """
    if fipe_mode and fipe_price and fipe_price > 0:
        base = fipe_price
        if channel_spread is not None:
            base *= 1.0 + channel_spread
        return base
    if len(channel_df) > 0:
        year_adj = year_adjusted_prices(channel_df, target_year, year_pct_per_year)
        return float(year_adj.median())
    return None


def _apply_km_factors(
    request: AppraisalRequest,
    suggestion: AppraisalSuggestion,
    appraisal_config=None,
) -> tuple[float, float]:
    """Compute per-channel KM percent adjustments and store metadata on the suggestion.

    When `appraisal_config.km_curve.enabled=True`, the piecewise empirical
    curve is used; otherwise the legacy linear formula is applied.
    """
    km_ref = calc_km_referencia(request.year_model) if request.km is not None else None
    suggestion.km_referencia = km_ref

    if request.km is None:
        return 0.0, 0.0

    km_curve = getattr(appraisal_config, "km_curve", None)

    loja_pct = calc_ajuste_km_pct(
        request.brand, "Loja", request.km, request.year_model, km_curve=km_curve
    )
    revenda_pct = calc_ajuste_km_pct(
        request.brand, "Revenda", request.km, request.year_model, km_curve=km_curve
    )
    suggestion.fator_km_loja = get_fator_km(request.brand, "Loja")
    suggestion.fator_km_revenda = get_fator_km(request.brand, "Revenda")
    suggestion.loja_km_adjustment_pct = loja_pct
    suggestion.revenda_km_adjustment_pct = revenda_pct
    return loja_pct, revenda_pct


def _apply_fipe_spreads(
    suggestion: AppraisalSuggestion,
    loja_df: pd.DataFrame,
    revenda_df: pd.DataFrame,
    fipe_mode: bool,
    fipe_client,
    fipe_brand_code: Optional[str],
    fipe_model_code: Optional[str],
    fipe_year_code: Optional[str],
    reference_date: pd.Timestamp,
    recency_halflife_days: float,
    appraisal_config=None,
) -> tuple[Optional[float], Optional[float]]:
    """Compute FIPE spreads, applying a fixed-ratio fallback when data is scarce.

    When the per-channel sample size (N comparables with a successful FIPE
    lookup) is below `fipe_spread.min_sample_for_spread`, the data-derived
    spread is too noisy to trust. In that case:

        • Revenda → fall back to `fipe_spread.revenda_fallback_ratio`
                    (default 0.80, i.e. FIPE × 0.80 — typical B2B discount)
        • Loja    → fall back only if `loja_fallback_ratio` is set (default None)

    The data-derived spreads remain stored on the suggestion for display; the
    suggestion also records whether a fallback was used and with which ratio,
    so the UI can be transparent about it.
    """
    can_compute = (
        fipe_mode
        and fipe_client is not None
        and fipe_brand_code
        and fipe_model_code
        and fipe_year_code
    )

    # Data-derived spreads (None when client/codes missing or no FIPE hits)
    fs_cfg_early = getattr(appraisal_config, "fipe_spread", None) if appraisal_config else None
    per_row_year = bool(getattr(fs_cfg_early, "comparable_year_fipe", False))
    aggregation = str(getattr(fs_cfg_early, "aggregation", "mean"))
    if can_compute:
        loja_spread, loja_n = compute_fipe_spreads(
            loja_df, fipe_client, fipe_brand_code, fipe_model_code,
            fipe_year_code, reference_date, recency_halflife_days,
            per_row_year=per_row_year, aggregation=aggregation,
        )
        revenda_spread, revenda_n = compute_fipe_spreads(
            revenda_df, fipe_client, fipe_brand_code, fipe_model_code,
            fipe_year_code, reference_date, recency_halflife_days,
            per_row_year=per_row_year, aggregation=aggregation,
        )
    else:
        loja_spread, loja_n = None, 0
        revenda_spread, revenda_n = None, 0

    # Store raw (data-derived) values for UI transparency
    suggestion.loja_fipe_spread_pct = loja_spread
    suggestion.revenda_fipe_spread_pct = revenda_spread
    suggestion.loja_spread_sample_size = loja_n
    suggestion.revenda_spread_sample_size = revenda_n

    # Resolve fallbacks (only meaningful in FIPE mode)
    fs_cfg = getattr(appraisal_config, "fipe_spread", None) if appraisal_config else None
    if fs_cfg is None or not fipe_mode:
        return loja_spread, revenda_spread

    min_n = fs_cfg.min_sample_for_spread

    effective_loja = loja_spread
    if (loja_spread is None or loja_n < min_n) and fs_cfg.loja_fallback_ratio is not None:
        effective_loja = fs_cfg.loja_fallback_ratio - 1.0
        suggestion.loja_used_fallback_spread = True
        suggestion.loja_fallback_ratio = fs_cfg.loja_fallback_ratio
        logger.info(
            f"Loja: insufficient spread data (n={loja_n} < {min_n}), "
            f"using fallback FIPE x {fs_cfg.loja_fallback_ratio}"
        )

    effective_revenda = revenda_spread
    if (revenda_spread is None or revenda_n < min_n) and fs_cfg.revenda_fallback_ratio is not None:
        effective_revenda = fs_cfg.revenda_fallback_ratio - 1.0
        suggestion.revenda_used_fallback_spread = True
        suggestion.revenda_fallback_ratio = fs_cfg.revenda_fallback_ratio
        logger.info(
            f"Revenda: insufficient spread data (n={revenda_n} < {min_n}), "
            f"using fallback FIPE x {fs_cfg.revenda_fallback_ratio}"
        )

    return effective_loja, effective_revenda


def _compute_channel_prices(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    loja_df: pd.DataFrame,
    revenda_df: pd.DataFrame,
    loja_km_pct: float,
    revenda_km_pct: float,
    loja_spread: Optional[float],
    revenda_spread: Optional[float],
    fipe_mode: bool,
    has_sale_date: bool,
    reference_date: pd.Timestamp,
    year_pct_per_year: float,
    recency_halflife_days: float,
    loja_target_margin: float,
    revenda_target_margin: float,
    margin_basis: str = "markup",
    tax_pct: float = 0.0,
) -> None:
    """Compute estimated sale + max trade value for both channels.

    Writes directly onto `suggestion`.
    """
    def _channel_price(
        channel_df: pd.DataFrame,
        km_pct: float,
        channel_spread: Optional[float],
    ) -> tuple[float, Decimal]:
        """(base_price, km-adjusted_price) for a channel.

        FIPE mode:  base = FIPE × (1 + spread)
        Otherwise:  base = weighted/simple median of year-adjusted comparables.
        """
        if fipe_mode:
            base = float(request.fipe_price)  # type: ignore[arg-type]
            if channel_spread is not None:
                base *= 1.0 + channel_spread
        elif len(channel_df) > 0:
            year_adj = year_adjusted_prices(channel_df, request.year_model, year_pct_per_year)
            if has_sale_date:
                w = compute_weights(channel_df, reference_date, recency_halflife_days)
                base = weighted_median(year_adj, w)
            else:
                base = float(year_adj.median())
        else:
            return 0.0, Decimal("0")

        km_adj = Decimal(str(base)) * Decimal(str(km_pct))
        return base, max(Decimal(str(base)) + km_adj, Decimal("0"))

    def _hist_median(channel_df: pd.DataFrame) -> float:
        """Simple historical median (no weighting) for FIPE-spread display."""
        if len(channel_df) == 0:
            return 0.0
        year_adj = year_adjusted_prices(channel_df, request.year_model, year_pct_per_year)
        return float(year_adj.median())

    def _channel_trade_band(
        channel_df: pd.DataFrame,
        km_pct: float,
        target_margin: float,
    ) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """P25/P75 band of max_trade_value derived from same-channel dispersion.

        Not computed in fipe_mode (which produces a single point via spread
        median, no within-channel distribution to quantile over). Skipped
        when fewer than 4 comparables exist (too noisy).
        """
        if fipe_mode or len(channel_df) < 4:
            return None, None
        year_adj = year_adjusted_prices(channel_df, request.year_model, year_pct_per_year)
        p25 = float(year_adj.quantile(0.25))
        p75 = float(year_adj.quantile(0.75))
        if p25 <= 0 or p75 <= 0:
            return None, None
        p25_km = Decimal(str(p25)) * (Decimal("1") + Decimal(str(km_pct)))
        p75_km = Decimal(str(p75)) * (Decimal("1") + Decimal(str(km_pct)))
        low = _calc_max_trade(
            estimated_sale_price=p25_km,
            target_margin_percent=target_margin,
            repair_cost=request.estimated_repair_cost,
            basis=margin_basis,
            tax_pct=tax_pct,
        )
        high = _calc_max_trade(
            estimated_sale_price=p75_km,
            target_margin_percent=target_margin,
            repair_cost=request.estimated_repair_cost,
            basis=margin_basis,
            tax_pct=tax_pct,
        )
        return _round_to_500(low), _round_to_500(high)

    # Loja
    if len(loja_df) > 0:
        suggestion.loja_comparables = build_comparables(loja_df)
        suggestion.loja_comparables_count = len(suggestion.loja_comparables)
        suggestion.loja_avg_days_in_stock = round(float(loja_df["days_in_stock"].mean()), 1)

    _, loja_adjusted = _channel_price(loja_df, loja_km_pct, loja_spread)
    if loja_adjusted > 0:
        suggestion.loja_estimated_sale_price = _round_to_500(loja_adjusted)
        suggestion.loja_max_trade_value = _calc_max_trade(
            estimated_sale_price=loja_adjusted,
            target_margin_percent=loja_target_margin,
            repair_cost=request.estimated_repair_cost,
            basis=margin_basis,
            tax_pct=tax_pct,
        )
        loja_low, loja_high = _channel_trade_band(loja_df, loja_km_pct, loja_target_margin)
        suggestion.loja_max_trade_low = loja_low
        suggestion.loja_max_trade_high = loja_high
        if fipe_mode and len(loja_df) > 0:
            hist = _hist_median(loja_df)
            if hist > 0 and float(request.fipe_price) > 0:  # type: ignore[arg-type]
                suggestion.fipe_historical_spread_pct = (
                    (hist - float(request.fipe_price)) / float(request.fipe_price)
                )

    # Revenda
    if len(revenda_df) > 0:
        suggestion.revenda_comparables = build_comparables(revenda_df)
        suggestion.revenda_comparables_count = len(suggestion.revenda_comparables)
        suggestion.revenda_avg_days_in_stock = round(
            float(revenda_df["days_in_stock"].mean()), 1
        )

    _, revenda_adjusted = _channel_price(revenda_df, revenda_km_pct, revenda_spread)
    if revenda_adjusted > 0:
        suggestion.revenda_estimated_sale_price = _round_to_500(revenda_adjusted)
        suggestion.revenda_max_trade_value = _calc_max_trade(
            estimated_sale_price=revenda_adjusted,
            target_margin_percent=revenda_target_margin,
            repair_cost=request.estimated_repair_cost,
            basis=margin_basis,
            tax_pct=tax_pct,
        )
        rev_low, rev_high = _channel_trade_band(revenda_df, revenda_km_pct, revenda_target_margin)
        suggestion.revenda_max_trade_low = rev_low
        suggestion.revenda_max_trade_high = rev_high


def _apply_blindado_premium(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    loja_target_margin: float,
    revenda_target_margin: float,
    appraisal_config,
    margin_basis: str = "markup",
    tax_pct: float = 0.0,
) -> None:
    """Add the armored-car premium to both channel sale prices (and re-derive trade values)."""
    suggestion.blindado = True
    premium_table = (
        appraisal_config.blindado.premium_by_year
        if appraisal_config is not None
        else None
    )
    premium = blindado_sale_premium(request.year_model, premium_table)
    if premium <= 0:
        return

    if suggestion.loja_estimated_sale_price is not None:
        new_loja = suggestion.loja_estimated_sale_price + premium
        suggestion.loja_estimated_sale_price = _round_to_500(new_loja)
        suggestion.loja_max_trade_value = _calc_max_trade(
            estimated_sale_price=new_loja,
            target_margin_percent=loja_target_margin,
            repair_cost=request.estimated_repair_cost,
            basis=margin_basis,
            tax_pct=tax_pct,
        )
    if suggestion.revenda_estimated_sale_price is not None:
        new_rev = suggestion.revenda_estimated_sale_price + premium
        suggestion.revenda_estimated_sale_price = _round_to_500(new_rev)
        suggestion.revenda_max_trade_value = _calc_max_trade(
            estimated_sale_price=new_rev,
            target_margin_percent=revenda_target_margin,
            repair_cost=request.estimated_repair_cost,
            basis=margin_basis,
            tax_pct=tax_pct,
        )
    suggestion.blindado_premium_applied = premium
    logger.info(
        f"Blindado premium applied: R$ {premium:,.0f} for year {request.year_model}"
    )


def _apply_buy_ratio(
    suggestion: AppraisalSuggestion,
    request: AppraisalRequest,
    appraisal_df,
    year_profile: Optional[dict],
    appraisal_config,
    reference_date: Optional[pd.Timestamp] = None,
    km_slope: Optional[float] = None,
    brand_year_profile: Optional[dict] = None,
) -> None:
    """Run the buy-ratio engine and populate the primary anchor fields."""
    buy_result: BuyRatioResult = compute_buy_ratio(
        model_red=request.model_red,
        year_model=request.year_model,
        km=request.km,
        appraisal_df=appraisal_df,
        year_profile=year_profile,
        config=appraisal_config.buy_ratio if appraisal_config is not None else None,
        reference_date=reference_date,
        km_slope=km_slope,
        brand_year_profile=brand_year_profile,
        prefer_purpose=(
            "REPASSE"
            if (appraisal_config is not None and getattr(appraisal_config.buy_ratio, "purpose_aware", False)
                and (request.purpose or "auto").lower() == "revenda")
            else None
        ),
    )
    suggestion.buy_ratio_km_min = buy_result.km_min_used
    suggestion.buy_ratio_km_max = buy_result.km_max_used
    suggestion.buy_ratio_purpose_filtered = buy_result.purpose_filtered

    if not buy_result.available:
        suggestion.buy_ratio_description = buy_result.description
        return

    suggestion.buy_ratio_available = True
    suggestion.buy_ratio_median = buy_result.ratio_median
    suggestion.buy_ratio_p25 = buy_result.ratio_p25
    suggestion.buy_ratio_p75 = buy_result.ratio_p75
    suggestion.buy_ratio_sample_size = buy_result.sample_size
    suggestion.buy_ratio_closed_deal_count = buy_result.closed_deal_count
    suggestion.buy_ratio_offered_count = buy_result.offered_count
    suggestion.buy_ratio_tier = buy_result.tier
    suggestion.buy_ratio_description = buy_result.description

    fipe_float = float(request.fipe_price)
    suggestion.buy_ratio_price = _round_to_500(
        Decimal(str(fipe_float * buy_result.ratio_median))
    )
    suggestion.buy_ratio_low = _round_to_500(
        Decimal(str(fipe_float * buy_result.ratio_p25))
    )
    suggestion.buy_ratio_high = _round_to_500(
        Decimal(str(fipe_float * buy_result.ratio_p75))
    )

    if suggestion.loja_max_trade_value and suggestion.loja_max_trade_value > 0:
        sales_based = float(suggestion.loja_max_trade_value)
        buy_based = float(suggestion.buy_ratio_price)
        suggestion.anchor_divergence_pct = (buy_based - sales_based) / sales_based


# ── Small math helpers (kept here for clarity) ──────────────────────────────


def _calc_max_trade(
    estimated_sale_price: Decimal,
    target_margin_percent: float,
    repair_cost: Decimal,
    basis: str = "markup",
    tax_pct: float = 0.0,
) -> Decimal:
    """Max trade-in value that preserves the target gross margin.

    markup (legacy): max_trade = sale / (1 + m) − repair
    sale:            max_trade = sale × (1 − tax − m) − repair   (m and tax as % of the sale)

    Rounded to the nearest R$500.
    """
    if estimated_sale_price <= 0:
        return Decimal("0")

    if basis == "sale":
        max_cost = estimated_sale_price * Decimal(str(1 - tax_pct / 100 - target_margin_percent / 100))
    else:
        margin_factor = Decimal(str(1 + target_margin_percent / 100))
        max_cost = estimated_sale_price / margin_factor
    max_trade = max_cost - repair_cost
    return _round_to_500(max(max_trade, Decimal("0")))


def _round_to_500(value: Decimal) -> Decimal:
    """Round a Decimal to the nearest R$500."""
    return (value / 500).to_integral_value(rounding=ROUND_HALF_UP) * 500


def _assess_confidence(
    total: int,
    loja_count: int,
    revenda_count: int,
    min_comparables: int,
) -> str:
    """Map comparable count to a confidence band: sem dados / baixa / media / alta."""
    if total == 0:
        return "sem dados"
    if total < min_comparables:
        return "baixa"
    if total < min_comparables * 3:
        return "media"
    return "alta"
