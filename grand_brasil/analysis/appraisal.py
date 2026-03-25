"""Appraisal engine — suggests trade-in values based on comparable sales.

V1: Pure historical comparables approach.
- Finds similar cars (same MODELO RED, close year range) from sales history
- Removes blindados via year-band premium threshold (anchored to p75 median)
- Splits by channel (Loja / Revenda)
- Calculates median sale price per channel
- Applies target margin to derive max trade-in value
- Subtracts estimated repair cost

Blindado filtering logic:
- Anchor = median of the bottom 75% of sale prices (immune to blindado inflation)
- If a sale price exceeds anchor + year-band threshold, it is flagged as blindado
- Year bands: 2024-2025 -> +45k, 2022-2023 -> +35k, 2020-2021 -> +22.5k
- Cars from 2019 or older: no blindado filtering applied

Future improvements (V2+):
- FIPE price as anchor/ceiling
- KM-based adjustments
- Recency weighting (recent sales worth more)
- Days-in-stock prediction
- Seasonal patterns
- Confidence intervals
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import pandas as pd

from grand_brasil.models.appraisal import (
    AppraisalRequest,
    AppraisalSuggestion,
    Comparable,
)

logger = logging.getLogger(__name__)


def appraise(
    request: AppraisalRequest,
    sales_df: pd.DataFrame,
    year_tolerance: int = 2,
    loja_target_margin: float = 15.0,
    revenda_target_margin: float = 5.5,
    min_comparables: int = 3,
    km_pct_per_10k: float = 1.0,
    recency_halflife_days: float = 180.0,
    year_pct_per_year: float = 10.0,
) -> AppraisalSuggestion:
    """Generate a trade-in appraisal based on comparable historical sales.

    Args:
        request: The car being appraised.
        sales_df: Historical sales DataFrame (from load_sales_history).
        year_tolerance: How many years +/- to search for comparables.
        loja_target_margin: Target gross margin % for Loja (B2C) sales.
        revenda_target_margin: Target gross margin % for Revenda (B2B) sales.
        min_comparables: Minimum comparables needed for "media" confidence.

    Returns:
        AppraisalSuggestion with trade values for both channels.
    """
    # ── Find comparables (trim-level first, fallback to model_red) ──
    used_trim = False
    match_key = request.model_red

    if request.model_trim and "model_trim" in sales_df.columns:
        # Try trim-level match first
        trim_df = _find_comparables(
            sales_df=sales_df,
            model_key=request.model_trim,
            match_column="model_trim",
            year_model=request.year_model,
            year_tolerance=year_tolerance,
        )
        if len(trim_df) >= min_comparables:
            comparables_df = trim_df
            used_trim = True
            match_key = request.model_trim
            logger.info(
                f"Using trim-level match: {request.model_trim} "
                f"({len(trim_df)} comparables)"
            )
        else:
            # Not enough trim-level data, fall back to model_red
            logger.info(
                f"Trim {request.model_trim} has only {len(trim_df)} comps, "
                f"falling back to {request.model_red}"
            )
            comparables_df = _find_comparables(
                sales_df=sales_df,
                model_key=request.model_red,
                match_column="model_red",
                year_model=request.year_model,
                year_tolerance=year_tolerance,
            )
    else:
        comparables_df = _find_comparables(
            sales_df=sales_df,
            model_key=request.model_red,
            match_column="model_red",
            year_model=request.year_model,
            year_tolerance=year_tolerance,
        )

    # ── Remove blindados ──
    raw_count = len(comparables_df)
    comparables_df = _remove_blindados(comparables_df, request.year_model)
    outliers_removed = raw_count - len(comparables_df)

    total_comps = len(comparables_df)

    # Split by channel
    loja_df = comparables_df[comparables_df["sale_channel"] == "Loja"]
    revenda_df = comparables_df[comparables_df["sale_channel"] == "Revenda"]

    # ── Build suggestion ──
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
        # V3: FIPE metadata echo
        fipe_code=request.fipe_code,
        fipe_reference_month=request.fipe_reference_month,
        fipe_model_name=request.fipe_model_name,
    )

    # Without FIPE and without comparables: nothing to compute
    if total_comps == 0 and not fipe_mode:
        suggestion.confidence = "sem dados"
        suggestion.rationale = (
            f"Nenhuma venda comparavel encontrada para {match_key} "
            f"ano {request.year_model} (tolerancia: +/-{year_tolerance} anos)."
        )
        return suggestion

    # Year range used (may be None when total_comps == 0 in FIPE mode)
    if total_comps > 0:
        min_year = int(comparables_df["year_model"].min())
        max_year = int(comparables_df["year_model"].max())
        suggestion.year_range_used = f"{min_year} - {max_year}"

    # ── V2: Weighting / adjustment setup ──
    has_sale_date = (
        "sale_date" in comparables_df.columns
        and comparables_df["sale_date"].notna().any()
    )
    suggestion.used_weighted_median = has_sale_date and not fipe_mode
    reference_date = pd.Timestamp.now()

    # ── V2: KM adjustment percentage (computed once from all comparables) ──
    km_pct, median_km = _km_adjustment_pct(request.km, comparables_df, km_pct_per_10k)
    suggestion.km_adjustment_pct = km_pct if request.km is not None else None
    suggestion.comparables_median_km = median_km

    # ── Helper: compute base price and adjusted price for a channel ──
    def _channel_price(channel_df: pd.DataFrame) -> tuple[float, Decimal]:
        """Return (historical_median, adjusted_price) for a channel DataFrame."""
        if fipe_mode:
            base = float(request.fipe_price)  # type: ignore[arg-type]
        elif len(channel_df) > 0:
            year_adj = _year_adjusted_prices(channel_df, request.year_model, year_pct_per_year)
            if has_sale_date:
                w = _compute_weights(channel_df, reference_date, recency_halflife_days)
                base = _weighted_median(year_adj, w)
            else:
                base = float(year_adj.median())
        else:
            return 0.0, Decimal("0")

        km_adj = Decimal(str(base)) * Decimal(str(km_pct))
        adj = max(Decimal(str(base)) + km_adj, Decimal("0"))
        return base, adj

    def _hist_median(channel_df: pd.DataFrame) -> float:
        """Compute unweighted historical median for FIPE spread calculation."""
        if len(channel_df) == 0:
            return 0.0
        year_adj = _year_adjusted_prices(channel_df, request.year_model, year_pct_per_year)
        return float(year_adj.median())

    # ── Loja (B2C) ──
    if len(loja_df) > 0:
        suggestion.loja_comparables = _build_comparables(loja_df)
        suggestion.loja_comparables_count = len(suggestion.loja_comparables)
        suggestion.loja_avg_days_in_stock = round(float(loja_df["days_in_stock"].mean()), 1)

    loja_base, loja_adjusted = _channel_price(loja_df)
    if loja_adjusted > 0:
        suggestion.loja_estimated_sale_price = _round_to_500(loja_adjusted)
        suggestion.loja_max_trade_value = _calc_max_trade(
            estimated_sale_price=loja_adjusted,
            target_margin_percent=loja_target_margin,
            repair_cost=request.estimated_repair_cost,
        )
        if fipe_mode and len(loja_df) > 0:
            hist = _hist_median(loja_df)
            if hist > 0 and float(request.fipe_price) > 0:  # type: ignore[arg-type]
                suggestion.fipe_historical_spread_pct = (hist - float(request.fipe_price)) / float(request.fipe_price)

    # ── Revenda (B2B) ──
    if len(revenda_df) > 0:
        suggestion.revenda_comparables = _build_comparables(revenda_df)
        suggestion.revenda_comparables_count = len(suggestion.revenda_comparables)
        suggestion.revenda_avg_days_in_stock = round(float(revenda_df["days_in_stock"].mean()), 1)

    _, revenda_adjusted = _channel_price(revenda_df)
    if revenda_adjusted > 0:
        suggestion.revenda_estimated_sale_price = _round_to_500(revenda_adjusted)
        suggestion.revenda_max_trade_value = _calc_max_trade(
            estimated_sale_price=revenda_adjusted,
            target_margin_percent=revenda_target_margin,
            repair_cost=request.estimated_repair_cost,
        )

    if fipe_mode:
        suggestion.fipe_used_as_anchor = True

    # ── FIPE ratios (for display) ──
    suggestion.loja_fipe_ratio = _fipe_ratio(
        suggestion.loja_estimated_sale_price, request.fipe_price
    )
    suggestion.revenda_fipe_ratio = _fipe_ratio(
        suggestion.revenda_estimated_sale_price, request.fipe_price
    )

    # ── Confidence ──
    suggestion.confidence = _assess_confidence(
        total=total_comps,
        loja_count=len(loja_df),
        revenda_count=len(revenda_df),
        min_comparables=min_comparables,
    )

    # ── Rationale ──
    suggestion.rationale = _build_rationale(suggestion, year_tolerance)

    return suggestion


# ── Internal helpers ────────────────────────────────────────────────


def _weighted_median(values: pd.Series, weights: pd.Series) -> float:
    """Compute a weighted median.

    Falls back to simple median if all weights are zero.
    """
    total = weights.sum()
    if total == 0:
        return float(values.median())

    df = pd.DataFrame({"v": values.values, "w": weights.values})
    df = df.sort_values("v")
    df["cumw"] = df["w"].cumsum() / total
    return float(df.loc[df["cumw"] >= 0.5, "v"].iloc[0])


def _year_adjusted_prices(
    df: pd.DataFrame,
    target_year: int,
    year_pct_per_year: float,
) -> pd.Series:
    """Adjust each comparable's sale_price to reflect the target year model.

    Formula: adjusted = sale_price × (1 + (target_year - comparable_year) × pct/100)

    Examples (year_pct_per_year=10):
        Comparable 2023, appraising 2024 → × 1.10 (newer = worth more)
        Comparable 2023, appraising 2022 → × 0.90 (older = worth less)
        Comparable 2023, appraising 2023 → × 1.00 (same year, no change)
    """
    factor = df["year_model"].apply(
        lambda y: 1 + (target_year - int(y)) * (year_pct_per_year / 100)
    )
    return df["sale_price"].astype(float) * factor


def _compute_weights(
    df: pd.DataFrame,
    reference_date: pd.Timestamp,
    halflife_days: float,
) -> pd.Series:
    """Compute recency weights for each row using exponential decay.

    w = exp(-λ × days_since_sale), where λ = ln(2) / halflife_days.
    NaT sale_dates receive a neutral weight of 0.5.
    """
    import math
    lam = math.log(2) / max(halflife_days, 1.0)
    weights = []

    for _, row in df.iterrows():
        sd = row.get("sale_date")
        if pd.isna(sd):
            weights.append(0.5)
        else:
            days = max((reference_date - pd.Timestamp(sd)).days, 0)
            weights.append(math.exp(-lam * days))

    return pd.Series(weights, index=df.index)


def _km_adjustment_pct(
    car_km: Optional[int],
    comparables_df: pd.DataFrame,
    km_pct_per_10k: float,
) -> tuple[float, Optional[int]]:
    """Return (adjustment_pct, median_km_of_comparables).

    adjustment_pct > 0 means the car is worth more (fewer km than median).
    Each 10k km below median = +km_pct_per_10k / 100 in price.
    """
    if car_km is None or "km" not in comparables_df.columns:
        return 0.0, None

    km_series = comparables_df["km"].dropna()
    if km_series.empty:
        return 0.0, None

    median_km = int(km_series.median())
    delta_km = median_km - car_km
    pct = delta_km / 10_000 * (km_pct_per_10k / 100)
    return pct, median_km


def _fipe_ratio(
    estimated_sale_price: Optional[Decimal],
    fipe_price: Optional[Decimal],
) -> Optional[float]:
    """Return estimated_sale_price / fipe_price, or None if not applicable."""
    if estimated_sale_price is None or fipe_price is None or fipe_price <= 0:
        return None
    return float(estimated_sale_price / fipe_price)


def _blindado_premium(year_model: int) -> Optional[float]:
    """Return the blindado premium threshold for a given model year.

    Returns None if blindado filtering should not be applied (2019 or older).

    Year bands and thresholds (midpoint of the domain-knowledge ranges):
        2024-2025 -> R$ 45.000  (range: 40k-50k)
        2022-2023 -> R$ 35.000  (range: 30k-40k)
        2020-2021 -> R$ 22.500  (range: 15k-30k)
        2019 and older -> None (no filtering)
    """
    if year_model >= 2024:
        return 45_000.0
    if year_model >= 2022:
        return 35_000.0
    if year_model >= 2020:
        return 22_500.0
    return None


def _remove_blindados(df: pd.DataFrame, year_model: int) -> pd.DataFrame:
    """Remove blindados using a year-band premium threshold.

    Anchor = median of the bottom 75% of sale prices. This makes the anchor
    immune to blindado inflation even when multiple blindados are in the sample.

    A sale is flagged as blindado if:
        sale_price > anchor + blindado_premium(year_model)

    For 2019 or older model years, no filtering is applied.

    Args:
        df: DataFrame of comparables.
        year_model: The model year being appraised (used to pick the threshold).

    Returns:
        Filtered DataFrame with blindados removed.
    """
    premium = _blindado_premium(year_model)

    if premium is None:
        logger.info(f"Blindado filter disabled for year_model {year_model} (2019 or older)")
        return df

    if len(df) == 0:
        return df

    # Anchor: median of the lower 75% — unaffected by high-end blindados
    p75_cutoff = df["sale_price"].quantile(0.75)
    lower_half = df[df["sale_price"] <= p75_cutoff]["sale_price"]
    anchor = float(lower_half.median())

    upper_fence = anchor + premium
    filtered = df[df["sale_price"] <= upper_fence]

    removed = len(df) - len(filtered)
    if removed > 0:
        logger.info(
            f"Removed {removed} blindado(s): anchor={anchor:.0f}, "
            f"premium={premium:.0f}, fence={upper_fence:.0f}"
        )

    return filtered


def _find_comparables(
    sales_df: pd.DataFrame,
    model_key: str,
    match_column: str = "model_red",
    year_model: int = 0,
    year_tolerance: int = 2,
) -> pd.DataFrame:
    """Filter sales history to find comparable vehicles.

    Args:
        sales_df: Sales history DataFrame.
        model_key: Value to match (model_red or model_trim).
        match_column: Column to match against ("model_red" or "model_trim").
        year_model: Target year model.
        year_tolerance: +/- years to include.
    """
    key_upper = model_key.strip().upper()

    if match_column not in sales_df.columns:
        match_column = "model_red"

    mask = (
        (sales_df[match_column] == key_upper)
        & (sales_df["year_model"] >= year_model - year_tolerance)
        & (sales_df["year_model"] <= year_model + year_tolerance)
    )
    result = sales_df[mask].copy()

    logger.info(
        f"Found {len(result)} comparables for {key_upper} "
        f"(col={match_column}) year {year_model} (+/-{year_tolerance})"
    )
    return result


def _build_comparables(df: pd.DataFrame) -> list[Comparable]:
    """Convert DataFrame rows to Comparable model instances."""
    comps = []
    for _, row in df.iterrows():
        comps.append(Comparable(
            sale_price=Decimal(str(row["sale_price"])),
            purchase_cost=Decimal(str(row["purchase_cost"])),
            adjusted_cost=Decimal(str(row["adjusted_cost"])),
            year_model=int(row["year_model"]),
            km=int(row["km"]) if pd.notna(row.get("km")) else None,
            days_in_stock=int(row["days_in_stock"]),
            sale_channel=str(row["sale_channel"]),
            margin_percent=float(row["margin_percent"]) if pd.notna(row.get("margin_percent")) else 0.0,
        ))
    return comps


def _calc_max_trade(
    estimated_sale_price: Decimal,
    target_margin_percent: float,
    repair_cost: Decimal,
) -> Decimal:
    """Calculate maximum trade-in value.

    max_trade = estimated_sale_price / (1 + target_margin/100) - repair_cost

    This ensures that if we buy at max_trade + repair_cost,
    and sell at estimated_sale_price, we achieve the target margin.
    """
    if estimated_sale_price <= 0:
        return Decimal("0")

    margin_factor = Decimal(str(1 + target_margin_percent / 100))
    max_cost = estimated_sale_price / margin_factor
    max_trade = max_cost - repair_cost

    # Round down to nearest 500 (conservative)
    return _round_to_500(max(max_trade, Decimal("0")))


def _round_to_500(value: Decimal) -> Decimal:
    """Round a Decimal value down to the nearest R$ 500."""
    return (value / 500).to_integral_value(rounding=ROUND_HALF_UP) * 500


def _assess_confidence(
    total: int,
    loja_count: int,
    revenda_count: int,
    min_comparables: int,
) -> str:
    """Assess confidence level based on number of comparables."""
    if total == 0:
        return "sem dados"
    if total < min_comparables:
        return "baixa"
    if total < min_comparables * 3:
        return "media"
    return "alta"


def _build_rationale(suggestion: AppraisalSuggestion, year_tolerance: int) -> str:
    """Build a human-readable rationale in PT-BR."""
    display_name = suggestion.fipe_model_name or suggestion.model_trim or suggestion.model_red
    match_level = "versao especifica" if suggestion.used_trim_level else "modelo geral"
    median_method = "ponderada (recencia)" if suggestion.used_weighted_median else "simples"

    parts = []

    if suggestion.fipe_used_as_anchor:
        ref = f" ({suggestion.fipe_reference_month})" if suggestion.fipe_reference_month else ""
        code = f" — codigo {suggestion.fipe_code}" if suggestion.fipe_code else ""
        parts.append(
            f"Preco FIPE{ref}{code} usado como ancora principal. "
            f"Vendas historicas usadas para ajuste de KM e contexto de mercado."
        )
        if suggestion.fipe_historical_spread_pct is not None:
            spread_pct = suggestion.fipe_historical_spread_pct * 100
            direction = "acima" if spread_pct >= 0 else "abaixo"
            parts.append(
                f"Historico de vendas comparaveis: {abs(spread_pct):.1f}% {direction} da FIPE "
                f"({suggestion.total_comparables} vendas)."
            )
    else:
        parts.append(
            f"Avaliacao baseada em {suggestion.total_comparables} vendas comparaveis "
            f"de {display_name} ({suggestion.year_range_used}). "
            f"Nivel de comparacao: {match_level}. Mediana {median_method}.",
        )

    if suggestion.outliers_removed > 0:
        parts.append(
            f"{suggestion.outliers_removed} venda(s) removida(s) como outlier "
            f"(ex: blindados, vendas atipicas)."
        )

    if suggestion.km_adjustment_pct is not None and suggestion.comparables_median_km is not None:
        pct = suggestion.km_adjustment_pct * 100
        sign = "+" if pct >= 0 else ""
        parts.append(
            f"Ajuste de KM: {sign}{pct:.1f}% "
            f"(KM mediano dos comparaveis: {suggestion.comparables_median_km:,} km)."
        )

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

    if suggestion.estimated_repair_cost > 0:
        parts.append(
            f"Custo de reparo estimado de R$ {suggestion.estimated_repair_cost:,.0f} ja descontado."
        )

    parts.append(f"Confianca: {suggestion.confidence}.")

    return " ".join(parts)
