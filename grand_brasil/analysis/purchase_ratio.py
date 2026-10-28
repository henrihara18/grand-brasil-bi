"""Purchase ratio engine — derives the "buy discount" from Grand Brasil's
historical appraisal database.

For each car bought historically, we have:
    ratio = valor_avaliado / FIPE_at_time

This ratio captures the appraiser's actual behavior — how much they paid
relative to FIPE — and is more accurate than working backwards from a
fixed target margin on the sell side.

Given a car to appraise, this module finds the most relevant comparables
in the appraisal history and returns a weighted ratio, with tiered
matching and a year-delta adjustment so older/newer comparables can be
used carefully.

Matching tiers (in priority order):
    1. Same year_model, KM within ±6k        (12k window)
    2. Same year_model, KM within ±12k        (24k window)
    3. year ±1 (year-adjusted),  KM ±12k
    4. year ±2 (year-adjusted),  KM ±24k
    5. Model fallback with full year-adjustment (no KM filter)

Year adjustment:
    For each year delta, there is a typical ratio shift (newer cars are
    worth a higher fraction of FIPE). The shift is computed from the data
    itself — the population median ratio per year_model — so it is
    empirically grounded rather than guessed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Matching configuration (defaults; overridable via BuyRatioConfig) ──────
# These default values keep the module usable from tests/scripts without
# requiring the full config bootstrap. Production code flows through
# config.yaml → BuyRatioConfig and may override via compute_buy_ratio(...,
# config=...).

_KM_WINDOW_TIGHT = 6_000       # ±6k → 12k total
_KM_WINDOW_WIDE = 12_000       # ±12k → 24k total
_KM_WINDOW_WIDEST = 24_000     # ±24k → 48k total
_MIN_TIER_SAMPLE = 5           # Need at least 5 comps in a tier to use it
_MIN_FALLBACK_SAMPLE = 3       # Bare minimum for any estimate at all


@dataclass
class BuyRatioResult:
    """Output of a buy-ratio lookup."""

    ratio_median: Optional[float] = None       # Adjusted weighted median ratio
    ratio_p25: Optional[float] = None          # 25th percentile (conservative band)
    ratio_p75: Optional[float] = None          # 75th percentile (optimistic band)
    sample_size: int = 0                       # Number of comparables used (raw count)
    effective_sample: float = 0.0              # Sum of weights (effective sample size)
    closed_deal_count: int = 0                 # Of those, how many were closed deals
    offered_count: int = 0                     # Of those, how many were offers only
    tier: str = "none"                         # Which tier matched
    year_delta_applied: bool = False           # Whether a year adjustment was used
    model_key_used: str = ""                   # model_red actually matched in the base
    shrink_weight: Optional[float] = None      # weight of the local median after shrinkage (1 = none)
    prior_ratio: Optional[float] = None        # prior the ratio was shrunk toward
    family_fallback: bool = False              # True when trim had no rows and the family was used
    description: str = ""                      # Human-readable explanation
    comparables: pd.DataFrame = field(default_factory=pd.DataFrame)  # Rows used

    @property
    def available(self) -> bool:
        return self.ratio_median is not None and self.sample_size >= _MIN_FALLBACK_SAMPLE

    def price_at(self, fipe_value: float) -> Optional[float]:
        """Apply the ratio to a FIPE value to get a suggested purchase price."""
        if not self.available:
            return None
        return fipe_value * self.ratio_median

    def band_at(self, fipe_value: float) -> Optional[tuple[float, float]]:
        """(low, high) confidence band based on P25/P75."""
        if not self.available or self.ratio_p25 is None or self.ratio_p75 is None:
            return None
        return fipe_value * self.ratio_p25, fipe_value * self.ratio_p75


# ── Year-delta adjustment ───────────────────────────────────────────────────

def compute_year_ratio_profile(appraisal_df: pd.DataFrame) -> dict[int, float]:
    """Compute the weighted median ratio per year_model across the whole appraisal base.

    Uses the `weight` column if present (closed deals count full, offered
    appraisals count 0.4) so the empirical year-curve isn't pulled by
    the offer-only rows.

    Returns:
        Mapping of year_model → weighted-median ratio. Empty dict if the
        input has no year_model/ratio columns or is empty.
    """
    if len(appraisal_df) == 0 or not {"year_model", "ratio"}.issubset(appraisal_df.columns):
        return {}
    df = appraisal_df.dropna(subset=["year_model", "ratio"])
    profile: dict[int, float] = {}
    has_weights = "weight" in df.columns

    for year, group in df.groupby("year_model"):
        if has_weights:
            median = _weighted_quantile(group["ratio"], group["weight"], 0.50)
        else:
            median = float(group["ratio"].median())
        profile[int(year)] = median

    return profile


def compute_brand_year_profile(appraisal_df: pd.DataFrame, min_rows: int = 15) -> dict[str, dict[int, float]]:
    """Weighted-median ratio per (brand, year_model), only for cells with enough rows.

    The global curve mixes brands that depreciate very differently (a 2022 BYD
    trades at ~0.59 of FIPE, a 2022 Toyota at ~0.86); the per-brand curve
    removes that mix effect when adjacent-year comparables are used.
    """
    if len(appraisal_df) == 0 or not {"brand", "year_model", "ratio"}.issubset(appraisal_df.columns):
        return {}
    df = appraisal_df.dropna(subset=["brand", "year_model", "ratio"])
    has_weights = "weight" in df.columns
    out: dict[str, dict[int, float]] = {}
    for (brand, year), group in df.groupby(["brand", "year_model"]):
        if len(group) < min_rows:
            continue
        median = _weighted_quantile(group["ratio"], group["weight"], 0.50) if has_weights else float(group["ratio"].median())
        out.setdefault(str(brand).upper(), {})[int(year)] = median
    return out


def _adjust_ratio_for_year(
    row_ratio: float,
    row_year: int,
    target_year: int,
    year_profile: dict[int, float],
    brand_profile: Optional[dict[int, float]] = None,
) -> float:
    """Shift a comparable's ratio to reflect the target year.

    When `brand_profile` covers both years, the brand curve is used instead
    of the global one.

    Uses the empirical year→ratio curve: the delta between the two years'
    typical ratios is added to the comparable's own ratio.

    Example:
        Comparable is a 2022 (ratio profile 0.850) sold at 0.88,
        Target is a 2024 (ratio profile 0.877).
        Delta = 0.877 - 0.850 = +0.027
        Adjusted ratio = 0.88 + 0.027 = 0.907
    """
    curve = year_profile
    if brand_profile and int(row_year) in brand_profile and int(target_year) in brand_profile:
        curve = brand_profile
    row_year_ref = curve.get(int(row_year))
    target_year_ref = curve.get(int(target_year))
    if row_year_ref is None or target_year_ref is None:
        return row_ratio
    delta = target_year_ref - row_year_ref
    return row_ratio + delta


# ── Core matching ───────────────────────────────────────────────────────────

def compute_buy_ratio(
    model_red: str,
    year_model: int,
    km: Optional[int],
    appraisal_df: pd.DataFrame,
    year_profile: Optional[dict[int, float]] = None,
    config=None,
    reference_date: Optional[pd.Timestamp] = None,
    km_slope: Optional[float] = None,
    brand_year_profile: Optional[dict[str, dict[int, float]]] = None,
) -> BuyRatioResult:
    """Find comparables in the appraisal base and return a buy-ratio estimate.

    Args:
        model_red: Model key in "BRAND MODEL" format (e.g. "HYUNDAI CRETA").
        year_model: Target model year.
        km: Target car km (optional; KM-window tiers are skipped if None).
        appraisal_df: Cleaned appraisal history (see appraisal_history.py).
        year_profile: Precomputed per-year ratio curve. Computed on-the-fly
            if not provided (for convenience; cache it in prod).
        config: Optional BuyRatioConfig overriding the module defaults
            (tier thresholds, KM windows, tier order, recency, KM adjust).
        reference_date: "Today" for recency weighting (defaults to now).
            Only used when config.recency_halflife_days is set.
        km_slope: Ratio change per 10k km (negative), see compute_km_slope().
            Only used when config.km_adjust is True.

    Returns:
        BuyRatioResult with the ratio, confidence band, and metadata.
    """
    # Resolve tunable thresholds: prefer the injected config, otherwise
    # fall back to the module-level defaults.
    km_tight = config.km_window_tight if config is not None else _KM_WINDOW_TIGHT
    km_wide = config.km_window_wide if config is not None else _KM_WINDOW_WIDE
    km_widest = config.km_window_widest if config is not None else _KM_WINDOW_WIDEST
    min_tier = config.min_tier_sample if config is not None else _MIN_TIER_SAMPLE
    min_fallback = config.min_fallback_sample if config is not None else _MIN_FALLBACK_SAMPLE
    tier_order = getattr(config, "tier_order", "year_first") if config is not None else "year_first"
    halflife = getattr(config, "recency_halflife_days", None) if config is not None else None
    km_adjust = bool(getattr(config, "km_adjust", False)) if config is not None else False
    by_brand = bool(getattr(config, "year_profile_by_brand", False)) if config is not None else False
    year_scale = float(getattr(config, "year_adjust_scale", 1.0)) if config is not None else 1.0
    shrink_k = float(getattr(config, "shrink_k", 0.0)) if config is not None else 0.0

    if year_profile is None:
        year_profile = compute_year_ratio_profile(appraisal_df)
    if by_brand and brand_year_profile is None:
        brand_year_profile = compute_brand_year_profile(appraisal_df)
    if not by_brand:
        brand_year_profile = None

    requested_key = model_red.strip().upper()
    model_key, candidates = _resolve_model_key(requested_key, appraisal_df)
    if candidates.empty:
        return BuyRatioResult(description=f"Sem avaliacoes historicas para {requested_key}.")

    if halflife and "appraisal_date" in candidates.columns:
        candidates = _apply_recency(candidates, reference_date or pd.Timestamp.now(), float(halflife))

    prior = _prior_ratio(candidates, year_model, year_profile, brand_year_profile) if shrink_k > 0 else None
    tiers = _tier_sequence(tier_order, km_tight, km_wide, km_widest)
    result = _match_tiers(
        candidates, model_key, year_model, km, year_profile, tiers, min_tier, min_fallback,
        km_slope=km_slope if (km_adjust and km is not None) else None,
        brand_profiles=brand_year_profile,
        year_scale=year_scale,
        prior=prior,
        shrink_k=shrink_k,
    )
    result.model_key_used = model_key
    if model_key != requested_key:
        result.family_fallback = True
        result.description += (
            f" Acabamento {requested_key} sem historico proprio — usada a familia {model_key}."
        )
    return result


def _resolve_model_key(requested_key: str, appraisal_df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Exact model_red first; otherwise drop trailing (trim) tokens until the family matches.

    Sales carry the trim in model_red ("HYUNDAI CRETA LIMITED") while the
    appraisal base only has the family ("HYUNDAI CRETA"); without this the
    primary anchor silently disappears for every trim-level model.
    """
    tokens = requested_key.split()
    key = requested_key
    while True:
        candidates = appraisal_df[appraisal_df["model_red"] == key]
        if not candidates.empty:
            return key, candidates.copy()
        if len(tokens) <= 2:
            return requested_key, appraisal_df.iloc[0:0].copy()
        tokens = tokens[:-1]
        key = " ".join(tokens)


