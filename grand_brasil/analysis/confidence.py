"""Calibrated confidence for an appraisal.

Instead of counting comparables, the confidence of a suggestion is the
empirical error distribution of PAST suggestions that looked like it. Each
appraisal is described by four signals known at appraisal time:

    tier       — which buy-ratio tier matched (same year / KM window / fallback)
    divergence — how far the two anchors (historical buy ratio vs. sales-based)
                 are from each other
    width      — relative width of the buy-ratio P25–P75 band
    closed_n   — number of closed deals behind the buy ratio

The calibration table stores, for every combination seen often enough, the
quantiles of |error| realized on linked sales. At prediction time the most
specific combination with enough history is used (tier×div×width×n →
tier×div×width → tier×div → tier → global), and the level follows from the
90 % quantile:

    alta   q90 <= high_max   (default 10 %)
    media  q90 <= medium_max (default 15 %)
    baixa  otherwise

Calibrated walk-forward in the backtest (only residuals dated before the
appraisal) and refreshed from the same backtest for production.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

QUANTILES = (0.5, 0.8, 0.9)
LEVELS = ("alta", "media", "baixa")


def divergence_bucket(div: Optional[float]) -> str:
    if div is None or (isinstance(div, float) and np.isnan(div)):
        return "none"
    d = abs(float(div))
    return "<=3%" if d <= 0.03 else "<=8%" if d <= 0.08 else ">8%"


def width_bucket(low: Optional[float], high: Optional[float], price: Optional[float]) -> str:
    if low is None or high is None or price is None or not price or any(
        isinstance(v, float) and np.isnan(v) for v in (low, high, price)
    ):
        return "none"
    w = (float(high) - float(low)) / float(price)
    return "<=4%" if w <= 0.04 else "<=8%" if w <= 0.08 else ">8%"


def closed_bucket(n: Optional[int]) -> str:
    if n is None or (isinstance(n, float) and np.isnan(n)):
        return "0"
    n = int(n)
    return "<5" if n < 5 else "5-9" if n < 10 else "10+"


@dataclass(frozen=True)
class Signals:
    tier: str
    divergence: str
    width: str
    closed: str

    def keys(self) -> list[tuple[str, ...]]:
        """Most specific first."""
        return [
            (self.tier, self.divergence, self.width, self.closed),
            (self.tier, self.divergence, self.width),
            (self.tier, self.divergence),
            (self.tier,),
            (),
        ]


def signals_from_suggestion(s) -> Signals:
    return Signals(
        tier=str(s.buy_ratio_tier or "none"),
        divergence=divergence_bucket(s.anchor_divergence_pct),
        width=width_bucket(
            float(s.buy_ratio_low) if s.buy_ratio_low else None,
            float(s.buy_ratio_high) if s.buy_ratio_high else None,
            float(s.buy_ratio_price) if s.buy_ratio_price else None,
        ),
        closed=closed_bucket(s.buy_ratio_closed_n if hasattr(s, "buy_ratio_closed_n") else s.buy_ratio_closed_deal_count),
    )


def signals_from_row(r) -> Signals:
    tier = r.get("buy_ratio_tier")
    if tier is None or (isinstance(tier, float) and np.isnan(tier)) or str(tier).lower() in ("nan", "none", ""):
        tier = "none"
    return Signals(
        tier=str(tier),
        divergence=divergence_bucket(r.get("anchor_divergence_pct")),
        width=width_bucket(r.get("buy_ratio_low"), r.get("buy_ratio_high"), r.get("buy_ratio_price")),
        closed=closed_bucket(r.get("buy_ratio_closed_n")),
    )


@dataclass
class Verdict:
    level: str
    q50: float
    q80: float
    q90: float
    n: int
    key: tuple[str, ...]
    reason: str


@dataclass
class ConfidenceModel:
    min_group: int = 40
    high_max_q90: float = 0.10
    medium_max_q90: float = 0.15
    table: dict[tuple[str, ...], dict] = field(default_factory=dict)

    # ── Fit ──
    def fit(self, residuals: pd.DataFrame) -> "ConfidenceModel":
        """residuals: one row per past case with `abs_err_pct` and the signal columns."""
        df = residuals.dropna(subset=["abs_err_pct"]).copy()
        sig = df.apply(signals_from_row, axis=1)
        groups: dict[tuple[str, ...], list[float]] = {}
        for s, err in zip(sig, df["abs_err_pct"].astype(float)):
            for key in s.keys():
                groups.setdefault(key, []).append(err)
        self.table = {}
        for key, errs in groups.items():
            if len(errs) >= self.min_group or key == ():
                arr = np.sort(np.asarray(errs))
                self.table[key] = {"n": int(len(arr)), **{f"q{int(q * 100)}": _conformal_quantile(arr, q) for q in QUANTILES}}
        return self

    # ── Predict ──
    def verdict(self, signals: Signals) -> Verdict:
        for key in signals.keys():
            if key in self.table:
                row = self.table[key]
                level = "alta" if row["q90"] <= self.high_max_q90 else "media" if row["q90"] <= self.medium_max_q90 else "baixa"
                desc = _describe(signals, key)
                return Verdict(
                    level=level, q50=row["q50"], q80=row["q80"], q90=row["q90"], n=row["n"], key=key,
                    reason=(
                        f"Em {row['n']} avaliações passadas com este perfil ({desc}), 90 % ficaram "
                        f"dentro de ±{row['q90']:.0%} do custo ideal (metade dentro de ±{row['q50']:.0%})."
                    ),
                )
        return Verdict("baixa", float("nan"), float("nan"), float("nan"), 0, (), "Sem histórico de calibração.")

    # ── Persistence ──
    def to_json(self, path: Path) -> None:
        payload = {
            "min_group": self.min_group, "high_max_q90": self.high_max_q90, "medium_max_q90": self.medium_max_q90,
            "table": [{"key": list(k), **v} for k, v in self.table.items()],
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> "ConfidenceModel":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        m = cls(min_group=payload["min_group"], high_max_q90=payload["high_max_q90"], medium_max_q90=payload["medium_max_q90"])
        m.table = {tuple(row["key"]): {k: v for k, v in row.items() if k != "key"} for row in payload["table"]}
        return m


def _conformal_quantile(sorted_abs_errors: np.ndarray, level: float) -> float:
    """Split-conformal quantile: the ⌈(n+1)·level⌉-th smallest error.

    Slightly above the plain sample quantile, so that a new case falls inside
    the band with probability ≥ level even for modest group sizes.
    """
    n = len(sorted_abs_errors)
    k = int(np.ceil((n + 1) * level))
    return float(sorted_abs_errors[min(k, n) - 1])


_LABELS = {
    "same_year_km6k": "mesmo ano, KM ±6k", "same_year_km12k": "mesmo ano, KM ±12k", "same_year": "mesmo ano, sem KM",
    "year_pm1_km12k": "ano ±1, KM ±12k", "year_pm2_km24k": "ano ±2, KM ±24k", "model_fallback": "modelo, qualquer KM",
    "none": "sem histórico de compra",
}


def _describe(s: Signals, key: tuple[str, ...]) -> str:
    parts = [_LABELS.get(s.tier, s.tier)]
    if len(key) >= 2:
        parts.append(f"âncoras divergindo {s.divergence}" if s.divergence != "none" else "sem segunda âncora")
    if len(key) >= 3:
        parts.append(f"faixa {s.width}")
    if len(key) >= 4:
        parts.append(f"{s.closed} fechadas")
    return ", ".join(parts)
