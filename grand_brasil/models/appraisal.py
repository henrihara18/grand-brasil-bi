"""Appraisal models — input/output for the trade-in valuation engine."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class AppraisalRequest(BaseModel):
    """Input for a trade-in appraisal."""

    brand: str                                  # Marca (ex: HYUNDAI)
    model_red: str                              # MODELO RED (ex: HYUNDAI HB20)
    model_trim: Optional[str] = None            # Trim-level key (ex: HONDA HR-V EXL)
    year_model: int                             # Ano modelo
    km: Optional[int] = None                    # Quilometragem
    estimated_repair_cost: Decimal = Decimal("0")  # Custo estimado de reparo
    fipe_price: Optional[Decimal] = None        # Valor FIPE de referencia
    fipe_code: Optional[str] = None             # Codigo FIPE (ex: "004278-1")
    fipe_reference_month: Optional[str] = None  # Mes de referencia (ex: "abril de 2026")
    fipe_model_name: Optional[str] = None       # Nome completo do modelo na FIPE
    blindado: bool = False                      # Veiculo blindado (aplica premio no preco Loja)
    # Finalidade da compra: "auto" usa P(Revenda) para ponderar Loja/Revenda;
    # "loja" / "revenda" forçam o canal correspondente.
    purpose: str = "auto"                       # "auto" | "loja" | "revenda"


class Comparable(BaseModel):
    """A single historical sale used as a comparable."""

    sale_price: Decimal                         # Vl Venda
    purchase_cost: Decimal                      # Custo (what we paid the customer)
    adjusted_cost: Decimal                      # Custo Ajustado (Custo - Bonus)
    year_model: int
    km: Optional[int] = None
    days_in_stock: int
    sale_channel: str                           # "Loja" or "Revenda"
    margin_percent: float                       # % MF
    plate: Optional[str] = None                # Placa
    model_red: Optional[str] = None            # MODELO RED


class AppraisalSuggestion(BaseModel):
    """Output of the appraisal engine — suggested trade values.

    Provides both Loja (B2C) and Revenda (B2B) scenarios.
    """

    # Request echo
    brand: str
    model_red: str
    model_trim: Optional[str] = None            # Trim used for matching
    year_model: int
    km: Optional[int] = None
    estimated_repair_cost: Decimal = Decimal("0")
    used_trim_level: bool = False                # True if matched at trim level

    # Loja (B2C) scenario — target ~15% margin
    loja_estimated_sale_price: Optional[Decimal] = None
    loja_target_margin_percent: float = 15.0
    loja_max_trade_value: Optional[Decimal] = None
    loja_max_trade_low: Optional[Decimal] = None   # P25 band (same-channel dispersion)
    loja_max_trade_high: Optional[Decimal] = None  # P75 band
    loja_comparables_count: int = 0
    loja_avg_days_in_stock: Optional[float] = None

    # Revenda (B2B) scenario — target ~5-6% margin
    revenda_estimated_sale_price: Optional[Decimal] = None
    revenda_target_margin_percent: float = 5.5
    revenda_max_trade_value: Optional[Decimal] = None
    revenda_max_trade_low: Optional[Decimal] = None   # P25 band
    revenda_max_trade_high: Optional[Decimal] = None  # P75 band
    revenda_comparables_count: int = 0
    revenda_avg_days_in_stock: Optional[float] = None

    # Confidence
    total_comparables: int = 0
    outliers_removed: int = 0                    # Removed by the blindado price fence
    confidence: str = "baixa"  # baixa, media, alta
    # Calibrated confidence (analysis/confidence.py): empirical error quantiles
    # of past appraisals with the same profile. source = "calibrada" | "contagem".
    confidence_source: str = "contagem"
    confidence_q50: Optional[float] = None
    confidence_q80: Optional[float] = None
    confidence_q90: Optional[float] = None
    confidence_n: int = 0
    confidence_reason: Optional[str] = None
    year_range_used: Optional[str] = None       # e.g. "2019 - 2023"

    # KM adjustment (por canal, baseado em fator empirico por marca)
    km_referencia: Optional[int] = None          # KM esperado para o ano modelo
    loja_km_adjustment_pct: Optional[float] = None   # % ajuste KM canal Loja
    revenda_km_adjustment_pct: Optional[float] = None # % ajuste KM canal Revenda
    fator_km_loja: Optional[float] = None        # Fator usado (ex: 0.022 = 2.2%/10k)
    fator_km_revenda: Optional[float] = None     # Fator usado (ex: 0.001 = 0.1%/10k)

    # V2: FIPE comparison
    loja_fipe_ratio: Optional[float] = None     # loja_estimated_sale / fipe_price
    revenda_fipe_ratio: Optional[float] = None  # revenda_estimated_sale / fipe_price

    # V3: FIPE historical spread (como vendemos vs FIPE historicamente)
    loja_fipe_spread_pct: Optional[float] = None    # e.g. 0.032 = vendemos 3.2% acima da FIPE
    revenda_fipe_spread_pct: Optional[float] = None
    loja_spread_sample_size: int = 0                # qtd comparaveis com FIPE historica
    revenda_spread_sample_size: int = 0

    # V5: FIPE-spread fallback (quando amostra historica e insuficiente)
    revenda_used_fallback_spread: bool = False
    revenda_fallback_ratio: Optional[float] = None  # e.g. 0.80 = FIPE x 80%
    loja_used_fallback_spread: bool = False
    loja_fallback_ratio: Optional[float] = None

    # V3: FIPE as primary anchor
    fipe_code: Optional[str] = None
    fipe_reference_month: Optional[str] = None
    fipe_model_name: Optional[str] = None
    fipe_used_as_anchor: bool = False            # True when FIPE price is the base
    fipe_historical_spread_pct: Optional[float] = None  # (hist_median - fipe) / fipe

    # V2: Weighting metadata
    used_weighted_median: bool = False           # True if recency/year weights were applied

    # Blindado
    blindado: bool = False                       # True se o veiculo e blindado
    blindado_premium_applied: Optional[Decimal] = None  # Premio adicionado ao preco Loja

    # V5: Dynamic margin — used when dynamic_margin.enabled=true (replaces fixed targets)
    loja_margin_base_pct: Optional[float] = None           # Base from price band
    loja_margin_speed_adj_pp: float = 0.0                  # Days-in-stock penalty (pp)
    loja_margin_volatility_adj_pp: float = 0.0             # Std-of-margin penalty (pp)
    loja_margin_capped: bool = False                       # True if total adjustment hit the cap
    revenda_margin_base_pct: Optional[float] = None
    revenda_margin_speed_adj_pp: float = 0.0
    revenda_margin_volatility_adj_pp: float = 0.0
    revenda_margin_capped: bool = False
    model_sample_size_for_margin: int = 0                  # Rows that backed the per-model adjustment
    model_median_days_in_stock: Optional[float] = None
    model_margin_std_pp: Optional[float] = None

    # V4: Purchase-ratio anchor (from historical appraisal database)
    # This anchor reflects what Grand Brasil ACTUALLY PAID historically,
    # independent of margin targets on the sell side.
    buy_ratio_available: bool = False
    buy_ratio_median: Optional[float] = None     # e.g. 0.87 → we pay 87% of FIPE
    buy_ratio_p25: Optional[float] = None        # Conservative bound
    buy_ratio_p75: Optional[float] = None        # Optimistic bound
    buy_ratio_sample_size: int = 0
    buy_ratio_closed_deal_count: int = 0         # UTILIZADO/REPASSE count
    buy_ratio_offered_count: int = 0             # AVALIADO count (if used as fallback)
    buy_ratio_tier: Optional[str] = None         # Which matching tier produced this
    buy_ratio_km_min: Optional[int] = None       # KM range of the comparables used
    buy_ratio_km_max: Optional[int] = None
    buy_ratio_purpose_filtered: bool = False     # comparables restricted to REPASSE (purpose=revenda)
    buy_ratio_description: Optional[str] = None
    buy_ratio_price: Optional[Decimal] = None    # FIPE × ratio_median
    buy_ratio_low: Optional[Decimal] = None      # FIPE × P25
    buy_ratio_high: Optional[Decimal] = None     # FIPE × P75

    # Divergence diagnostic: how far apart the two anchors sit
    anchor_divergence_pct: Optional[float] = None  # (buy_ratio - sales_based) / sales_based

    # V6: Brand tier (Alavanca B) — pricing aggressiveness adjustment by brand
    brand_tier: Optional[str] = None                    # "SAFE" / "NEUTRAL" / "RISKY"
    brand_tier_adjustment_pp: float = 0.0               # pp added to target margin
    brand_tier_reason: Optional[str] = None             # PT-BR description for UI

    # V6: Channel probability (Alavanca A) — P(Revenda) for this profile
    p_revenda: Optional[float] = None                   # 0.0-1.0
    p_loja: Optional[float] = None                      # = 1 - p_revenda
    channel_profile_tier: Optional[str] = None          # echo of brand_tier used by predictor
    channel_km_bucket: Optional[str] = None             # e.g. "90-120k"
    channel_age_bucket: Optional[str] = None            # e.g. "5-7"
    is_revenda_profile: bool = False                    # p_revenda >= threshold
    channel_probability_reason: Optional[str] = None    # PT-BR description for UI

    # V7: Blended single price — final recommended buy value
    # Mode "auto":   blended = (1 - p_revenda) * loja + p_revenda * revenda
    # Mode "loja":   blended = loja_max_trade_value
    # Mode "revenda":blended = revenda_max_trade_value
    # When buy_ratio is available and converges, blended uses buy_ratio_price
    # as the headline value (it stays the most reliable single number).
    purpose: str = "auto"                               # echo of request.purpose
    # V8: what the UI shows as THE number. "buy_ratio_first" = legacy (A when
    # available, else the channel blend); "ensemble" = weighted mix of A and B.
    recommended_value: Optional[Decimal] = None
    recommended_source: Optional[str] = None            # "buy_ratio" | "blend" | "ensemble"
    recommended_reason: Optional[str] = None            # PT-BR explanation
    blended_max_trade_value: Optional[Decimal] = None   # single recommended price
    blended_weight_loja: Optional[float] = None         # weight applied to Loja
    blended_weight_revenda: Optional[float] = None      # weight applied to Revenda
    blended_source: Optional[str] = None                # "buy_ratio" | "blend" | "loja" | "revenda"
    blended_reason: Optional[str] = None                # PT-BR explanation

    # Rationale
    rationale: str = ""

    # Raw comparables for transparency
    loja_comparables: list[Comparable] = Field(default_factory=list)
    revenda_comparables: list[Comparable] = Field(default_factory=list)