@dataclass(frozen=True)
class Tier:
    name: str
    year_tolerance: int
    km_window: Optional[int]      # None = no KM filter


def _tier_sequence(order: str, km_tight: int, km_wide: int, km_widest: int) -> list[Tier]:
    """Matching tiers in priority order.

    year_first (legacy): exhaust the exact year (even without KM) before
    touching adjacent years. km_first: prefer a KM-matched adjacent year over
    the same year with any KM — the backtest shows KM explains more of the
    ratio than one model year does.
    """
    km6 = Tier("same_year_km6k", 0, km_tight)
    km12 = Tier("same_year_km12k", 0, km_wide)
    same = Tier("same_year", 0, None)
    pm1 = Tier("year_pm1_km12k", 1, km_wide)
    pm2 = Tier("year_pm2_km24k", 2, km_widest)
    if order == "km_first":
        return [km6, km12, pm1, pm2, same]
    return [km6, km12, same, pm1, pm2]


def _match_tiers(
    candidates: pd.DataFrame,
    model_key: str,
    year_model: int,
    km: Optional[int],
    year_profile: dict[int, float],
    tiers: list[Tier],
    min_tier: int,
    min_fallback: int,
    km_slope: Optional[float] = None,
    brand_profiles: Optional[dict[str, dict[int, float]]] = None,
    year_scale: float = 1.0,
    prior: Optional[float] = None,
    shrink_k: float = 0.0,
) -> BuyRatioResult:
    """Walk the matching tiers over an already-resolved candidate set."""
    for tier in tiers:
        if tier.km_window is not None:
            if km is None:
                continue
            rows = _filter_year_km(candidates, year_model, tier.year_tolerance, km, tier.km_window)
            km_note = f"com KM em [{km - tier.km_window:,} - {km + tier.km_window:,}]"
        else:
            rows = candidates[candidates["year_model"] == year_model].copy()
            km_note = "(sem filtro de KM por nao haver amostra suficiente na faixa)"
        if len(rows) < min_tier:
            continue

        year_adjusted = tier.year_tolerance > 0
        if year_adjusted:
            rows = _apply_year_adjustment(rows, year_model, year_profile, brand_profiles, year_scale)
            years = f"anos {year_model - tier.year_tolerance}-{year_model + tier.year_tolerance}"
            note = f"{km_note}, ratio ajustado ao ano {year_model}."
        else:
            years = f"ano {year_model}" if tier.km_window is None else str(year_model)
            note = f"{km_note}."
        rows = _apply_km_adjustment(rows, km, km_slope)
        return _build_result(
            rows, tier=tier.name,
            description=f"{len(rows)} avaliacoes de {model_key} {years} {note}",
            year_delta_applied=year_adjusted,
            min_tier=min_tier,
            prior=prior,
            shrink_k=shrink_k,
        )

    # Fallback: model-wide, year +-2, no KM filter
    rows = candidates[
        (candidates["year_model"] >= year_model - 2)
        & (candidates["year_model"] <= year_model + 2)
    ].copy()
    if len(rows) >= min_fallback:
        rows = _apply_km_adjustment(_apply_year_adjustment(rows, year_model, year_profile, brand_profiles, year_scale), km, km_slope)
        return _build_result(
            rows, tier="model_fallback",
            description=(
                f"{len(rows)} avaliacoes de {model_key} anos "
                f"{year_model - 2}-{year_model + 2} (sem filtro de KM), "
                f"ratio ajustado ao ano {year_model}. Confianca baixa."
            ),
            year_delta_applied=True,
            min_tier=min_tier,
            prior=prior,
            shrink_k=shrink_k,
        )

    return BuyRatioResult(
        description=(
            f"Amostra insuficiente para {model_key} {year_model} "
            f"(apenas {len(candidates)} avaliacoes no total para o modelo)."
        ),
    )


