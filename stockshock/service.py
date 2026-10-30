"""The STOCKSHOCK service: everything the website's API returns, as plain Python functions.

    catalog()                 -> destinations, season types
    plan(dest, ...)           -> forecast + buy plan + KPIs for the next N weeks, plus last-year replay
    frontier(dest, ...)       -> best profit at each risk level (the "investment portfolio" curve)
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from . import catalog as cat
from .data import FEST_BY_WEEK, history
from .forecast import fit_predict, sample_scenarios
from .optimize import BLOCK, evaluate, live_availability, solve

N_SCEN = 60
RISK_LEVELS = {"careful": -0.35, "balanced": 0.0, "bold": None}   # cap = today's worst-5% loss shifted by this share


def next_monday(d: date | None = None) -> pd.Timestamp:
    d = d or date.today()
    return pd.Timestamp(d + timedelta(days=(7 - d.weekday()) % 7 or 7))


def catalog() -> dict:
    return {"destinations": cat.all_destinations(),
            "types": [{"id": k, "label": v["label"], "season": v["m"]} for k, v in cat.SEASONS.items()],
            "default_start": next_monday().strftime("%Y-%m-%d")}


@lru_cache(maxsize=64)
def _history_cached(did: str, dest_key: tuple, until: str) -> pd.DataFrame:
    dest = dict(dest_key)
    return history(dest, cat.products_for(dest), cat.seed_for(did), pd.Timestamp(until))


def _history(dest: dict, until: pd.Timestamp) -> pd.DataFrame:
    key = tuple(sorted((k, v) for k, v in dest.items() if not isinstance(v, (list, dict))))
    return _history_cached(dest["id"], key, until.strftime("%Y-%m-%d")).copy()


def _round(x):
    return np.round(np.asarray(x, float) / BLOCK) * BLOCK


def _window(df: pd.DataFrame, start: pd.Timestamp, weeks: int, seed: int):
    """Forecast `weeks` weeks from `start` using only data before it, and build the decision table."""
    end = start + pd.Timedelta(weeks=weeks)
    test = fit_predict(df[df["week"] < end], start.strftime("%Y-%m-%d"))
    items = test.sort_values(["product_id", "week"]).reset_index(drop=True)
    last_year = df[(df["week"] < start) & (df["week"] >= start - pd.Timedelta(weeks=52))]
    typical = last_year.groupby("product")["demand"].mean()
    month_avg = last_year.groupby(["product", last_year["week"].dt.month])["demand"].mean()
    items["typical"] = items["product"].map(typical).to_numpy()
    items["q_today"] = _round([month_avg.get((p, m), typical[p]) for p, m in zip(items["product"], items["week"].dt.month)])
    items["avail"] = live_availability(items["p50"].to_numpy(), items["typical"].to_numpy())
    items["max_units"] = np.ceil(items["p90"] * 1.6 + 10)
    d_map = df.set_index(["product", "week"])["demand"].to_dict()
    s_map = df.set_index(["product", "week"])["searches_6w_ahead"].to_dict()
    yr = pd.Timedelta(weeks=52)
    items["last_year"] = [int(d_map[(p, w - yr)]) if (p, w - yr) in d_map else None for p, w in zip(items["product"], items["week"])]
    items["searches_ly"] = [float(s_map.get((p, w - yr), 0)) for p, w in zip(items["product"], items["week"])]
    rng = np.random.default_rng(seed)
    scen = np.vstack([sample_scenarios(r, N_SCEN, rng) for _, r in items.iterrows()])
    return items, scen


def _optimise(items, scen, budget_pct: float, risk: str):
    today = evaluate(items, items["q_today"].to_numpy(), scen)
    budget = today["spend"] * budget_pct / 100
    shift = RISK_LEVELS.get(risk, 0.0)
    cap = None if shift is None else today["cvar95_loss"] + shift * abs(today["cvar95_loss"])
    served = today["served_units"] if budget_pct >= 100 else None
    for c, s in ((cap, served), (cap, None), (None, served), (None, None)):
        res = solve(items, scen, budget=budget, risk_cap=c, min_served=s, time_limit=5, relax=True)
        if "exp_profit" in res:
            return res, today, budget
    return res, today, budget


def _drivers(r) -> list[str]:
    out = []
    if r["festival"]:
        out.append(r["festival"])
    sf = r["season_factor"]
    if sf >= 1.3:
        out.append("peak season")
    elif sf <= 0.7:
        out.append("low season")
    if r["searches_ly"] > 0:
        ch = (r["searches_6w_ahead"] / r["searches_ly"] - 1) * 100
        if abs(ch) >= 12:
            out.append(f"searches {ch:+.0f}% vs last year")
    if r["avail"] <= 0.45:
        out.append("suppliers likely to sell out")
    spread = (r["p90"] - r["p10"]) / max(r["p50"], 1)
    if spread >= 1.2:
        out.append("wide uncertainty")
    return out[:3]


def _decide(r) -> tuple[str, str]:
    q, p50, today = r["q"], r["p50"], r["q_today"]
    unit = {"hotel": "nights", "flight": "seats", "transfer": "seats", "activity": "passes"}[r["kind"]]
    if q <= 0:
        return "SKIP", f"Buy live instead: margin doesn't cover the risk of {p50:.0f} {unit} going unsold."
    if q < 0.6 * p50:
        return "WAIT", f"Lock {q:.0f} {unit} now and buy the rest live once demand firms up."
    diff = q - today
    tail = f"{abs(diff):.0f} more than today's rule" if diff > 0 else (f"{abs(diff):.0f} fewer than today's rule" if diff < 0 else "same as today's rule")
    return "BUY", f"Pre-buy {q:.0f} {unit} ({tail}); likely demand {p50:.0f}."


def _kpis(e: dict) -> dict:
    return {"expected_profit": round(e["exp_profit"]), "worst5_loss": round(e["cvar95_loss"]),
            "spend": round(e["spend"]), "unsold_units": round(float(e["unsold_units"]), 1),
            "served_pct": round(100 * float(e["served_units"]) / max(float(e["demand_units"]), 1), 1),
            "lost_units": round(float(e["lost_units"]), 1)}


def resolve(dest_id: str | None, custom: dict | None) -> dict:
    if custom:
        return cat.custom_destination(**custom)
    d = cat.find(dest_id or "goa")
    if not d:
        raise ValueError(f"unknown destination '{dest_id}'")
    return d


def plan(dest: dict, start: str | None = None, weeks: int = 8, budget_pct: float = 100,
         risk: str = "balanced", replay: bool = True) -> dict:
    t0 = time.time()
    weeks = int(min(max(weeks, 2), 12))
    budget_pct = float(min(max(budget_pct, 40), 160))
    start_ts = pd.Timestamp(start) if start else next_monday()
    start_ts = start_ts - pd.Timedelta(days=start_ts.weekday())
    end = start_ts + pd.Timedelta(weeks=weeks)
    df = _history(dest, end)
    seed = cat.seed_for(dest["id"]) % 10_000 + start_ts.dayofyear
    items, scen = _window(df, start_ts, weeks, seed)
    res, today, budget = _optimise(items, scen, budget_pct, risk)
    items["q"] = res["q"]
    acts = [(_decide(r), _drivers(r)) for _, r in items.iterrows()]
    items["action"] = [a[0][0] for a in acts]
    items["reason"] = [a[0][1] for a in acts]
    items["drivers"] = [a[1] for a in acts]

    products = []
    for name, g in items.groupby("product", sort=False):
        products.append({
            "name": name, "kind": g["kind"].iloc[0], "unit_cost": int(g["unit_cost"].iloc[0]),
            "sell_price": int(g["sell_price"].iloc[0]),
            "weeks": [{"week": w.strftime("%Y-%m-%d"), "p10": round(a), "p50": round(b), "p90": round(c),
                       "last_year": ly, "q": int(q), "q_today": int(qt), "action": act, "reason": rs, "drivers": dr,
                       "festival": fe}
                      for w, a, b, c, ly, q, qt, act, rs, dr, fe in zip(g["week"], g["p10"], g["p50"], g["p90"], g["last_year"],
                                                                         g["q"], g["q_today"], g["action"], g["reason"],
                                                                         g["drivers"], g["festival"])]})
    out = {"destination": dest, "start": start_ts.strftime("%Y-%m-%d"), "weeks": weeks,
           "budget_pct": budget_pct, "risk": risk, "budget": round(budget),
           "kpis": {"stockshock": _kpis(res), "today": _kpis(today)},
           "products": products, "scenarios": N_SCEN}
    if replay:
        out["replay"] = _replay(df, dest, start_ts, weeks, budget_pct, risk)
    out["seconds"] = round(time.time() - t0, 2)
    return out


def _replay(df, dest, start_ts, weeks, budget_pct, risk) -> dict:
    """Same window one year earlier, planned with data available then, scored on what really happened."""
    s0 = start_ts - pd.Timedelta(weeks=52)
    items, scen = _window(df, s0, weeks, cat.seed_for(dest["id"]) % 997)
    res, _, _ = _optimise(items, scen, budget_pct, risk)
    actual = items["demand"].to_numpy(float)[:, None]
    ss = evaluate(items, res["q"], actual)
    td = evaluate(items, items["q_today"].to_numpy(), actual)
    return {"start": s0.strftime("%Y-%m-%d"), "stockshock": _kpis(ss), "today": _kpis(td),
            "profit_gain": round(ss["exp_profit"] - td["exp_profit"]),
            "unsold_cut_units": round(float(td["unsold_units"] - ss["unsold_units"]), 1)}


def frontier(dest: dict, start: str | None = None, weeks: int = 8, budget_pct: float = 100) -> dict:
    start_ts = pd.Timestamp(start) if start else next_monday()
    start_ts = start_ts - pd.Timedelta(days=start_ts.weekday())
    df = _history(dest, start_ts + pd.Timedelta(weeks=weeks))
    items, scen = _window(df, start_ts, int(weeks), cat.seed_for(dest["id"]) % 10_000 + start_ts.dayofyear)
    today = evaluate(items, items["q_today"].to_numpy(), scen)
    budget = today["spend"] * float(budget_pct) / 100
    served = today["served_units"] if float(budget_pct) >= 100 else None   # same service target as the plan
    pts = []
    for w in (0.0, 0.15, 0.4, 0.8, 1.5, 3.0, 8.0):
        r = solve(items, scen, budget=budget, risk_cap=None, risk_weight=w, relax=True, time_limit=6, min_served=served)
        if "exp_profit" not in r:
            r = solve(items, scen, budget=budget, risk_cap=None, risk_weight=w, relax=True, time_limit=6)
        if "exp_profit" in r:
            pts.append({"worst5_loss": round(r["cvar95_loss"]), "expected_profit": round(r["exp_profit"]), "risk_weight": w})
    pts.sort(key=lambda p: p["worst5_loss"])
    pareto, best = [], -1e18
    for p in pts:
        if p["expected_profit"] > best:
            pareto.append(p); best = p["expected_profit"]
    return {"points": pareto, "today": {"worst5_loss": round(today["cvar95_loss"]), "expected_profit": round(today["exp_profit"])}}
