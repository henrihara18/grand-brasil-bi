"""Trim/version extractor — derives trim level from DealerUp full model descriptions.

DealerUp's 'Modelo' column contains the full model description, e.g.:
    "HR-V 1.8 16V FLEX EXL 4P AUTOMATICO"
    "NIVUS 1.0 200 TSI TOTAL FLEX HIGHLINE AUTOMATICO"
    "CRETA 1.0 TGDI FLEX LIMITED AUTOMATICO"

This module extracts the trim keyword (EXL, HIGHLINE, LIMITED) and combines it
with MODELO RED to create a `model_trim` key for precise appraisal matching.

Some models already have the trim in MODELO RED (e.g. HYUNDAI CRETA PLATINUM,
TOYOTA COROLLA XEI). In those cases, model_trim == model_red.
"""

import re
import unicodedata

# Words that are NOT trim identifiers — engine specs, transmission, etc.
_NOISE_WORDS = frozenset({
    # Engine / displacement
    "FLEX", "GASOLINA", "DIESEL", "TURBO", "TGDI", "TOTAL", "TSI",
    "DI", "IVTEC", "I-VTEC", "VVTIE", "VVT-IE", "VVT-I", "VVTI", "FFV", "MPFI", "VVT",
    # Transmission
    "CVT", "DIRECT", "SHIFT", "AUTOMATICO", "AUTOMATIC", "MANUAL", "MEC",
    "AUT", "AT", "AT6", "AT9", "XTRONIC", "MULTIDRIVE",
    "TIPTRONIC", "TIPTRONI", "GEARTRONIC", "ECOSHIFT",
    "POWERSHIFT", "AUTOMATIZADO",
    # Hybrid / electric
    "HYBRID", "HIBRIDO", "HV", "HB", "DMI",
    # Drivetrain
    "4X2", "4X4", "4XE", "AWD", "FWD", "4MOTION", "4MOTI",
    "ALLGRIP", "QUATTRO",
    # Misc noise
    "TB", "SPE", "NEW", "SEDAN", "HATCH", "MT",
    "FLEXSTART",
    "EVO", "FIREFLY", "SCE", "TCE", "MPI",
    "MIVEC", "MSI", "ACTIVEFLEX",
    "THP", "CGI", "MHEV", "NGA",
    "EAT6",
    "IFLEX",
    # Connector words
    "DE", "DO", "DA",
    # Noise from truncated column
    "AUTOMAT", "AUTOMATI", "AUTOMTIC", "AUTOM",
    # Generic words
    "CD", "CS",
})

# Truncated words at end of model string (DealerUp cuts off at ~40 chars)
# Map truncated -> full form
_TRUNCATION_FIXES = {
    "AUTOMAT": "",
    "AUTOMATI": "",
    "AUTOMATIC": "",
    "AUTOMTIC": "",
    "AUTOM": "",
    "TIPTRONI": "",
    "TIPTRO": "",
    "INTERCOO": "",
    "INTERCOOLER": "",
    "AUTOMATI/": "",
}

# Normalize trim names that appear as variants
_TRIM_ALIASES = {
    "COMFORTLINE AUTOMAT": "COMFORTLINE",
    "COMFORTLINE AUTOMATIC": "COMFORTLINE",
    "COMFORTLINE AUTOMATI": "COMFORTLINE",
    "HIGHLINE AUTOMAT": "HIGHLINE",
    "HIGHLINE AUTOMATIC": "HIGHLINE",
    "HIGHLINE AUTOMATI": "HIGHLINE",
    "LONGITUDE AUTOMAT": "LONGITUDE",
    "LONGITUDE AUTOMATIC": "LONGITUDE",
    "LIMITED AUTOMAT": "LIMITED",
    "LIMITED AUTOMATIC": "LIMITED",
    "I-VTEC EX": "EX",
    "I-VTEC EXL": "EXL",
    "I-VTEC TOURING": "TOURING",
    "I-VTEC ADVANCE": "ADVANCE",
    "EXL SENSING": "EXL",
    "FLEXONE EXL": "EXL",
    "FLEXONE EX": "EX",
    "FLEXONE SPORT": "SPORT",
    "LONGITUD": "LONGITUDE",
    "COMFORT PLUS TECH": "COMFORT PLUS",
    "LTZ SPE/(FLEX": "LTZ",
    "XRS FLEX)(AUT": "XRS",
    "COROLLA VVT-IE XEI": "XEI",
    "COROLLA VVT-IE GLI": "GLI",
    "COROLLA VVT-IE XRE": "XRE",
    "COROLLA VVT-IE XRX": "XRX",
    "COROLLA VVT-IE ALTIS": "ALTIS",
    "COROLLA VVT-I XRV": "XRV",
    "COROLLA VVT-I XRX": "XRX",
    "COROLLA VVT-I ALTIS": "ALTIS",
    "COROLLA VVT-I ALTIS PREMIUM": "ALTIS PREMIUM",
    "COROLLA APREMIUMH": "ALTIS PREMIUM",
    "CROSS HIGHLINE": "HIGHLINE",
    "CRETA ATITUDE": "ATTITUDE",
    "CRETA PLATINUM": "PLATINUM",
}