# -- Recency and KM adjustments ----------------------------------------------

def _apply_recency(df: pd.DataFrame, reference_date: pd.Timestamp, halflife_days: float) -> pd.DataFrame:
    """Scale `weight` by exp(-ln2 * age / halflife); rows without a date keep half weight."""
    df = df.copy()
    age = (pd.Timestamp(reference_date) - pd.to_datetime(df["appraisal_date"], errors="coerce")).dt.days
    decay = np.exp(-np.log(2) * age.clip(lower=0) / max(halflife_days, 1.0)).fillna(0.5)
    base = df["weight"] if "weight" in df.columns else pd.Series(1.0, index=df.index)
    df["weight"] = base * decay
    return df


def compute_km_slope(appraisal_df: pd.DataFrame, min_group: int = 3) -> Optional[float]:
    """Pooled within-(model, year) slope of ratio on KM, per 10k km (negative = more km, lower ratio).

    Demeans ratio and km inside each (model_red, year_model) group so that
    model and year effects cancel, then fits one slope on the pooled
    deviations (weighted by `weight`). Clipped to [-0.05, 0].
    """
    needed = {"model_red", "year_model", "km", "ratio"}
    if not needed.issubset(appraisal_df.columns):
        return None
    df = appraisal_df.dropna(subset=["km", "ratio", "year_model"]).copy()
    if df.empty:
        return None
    df["w"] = df["weight"] if "weight" in df.columns else 1.0
    df = df[df.groupby(["model_red", "year_model"])["ratio"].transform("size") >= min_group]
    if df.empty:
        return None
    grp = df.groupby(["model_red", "year_model"])
    dx = (df["km"].astype(float) - grp["km"].transform("mean")) / 10_000.0
    dy = df["ratio"] - grp["ratio"].transform("mean")
    denom = float((df["w"] * dx * dx).sum())
    if denom <= 0:
        return None
    slope = float((df["w"] * dx * dy).sum() / denom)
    return float(np.clip(slope, -0.05, 0.0))


