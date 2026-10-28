"""Calibrate the channel_probability lookup tables from real sales data.

Computes, for each cell (tier × age_bucket × km_bucket), the empirical
P(Revenda) = Revenda / (Loja + Revenda), using the same bucket edges as
`grand_brasil/utils/channel_probability.py`.

Outputs:
    - A per-cell table with counts (to spot low-n cells)
    - A suggested Python dict literal ready to paste in place of the hand-
      calibrated constants in channel_probability.py
    - A comparison against the current hand-calibrated values (max delta,
      mean delta per tier)

Cells with n < MIN_CELL_SAMPLE (default 10) fall back to the current hand-
calibrated value - avoids replacing a reasonable prior with a noisy 2/3
observation.

Run:
    py -3.12 -m tests.backtests.calibrate_channel_probability
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from grand_brasil.ingestion.sales_history import load_sales_history
from grand_brasil.utils.brand_tier import BrandTierConfig
from grand_brasil.utils.channel_probability import (
    AGE_BUCKETS,
    KM_BUCKETS,
    _NEUTRAL_TABLE,
    _RISKY_TABLE,
    _SAFE_TABLE,
    _age_bucket,
    _km_bucket,
)


MIN_CELL_SAMPLE = 10  # fewer than this -> keep hand-calibrated value


def _load_sales() -> pd.DataFrame:
    for fname in (
        "Relatorio vendas 20255 processado.xlsx",
        "Relatorio vendas 2025 processado.xlsx",
    ):
        p = Path(fname)
        if p.exists():
            return load_sales_history(p)
    raise FileNotFoundError("Sales file not found")


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add tier, age, age_bucket, km_bucket, channel."""
    cfg = BrandTierConfig()
    safe = {b.upper() for b in cfg.safe_brands}
    risky = {b.upper() for b in cfg.risky_brands}

    def tier(b: str) -> str:
        bu = str(b).upper().strip()
        if bu in safe:
            return "SAFE"
        if bu in risky:
            return "RISKY"
        return "NEUTRAL"

    df = df.copy()
    df["sale_year"] = pd.to_datetime(df["sale_date"], errors="coerce").dt.year
    df["sale_year"] = df["sale_year"].fillna(2025).astype(int)
    df["age"] = (df["sale_year"] - df["year_model"].astype(int)).clip(lower=0, upper=30)
    df["brand_tier"] = df["brand"].map(tier)

    def chan(raw: str) -> str:
        s = str(raw).upper()
        if "REVENDA" in s or "ATACADO" in s or "REPASSE" in s:
            return "Revenda"
        if "LOJA" in s or "VAREJO" in s:
            return "Loja"
        return "Other"

    df["channel"] = df["sale_channel"].apply(chan)
    df["km"] = pd.to_numeric(df["km"], errors="coerce")
    df["age_bucket_calc"] = df["age"].apply(_age_bucket)
    df["km_bucket_calc"] = df["km"].apply(
        lambda k: _km_bucket(None if pd.isna(k) else int(k))
    )
    return df


def _compute_empirical_table(
    df: pd.DataFrame, tier: str
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, int]]]:
    """Return (empirical_p_revenda, counts) nested dicts for one tier."""
    sub = df[(df["brand_tier"] == tier) & (df["channel"].isin(["Loja", "Revenda"]))]
    p_table: dict[str, dict[str, float]] = {}
    n_table: dict[str, dict[str, int]] = {}

    for _, age_label in AGE_BUCKETS:
        p_table[age_label] = {}
        n_table[age_label] = {}
        for _, km_label in KM_BUCKETS:
            cell = sub[
                (sub["age_bucket_calc"] == age_label)
                & (sub["km_bucket_calc"] == km_label)
            ]
            n = len(cell)
            if n == 0:
                p_table[age_label][km_label] = np.nan
                n_table[age_label][km_label] = 0
                continue
            rev = (cell["channel"] == "Revenda").sum()
            p_table[age_label][km_label] = round(rev / n, 3)
            n_table[age_label][km_label] = n

    return p_table, n_table


def _print_table(title: str, table: dict[str, dict[str, float]], counts: dict[str, dict[str, int]]) -> None:
    print(f"\n### {title}")
    age_labels = [lbl for _, lbl in AGE_BUCKETS]
    km_labels = [lbl for _, lbl in KM_BUCKETS]
    header = f"  {'age':<6}" + "".join(f"{k:>11}" for k in km_labels)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for a in age_labels:
        cells: list[str] = []
        for k in km_labels:
            p = table[a][k]
            n = counts[a][k]
            if np.isnan(p):
                cells.append(f"{'-':>11}")
            else:
                mark = " " if n >= MIN_CELL_SAMPLE else "*"
                cells.append(f"{p:>6.2f} (n{n:>2}){mark}")
        print(f"  {a:<6}" + "".join(cells))


