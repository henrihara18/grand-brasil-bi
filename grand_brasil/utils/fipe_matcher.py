"""FIPE matcher — cross-references a FIPE model name against DealerUp sales history.

FIPE model names are highly detailed:
    "HR-V 1.8 EX FlexOne 16V 5p Aut."
    "Gol 1.0 16V Total Flex 4p"
    "Creta 1.0 TGDI Flex Limited Aut."

DealerUp model names are shorter:
    model_red:  "HONDA HR-V"
    model_trim: "HONDA HR-V EX"

This module:
1. Normalizes the FIPE brand name to match DealerUp's convention.
2. Extracts meaningful trim tokens from the FIPE model name.
3. Scores each DealerUp sales row against those tokens.
4. Returns the best-matching comparable sales as a DataFrame.
"""

import logging
import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

logger = logging.getLogger(__name__)

# ── Brand name aliases ──────────────────────────────────────────────────────
# Maps normalized FIPE brand name → DealerUp brand name (both uppercase)
_BRAND_ALIASES: dict[str, str] = {
    "VW - VOLKSWAGEN": "VOLKSWAGEN",
    "GM - CHEVROLET": "CHEVROLET",
    "MERCEDES-BENZ": "MERCEDES BENZ",
    "LAND ROVER": "LAND ROVER",
    "JAC": "JAC",
    "CAOA CHERY": "CHERY",
    "CHERY": "CHERY",
    "GWM": "GWM",
    "BYD": "BYD",
    "HAVAL": "HAVAL",
}

# ── Noise words to strip from FIPE model names ──────────────────────────────
# Mirrors trim_extractor._NOISE_WORDS plus FIPE-specific additions
_NOISE_WORDS: frozenset[str] = frozenset({
    # Fuel / engine technology
    "FLEX", "FLEXONE", "FLEXP", "FLEXSTART", "GASOLINA", "ALCOOL", "DIESEL",
    "GNV", "TOTAL", "TURBO", "TGDI", "TSI", "DI", "MPFI", "VVT", "IVTEC",
    "FFV", "SCE", "TCE", "MPI", "MIVEC", "MSI", "ACTIVEFLEX", "THP", "CGI",
    "FIREFLY", "MHEV", "EVO",
    # Transmission
    "AUT", "AT", "CVT", "MANUAL", "MEC", "AUTOMATICO", "AUTOMATIC",
    "XTRONIC", "MULTIDRIVE", "TIPTRONIC", "POWERSHIFT", "GEARTRONIC",
    "ECOSHIFT", "DIRECT", "SHIFT", "AUTOMATIZADO", "EAT6", "AT6", "AT9",
    # Drivetrain
    "4X2", "4X4", "4XE", "AWD", "FWD", "4MOTION", "ALLGRIP", "QUATTRO",
    # Hybrid / electric
    "HYBRID", "HIBRIDO", "HV", "ELECTRIC", "DMI",
    # Body style
    "SEDAN", "HATCH", "SPORT",
    # Misc
    "NEW", "TB", "SPE", "MT", "NGA", "IFLEX",
})

# Regex patterns for things to strip before tokenizing
_DISPLACEMENT_RE = re.compile(r"\b\d+[.,]\d+[A-Z]?\b")  # 1.8, 2.0T
_VOLTAGE_RE = re.compile(r"\b\d+V\b")                    # 16V, 8V
_DOORS_RE = re.compile(r"\b\d+[Pp]\b")                   # 5p, 4P
_PURE_NUMBER_RE = re.compile(r"^\d+$")


# ── Normalization ───────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Uppercase, strip accents, and strip whitespace."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_text.upper().strip()


def _normalize_brand(fipe_brand_name: str) -> str:
    """Map a FIPE brand name to the DealerUp convention.

    Falls back to the normalized input if no alias is found.
    """
    normed = _normalize(fipe_brand_name)
    return _BRAND_ALIASES.get(normed, normed)


# ── Token extraction ────────────────────────────────────────────────────────