def _apply_km_adjustment(df: pd.DataFrame, km: Optional[int], km_slope: Optional[float]) -> pd.DataFrame:
    """Shift each comparable's ratio to the target KM using the pooled slope."""
    if km_slope is None or km is None or "km" not in df.columns:
        return df
    df = df.copy()
    col = "adjusted_ratio" if "adjusted_ratio" in df.columns else "ratio"
    delta = km_slope * (float(km) - df["km"].astype(float)) / 10_000.0
    df["adjusted_ratio"] = df[col] + delta.fillna(0.0)
    return df


def _prior_ratio(
    candidates: pd.DataFrame,
    year_model: int,
    year_profile: dict[int, float],
    brand_profiles: Optional[dict[str, dict[int, float]]],
) -> Optional[float]:
    """Reference ratio for shrinkage: brand-year curve if available, else the global year curve."""
    if brand_profiles and "brand" in candidates.columns and len(candidates):
        brand = str(candidates["brand"].iloc[0]).upper()
        curve = brand_profiles.get(brand) or {}
        if int(year_model) in curve:
            return float(curve[int(year_model)])
    value = year_profile.get(int(year_model))
    return float(value) if value is not None else None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _filter_year_km(
    df: pd.DataFrame,
    target_year: int,
    year_tolerance: int,
    km: int,
    km_window: int,
) -> pd.DataFrame:
    """Filter the candidate frame by year and KM windows."""
    mask = (
        (df["year_model"] >= target_year - year_tolerance)
        & (df["year_model"] <= target_year + year_tolerance)
        & (df["km"].notna())
        & (df["km"] >= km - km_window)
        & (df["km"] <= km + km_window)
    )
    return df[mask].copy()


