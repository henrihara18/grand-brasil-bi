"""Item 6 — does a gradient-boosting model beat the rule engine?

Walk-forward by month on the long backtest predictions file: for each test
month the model is trained ONLY on cases whose sale happened before that
month (so the target was known), using features available at appraisal time
plus the engine's own outputs (stacking). Target = custo_ideal / FIPE.

Uso:
    py -3.12 scripts/ml_stacking.py --predictions backtest_results/long_final_predictions.csv --test-start 2026-01-01
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NUMERIC = [
    "log_fipe", "year_model", "age", "km", "km_per_year", "model_volume_train", "p_revenda",
    "br_ratio", "br_low_ratio", "br_high_ratio", "br_width", "br_n", "br_closed_n",
    "blend_ratio", "loja_ratio", "revenda_ratio", "loja_spread", "revenda_spread",
    "loja_spread_n", "revenda_spread_n", "loja_margin_target", "revenda_margin_target",
    "anchor_divergence_pct", "repair_ratio", "blindado", "is_repasse", "total_comparables",
]
CATEGORICAL = ["sale_brand", "buy_ratio_tier"]


def features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    fipe = df["fipe_value"].astype(float)
    f["log_fipe"] = np.log(fipe)
    f["year_model"] = df["year_model"].astype(float)
    f["age"] = df["appraisal_date"].dt.year - df["year_model"].astype(float)
    f["km"] = df["km"].astype(float)
    f["km_per_year"] = f["km"] / f["age"].clip(lower=1)
    f["model_volume_train"] = df["model_volume_train"].astype(float)
    f["p_revenda"] = df["p_revenda"].astype(float)
    f["br_ratio"] = df["buy_ratio_price"] / fipe
    f["br_low_ratio"] = df["buy_ratio_low"] / fipe
    f["br_high_ratio"] = df["buy_ratio_high"] / fipe
    f["br_width"] = (df["buy_ratio_high"] - df["buy_ratio_low"]) / df["buy_ratio_price"]
    f["br_n"] = df["buy_ratio_n"].astype(float)
    f["br_closed_n"] = df["buy_ratio_closed_n"].astype(float)
    f["blend_ratio"] = df["blended"] / fipe
    f["loja_ratio"] = df["loja_trade"] / fipe
    f["revenda_ratio"] = df["revenda_trade"] / fipe
    f["loja_spread"] = df["loja_spread"].astype(float)
    f["revenda_spread"] = df["revenda_spread"].astype(float)
    f["loja_spread_n"] = df["loja_spread_n"].astype(float)
    f["revenda_spread_n"] = df["revenda_spread_n"].astype(float)
    f["loja_margin_target"] = df["loja_margin_target"].astype(float)
    f["revenda_margin_target"] = df["revenda_margin_target"].astype(float)
    f["anchor_divergence_pct"] = df["anchor_divergence_pct"].astype(float)
    f["repair_ratio"] = df["expected_repair_cost"].fillna(0).astype(float) / fipe
    f["blindado"] = df["blindado_flag"].fillna(False).astype(bool).astype(float)
    f["is_repasse"] = (df["status_norm"] == "REPASSE").astype(float)
    f["total_comparables"] = df["total_comparables"].astype(float)
    for c in CATEGORICAL:
        f[c] = df[c].astype("category")
    return f


def metrics(err: pd.Series) -> str:
    e = err.dropna()
    return f"MAPE {e.abs().mean():.1%} | mediana {e.median():+.1%} | viés {e.mean():+.1%} | ±5% {(e.abs() <= .05).mean():.0%} | ±10% {(e.abs() <= .10).mean():.0%}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--test-start", default="2026-01-01")
    ap.add_argument("--min-train", type=int, default=300)
    args = ap.parse_args()

    df = pd.read_csv(ROOT / args.predictions, sep=";", parse_dates=["appraisal_date", "sale_date"])
    df = df[df["pred"].notna() & df["fipe_value"].gt(0)].copy()
    X_all = features(df)
    y_all = df["custo_ideal"] / df["fipe_value"]
    test_start = pd.Timestamp(args.test_start)
    test = df[df["appraisal_date"] >= test_start]
    print(f"casos: {len(df)} total, {len(test)} teste")

    # Linear (explainable) variant: engine ratio + a handful of corrections
    LINEAR_COLS = ["engine_ratio", "p_revenda", "km_per_year", "age", "is_repasse", "br_width", "anchor_divergence_pct"]
    X_lin_all = X_all[[c for c in LINEAR_COLS if c != "engine_ratio"]].copy()
    X_lin_all.insert(0, "engine_ratio", df["pred"] / df["fipe_value"])
    X_lin_all = X_lin_all.fillna(0.0)

    preds = pd.Series(np.nan, index=df.index)
    preds_lin = pd.Series(np.nan, index=df.index)
    last_model = None
    last_lin = None
    for month, cases in test.groupby(test["appraisal_date"].dt.to_period("M")):
        cutoff = month.start_time
        train_idx = df.index[df["sale_date"] < cutoff]
        if len(train_idx) < args.min_train:
            continue
        model = HistGradientBoostingRegressor(
            loss="absolute_error", max_iter=400, learning_rate=0.04, max_depth=4,
            min_samples_leaf=30, l2_regularization=1.0, categorical_features="from_dtype", random_state=0,
        )
        model.fit(X_all.loc[train_idx], y_all.loc[train_idx])
        preds.loc[cases.index] = model.predict(X_all.loc[cases.index])
        last_model = (model, train_idx)

        from sklearn.linear_model import HuberRegressor
        lin = HuberRegressor(alpha=1e-3, max_iter=500)
        lin.fit(X_lin_all.loc[train_idx], y_all.loc[train_idx])
        preds_lin.loc[cases.index] = lin.predict(X_lin_all.loc[cases.index])
        last_lin = lin
        print(f"  {month}: treino {len(train_idx)} | teste {len(cases)}")

    t = df.loc[test.index].copy()
    t["ml_pred"] = preds.loc[test.index] * t["fipe_value"]
    t["lin_pred"] = preds_lin.loc[test.index] * t["fipe_value"]
    ok = t["ml_pred"].notna()
    t = t[ok]
    e_engine = (t["pred"] - t["custo_ideal"]) / t["custo_ideal"]
    e_ml = (t["ml_pred"] - t["custo_ideal"]) / t["custo_ideal"]
    e_lin = (t["lin_pred"] - t["custo_ideal"]) / t["custo_ideal"]
    e_mix = ((t["pred"] + t["ml_pred"]) / 2 - t["custo_ideal"]) / t["custo_ideal"]
    print(f"\n== mesmo conjunto de teste: n={len(t)} ==")
    print("motor (regras)      :", metrics(e_engine))
    print("gradient boosting   :", metrics(e_ml))
    print("linear (Huber)      :", metrics(e_lin))
    print("média motor + GBM   :", metrics(e_mix))
    for ch in ("Loja", "Revenda"):
        m = t["sale_channel"] == ch
        print(f"  {ch:8s} motor  {metrics(e_engine[m])}\n  {ch:8s} GBM    {metrics(e_ml[m])}\n  {ch:8s} linear {metrics(e_lin[m])}")
    if last_lin is not None:
        print("\n== coeficientes do linear (último mês) ==")
        for name, coef in zip(X_lin_all.columns, last_lin.coef_):
            print(f"  {name:22s} {coef:+.4f}")
        print(f"  {'intercept':22s} {last_lin.intercept_:+.4f}")

    if last_model is not None:
        model, train_idx = last_model
        hold = t.index
        imp = permutation_importance(model, X_all.loc[hold], y_all.loc[hold], n_repeats=5, random_state=0,
                                     scoring="neg_mean_absolute_error")
        order = np.argsort(-imp.importances_mean)[:12]
        print("\n== importância por permutação (modelo do último mês, no teste) ==")
        for i in order:
            print(f"  {X_all.columns[i]:22s} {imp.importances_mean[i]:.4f}")


if __name__ == "__main__":
    main()