def extract_trim(modelo_full: str, shortname: str) -> str:
    """Extract the trim/version from a full DealerUp model description.

    Args:
        modelo_full: Full model text (e.g. "HR-V 1.8 16V FLEX EXL 4P AUTOMATICO").
        shortname: The model's short name (e.g. "HR-V", "NIVUS", "CRETA").

    Returns:
        Trim name (e.g. "EXL", "HIGHLINE", "COMFORT PLUS").
        Returns "BASE" if no trim can be identified.

    Examples:
        >>> extract_trim("HR-V 1.8 16V FLEX EXL 4P AUTOMATICO", "HR-V")
        'EXL'
        >>> extract_trim("NIVUS 1.0 200 TSI TOTAL FLEX HIGHLINE AUTOMATICO", "NIVUS")
        'HIGHLINE'
        >>> extract_trim("CRETA 1.0 TGDI FLEX LIMITED AUTOMATICO", "CRETA")
        'LIMITED'
        >>> extract_trim("ONIX 1.0 MPFI LT 8V FLEX 4P MANUAL", "ONIX")
        'LT'
    """
    text = _normalize(modelo_full)
    shortname_norm = _normalize(shortname)

    # Remove the model shortname and everything before it
    idx = text.find(shortname_norm)
    if idx >= 0:
        text = text[idx + len(shortname_norm):].strip()

    # Remove displacement patterns (1.0, 1.5L, 2.0, etc.)
    text = re.sub(r"\b\d+[\.,]\d+[A-Z]?\b", "", text)

    # Remove voltage patterns (16V, 12V, 8V)
    text = re.sub(r"\b\d+V\b", "", text)

    # Remove door count (4P, 5P, 7S, 5S, 7L)
    text = re.sub(r"\b\d+[PSLM]\b", "", text)

    # Remove year patterns (20/20, 23/23, 2020/2021, _P, _L suffixes)
    text = re.sub(r"\b\d{2,4}/\d{2,4}\b", "", text)
    text = re.sub(r"\b\d{2,4}_[A-Z]\b", "", text)

    # Remove engine codes (T270, T350, TD350, P250, D200)
    text = re.sub(r"\b[A-Z]?\d{3,}\b", "", text)

    # Remove standalone numbers (200, 350, etc.)
    text = re.sub(r"\b\d+\b", "", text)

    # Remove CVT_L, HV_L type suffixes
    text = re.sub(r"CVT_[A-Z]", "", text)
    text = re.sub(r"HV_[A-Z]", "", text)

    # Split into words, clean punctuation
    words = [w.strip("()[].,/_-") for w in text.split()]
    words = [w for w in words if len(w) > 0]

    # Filter noise words
    trim_parts = []
    for w in words:
        if w in _NOISE_WORDS:
            continue
        if len(w) < 2:
            continue
        # Skip known truncation artifacts
        if w in _TRUNCATION_FIXES:
            replacement = _TRUNCATION_FIXES[w]
            if replacement:
                trim_parts.append(replacement)
            continue
        trim_parts.append(w)

    result = " ".join(trim_parts).strip()

    # Apply alias normalization
    if result in _TRIM_ALIASES:
        result = _TRIM_ALIASES[result]

    # Final cleanup: remove trailing transmission words that slipped through
    result = re.sub(r"\s*(AUTOMAT|AUTOMATI|AUTOMATIC|AUTOM|TIPTRONI|TIPTRO)\s*$", "", result).strip()

    return result if result else "BASE"


def build_model_trim(model_red: str, modelo_full: str, shortname: str) -> str:
    """Build a model_trim key combining MODELO RED + extracted trim.

    If MODELO RED already contains the trim (e.g. "HYUNDAI CRETA PLATINUM"),
    returns model_red as-is. Otherwise appends the trim.

    Args:
        model_red: The MODELO RED value (e.g. "HONDA HR-V").
        modelo_full: Full model description for trim extraction.
        shortname: Model short name (e.g. "HR-V").

    Returns:
        model_trim key (e.g. "HONDA HR-V EXL", "HYUNDAI CRETA PLATINUM").
    """
    model_red_norm = _normalize(model_red)
    trim = extract_trim(modelo_full, shortname)

    if trim == "BASE":
        return model_red_norm

    # Check if the trim is already part of MODELO RED
    # e.g. model_red="HYUNDAI CRETA PLATINUM", trim="PLATINUM"
    trim_upper = trim.upper()
    if trim_upper in model_red_norm:
        return model_red_norm

    return f"{model_red_norm} {trim_upper}"


def _normalize(text: str) -> str:
    """Normalize text: remove accents, uppercase, strip."""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.upper().strip()