def _apply_year_adjustment(
    df: pd.DataFrame,
    target_year: int,
    year_profile: dict[int, float],
    brand_profiles: Optional[dict[str, dict[int, float]]] = None,
    scale: float = 1.0,
) -> pd.DataFrame:
    """Add an `adjusted_ratio` column with year-delta adjustment applied (times `scale`)."""
    df = df.copy()
    has_brand = brand_profiles is not None and "brand" in df.columns
    df["adjusted_ratio"] = df.apply(
        lambda r: float(r["ratio"]) + scale * (_adjust_ratio_for_year(
            float(r["ratio"]), int(r["year_model"]), target_year, year_profile,
            brand_profiles.get(str(r["brand"]).upper()) if has_brand else None,
        ) - float(r["ratio"])),
        axis=1,
    )
    return df


def _weighted_quantile(values: pd.Series, weights: pd.Series, q: float) -> float:
    """Compute the weighted quantile of `values` using `weights`.

    Falls back to the unweighted quantile if all weights are zero.
    """
    if len(values) == 0:
        return float("nan")
    if weights.sum() == 0:
        return float(values.quantile(q))

    df = pd.DataFrame({"v": values.values, "w": weights.values}).sort_values("v")
    cumw = df["w"].cumsum() / df["w"].sum()
    mask = cumw >= q
    return float(df.loc[mask, "v"].iloc[0]) if mask.any() else float(df["v"].iloc[-1])


