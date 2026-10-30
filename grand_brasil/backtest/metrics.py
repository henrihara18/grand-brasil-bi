"""Error metrics and breakdowns for backtest predictions."""

from __future__ import annotations

import numpy as np
import pandas as pd

KM_EDGES = [-1, 20_000, 50_000, 100_000, np.inf]
KM_LABELS = ["<=20k", "20-50k", "50-100k", ">100k"]
YEAR_EDGES = [0, 2017, 2022, 9999]
YEAR_LABELS = ["<=2017", "2018-2022", "2023+"]
VOLUME_EDGES = [-1, 4, 19, 49, np.inf]
VOLUME_LABELS = ["0-4", "5-19", "20-49", "50+"]


def add_errors(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["err_pct"] = (out["pred"] - out["custo_ideal"]) / out["custo_ideal"]
    out["abs_err_pct"] = out["err_pct"].abs()
    out["margin_if_paid_pred"] = (out["sale_price"] - out["taxes"].fillna(0.0) - out["pred"]) / out["sale_price"]
    out["km_band"] = pd.cut(out["km"], KM_EDGES, labels=KM_LABELS).astype(str)
    out["year_band"] = pd.cut(out["year_model"].astype(float), YEAR_EDGES, labels=YEAR_LABELS).astype(str)
    out["volume_band"] = pd.cut(out["model_volume_train"], VOLUME_EDGES, labels=VOLUME_LABELS).astype(str)
    return out


def summarize(df: pd.DataFrame) -> dict:
    has = df["pred"].notna() & np.isfinite(df["pred"].astype(float))
    e = df.loc[has, "err_pct"]
    if len(e) == 0:
        return {"n": len(df), "coverage": 0.0}
    return {
        "n": int(len(df)),
        "n_pred": int(has.sum()),
        "coverage": float(has.mean()),
        "mape": float(e.abs().mean()),
        "median_err": float(e.median()),
        "bias": float(e.mean()),
        "p10": float(e.quantile(0.10)),
        "p90": float(e.quantile(0.90)),
        "within_3": float((e.abs() <= 0.03).mean()),
        "within_5": float((e.abs() <= 0.05).mean()),
        "within_10": float((e.abs() <= 0.10).mean()),
        "margin_if_paid_median": float(df.loc[has, "margin_if_paid_pred"].median()),
        "margin_if_paid_neg_share": float((df.loc[has, "margin_if_paid_pred"] < 0).mean()),
    }


def breakdown(df: pd.DataFrame, by: str, min_n: int = 20, top: int | None = None) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(by, dropna=False):
        if len(g) < min_n:
            continue
        s = summarize(g)
        s[by] = key
        rows.append(s)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.set_index(by).sort_values("n", ascending=False)
    return out.head(top) if top else out


def all_breakdowns(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "canal real": breakdown(df, "sale_channel"),
        "status da avaliacao": breakdown(df, "status_norm"),
        "fonte do destaque": breakdown(df, "pred_source"),
        "confianca atual": breakdown(df, "confidence"),
        "modo de preco (portao)": breakdown(df, "price_mode") if "price_mode" in df.columns else breakdown(df, "confidence"),
        "tier do buy-ratio": breakdown(df, "buy_ratio_tier"),
        "marca": breakdown(df, "sale_brand", min_n=30),
        "modelo (top 25)": breakdown(df, "sale_model_red", min_n=25, top=25),
        "faixa de ano": breakdown(df, "year_band"),
        "faixa de km": breakdown(df, "km_band"),
        "faixa de preco de venda": breakdown(df, "price_band"),
        "filial": breakdown(df, "Filial"),
        "volume do modelo no treino": breakdown(df, "volume_band"),
        "mes": breakdown(df.assign(mes=df["appraisal_date"].dt.to_period("M").astype(str)), "mes"),
    }


def fmt_summary(s: dict) -> str:
    if s.get("n_pred", 0) == 0:
        return f"n={s['n']} sem previsao"
    return (
        f"n={s['n']} | cobertura {s['coverage']:.1%} | MAPE {s['mape']:.1%} | mediana {s['median_err']:+.1%} | "
        f"vies {s['bias']:+.1%} | P10 {s['p10']:+.1%} P90 {s['p90']:+.1%} | "
        f"±3% {s['within_3']:.0%} ±5% {s['within_5']:.0%} ±10% {s['within_10']:.0%} | "
        f"margem se pagasse: mediana {s['margin_if_paid_median']:+.1%}, negativa em {s['margin_if_paid_neg_share']:.0%}"
    )


def table_md(t: pd.DataFrame) -> str:
    if t.empty:
        return "_(sem grupos com n suficiente)_"
    cols = ["n", "coverage", "mape", "median_err", "bias", "within_5", "within_10", "margin_if_paid_median"]
    hdr = "| grupo | n | cobert. | MAPE | mediana | viés | ±5% | ±10% | margem se pagasse |\n|---|---|---|---|---|---|---|---|---|"
    lines = [hdr]
    for k, r in t[cols].iterrows():
        lines.append(
            f"| {k} | {int(r['n'])} | {r['coverage']:.0%} | {r['mape']:.1%} | {r['median_err']:+.1%} | "
            f"{r['bias']:+.1%} | {r['within_5']:.0%} | {r['within_10']:.0%} | {r['margin_if_paid_median']:+.1%} |"
        )
    return "\n".join(lines)
