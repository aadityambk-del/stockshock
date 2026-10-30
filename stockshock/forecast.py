"""Demand ranges (low / likely / high) with quantile gradient boosting."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

QUANTILES = {"p10": 0.10, "p50": 0.50, "p90": 0.90}


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["product_id", "week"]).copy()
    woy = df["week"].dt.isocalendar().week.astype(int)
    df["woy_sin"] = np.sin(2 * np.pi * woy / 52)
    df["woy_cos"] = np.cos(2 * np.pi * woy / 52)
    df["month"] = df["week"].dt.month
    df["t"] = (df["week"] - df["week"].min()).dt.days / 365
    df["log_searches"] = np.log1p(df["searches_6w_ahead"])
    g = df.groupby("product_id")["demand"]
    df["lag52"] = g.shift(52)
    df["lag52_avg4"] = g.transform(lambda s: s.shift(52).rolling(5, center=True, min_periods=1).mean())
    return df


FEATURES = ["product_id", "woy_sin", "woy_cos", "month", "t", "festival_week",
            "log_searches", "lag52", "lag52_avg4"]


def _models(train: pd.DataFrame) -> dict:
    out = {}
    for name, q in QUANTILES.items():
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=120,
                                          learning_rate=0.1, max_leaf_nodes=12, min_samples_leaf=15,
                                          l2_regularization=1.0, categorical_features=[0], random_state=0)
        out[name] = m.fit(train[FEATURES], np.log1p(train["demand"]))
    return out


def _predict(models: dict, X: pd.DataFrame) -> dict:
    return {k: np.expm1(m.predict(X[FEATURES])) for k, m in models.items()}


def fit_predict(df: pd.DataFrame, cutoff: str, calib_weeks: int = 20) -> pd.DataFrame:
    """Train on weeks before `cutoff`, return P10/P50/P90 for weeks on/after it.

    The P10-P90 band is calibrated (conformal style) on the last `calib_weeks` before the
    cutoff, so that about 80% of real weeks land inside it."""
    df = add_features(df)
    # trees cannot extrapolate growth, so remove the yearly trend before fitting and add it back after
    pre = df[df["week"] < cutoff]
    yearly = pre.groupby(pre["week"].dt.year)["demand"].sum()
    full_years = yearly[pre.groupby(pre["week"].dt.year)["week"].nunique() >= 50]
    g = float((full_years.iloc[-1] / full_years.iloc[0]) ** (1 / max(len(full_years) - 1, 1))) if len(full_years) > 1 else 1.0
    trend = g ** df["t"].to_numpy()
    df["demand_raw"] = df["demand"]
    df["demand"] = df["demand"] / trend
    for c in ("lag52", "lag52_avg4"):
        df[c] = df[c] * g / trend  # last year's value, grown one year, then de-trended
    df["_trend"] = trend
    train, test = df[df["week"] < cutoff], df[df["week"] >= cutoff].copy()
    cal_start = train["week"].max() - pd.Timedelta(weeks=calib_weeks - 1)
    fit, cal = train[train["week"] < cal_start], train[train["week"] >= cal_start]
    pc = _predict(_models(fit), cal)
    y = np.log1p(cal["demand"].to_numpy())
    lo, hi = np.log1p(pc["p10"]), np.log1p(pc["p90"])
    widen = float(np.quantile(np.maximum(lo - y, y - hi), 0.8))
    # level correction: the model predicts medians, buying needs the right average
    level = float(cal["demand"].sum() / max(pc["p50"].sum(), 1))
    pt = {k: v * level for k, v in _predict(_models(train), test).items()}
    test["p50"] = np.clip(pt["p50"], 0, None)
    test["p10"] = np.clip(np.expm1(np.log1p(pt["p10"]) - widen), 0, None)
    test["p90"] = np.expm1(np.log1p(pt["p90"]) + widen)
    # keep the three quantiles in order, and put the trend back
    q = np.sort(test[["p10", "p50", "p90"]].to_numpy(), axis=1) * test["_trend"].to_numpy()[:, None]
    test[["p10", "p50", "p90"]] = q
    test["demand"] = test["demand_raw"]
    test["lag52"] = test["lag52"] * test["_trend"] / g
    # seasonal-naive baseline: same week last year, grown by the average yearly trend
    test["naive"] = (test["lag52"] * g).fillna(test["p50"])
    return test.drop(columns=["demand_raw", "_trend"])


def sample_scenarios(row: pd.Series, n: int, rng: np.random.Generator) -> np.ndarray:
    """Draw demand scenarios that match the forecast's P10, P50 and P90."""
    u = rng.random(n)
    p10, p50, p90 = row["p10"], row["p50"], max(row["p90"], row["p50"] + 1)
    lo_tail = max(p50 - p10, 1) / 1.2816
    hi_tail = max(p90 - p50, 1) / 1.2816
    z = np.sqrt(2) * _erfinv(2 * u - 1)
    d = np.where(z < 0, p50 + z * lo_tail, p50 + z * hi_tail)
    return np.clip(np.round(d), 0, None)


def _erfinv(x: np.ndarray) -> np.ndarray:
    from scipy.special import erfinv
    return erfinv(np.clip(x, -0.999999, 0.999999))


def accuracy(test: pd.DataFrame) -> dict:
    def wape(pred):
        return float(np.abs(test["demand"] - pred).sum() / test["demand"].sum())
    inside = ((test["demand"] >= test["p10"]) & (test["demand"] <= test["p90"])).mean()
    return {"wape_stockshock": wape(test["p50"]), "wape_last_year": wape(test["naive"]),
            "p10_p90_coverage": float(inside)}