def _build_result(
    df: pd.DataFrame,
    tier: str,
    description: str,
    year_delta_applied: bool = False,
    min_tier: int = _MIN_TIER_SAMPLE,
    prior: Optional[float] = None,
    shrink_k: float = 0.0,
) -> BuyRatioResult:
    """Aggregate ratios into a BuyRatioResult.

    Closed-deal preference policy:
      • If there are >= min_tier UTILIZADO/REPASSE rows, use ONLY those.
        These reflect the price actually paid — the signal we care about.
      • Otherwise, fall back to the full set (including AVALIADO) with
        status weights. This extends coverage to rare models where closed
        deals are sparse.

    This policy avoids the bias where many low-ratio AVALIADO rows (offers
    customers rejected) drag the estimate below what we would actually pay.
    """
    col = "adjusted_ratio" if "adjusted_ratio" in df.columns else "ratio"
    mask = df[col].notna()
    valid = df[mask].copy()
    if valid.empty:
        return BuyRatioResult(description=description + " (sem ratios validos)")

    has_status = "status_norm" in valid.columns
    if has_status:
        closed_mask = valid["status_norm"].isin({"UTILIZADO", "REPASSE"})
        closed_rows = valid[closed_mask]
        offered_rows = valid[~closed_mask]
    else:
        closed_rows = valid
        offered_rows = valid.iloc[0:0]

    # ── Closed-deal-only path (preferred) ──
    if len(closed_rows) >= min_tier:
        sub = closed_rows
        ratios = sub[col]
        weights = sub["weight"] if "weight" in sub.columns else pd.Series([1.0] * len(sub), index=sub.index)
        used_avaliado = False
    else:
        # ── Fallback: include AVALIADO (weighted) to reach sample threshold ──
        sub = valid
        ratios = sub[col]
        weights = sub["weight"] if "weight" in sub.columns else pd.Series([1.0] * len(sub), index=sub.index)
        used_avaliado = len(offered_rows) > 0

    closed = int(len(closed_rows))
    offered = int(len(offered_rows)) if used_avaliado else 0

    # Annotate description with the policy that was applied
    if not used_avaliado:
        final_desc = description + f" [{closed} vendas fechadas apenas]"
    else:
        final_desc = (
            description
            + f" [{closed} fechadas + {offered} avaliacoes nao-fechadas c/ peso 0.4 "
            + "— UTILIZADO insuficiente]"
        )

    median = _weighted_quantile(ratios, weights, 0.50)
    p25 = _weighted_quantile(ratios, weights, 0.25)
    p75 = _weighted_quantile(ratios, weights, 0.75)
    shrink_w: Optional[float] = None
    if prior is not None and shrink_k > 0:
        # Small samples are noisy: pull the local median toward the prior with
        # weight n/(n+k); the P25-P75 band moves with it (same width).
        n_eff = float(weights.sum())
        shrink_w = n_eff / (n_eff + shrink_k)
        shift = (shrink_w - 1.0) * (median - prior)
        median, p25, p75 = median + shift, p25 + shift, p75 + shift
        final_desc += f" Mediana ajustada {shrink_w:.0%} local / {1 - shrink_w:.0%} referencia ({prior:.3f})."

    return BuyRatioResult(
        ratio_median=median,
        ratio_p25=p25,
        ratio_p75=p75,
        shrink_weight=shrink_w,
        prior_ratio=prior,
        sample_size=len(sub),
        effective_sample=float(weights.sum()),
        closed_deal_count=closed,
        offered_count=offered,
        tier=tier,
        year_delta_applied=year_delta_applied,
        description=final_desc,
        comparables=sub.reset_index(drop=True),
    )
