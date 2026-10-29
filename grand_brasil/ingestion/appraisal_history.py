"""Appraisal history loader — reads Grand Brasil's historical appraisal database.

Two source layouts are supported and auto-detected from the header:

LEGACY (Excel export up to Apr/2026, ~17k rows)
    "Data de Avaliação"  → appraisal_date
    "Status"              → status
    "Marca"               → brand
    "Modelo"              → model               (family only, e.g. "CRETA")
    "Versão"              → version
    "Ano Modelo"          → year_model
    "KM"                  → km
    "Valor avaliado"      → appraised_value     (what we PAID / offered)
    "FIPE"                → fipe_value          (FIPE at time of appraisal)
    "ref. AAV B2C/B2B", "ref. Web", "Gasto previsto", "Finalidade",
    "Placa da Avaliação", "Lojas", "Avaliador", "Classificação"

V2 (Google Sheets export of the appraisal platform, 2026 onwards)
    "Data de Criação"     → appraisal_date      ("Data Avaliação" as fallback)
    "Status" / "Marca" / "Modelo" / "Versão" / "Ano Modelo" / "km"
    "Valor Avaliado"      → appraised_value     (text "R$ 85.000,00")
    "Valor Ref. Fipe"     → fipe_value          (text "R$ 100.000,00")
    "Valor Ref. Web"      → ref_web
    "Valor Ref. Auto Avaliar" → ref_aav
    "Custos"              → expected_repair_cost
    "Finalidade" / "Placa" / "Empresa" (store) / "Avaliador" / "Classificação"
    "BLindado"            → blindado_flag       ("Sim"/"Não")

In both layouts the subset with Status == "UTILIZADO" / "REPASSE" represents
cars we actually bought and is the gold-standard training data for the
purchase price algorithm. A derived `model_red` column is built as
"BRAND MODEL" to match the format used in the sales history ingestion.
"""

import logging
import unicodedata
from pathlib import Path
from typing import Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


APPRAISAL_COLUMN_MAP: dict[str, str] = {
    "Data de Avaliação": "appraisal_date",
    "Status": "status",
    "Marca": "brand",
    "Modelo": "model",
    "Versão": "version",
    "Ano Modelo": "year_model",
    "KM": "km",
    "Valor avaliado": "appraised_value",
    "FIPE": "fipe_value",
    "ref. AAV B2C": "ref_aav_b2c",
    "ref. AAV B2B": "ref_aav_b2b",
    "ref. Web": "ref_web",
    "Gasto previsto": "expected_repair_cost",
    "Finalidade": "purpose",
    "Placa da Avaliação": "plate",
    "Lojas": "store",
    "Avaliador": "appraiser",
    "Classificação": "classification",
}

APPRAISAL_COLUMN_MAP_V2: dict[str, str] = {
    "Data de Criação": "appraisal_date",
    "Data Avaliação": "appraisal_date_alt",
    "Status": "status",
    "Marca": "brand",
    "Modelo": "model",
    "Versão": "version",
    "Ano Modelo": "year_model",
    "km": "km",
    "Valor Avaliado": "appraised_value",
    "Valor Ref. Fipe": "fipe_value",
    "Valor Ref. Web": "ref_web",
    "Valor Ref. Auto Avaliar": "ref_aav",
    "Custos": "expected_repair_cost",
    "Finalidade": "purpose",
    "Placa": "plate",
    "Empresa": "store",
    "Avaliador": "appraiser",
    "Classificação": "classification",
    "BLindado": "blindado_flag",
}

# Ratio bounds used to discard clearly-bad rows (data entry errors, outliers).
# These bounds are intentionally wide — the algorithm will median-aggregate
# the kept rows, so a couple of percentage points of noise at the tail is fine.
_MIN_RATIO = 0.40
_MAX_RATIO = 1.30
_MIN_FIPE = 5_000
_MIN_APPRAISED = 1_000

# Weight assigned to each status when computing the weighted median ratio.
# UTILIZADO and REPASSE are cars we actually bought (closed deals) — full weight.
# AVALIADO rows represent our team's offered value that did NOT close: still
# informative about our pricing judgment but weighted less.
STATUS_WEIGHTS: dict[str, float] = {
    "UTILIZADO": 1.0,
    "REPASSE": 1.0,
    "AVALIADO": 0.4,
}


