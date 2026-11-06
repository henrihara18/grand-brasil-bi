"""Model-generation / body-style splitter.

Some vehicles share a `model_red` in both data sources (sales & appraisals)
but are actually DIFFERENT cars — different generations, body styles, or
trim families that command very different prices. Treating them as the
same model leads to:

  • Sales side: median-price aggregation pollutes both the anchor and the
    FIPE spread (a plain Tiguan can pull in Tiguan Allspace rows).
  • Buy-ratio side: the tiered matching falls back to model_fallback that
    averages ratios across incompatible vehicles.

This module applies targeted re-labeling rules at ingestion time, writing
the distinguishing feature into `model_red` itself so downstream code
treats them as separate models without any behavioral changes.

Calibrated empirically (2026-04) from analysis in
tests/backtests/analyze_trim_deep.py.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """Uppercase, strip accents."""
    if text is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_text.upper().strip()


@dataclass(frozen=True)
class GenerationRule:
    """Rule for splitting a model_red into generation variants.

    Attributes:
        base_model_red: The source model_red that will be rewritten when
            the marker matches. Uppercase, no accents.
        marker_pattern: Regex matched against a source string (modelo_full
            for sales, versão for appraisals). Case-insensitive.
        new_model_red: The replacement model_red when the marker matches.
        description: Human-readable rationale (for logs).
    """
    base_model_red: str
    marker_pattern: str
    new_model_red: str
    description: str


# Keep rules ordered — the first matching rule wins. Place more-specific
# rules before more-general ones when they share a base_model_red.
GENERATION_RULES: tuple[GenerationRule, ...] = (
    # 1) VW Tiguan: plain 5-seat (SUV compacto) vs Allspace (SUV grande 7-lug).
    #    Completely different vehicles — Allspace ~2x the price. Evidence:
    #    plain Tiguan median R$ 46k (n=7); Allspace variants R$ 87k-290k.
    GenerationRule(
        base_model_red="VOLKSWAGEN TIGUAN",
        marker_pattern=r"\bALLSPACE\b",
        new_model_red="VOLKSWAGEN TIGUAN ALLSPACE",
        description="Tiguan Allspace é o SUV 7-lug, Tiguan é 5-lug.",
    ),

    # 2) Hyundai Tucson: old 143CV 2WD vs new T-GDI generation.
    #    Same badge, completely different cars. Evidence:
    #    GLS 143CV rows R$ 28-55k; T-GDI rows R$ 71-148k.
    GenerationRule(
        base_model_red="HYUNDAI TUCSON",
        marker_pattern=r"\bT[-\s]?GDI\b|\bTGDI\b",
        new_model_red="HYUNDAI TUCSON T-GDI",
        description="Tucson T-GDI é a geração nova (2020+), GLS é antiga.",
    ),

    # 3) Toyota Yaris: hatch vs sedan. DealerUp's modelo_full often contains
    #    the explicit 'SEDAN' marker. Evidence: hatch median R$ 85k vs
    #    sedan median R$ 109-115k.
    GenerationRule(
        base_model_red="TOYOTA YARIS",
        marker_pattern=r"\bSEDAN\b",
        new_model_red="TOYOTA YARIS SEDAN",
        description="Yaris sedan e hatch têm preços distintos.",
    ),

    # 4) Mitsubishi Outlander: the 'Outlander Sport' is actually a distinct
    #    model (Brazil-market name for ASX in some years), not a trim.
    #    Evidence: plain Outlander R$ 67-92k vs Outlander Sport R$ 98-132k.
    GenerationRule(
        base_model_red="MITSUBISHI OUTLANDER",
        marker_pattern=r"\bSPORT\b",
        new_model_red="MITSUBISHI OUTLANDER SPORT",
        description="Outlander Sport é modelo diferente do Outlander.",
    ),
)


# Trim rules: families where the trim moves the price by ≥5% at the same model year
# with ≥10 sales on each side (scan of 2025-2026 sales, 29/10/2026). The first
# pattern that matches the source text wins; rows without any marker keep the
# family key and are reached through the prefix fallback.
TRIM_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "HYUNDAI HB20": ((r"\bPLATINUM\b", "PLATINUM"), (r"\bPREMIUM\b", "PREMIUM"), (r"\bEVOLUTION\b", "EVOLUTION"), (r"\bSENSE\b", "SENSE")),
    "HYUNDAI HB20S": ((r"\bPREMIUM\b", "PREMIUM"), (r"\bCOMFORT\b", "COMFORT")),
    "HONDA HR-V": ((r"\bTOURING\b", "TOURING"), (r"\bADVANCE\b", "ADVANCE"), (r"\bEXL\b", "EXL"), (r"\bLX\b", "LX"), (r"\bEX\b", "EX")),
    "HONDA CIVIC": ((r"\bTOURING\b", "TOURING"),),
    "CHEVROLET ONIX": ((r"\bPREMIER\b", "PREMIER"), (r"\bLTZ\b", "LTZ"), (r"\bLT\b", "LT")),
    "CHEVROLET TRACKER": ((r"\bPREMIER\b", "PREMIER"),),
    "JEEP COMPASS": ((r"\bTRAILHAWK\b", "TRAILHAWK"), (r"\bSPORT\b", "SPORT"), (r"\bLONGITUDE\b", "LONGITUDE"), (r"\bLIMITED\b", "LIMITED")),
    "JEEP RENEGADE": ((r"\bTRAILHAWK\b|\b4X4\b", "4X4"),),
    "JEEP COMMANDER": ((r"\bDIESEL\b|\bTD380\b", "DIESEL"),),
    "NISSAN KICKS": ((r"\bEXCLUSIVE\b", "EXCLUSIVE"), (r"\bADVANCE\b", "ADVANCE"), (r"\bSENSE\b", "SENSE")),
    "VOLKSWAGEN NIVUS": ((r"\bHIGHLINE\b", "HIGHLINE"), (r"\bCOMFORTLINE\b", "COMFORTLINE")),
    "VOLKSWAGEN T-CROSS": ((r"\bHIGHLINE\b", "HIGHLINE"), (r"\bCOMFORTLINE\b", "COMFORTLINE"), (r"\bSENSE\b", "SENSE")),
    "VOLKSWAGEN POLO": ((r"\bHIGHLINE\b", "HIGHLINE"),),
    "BMW X1": ((r"\bSPORT\b", "SPORT"),),
    "TOYOTA COROLLA ALTIS": ((r"PREMIUM.*(HYBRID|HIBRIDO|\bHV\b)|(HYBRID|HIBRIDO|\bHV\b).*PREMIUM", "HIBRIDO PREMIUM"),
                             (r"HYBRID|HIBRIDO|\bHV\b", "HIBRIDO"), (r"\bPREMIUM\b", "PREMIUM")),
}


def apply_trim_rule(model_red: str, source_text: str) -> str:
    """Append the trim to model_red when the family has trim rules and the text carries a marker."""
    base = _normalize(model_red)
    src = _normalize(source_text)
    if not base or not src:
        return base
    for family, rules in TRIM_RULES.items():
        if base == family or base.startswith(family + " "):
            for pattern, suffix in rules:
                if re.search(pattern, src, flags=re.IGNORECASE):
                    return f"{family} {suffix}"
            return family if base.startswith(family + " ") and base[len(family) + 1:] in {s for _, s in rules} else base
    return base


def apply_generation_split(
    model_red: str,
    source_text: str,
) -> str:
    """Return a possibly-rewritten model_red based on generation rules.

    Args:
        model_red: Current model_red (e.g. "VOLKSWAGEN TIGUAN").
        source_text: Free-text field to scan for generation markers
            (modelo_full for sales, versão for appraisals).

    Returns:
        Rewritten model_red when a rule fires, otherwise model_red
        unchanged (after normalization).
    """
    base = _normalize(model_red)
    src = _normalize(source_text)

    if not base or not src:
        return base

    for rule in GENERATION_RULES:
        if base != rule.base_model_red:
            continue
        if re.search(rule.marker_pattern, src, flags=re.IGNORECASE):
            return rule.new_model_red

    return base


def apply_generation_split_df(
    df: pd.DataFrame,
    source_col: str,
    model_red_col: str = "model_red",
    model_trim_col: Optional[str] = "model_trim",
    trim_rules: bool = True,
) -> pd.DataFrame:
    """Apply generation-split rules (and, optionally, trim rules) to a DataFrame in-place.

    Also updates `model_trim` so that rows whose model_red gets rewritten
    keep a consistent trim key. Rows where model_trim was equal to the
    old model_red get their model_trim bumped to the new model_red too
    (preserving the "no extracted trim" semantics).

    Args:
        df: DataFrame with model_red and (optionally) model_trim columns.
        source_col: Name of the free-text column to scan (e.g. 'modelo_full'
            for sales, 'version' for appraisals).
        model_red_col: Column holding the current model_red.
        model_trim_col: Column holding the current model_trim. Pass None
            to skip trim alignment.

    Returns:
        The same DataFrame (mutated in place) for chaining.
    """
    if model_red_col not in df.columns:
        return df
    if source_col not in df.columns:
        logger.debug(
            f"Coluna '{source_col}' ausente — pulando split de geração."
        )
        return df

    # Compute new_model_red per row
    def _rewrite(r):
        mr = apply_generation_split(str(r.get(model_red_col, "")), str(r.get(source_col, "")))
        return apply_trim_rule(mr, str(r.get(source_col, ""))) if trim_rules else mr
    new_model_red = df.apply(_rewrite, axis=1)

    # Update model_trim alignment when the old model_red was used as the trim
    if model_trim_col and model_trim_col in df.columns:
        def _adjust_trim(old_trim: str, old_mr: str, new_mr: str) -> str:
            old_trim_u = _normalize(old_trim)
            old_mr_u = _normalize(old_mr)
            new_mr_u = _normalize(new_mr)
            if old_mr_u == new_mr_u:
                return old_trim_u or old_mr_u
            # If old trim was just a copy of old model_red, bump to new.
            if old_trim_u == old_mr_u or not old_trim_u:
                return new_mr_u
            # If old trim STARTS with old model_red, rewrite prefix
            if old_trim_u.startswith(old_mr_u):
                return new_mr_u + old_trim_u[len(old_mr_u):]
            return old_trim_u

        df[model_trim_col] = [
            _adjust_trim(t, o, n)
            for t, o, n in zip(df[model_trim_col], df[model_red_col], new_model_red)
        ]

    # Finally update model_red
    changed_mask = new_model_red != df[model_red_col].map(_normalize)
    changed_count = int(changed_mask.sum())
    df[model_red_col] = new_model_red.values

    if changed_count > 0:
        breakdown = df.loc[changed_mask, model_red_col].value_counts().to_dict()
        logger.info(
            f"Split de geração aplicado em {changed_count} linhas: {breakdown}"
        )

    return df