def _blend(
    empirical: dict[str, dict[str, float]],
    counts: dict[str, dict[str, int]],
    prior: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Keep prior when n < MIN_CELL_SAMPLE, else take empirical."""
    age_labels = [lbl for _, lbl in AGE_BUCKETS]
    km_labels = [lbl for _, lbl in KM_BUCKETS]
    out: dict[str, dict[str, float]] = {}
    for a in age_labels:
        out[a] = {}
        for k in km_labels:
            p = empirical[a][k]
            n = counts[a][k]
            if np.isnan(p) or n < MIN_CELL_SAMPLE:
                out[a][k] = prior[a][k]
            else:
                out[a][k] = round(p, 2)
    return out


def _enforce_monotonicity(
    table: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Force P(Revenda) to be non-decreasing across km (fixed age) and
    non-decreasing across age (fixed km) via iterative running-max.

    Empirical noise in low-n cells can produce small monotonicity violations
    (e.g. 0.53 at 60-90k then 0.40 at 90-120k because the latter only had
    n=4). Enforcing non-decreasing on both axes respects the domain prior
    ("more km/age -> more Revenda") while staying close to the empirical
    signal (we only bump the LOW cells, never reduce HIGH ones).
    """
    age_labels = [lbl for _, lbl in AGE_BUCKETS]
    km_labels = [lbl for _, lbl in KM_BUCKETS]
    out = {a: dict(table[a]) for a in age_labels}

    for _ in range(5):  # convergence is usually immediate
        changed = False
        # along km (each row), left-to-right running max
        for a in age_labels:
            running = 0.0
            for k in km_labels:
                if out[a][k] < running:
                    out[a][k] = running
                    changed = True
                else:
                    running = out[a][k]
        # along age (each col), top-to-bottom running max
        for k in km_labels:
            running = 0.0
            for a in age_labels:
                if out[a][k] < running:
                    out[a][k] = running
                    changed = True
                else:
                    running = out[a][k]
        if not changed:
            break

    return {a: {k: round(out[a][k], 2) for k in km_labels} for a in age_labels}


def _dump_python_dict(
    var_name: str,
    table: dict[str, dict[str, float]],
    prior: dict[str, dict[str, float]],
    counts: dict[str, dict[str, int]],
) -> str:
    """Pretty-print a Python literal, with a trailing comment per row
    flagging which cells were calibrated vs kept-as-prior."""
    age_labels = [lbl for _, lbl in AGE_BUCKETS]
    km_labels = [lbl for _, lbl in KM_BUCKETS]

    lines = [f"{var_name}: dict[str, dict[str, float]] = {{"]
    km_header_fmt = "    # age   " + " ".join(f"{k:>10}" for k in km_labels)
    lines.append(km_header_fmt)
    for a in age_labels:
        pairs = ", ".join(f'"{k}": {table[a][k]:.2f}' for k in km_labels)
        calibrated = sum(
            1 for k in km_labels
            if counts[a][k] >= MIN_CELL_SAMPLE and not np.isnan(counts[a][k])
        )
        total = len(km_labels)
        tag = f"  # {calibrated}/{total} celulas calibradas"
        lines.append(f'    "{a}":   {{{pairs}}},{tag}')
    lines.append("}")
    return "\n".join(lines)


def _deltas_vs_prior(
    empirical: dict[str, dict[str, float]],
    counts: dict[str, dict[str, int]],
    prior: dict[str, dict[str, float]],
) -> tuple[float, float, int]:
    """Mean |delta|, max |delta|, and count of significantly-calibrated cells
    (n ≥ MIN_CELL_SAMPLE)."""
    diffs: list[float] = []
    age_labels = [lbl for _, lbl in AGE_BUCKETS]
    km_labels = [lbl for _, lbl in KM_BUCKETS]
    for a in age_labels:
        for k in km_labels:
            n = counts[a][k]
            p = empirical[a][k]
            if n >= MIN_CELL_SAMPLE and not np.isnan(p):
                diffs.append(abs(p - prior[a][k]))
    if not diffs:
        return 0.0, 0.0, 0
    return float(np.mean(diffs)), float(np.max(diffs)), len(diffs)


def main() -> None:
    print("=" * 90)
    print("  CALIBRAÇÃO EMPÍRICA - channel_probability lookup tables")
    print("=" * 90)

    sales = _load_sales()
    df = _enrich(sales)
    n_total = len(df[df["channel"].isin(["Loja", "Revenda"])])
    print(f"\nTotal Loja+Revenda: {n_total:,}")
    print(f"Por tier: {df[df['channel'].isin(['Loja', 'Revenda'])]['brand_tier'].value_counts().to_dict()}")
    print(f"\nObs: '*' após uma celula indica n < {MIN_CELL_SAMPLE} (mantem valor hand-calibrado).")

    priors = {"SAFE": _SAFE_TABLE, "NEUTRAL": _NEUTRAL_TABLE, "RISKY": _RISKY_TABLE}

    blended: dict[str, dict[str, dict[str, float]]] = {}

    for tier in ("SAFE", "NEUTRAL", "RISKY"):
        emp, cnt = _compute_empirical_table(df, tier)
        _print_table(f"TIER = {tier} (empirical)", emp, cnt)

        mean_d, max_d, n_cells = _deltas_vs_prior(emp, cnt, priors[tier])
        print(
            f"  -> celulas calibradas (n ≥ {MIN_CELL_SAMPLE}): {n_cells} | "
            f"|delta| medio vs prior: {mean_d:.3f} | máx: {max_d:.3f}"
        )
        blended[tier] = _enforce_monotonicity(_blend(emp, cnt, priors[tier]))

    # ── Dump python literals (ready to paste) ───────────────────────────
    print("\n" + "=" * 90)
    print("  TABELAS CALIBRADAS (copie para grand_brasil/utils/channel_probability.py)")
    print("=" * 90)

    for tier, var in (
        ("SAFE", "_SAFE_TABLE"),
        ("NEUTRAL", "_NEUTRAL_TABLE"),
        ("RISKY", "_RISKY_TABLE"),
    ):
        emp, cnt = _compute_empirical_table(df, tier)
        print("\n" + _dump_python_dict(var, blended[tier], priors[tier], cnt))


if __name__ == "__main__":
    main()