def load_appraisal_history(
    source: Union[str, Path],
    utilizado_only: bool = False,
    include_avaliado: bool = True,
    status_weights: Optional[dict[str, float]] = None,
    trim_rules: bool = True,
) -> pd.DataFrame:
    """Load the historical appraisal Excel into a cleaned DataFrame.

    Args:
        source: Path to the appraisal Excel file (legacy or V2 layout).
        utilizado_only: If True, keep only rows where Status == "UTILIZADO"
            (cars we actually bought). Default False — AVALIADO rows are
            also valuable (team's pricing judgment) and included with
            reduced weight.
        include_avaliado: If True and utilizado_only is False, also include
            AVALIADO rows (appraisals that didn't close) with reduced weight.
        status_weights: Optional override for {status: weight}. Defaults to
            STATUS_WEIGHTS (UTILIZADO=1.0, REPASSE=1.0, AVALIADO=0.4).

    Returns:
        DataFrame with cleaned columns, a computed `ratio` column, a
        `weight` column (1.0 for closed deals, 0.4 for AVALIADO), and
        a `model_red` column ("BRAND MODEL") for cross-reference.
    """
    path = Path(source)
    df = _read_excel_auto_header(path)
    logger.info(f"Loaded {len(df)} raw appraisal rows from {path.name}")

    layout = detect_layout(df.columns)
    mapping = APPRAISAL_COLUMN_MAP_V2 if layout == "v2" else APPRAISAL_COLUMN_MAP
    df = df.rename(columns=_build_rename_map(df.columns, mapping))
    logger.info(f"Appraisal layout detected: {layout}")

    if layout == "v2":
        # Platform export: ISO timestamps; "Data Avaliação" fills gaps in "Data de Criação"
        parsed = pd.to_datetime(df["appraisal_date"], errors="coerce")
        if "appraisal_date_alt" in df.columns:
            parsed = parsed.fillna(pd.to_datetime(df.pop("appraisal_date_alt"), errors="coerce"))
        df["appraisal_date"] = parsed
    else:
        # Legacy export: dd/mm/yyyy strings
        df["appraisal_date"] = pd.to_datetime(df["appraisal_date"], dayfirst=True, errors="coerce")

    # Filter by status
    df["status_norm"] = df["status"].astype(str).str.upper().str.strip()
    if utilizado_only:
        allowed = {"UTILIZADO"}
    elif include_avaliado:
        allowed = {"UTILIZADO", "REPASSE", "AVALIADO"}
    else:
        allowed = {"UTILIZADO", "REPASSE"}
    df = df[df["status_norm"].isin(allowed)].copy()
    logger.info(
        f"Filtered by status {sorted(allowed)}: {len(df)} rows "
        f"(breakdown: {df['status_norm'].value_counts().to_dict()})"
    )

    # Clean numeric fields (V2 exports currency as "R$ 85.000,00" text)
    df["appraised_value"] = _parse_brl(df["appraised_value"])
    df["fipe_value"] = _parse_brl(df["fipe_value"])
    df["km"] = pd.to_numeric(df["km"], errors="coerce")
    df["year_model"] = pd.to_numeric(df["year_model"], errors="coerce").astype("Int64")

    for opt_col in ("ref_aav", "ref_aav_b2c", "ref_aav_b2b", "ref_web", "expected_repair_cost"):
        if opt_col in df.columns:
            df[opt_col] = _parse_brl(df[opt_col])

    if "blindado_flag" in df.columns:
        df["blindado_flag"] = (
            df["blindado_flag"].astype(str).str.strip().str.upper().eq("SIM")
        )

    # Normalize brand and model for matching
    df["brand"] = df["brand"].astype(str).str.strip().str.upper()
    df["model"] = df["model"].astype(str).str.strip().str.upper()
    df["model_red"] = df["brand"] + " " + df["model"]

    # Keep only rows with usable data
    before = len(df)
    df = df[
        (df["fipe_value"] >= _MIN_FIPE)
        & (df["appraised_value"] >= _MIN_APPRAISED)
        & df["year_model"].notna()
        & (df["brand"] != "NAN")
        & (df["model"] != "NAN")
    ].copy()

    # Compute ratio (what we paid/offered / FIPE at time)
    df["ratio"] = df["appraised_value"] / df["fipe_value"]

    # Drop obvious outliers (data entry errors → ratios way outside reasonable range)
    df = df[(df["ratio"] >= _MIN_RATIO) & (df["ratio"] <= _MAX_RATIO)].copy()

    # Assign weight based on status: closed deals full weight, AVALIADO partial
    weights_to_use = status_weights if status_weights is not None else STATUS_WEIGHTS
    df["weight"] = df["status_norm"].map(weights_to_use).fillna(0.0)

    weight_breakdown = df.groupby("status_norm")["weight"].first().to_dict()
    logger.info(
        f"Appraisal history cleaned: {len(df)} rows kept of {before} "
        f"({before - len(df)} outliers/invalid dropped). "
        f"Weights by status: {weight_breakdown}"
    )

    # Apply generation / body-style splits using the 'version' column as
    # the source text. Mirrors sales_history for consistency so the
    # buy-ratio engine can match properly across data sources.
    from grand_brasil.utils.model_generation import apply_generation_split_df
    if "version" in df.columns:
        apply_generation_split_df(df, source_col="version",
                                  model_red_col="model_red",
                                  model_trim_col=None,
                                  trim_rules=trim_rules)

    return df.reset_index(drop=True)


