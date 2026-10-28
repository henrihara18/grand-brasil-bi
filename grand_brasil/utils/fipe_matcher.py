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
    "HYBRID", "HIBRIDO", "HV", "ELECTRIC", "ELETRICO", "ELECTRICO",
    "EV", "BEV", "PHEV", "DMI", "ELETRICA", "ELECTRICA",
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
    if "year_model" not in sales_df.columns or len(sales_df) == 0:
        return pd.DataFrame()

    year_mask = (
        (sales_df["year_model"] >= year_model - year_tolerance)
        & (sales_df["year_model"] <= year_model + year_tolerance)
    )
    brand_mask = sales_df["brand"].str.upper() == brand_norm
    candidates = sales_df[year_mask & brand_mask].copy()

    if candidates.empty:
        logger.warning(
            f"Nenhuma venda encontrada para marca '{brand_norm}' "
            f"nos anos {year_model - year_tolerance}-{year_model + year_tolerance}. "
            f"Marcas disponiveis na base: "
            f"{sorted(sales_df['brand'].str.upper().unique().tolist())}"
        )
        return candidates

    if not tokens:
        # No trim tokens extracted — return all brand+year matches
        logger.info(
            f"Sem tokens de versao extraidos para '{fipe_model}'; "
            f"retornando todas as {len(candidates)} vendas da marca/ano"
        )
        return candidates

    # ── Step 2: Score each row ──
    scores = candidates.apply(lambda row: _score_row(row, tokens), axis=1)

    # Log score distribution for debugging
    if logger.isEnabledFor(logging.DEBUG):
        score_details = candidates[["model_red", "model_trim"]].copy() if "model_trim" in candidates.columns else candidates[["model_red"]].copy()
        score_details["score"] = scores.values
        logger.debug(f"Scores para tokens {tokens}:\n{score_details.sort_values('score', ascending=False).to_string()}")

    # ── Step 3: Tiered selection — prefer exact trim matches over fallbacks ──
    #
    # Score bands:
    #   1.0      = exact trim match  (all tokens found in model_trim)
    #   0.6-0.99 = fuzzy trim match  (SequenceMatcher on available trim data)
    #   0.65     = no-trim fallback  (model_red matches but trim data is absent)
    #
    # Priority: if ANY row has score == 1.0 (exact trim match), return only those.
    # This prevents e.g. "Song Plus" rows (no trim → score 0.65) from contaminating
    # a "Song Plus Premium" search when Premium rows already exist in the data.
    # The 0.65 fallback is only used when NO exact match is available, which handles
    # models where DealerUp trim extraction failed entirely (e.g. all Polo rows with
    # model_trim == model_red).
    _EXACT_SCORE = 1.0
    _NO_TRIM_SCORE = 0.65

    exact_matched = candidates[scores == _EXACT_SCORE].copy()
    if not exact_matched.empty:
        matched_models = exact_matched["model_red"].value_counts().to_dict()
        logger.info(
            f"FIPE match (exact trim): {len(exact_matched)}/{len(candidates)} vendas "
            f"| modelos: {matched_models}"
        )
        return exact_matched

    # No exact trim match — try fuzzy matches (trim IS available but partial)
    fuzzy_matched = candidates[
        (scores >= score_threshold) & (scores < _EXACT_SCORE) & (scores != _NO_TRIM_SCORE)
    ].copy()
    if not fuzzy_matched.empty:
        matched_models = fuzzy_matched["model_red"].value_counts().to_dict()
        logger.info(
            f"FIPE match (fuzzy trim): {len(fuzzy_matched)}/{len(candidates)} vendas "
            f"| modelos: {matched_models}"
        )
        return fuzzy_matched

    # No trim data at all — fall back to model-level matches (score == 0.65)
    notrim_matched = candidates[scores == _NO_TRIM_SCORE].copy()
    if not notrim_matched.empty:
        matched_models = notrim_matched["model_red"].value_counts().to_dict()
        logger.warning(
            f"FIPE match (sem trim — fallback modelo): {len(notrim_matched)} vendas "
            f"para '{fipe_model}'. Dados de trim ausentes; incluindo todas as vendas "
            f"do modelo. | modelos: {matched_models}"
        )
        return notrim_matched

    # Nothing matched at all
    top_candidates = candidates[["model_red"]].copy()
    top_candidates["score"] = scores.values
    top_candidates = top_candidates.sort_values("score", ascending=False).head(5)
    logger.warning(
        f"Nenhuma venda passou o threshold {score_threshold} para tokens {tokens}. "
        f"Top candidatos (sem threshold):\n{top_candidates.to_string(index=False)}\n"
        f"Retornando vazio — sem comparaveis confiaveis para '{fipe_model}'."
    )
    return pd.DataFrame()


def _score_row(row: pd.Series, tokens: list[str]) -> float:
    """Score a DealerUp sales row against extracted FIPE tokens.

    Scoring logic:
    1. Hard guard: the first token (model name) MUST appear in model_red.
       This prevents e.g. "POLO HIGHLINE" from ever matching "VOLKSWAGEN T-CROSS HIGHLINE"
       just because they share the "HIGHLINE" trim token.
    2. If all tokens appear in model_trim (or model_red when trim is absent) → 1.0.
    3. If trim data is unavailable (model_trim == model_red or NaN) → 0.65 (model-level
       match; trim can't be verified but is better than returning nothing).
    4. If trim IS available but doesn't fully match → SequenceMatcher for partial credit.
    """
    import pandas as _pd

    model_red = _normalize(str(row.get("model_red", "")))

    # Safely resolve model_trim — pandas NaN or the string "nan" both mean "no trim data"
    mt_raw = row.get("model_trim")
    if mt_raw is None or (_pd.isna(mt_raw) if not isinstance(mt_raw, str) else False):
        mt_raw = None
    elif isinstance(mt_raw, str) and mt_raw.strip().upper() in ("NAN", "NONE", ""):
        mt_raw = None
    model_trim = _normalize(str(mt_raw)) if mt_raw is not None else ""

    if not tokens:
        return 1.0

    first_token = tokens[0]

    # ── Hard guard: model name must be in model_red ──────────────────────────
    # This is the primary protection against cross-model contamination.
    # If "POLO" is not in model_red, no amount of shared trim tokens should
    # make this row a valid comparable for a Polo search.
    if first_token not in model_red:
        return 0.0

    # Use model_trim when it actually carries trim information
    has_trim_info = bool(model_trim) and model_trim != model_red
    target = model_trim if has_trim_info else model_red

    # ── All tokens found in target → perfect match ───────────────────────────
    if all(t in target for t in tokens):
        return 1.0

    # ── Only model name token (no trim requested) ────────────────────────────
    if len(tokens) == 1:
        return 0.8  # model_red guard already passed

    # ── No trim data available → can't verify trim, but model matches ─────────
    # Return a base score above the threshold so these rows aren't silently
    # discarded. This handles cases where DealerUp trim extraction returned
    # "BASE" (model_trim == model_red) or the column was empty.
    if not has_trim_info:
        logger.debug(
            f"Sem dados de trim para '{model_red}' — incluido com score base "
            f"(tokens solicitados: {tokens})"
        )
        return 0.65

    # ── Trim available but partial match → fuzzy score ───────────────────────
    query = " ".join(tokens)
    return SequenceMatcher(None, query, target).ratio()
