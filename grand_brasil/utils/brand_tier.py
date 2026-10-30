"""Brand-tier classification for pricing aggressiveness.

Brazilian used-car market shows systematic differences in how well certain
brands hold value and how quickly they turn over. Based on an empirical
analysis of 2,280 Grand Brasil sales (2025), three tiers emerge:

    SAFE    — TOYOTA, HONDA, HYUNDAI
              Hold value well, low Revenda share overall (19-39%),
              sell faster, lower volatility. Safe to be aggressive on
              trade-in offers.

    RISKY   — FORD, PEUGEOT, RENAULT, CITROEN
              Weaker residual values, high Revenda share (65-80%),
              longer time to sell. Be more conservative on trade-in offers.

    NEUTRAL — everything else (VW, Chevrolet, Fiat, Nissan, BMW, etc.)
              Average behavior; no tier-level adjustment applied.

JEEP is deliberately kept in NEUTRAL: modern Jeep (0-4 years) behaves like
SAFE (24-37% Revenda) while old Jeep behaves like RISKY (100% Revenda 8+
years). The age/km-based channel prediction handles that naturally.

Each tier has an `aggressiveness_adjustment_pp` which is added/subtracted
from the Loja/Revenda target margin:

    SAFE    →  0.0 pp (see note below)
    RISKY   → +2.0 pp (higher required margin → pay LESS for the car)
    NEUTRAL →  0.0 pp

Note on SAFE: the A/B backtest (tests/backtests/backtest_ab_tier.py, 1970
plate-matched rows) showed that the team ALREADY prices SAFE brands spot-on
historically — control bias was only +0.02% Loja / +1.17% Revenda on SAFE,
while RISKY had +8.46% Loja / +13.19% Revenda bias (systematic overpay).
Applying SAFE −2pp on top of already-accurate pricing made things worse
(bias jumped +1.80pp). So SAFE is kept at 0.0 pp: the baseline algorithm
already encodes the "aggressive on safe brands" behavior implicitly from
historical paid-price calibration. RISKY at +2.0 pp is preserved — the
backtest confirmed MAPE improvement of 1.18-1.69 pp in that tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel


class BrandTierConfig(BaseModel):
    """Configuration for brand-tier classification and pricing adjustment.

    Adjustments are applied to the target margin; a NEGATIVE pp means
    the algorithm requires less margin → higher trade-in offer.
    """

    enabled: bool = True
    safe_brands: list[str] = ["TOYOTA", "HONDA", "HYUNDAI"]
    risky_brands: list[str] = ["FORD", "PEUGEOT", "RENAULT", "CITROEN"]
    # Calibrated by tests/backtests/backtest_ab_tier.py:
    # SAFE at 0.0 (baseline already fits SAFE historical pay); RISKY at +2.0
    # (cuts MAPE 1.2-1.7 pp by reducing systematic overpay).
    safe_adjustment_pp: float = 0.0       # SAFE baseline already accurate
    risky_adjustment_pp: float = 2.0      # higher target margin → more conservative
    neutral_adjustment_pp: float = 0.0


@dataclass(frozen=True)
class BrandTierInfo:
    """Runtime classification result."""
    tier: str                     # "SAFE" / "NEUTRAL" / "RISKY"
    adjustment_pp: float          # pp to ADD to target margin
    reason: str                   # Portuguese description for UI / rationale


def classify_brand(brand: str, config: Optional[BrandTierConfig] = None) -> BrandTierInfo:
    """Classify a brand into a pricing tier.

    Args:
        brand: Brand name (case-insensitive).
        config: Optional override; defaults to BrandTierConfig().

    Returns:
        BrandTierInfo with tier label, pp adjustment, and a short reason
        for user-facing rationale.
    """
    cfg = config or BrandTierConfig()
    brand_u = str(brand).strip().upper()

    if not cfg.enabled:
        return BrandTierInfo("NEUTRAL", 0.0, "Classificação por marca desativada.")

    if brand_u in {b.upper() for b in cfg.safe_brands}:
        return BrandTierInfo(
            tier="SAFE",
            adjustment_pp=cfg.safe_adjustment_pp,
            reason=(
                f"Marca {brand_u} (perfil SAFE): ajuste de "
                f"{cfg.safe_adjustment_pp:+.1f}pp na margem-alvo "
                f"(histórico mostra alta retenção de valor, baixo share Revenda)."
            ),
        )

    if brand_u in {b.upper() for b in cfg.risky_brands}:
        return BrandTierInfo(
            tier="RISKY",
            adjustment_pp=cfg.risky_adjustment_pp,
            reason=(
                f"Marca {brand_u} (perfil RISKY): ajuste de "
                f"{cfg.risky_adjustment_pp:+.1f}pp na margem-alvo "
                f"(histórico mostra giro mais lento e maior share Revenda)."
            ),
        )

    return BrandTierInfo(
        tier="NEUTRAL",
        adjustment_pp=cfg.neutral_adjustment_pp,
        reason=f"Marca {brand_u} (perfil NEUTRAL): sem ajuste de tier.",
    )
