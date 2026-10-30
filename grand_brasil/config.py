"""Configuration loading — merges config.yaml (thresholds) with .env (secrets)."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings

from grand_brasil.utils.brand_tier import BrandTierConfig
from grand_brasil.utils.channel_probability import ChannelProbabilityConfig


class AgingThresholds(BaseModel):
    """Configurable day thresholds for aging brackets."""

    green_max_days: int = 30
    yellow_max_days: int = 60
    orange_max_days: int = 90
    # 90+ = red (implicit)


class PriceReductionRule(BaseModel):
    """A single price reduction rule based on days in stock."""

    days_threshold: int
    reduction_percent: float
    min_margin_percent: float


class B2BScoringWeights(BaseModel):
    """Weights and thresholds for B2B candidate scoring."""

    aging_weight: float = 0.4
    concentration_weight: float = 0.4
    margin_weight: float = 0.2
    score_threshold: float = 7.0          # Above this = B2B candidate
    concentration_limit: int = 3          # Same model count to trigger flag


class BuyRatioConfig(BaseModel):
    """Configuration for the buy-ratio engine (primary purchase anchor)."""

    # Status weights for weighted-median aggregation (appraisal base).
    # UTILIZADO/REPASSE are closed deals; AVALIADO is an offer that did not close.
    utilizado_weight: float = 1.0
    repasse_weight: float = 1.0
    avaliado_weight: float = 0.25

    # KM windows per matching tier (±N km)
    km_window_tight: int = 6_000    # Tier 1: same year, KM ±6k (12k total)
    km_window_wide: int = 12_000    # Tier 2: same year, KM ±12k (24k total)
    km_window_widest: int = 24_000  # Tier 5: year ±2, KM ±24k

    # Sample thresholds
    min_tier_sample: int = 5        # Min rows to lock in a tier
    min_fallback_sample: int = 3    # Absolute minimum for any estimate

    # Matching refinements (Fase 4 — each one measured against the backtest)
    tier_order: str = "year_first"                   # "year_first" (legacy) | "km_first"
    recency_halflife_days: Optional[float] = None    # weight decay for older appraisals; None = off
    km_adjust: bool = False                          # shift comparables' ratio to the target KM
    year_profile_by_brand: bool = False              # year curve per brand instead of global
    year_adjust_scale: float = 1.0                   # 1 = full year-curve delta, 0 = none
    shrink_k: float = 0.0                            # shrink ratio toward the prior: w = n/(n+k); 0 = off
    year_profile_min_rows: int = 1                   # year-curve cells with fewer rows are ignored (legacy 1)
    dedupe_by_plate: bool = False                    # same car appraised twice counts once among comparables
    km_adjust_mode: str = "linear"                   # "linear" (one slope) | "piecewise" (slope per KM band)
    km_piecewise_breaks: list[int] = [50_000, 100_000, 150_000]
    purpose_aware: bool = False                      # purpose=revenda -> prefer comparables appraised as REPASSE


class FipeSpreadConfig(BaseModel):
    """Behavior when historical FIPE-spread data is scarce.

    The algorithm uses the historical spread (sale_price / FIPE_at_time - 1)
    as a multiplier on today's FIPE to estimate the future sale price. When
    there are too few comparables with a valid historical FIPE lookup, the
    computed spread is noisy; we fall back to a fixed ratio instead:

        Revenda: FIPE × 0.80  (typical B2B dealer-to-dealer discount)
        Loja:    no fallback  (FIPE is already ~ retail price)
    """

    min_sample_for_spread: int = 3
    comparable_year_fipe: bool = False   # True = FIPE of each comparable's own year (fixes B1)
    aggregation: str = "mean"            # "mean" (legacy) | "median"
    # Set to None to disable the fallback for a given channel.
    revenda_fallback_ratio: Optional[float] = 0.80   # default: FIPE × 0.80 (B2B discount)
    loja_fallback_ratio: Optional[float] = None      # default: no fallback → raw FIPE


class PriceBandMargin(BaseModel):
    """Base target margin (%) for a single price band."""

    max_price: float       # upper bound of this band (inclusive), BRL
    margin_pct: float      # base target margin for this band


class DynamicMarginAdjustment(BaseModel):
    """A threshold → additive adjustment (pp) rule."""

    threshold: float       # metric threshold (e.g. 45 days, or 4.0 pp std)
    adjustment_pp: float   # percentage points to add above base margin


class DynamicMarginConfig(BaseModel):
    """Margin-alvo dinamica por faixa de preco + ajustes empiricos.

    Two-stage compute:
      1) Base margin from the price band the car falls into
      2) Per-model adjustments:
           - Speed (median days in stock → slower cars pay more conservative)
           - Volatility (std of historical margin → noisier cars pay more conservative)

    Adjustments are capped by `max_total_adjustment_pp` to prevent extreme values.
    Models with fewer than `min_model_sample` historical sales skip step 2 entirely
    (insufficient signal to justify an adjustment).
    """

    enabled: bool = True
    min_model_sample: int = 10          # rows needed to apply per-model adjustments
    max_total_adjustment_pp: float = 5  # cap on speed + volatility adjustments

    # Base margin by price band (evaluated in the declared order; first hit wins).
    loja_bands: list[PriceBandMargin] = [
        PriceBandMargin(max_price=60_000,     margin_pct=20.0),
        PriceBandMargin(max_price=90_000,     margin_pct=14.0),
        PriceBandMargin(max_price=120_000,    margin_pct=12.0),
        PriceBandMargin(max_price=160_000,    margin_pct=11.0),
        PriceBandMargin(max_price=220_000,    margin_pct=10.0),
        PriceBandMargin(max_price=10_000_000, margin_pct=10.0),
    ]
    revenda_bands: list[PriceBandMargin] = [
        PriceBandMargin(max_price=60_000,     margin_pct=6.0),
        PriceBandMargin(max_price=90_000,     margin_pct=3.5),
        PriceBandMargin(max_price=10_000_000, margin_pct=3.0),
    ]

    # Speed adjustment (median `days_in_stock` for the model → pp added to margin)
    speed_adjustments: list[DynamicMarginAdjustment] = [
        DynamicMarginAdjustment(threshold=60.0, adjustment_pp=4.0),  # >60d
        DynamicMarginAdjustment(threshold=45.0, adjustment_pp=2.0),  # 46-60d
        DynamicMarginAdjustment(threshold=30.0, adjustment_pp=1.0),  # 31-45d
    ]

    # Volatility adjustment (std of historical margin → pp added to margin)
    volatility_adjustments: list[DynamicMarginAdjustment] = [
        DynamicMarginAdjustment(threshold=8.0, adjustment_pp=3.0),   # >8pp std
        DynamicMarginAdjustment(threshold=6.0, adjustment_pp=2.0),   # 6-8
        DynamicMarginAdjustment(threshold=4.0, adjustment_pp=1.0),   # 4-6
    ]


class BlindadoConfig(BaseModel):
    """Sale-price premium (R$) added when the vehicle is armored.
    Applied to BOTH Loja and Revenda estimated sale prices.
    Missing year → premium of 0 (no effect).
    """
    premium_by_year: dict[int, int] = {
        2026: 25_000, 2025: 25_000, 2024: 25_000, 2023: 20_000,
        2022: 20_000, 2021: 20_000, 2020: 15_000, 2019: 15_000,
        2018: 15_000, 2017: 10_000, 2016: 15_000, 2015: 20_000,
        2014: 10_000,
    }


class KMCurveSegment(BaseModel):
    """A single segment of the piecewise KM depreciation curve.

    Each segment applies from the previous segment's km_max (or 0 if first)
    up to and including this segment's km_max. For the final "tail" segment,
    set km_max to a very large number (e.g. 10_000_000).

    `pp_per_10k` is the marginal depreciation (percentage points per 10k km)
    inside this band for the DEFAULT brand. Brand-specific curves scale this
    value by a multiplier derived from the legacy per-brand factor vs. default.
    """

    km_max: int
    pp_per_10k: float


class KMCurveConfig(BaseModel):
    """Non-linear (piecewise) KM depreciation curve.

    Empirical motivation: the prior model applied a single linear factor
    per brand across the whole KM range. Analysis of ~3k closed appraisals
    showed a bell-shaped marginal-decay curve: near-zero km cars (0-20k)
    depreciate slowly, 50-80k km hits the steepest decay, and after ~160k
    km decay flattens again.

    When enabled, `ajuste_km_pct` integrates this curve between km_ref
    and km_real instead of multiplying a single factor. The brand factor
    in FATOR_KM is reinterpreted as a *scale multiplier* applied on top
    of the curve (brand_factor / FATOR_KM_DEFAULT[canal]).

    Set `enabled=False` to restore the legacy linear behavior.
    """

    enabled: bool = True
    # Segments MUST be ordered by ascending km_max. First segment starts at km=0.
    segments: list[KMCurveSegment] = [
        KMCurveSegment(km_max=20_000,      pp_per_10k=0.5),
        KMCurveSegment(km_max=50_000,      pp_per_10k=1.2),
        KMCurveSegment(km_max=100_000,     pp_per_10k=1.6),
        KMCurveSegment(km_max=160_000,     pp_per_10k=1.0),
        KMCurveSegment(km_max=10_000_000,  pp_per_10k=0.7),
    ]


class OfficialGateConfig(BaseModel):
    """When is the headline an *official price* vs. a *suggestion* to be closed by the desk.

    Thresholds measured on the 2026 backtest (REVISAO_PRECIFICACAO.md 4.8): the calibrated
    confidence does most of the work; age, KM, 0 km / next model year and thin brands trim
    the tail. Every list is upper-case brand / model_red prefix.
    """
    enabled: bool = True
    allowed_confidence: list[str] = ["alta", "media"]   # calibrated levels that may be an official price
    max_age_years: Optional[int] = 10              # reference year - year_model
    max_km: Optional[int] = 150_000
    exclude_new: bool = True                       # 0 km (below new_km_threshold) or next model year
    new_km_threshold: int = 1_000
    exclude_brands: list[str] = ["AUDI", "BMW", "LAND ROVER"]
    exclude_models: list[str] = []                 # model_red prefixes, e.g. "BMW X6"
    exclude_blindado: bool = True
    min_closed_deals: int = 0                      # closed deals behind the buy-ratio


class AppraisalConfig(BaseModel):
    """Configuration for the trade-in appraisal engine."""

    year_tolerance: int = 2               # +/- years for comparable search
    loja_target_margin: float = 15.0      # Target gross margin % for Loja (B2C)
    revenda_target_margin: float = 5.5    # Target gross margin % for Revenda (B2B)
    min_comparables: int = 3              # Minimum comparables for "media" confidence
    sales_history_file: str = "Vendas 2025-2026 processado.xlsx"
    # Legacy appraisal Excel (2025) appended below the V2 Google Sheets export
    appraisal_legacy_file: str = "Avaliações 2025 e 2026.xlsx"
    appraisal_legacy_until: str = "2026-01-01"
    recency_halflife_days: float = 180.0  # Half-life for recency weighting (days)
    year_pct_per_year: float = 7.5        # % price adjustment per year difference

    # Margin basis for the sales anchor: "markup" (legacy: trade = sale / (1+m)) or
    # "sale" (trade = sale × (1 − tax − m), i.e. margin as % of the sale, after taxes)
    margin_basis: str = "markup"
    sales_tax_pct: float = 0.0            # % of the sale paid in taxes (only used with "sale")

    # Headline: "buy_ratio_first" (legacy) or "ensemble" (w·A + (1-w)·B when both exist)
    headline_mode: str = "buy_ratio_first"
    ensemble_weight_buy_ratio: float = 0.7
    ensemble_weight_by_tier: dict[str, float] = {}   # optional per-tier override of the weight
    # Alert when the headline sits above this share of FIPE (None = off). In 2026, a third of
    # the 78 closed deals above 95 % of FIPE (0 km / next model year, trade-in on a new-car
    # sale) ended with a negative margin.
    fipe_ratio_alert: Optional[float] = 0.95

    # Appraisal base hygiene: replace 'valor avaliado' by the sale's adjusted cost when the
    # plate matches a later sale and they differ by more than the tolerance; drop closed
    # deals whose ratio is below the empirical floor for the car's age (P1 of closed deals).
    trim_rules_enabled: bool = True              # trim in model_red for families where it moves price (utils/model_generation.TRIM_RULES)
    reconcile_paid_with_sales: bool = False
    reconcile_tolerance: float = 0.05
    ratio_floor_by_age: dict[int, float] = {}      # {max_age: floor}, e.g. {0: 0.70, 1: 0.65, 3: 0.65, 6: 0.58, 10: 0.50, 99: 0.40}

    # Calibrated confidence table (written by scripts/confidence_curve.py --out)
    confidence_calibration_file: str = "data/confidence_calibration.json"

    # Nested configs for the new anchors
    buy_ratio: BuyRatioConfig = BuyRatioConfig()
    blindado: BlindadoConfig = BlindadoConfig()
    dynamic_margin: DynamicMarginConfig = DynamicMarginConfig()
    fipe_spread: FipeSpreadConfig = FipeSpreadConfig()
    km_curve: KMCurveConfig = KMCurveConfig()
    brand_tier: BrandTierConfig = BrandTierConfig()
    channel_probability: ChannelProbabilityConfig = ChannelProbabilityConfig()
    official_gate: OfficialGateConfig = OfficialGateConfig()


class AppConfig(BaseModel):
    """All business rule configuration loaded from config.yaml."""

    aging: AgingThresholds = AgingThresholds()
    price_reduction_rules: list[PriceReductionRule] = []
    b2b_scoring: B2BScoringWeights = B2BScoringWeights()
    appraisal: AppraisalConfig = AppraisalConfig()


class Settings(BaseSettings):
    """Application settings combining YAML config and environment secrets."""

    # Secrets from .env
    dealerup_token: Optional[str] = None

    # Business config from config.yaml
    app: AppConfig = AppConfig()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def load_config(
    config_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> Settings:
    """Load YAML config and merge with .env secrets.

    Args:
        config_path: Explicit path to config.yaml. If None, searches in project_root.
        project_root: Project root directory. Defaults to Coding/ directory.

    Returns:
        Fully loaded Settings instance.
    """
    if project_root is None:
        # Walk up from this file to find config.yaml
        project_root = Path(__file__).resolve().parent.parent

    if config_path is None:
        config_path = project_root / "config.yaml"

    app_config = AppConfig()

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        if yaml_data:
            app_config = AppConfig(**yaml_data)

    return Settings(app=app_config)
