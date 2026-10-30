"""Walk-forward execution of the appraisal engine over backtest cases.

For every test month, the engine only sees sales and appraisals dated before
the first day of that month (never the same car's own appraisals), exactly the
information a live appraisal on that day would have had. Each case is scored
with the full `appraise()` pipeline and the number the UI would show as the
headline (buy-ratio price when available, otherwise the channel blend).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

import pandas as pd

from grand_brasil.analysis.appraisal import appraise
from grand_brasil.analysis.purchase_ratio import (
    compute_brand_year_profile,
    compute_km_slope,
    compute_km_slope_piecewise,
    compute_year_ratio_profile,
)
from grand_brasil.backtest.dataset import normalize_plate
from grand_brasil.config import AppraisalConfig
from grand_brasil.models.appraisal import AppraisalRequest, AppraisalSuggestion

logger = logging.getLogger(__name__)

# Which engine value stands as the prediction (mirrors result.py headline logic)
Headline = Callable[[AppraisalSuggestion], Optional[float]]


def ui_headline(s: AppraisalSuggestion) -> Optional[float]:
    if s.recommended_value is not None and s.recommended_value > 0:
        return float(s.recommended_value)
    if s.buy_ratio_available and s.buy_ratio_price and s.buy_ratio_price > 0:
        return float(s.buy_ratio_price)
    if s.blended_max_trade_value and s.blended_max_trade_value > 0:
        return float(s.blended_max_trade_value)
    return None


@dataclass
class RunOptions:
    purpose: str = "auto"
    confidence_model: object = None     # ConfidenceModel; None = count-based confidence
    exclude_same_plate: bool = True
    headline: Headline = ui_headline
    progress_every: int = 500


def run_backtest(
    cases: pd.DataFrame,
    sales: pd.DataFrame,
    appraisals: pd.DataFrame,
    cfg: AppraisalConfig,
    fipe_client,
    options: Optional[RunOptions] = None,
) -> pd.DataFrame:
    opts = options or RunOptions()
    appr = appraisals.copy()
    appr["plate_norm"] = normalize_plate(appr["plate"]) if "plate" in appr.columns else ""
    sales = sales[sales["sale_date"].notna()].copy()

    rows: list[dict] = []
    t0 = time.time()
    months = sorted(cases["appraisal_date"].dt.to_period("M").unique())
    done = 0
    for month in months:
        cutoff = month.start_time
        train_sales = sales[sales["sale_date"] < cutoff]
        train_appr = appr[appr["appraisal_date"] < cutoff]
        profile = compute_year_ratio_profile(train_appr, min_rows=getattr(cfg.buy_ratio, 'year_profile_min_rows', 1))
        if getattr(cfg.buy_ratio, 'km_adjust', False):
            km_slope = (compute_km_slope_piecewise(train_appr, list(cfg.buy_ratio.km_piecewise_breaks))
                        if getattr(cfg.buy_ratio, 'km_adjust_mode', 'linear') == 'piecewise' else compute_km_slope(train_appr))
        else:
            km_slope = None
        brand_profile = compute_brand_year_profile(train_appr) if getattr(cfg.buy_ratio, 'year_profile_by_brand', False) else None
        model_volume = train_sales["model_red"].value_counts()
        month_cases = cases[cases["appraisal_date"].dt.to_period("M") == month]

        for _, c in month_cases.iterrows():
            appr_df = train_appr[train_appr["plate_norm"] != c["plate_norm"]] if opts.exclude_same_plate else train_appr
            request = AppraisalRequest(
                brand=str(c["sale_brand"]),
                model_red=str(c["sale_model_red"]),
                year_model=int(c["year_model"]),
                km=int(c["km"]) if pd.notna(c["km"]) else None,
                estimated_repair_cost=Decimal(str(float(c.get("expected_repair_cost") or 0.0) if pd.notna(c.get("expected_repair_cost")) else 0.0)),
                fipe_price=Decimal(str(float(c["fipe_value"]))),
                blindado=bool(c.get("blindado_flag")) if pd.notna(c.get("blindado_flag")) else False,
                purpose=("revenda" if str(c.get("purpose", "")).upper() == "REPASSE" else "auto") if opts.purpose == "from_case" else opts.purpose,
            )
            try:
                s = appraise(
                    request=request,
                    sales_df=train_sales,
                    year_tolerance=cfg.year_tolerance,
                    loja_target_margin=cfg.loja_target_margin,
                    revenda_target_margin=cfg.revenda_target_margin,
                    min_comparables=cfg.min_comparables,
                    recency_halflife_days=cfg.recency_halflife_days,
                    year_pct_per_year=cfg.year_pct_per_year,
                    fipe_client=fipe_client,
                    fipe_brand_code=str(c["sale_brand"]),
                    fipe_model_code=str(c["model_red"]),       # family key used by the FIPE table
                    fipe_year_code=str(int(c["year_model"])),
                    appraisal_df=appr_df,
                    year_profile=profile,
                    appraisal_config=cfg,
                    reference_date=cutoff,
                    km_slope=km_slope,
                    brand_year_profile=brand_profile,
                    confidence_model=opts.confidence_model,
                )
            except Exception as e:  # keep the run alive; count failures
                logger.warning(f"appraise failed for case {c.get('plate_norm')}: {e}")
                rows.append({"case_idx": c.name, "error": str(e)})
                continue

            rows.append({
                "case_idx": c.name,
                "pred": opts.headline(s),
                "pred_source": s.recommended_source or ("buy_ratio" if (s.buy_ratio_available and s.buy_ratio_price) else (s.blended_source or "none")),
                "buy_ratio_price": float(s.buy_ratio_price) if s.buy_ratio_price else None,
                "buy_ratio_low": float(s.buy_ratio_low) if s.buy_ratio_low else None,
                "buy_ratio_high": float(s.buy_ratio_high) if s.buy_ratio_high else None,
                "buy_ratio_tier": s.buy_ratio_tier or "none",
                "buy_ratio_km_min": s.buy_ratio_km_min,
                "buy_ratio_km_max": s.buy_ratio_km_max,
                "buy_ratio_purpose_filtered": s.buy_ratio_purpose_filtered,
                "request_purpose": ("revenda" if str(c.get("purpose", "")).upper() == "REPASSE" else "auto") if opts.purpose == "from_case" else opts.purpose,
                "buy_ratio_n": s.buy_ratio_sample_size,
                "buy_ratio_closed_n": s.buy_ratio_closed_deal_count,
                "blended": float(s.blended_max_trade_value) if s.blended_max_trade_value else None,
                "loja_trade": float(s.loja_max_trade_value) if s.loja_max_trade_value else None,
                "revenda_trade": float(s.revenda_max_trade_value) if s.revenda_max_trade_value else None,
                "loja_sale_est": float(s.loja_estimated_sale_price) if s.loja_estimated_sale_price else None,
                "revenda_sale_est": float(s.revenda_estimated_sale_price) if s.revenda_estimated_sale_price else None,
                "loja_spread": s.loja_fipe_spread_pct,
                "revenda_spread": s.revenda_fipe_spread_pct,
                "loja_spread_n": s.loja_spread_sample_size,
                "revenda_spread_n": s.revenda_spread_sample_size,
                "loja_margin_target": s.loja_target_margin_percent,
                "revenda_margin_target": s.revenda_target_margin_percent,
                "p_revenda": s.p_revenda,
                "confidence": s.confidence,
                "price_mode": s.price_mode or "n/d",
                "price_mode_reasons": "; ".join(s.price_mode_reasons),
                "total_comparables": s.total_comparables,
                "loja_comparables": s.loja_comparables_count,
                "revenda_comparables": s.revenda_comparables_count,
                "anchor_divergence_pct": s.anchor_divergence_pct,
                "brand_tier": s.brand_tier,
                "model_volume_train": int(model_volume.get(str(c["sale_model_red"]), 0)),
                "train_sales_n": len(train_sales),
                "train_appr_n": len(appr_df),
            })
            done += 1
            if opts.progress_every and done % opts.progress_every == 0:
                logger.warning(f"  {done}/{len(cases)} cases ({time.time() - t0:.0f}s)")

    preds = pd.DataFrame(rows).set_index("case_idx")
    return cases.join(preds, how="left")