def extract_model_tokens(fipe_model_name: str) -> list[str]:
    """Extract meaningful trim/model tokens from a FIPE model name.

    Strips engine specs, transmission, fuel type, and other noise,
    leaving only the model family and trim level identifiers.

    Examples:
        "HR-V 1.8 EX FlexOne 16V 5p Aut."  → ["HR-V", "EX"]
        "Gol 1.0 16V Total Flex 4p"          → ["GOL"]
        "Creta 1.0 TGDI Flex Limited Aut."   → ["CRETA", "LIMITED"]
        "HB20 1.0 Comfort Plus Flex Aut."    → ["HB20", "COMFORT", "PLUS"]
    """
    text = _normalize(fipe_model_name)

    # Remove displacement, voltage, door-count patterns
    text = _DISPLACEMENT_RE.sub(" ", text)
    text = _VOLTAGE_RE.sub(" ", text)
    text = _DOORS_RE.sub(" ", text)

    # Tokenize, strip punctuation from each token
    raw_tokens = text.split()
    tokens = []
    for tok in raw_tokens:
        cleaned = tok.strip(".,/-()")
        if not cleaned:
            continue
        if cleaned in _NOISE_WORDS:
            continue
        if _PURE_NUMBER_RE.match(cleaned):
            continue
        if len(cleaned) < 2:
            continue
        tokens.append(cleaned)

    return tokens


# ── Main matching function ──────────────────────────────────────────────────

def find_comparables(
    fipe_brand: str,
    fipe_model: str,
    year_model: int,
    sales_df: pd.DataFrame,
    year_tolerance: int = 2,
    score_threshold: float = 0.6,
) -> pd.DataFrame:
    """Find DealerUp sales rows that match a FIPE brand/model/year.

    Matching strategy:
    1. Brand: normalize FIPE brand name → exact match against sales_df["brand"]
    2. Year: +/- year_tolerance
    3. Score: all extracted tokens appear in model_trim → score=1.0
              else SequenceMatcher ratio against model_trim/model_red
    4. Keep rows with score >= score_threshold
    5. Fallback: if no matches, return brand+year filtered rows with a warning

    Args:
        fipe_brand: FIPE brand name (e.g. "Honda")
        fipe_model: FIPE model name (e.g. "HR-V 1.8 EX FlexOne 16V 5p Aut.")
        year_model: Target model year
        sales_df: Full DealerUp sales DataFrame
        year_tolerance: +/- years to search
        score_threshold: Minimum score to include a row

    Returns:
        Filtered DataFrame of matching comparable sales.
    """
    brand_norm = _normalize_brand(fipe_brand)
    tokens = extract_model_tokens(fipe_model)

    logger.info(
        f"FIPE match: brand='{brand_norm}', tokens={tokens}, "
        f"year={year_model} +/-{year_tolerance}"
    )

    # ── Step 1: Narrow by brand + year ──
    year_mask = (
        (sales_df["year_model"] >= year_model - year_tolerance)
        & (sales_df["year_model"] <= year_model + year_tolerance)
    )
    brand_mask = sales_df["brand"].str.upper() == brand_norm
    candidates = sales_df[year_mask & brand_mask].copy()

    if candidates.empty:
        logger.warning(
            f"Nenhuma venda encontrada para marca '{brand_norm}' "
            f"nos anos {year_model - year_tolerance}-{year_model + year_tolerance}"
        )
        return candidates

    if not tokens:
        # No trim tokens extracted — return all brand+year matches
        logger.info("Sem tokens de versao extraidos; retornando todas as vendas da marca/ano")
        return candidates

    # ── Step 2: Score each row ──
    scores = candidates.apply(lambda row: _score_row(row, tokens), axis=1)
    matched = candidates[scores >= score_threshold].copy()

    if matched.empty:
        logger.warning(
            f"Nenhuma venda passou o threshold {score_threshold} para tokens {tokens}. "
            f"Usando fallback: marca + ano apenas."
        )
        return candidates

    logger.info(
        f"FIPE match: {len(matched)}/{len(candidates)} vendas selecionadas "
        f"(threshold={score_threshold})"
    )
    return matched


def _score_row(row: pd.Series, tokens: list[str]) -> float:
    """Score a DealerUp sales row against extracted FIPE tokens.

    Returns 1.0 if all tokens appear in the row's model string,
    otherwise falls back to SequenceMatcher ratio.
    """
    # Prefer model_trim; fall back to model_red
    target_raw = row.get("model_trim") or row.get("model_red", "")
    target = _normalize(str(target_raw))

    # Fast path: all tokens present → perfect score
    if all(t in target for t in tokens):
        return 1.0

    # Fuzzy fallback
    query = " ".join(tokens)
    return SequenceMatcher(None, query, target).ratio()
