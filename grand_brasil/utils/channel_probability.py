"""Channel probability — estimate P(Revenda) for a given car profile.

Predicts the probability that a given vehicle will be sold via Revenda (B2B
wholesale) rather than Loja (B2C retail), based on three empirical drivers:

    brand_tier  × km_bucket × age_bucket   → p_revenda

Calibrated from `tests/backtests/analyze_revenda_profile.py` on 2,280 sales:

    · SAFE brands (Toyota/Honda/Hyundai):
        Revenda share ~19–39% overall; jumps above 90k km or 8+ years.
    · NEUTRAL brands (VW, Chevrolet, Fiat, Nissan, BMW, …):
        ~45-55% Revenda; crosses 50% around 90k km or 5-7 years.
    · RISKY brands (Ford/Peugeot/Renault/Citroen):
        65-81% Revenda even new; 5 years is the pivot point.

Why this matters for pricing:

    1) It surfaces the right channel to trust for the margin calculation.
       A 150k-km 2014 Renault has P(Revenda) ≈ 0.97 → the Revenda margin
       band should dominate the final suggestion, not Loja.

    2) It allows the UI to display a CALIBRATED expectation
       ("this car has 82% chance of being sold via Revenda"), so the
       evaluator can sanity-check aggressive/passive offers.

    3) Downstream logic can BLEND Loja and Revenda anchors using
       p_revenda as a weight:
          blended = (1 - p) × loja_trade + p × revenda_trade

       (Currently we display both side by side; the blend is available
       for future UI work.)

The lookup tables are approximate first-order calibrations. They can be
refined with per-cell empirical analysis later. All numbers are in %.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from grand_brasil.utils.brand_tier import BrandTierConfig, classify_brand


# ── Bucket edges ────────────────────────────────────────────────────────────
# Match the same edges used in the revenda-profile analysis (so the
# calibration table and the production code see the world identically).

KM_BUCKETS: tuple[tuple[int, str], ...] = (
    (30_000,     "0-30k"),
    (60_000,     "30-60k"),
    (90_000,     "60-90k"),
    (120_000,    "90-120k"),
    (150_000,    "120-150k"),
    (10_000_000, "150k+"),
)

AGE_BUCKETS: tuple[tuple[int, str], ...] = (
    (3,  "0-2"),
    (5,  "3-4"),
    (8,  "5-7"),
    (12, "8-11"),
    (99, "12+"),
)


def _km_bucket(km: Optional[int]) -> str:
    """Map a km value to its bucket label. None / negative → first bucket."""
    if km is None or km < 0:
        return KM_BUCKETS[0][1]
    for upper, label in KM_BUCKETS:
        if km < upper:
            return label
    return KM_BUCKETS[-1][1]


def _age_bucket(age: int) -> str:
    """Map an age (years) to its bucket label."""
    if age < 0:
        age = 0
    for upper, label in AGE_BUCKETS:
        if age < upper:
            return label
    return AGE_BUCKETS[-1][1]


# ── Lookup tables (p_revenda, 0-1 scale) ────────────────────────────────────
# Rows → age bucket, cols → km bucket.
#
# Interpretation: P(Revenda | tier, age, km). A 0.40 means 40% of comparable
# cars in that cell ended up in Revenda historically. Calibrated to match
# the aggregate numbers observed in analyze_revenda_profile.py and the
# rupture thresholds the team has in mind (90k km, 5-year pivot for RISKY).

# Tables calibrated from 2,280 real Loja+Revenda sales via
# tests/backtests/calibrate_channel_probability.py (MIN_CELL_SAMPLE=10;
# isotonic smoothing applied on both axes to preserve monotonicity).
# Cells with n<10 fall back to the original hand-calibrated prior.

_SAFE_TABLE: dict[str, dict[str, float]] = {
    # age        0-30k     30-60k     60-90k    90-120k   120-150k      150k+
    "0-2":   {"0-30k": 0.05, "30-60k": 0.18, "60-90k": 0.53, "90-120k": 0.53, "120-150k": 0.60, "150k+": 0.80},
    "3-4":   {"0-30k": 0.06, "30-60k": 0.18, "60-90k": 0.53, "90-120k": 0.82, "120-150k": 0.82, "150k+": 0.85},
    "5-7":   {"0-30k": 0.19, "30-60k": 0.20, "60-90k": 0.53, "90-120k": 0.82, "120-150k": 0.82, "150k+": 1.00},
    "8-11":  {"0-30k": 0.25, "30-60k": 0.33, "60-90k": 0.53, "90-120k": 0.90, "120-150k": 0.90, "150k+": 1.00},
    "12+":   {"0-30k": 0.50, "30-60k": 0.60, "60-90k": 0.70, "90-120k": 0.90, "120-150k": 0.92, "150k+": 1.00},
}

_NEUTRAL_TABLE: dict[str, dict[str, float]] = {
    "0-2":   {"0-30k": 0.09, "30-60k": 0.41, "60-90k": 0.41, "90-120k": 0.55, "120-150k": 0.75, "150k+": 0.90},
    "3-4":   {"0-30k": 0.20, "30-60k": 0.41, "60-90k": 0.79, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
    "5-7":   {"0-30k": 0.20, "30-60k": 0.43, "60-90k": 0.79, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
    "8-11":  {"0-30k": 0.40, "30-60k": 0.50, "60-90k": 0.82, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
    "12+":   {"0-30k": 0.60, "30-60k": 0.70, "60-90k": 0.85, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
}

_RISKY_TABLE: dict[str, dict[str, float]] = {
    "0-2":   {"0-30k": 0.00, "30-60k": 0.25, "60-90k": 0.40, "90-120k": 0.65, "120-150k": 0.80, "150k+": 0.92},
    "3-4":   {"0-30k": 0.25, "30-60k": 0.35, "60-90k": 0.55, "90-120k": 0.75, "120-150k": 0.85, "150k+": 0.95},
    "5-7":   {"0-30k": 0.40, "30-60k": 0.50, "60-90k": 0.71, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
    "8-11":  {"0-30k": 0.60, "30-60k": 0.75, "60-90k": 0.85, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
    "12+":   {"0-30k": 0.80, "30-60k": 0.88, "60-90k": 0.93, "90-120k": 1.00, "120-150k": 1.00, "150k+": 1.00},
}

_TABLES = {
    "SAFE":    _SAFE_TABLE,
    "NEUTRAL": _NEUTRAL_TABLE,
    "RISKY":   _RISKY_TABLE,
}


class ChannelProbabilityConfig(BaseModel):
    """Configuration flag for the channel probability engine.

    The lookup tables themselves are kept as module-level constants because
    they're empirically calibrated and should not be edited casually from
    YAML — adjustments should come from re-running the analysis script.
    """

    enabled: bool = True
    # When p_revenda ≥ this threshold, UI can badge the car as "Revenda profile".
    # (Advisory only — the appraisal math always shows both channels.)
    revenda_profile_threshold: float = 0.70


@dataclass(frozen=True)
class ChannelProbabilityInfo:
    """Runtime prediction result."""
    p_revenda: float              # 0.0-1.0
    p_loja: float                 # = 1 - p_revenda
    tier: str                     # "SAFE" / "NEUTRAL" / "RISKY"
    km_bucket: str
    age_bucket: str
    reason: str                   # Portuguese description for UI
    is_revenda_profile: bool      # p_revenda >= config threshold


def predict_channel_probability(
    brand: str,
    km: Optional[int],
    year_model: int,
    reference_year: int,
    config: Optional[ChannelProbabilityConfig] = None,
    brand_tier_config: Optional[BrandTierConfig] = None,
) -> ChannelProbabilityInfo:
    """Predict P(Revenda) for a car profile.

    Args:
        brand: Brand name (case-insensitive).
        km: Mileage. None treated as 0.
        year_model: Model year.
        reference_year: Current year (typically today's year). Used to
            derive age. Passed explicitly so tests are deterministic.
        config: Optional override.
        brand_tier_config: Optional override for the brand classifier.

    Returns:
        ChannelProbabilityInfo with p_revenda, bucket labels and a reason.
    """
    cfg = config or ChannelProbabilityConfig()
    if not cfg.enabled:
        return ChannelProbabilityInfo(
            p_revenda=0.5, p_loja=0.5,
            tier="NEUTRAL", km_bucket="-", age_bucket="-",
            reason="Previsão de canal desativada.",
            is_revenda_profile=False,
        )

    tier_info = classify_brand(brand, brand_tier_config)
    tier = tier_info.tier
    age = max(int(reference_year) - int(year_model), 0)
    kmb = _km_bucket(km)
    ageb = _age_bucket(age)

    p = _TABLES[tier][ageb][kmb]
    is_profile = p >= cfg.revenda_profile_threshold

    reason = (
        f"Perfil {tier} | idade {age}a ({ageb}) | KM {_km_display(km)} ({kmb}) "
        f"→ P(Revenda) ≈ {p:.0%}."
    )
    if is_profile:
        reason += " Carro com forte perfil de Revenda."

    return ChannelProbabilityInfo(
        p_revenda=p,
        p_loja=1.0 - p,
        tier=tier,
        km_bucket=kmb,
        age_bucket=ageb,
        reason=reason,
        is_revenda_profile=is_profile,
    )


def _km_display(km: Optional[int]) -> str:
    if km is None:
        return "—"
    if km >= 1_000:
        return f"{km/1000:.0f}k"
    return str(km)