def merge_with_legacy(
    primary: pd.DataFrame,
    legacy: pd.DataFrame,
    legacy_until: Union[str, pd.Timestamp],
) -> pd.DataFrame:
    """Append legacy rows dated before `legacy_until` to the primary base.

    The V2 export only has reliable coverage from 2026 onwards; the legacy
    Excel carries 2025. Rows from the primary base always win — a legacy row
    is dropped when the primary already has the same plate + year_model on
    the same day.
    """
    cutoff = pd.Timestamp(legacy_until)
    old = legacy[legacy["appraisal_date"] < cutoff].copy()
    if old.empty:
        return primary

    def _key(df: pd.DataFrame) -> pd.Series:
        plate = df["plate"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
        return plate + "|" + df["year_model"].astype(str) + "|" + df["appraisal_date"].dt.strftime("%Y-%m-%d")

    if "plate" in primary.columns and "plate" in old.columns:
        old = old[~_key(old).isin(set(_key(primary)))]

    merged = pd.concat([primary, old], ignore_index=True, sort=False)
    logger.info(
        f"Merged {len(old)} legacy appraisal rows (before {cutoff:%d/%m/%Y}) "
        f"into {len(primary)} primary rows -> {len(merged)}"
    )
    return merged


def reconcile_with_sales(
    appraisal_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    tolerance: float = 0.05,
    max_lag_days: int = 365,
) -> pd.DataFrame:
    """Use the sale's adjusted cost as 'what we paid' when the appraisal record disagrees.

    For closed deals whose plate shows up in a sale within `max_lag_days`, the
    accounting cost is the truth; 94% already match within 2%, the rest are
    typing errors (a 2023 Corolla recorded at 58% of FIPE). `paid_source` is
    "confirmado" when the sale agrees with the record, "venda" when the sale
    cost replaced it (ratio recomputed), "avaliacao" when no sale matched.
    """
    if appraisal_df.empty or sales_df is None or sales_df.empty:
        return appraisal_df
    df = appraisal_df.copy()
    df["paid_source"] = "avaliacao"
    closed = df["status_norm"].isin({"UTILIZADO", "REPASSE"}) & df["plate"].notna() & df["appraisal_date"].notna()
    if not closed.any():
        return df
    norm = lambda s: s.astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    left = df[closed][["plate", "appraisal_date"]].copy()
    left["_plate"] = norm(left["plate"])
    left["_idx"] = left.index
    sales = sales_df[sales_df["sale_date"].notna() & sales_df["plate"].notna()][["plate", "sale_date", "adjusted_cost"]].copy()
    sales["_plate"] = norm(sales["plate"])
    merged = pd.merge_asof(
        left.sort_values("appraisal_date"), sales.sort_values("sale_date").drop(columns=["plate"]),
        left_on="appraisal_date", right_on="sale_date", by="_plate", direction="forward",
        tolerance=pd.Timedelta(days=max_lag_days),
    )
    merged = merged[merged["adjusted_cost"].notna() & (merged["adjusted_cost"] > 0)].set_index("_idx")
    paid = df.loc[merged.index, "appraised_value"]
    off = (paid - merged["adjusted_cost"]).abs() / merged["adjusted_cost"] > tolerance
    df.loc[merged.index[~off], "paid_source"] = "confirmado"
    fix_idx = merged.index[off]
    df.loc[fix_idx, "appraised_value"] = merged.loc[fix_idx, "adjusted_cost"]
    df.loc[fix_idx, "paid_source"] = "venda"
    df.loc[fix_idx, "ratio"] = df.loc[fix_idx, "appraised_value"] / df.loc[fix_idx, "fipe_value"]
    logger.info(f"Reconciled {len(fix_idx)} appraisals with the sale cost (of {len(merged)} matched)")
    return df


def drop_implausible_ratios(appraisal_df: pd.DataFrame, floor_by_age: dict[int, float]) -> pd.DataFrame:
    """Drop closed deals whose ratio is below the empirical floor for the car's age.

    `floor_by_age` maps the maximum age of a bracket to its floor, e.g.
    {0: 0.70, 1: 0.65, 3: 0.65, 6: 0.58, 10: 0.50, 99: 0.40} (P1 of closed deals).
    AVALIADO offers are left alone (a low offer that did not close is real), and
    so are closed deals whose paid value the later sale confirmed (`paid_source`
    "confirmado" or "venda"): a 300k-km car bought at 46% of FIPE is extreme, not an error.
    """
    if not floor_by_age or appraisal_df.empty:
        return appraisal_df
    df = appraisal_df
    unconfirmed = ~df["paid_source"].isin({"confirmado", "venda"}) if "paid_source" in df.columns else pd.Series(True, index=df.index)
    age = (pd.to_datetime(df["appraisal_date"], errors="coerce").dt.year - df["year_model"].astype(float)).fillna(0).clip(lower=0)
    edges = sorted(int(k) for k in floor_by_age)
    floors = pd.Series(min(floor_by_age.values()), index=df.index, dtype=float)
    for max_age in reversed(edges):
        floors = floors.where(age > max_age, float(floor_by_age[max_age]))
    closed = df["status_norm"].isin({"UTILIZADO", "REPASSE"})
    drop = closed & unconfirmed & (df["ratio"] < floors)
    if drop.any():
        logger.info(f"Dropped {int(drop.sum())} closed deals with implausible ratio for their age")
    return df[~drop].copy()


def detect_layout(columns) -> str:
    """Return "v2" for the appraisal-platform export, "legacy" otherwise."""
    normed = {_norm(c) for c in columns}
    return "v2" if "valorref.fipe" in normed else "legacy"


def _parse_brl(series: pd.Series) -> pd.Series:
    """Parse numbers that may come as Brazilian currency text ("R$ 1.234,56")."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype(str)
        .str.replace(r"[R$\s]", "", regex=True)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _read_excel_auto_header(path: Path) -> pd.DataFrame:
    """Read the appraisal Excel trying header=0..3 and picking the one that
    yields real column names (e.g. 'Status', 'Marca' and a FIPE column).

    Exports from the source system sometimes gain/lose leading blank rows.
    """
    for header_row in range(0, 4):
        try:
            df = pd.read_excel(path, sheet_name=0, header=header_row)
        except Exception:
            continue
        cols = {_norm(c) for c in df.columns}
        if {"status", "marca"}.issubset(cols) and any("fipe" in c for c in cols):
            if header_row > 0:
                logger.info(f"Auto-detected header at row {header_row} (blank rows above)")
            return df
    # Fallback to default (row 0) — loader will raise a clear error later
    return pd.read_excel(path, sheet_name=0)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = s.encode("ascii", "ignore").decode("ascii")
    return s.strip().lower().replace(" ", "")


def _build_rename_map(
    actual_columns: pd.Index,
    mapping: dict[str, str],
) -> dict[str, str]:
    """Tolerantly match expected column names (handles accent/case drift)."""
    rename: dict[str, str] = {}
    actual_norm = {_norm(c): c for c in actual_columns}

    for expected_orig, internal in mapping.items():
        key = _norm(expected_orig)
        if key in actual_norm:
            rename[actual_norm[key]] = internal

    return rename
