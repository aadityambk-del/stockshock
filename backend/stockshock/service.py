"""The STOCKSHOCK service: everything the website's API returns, as plain Python functions.

    catalog()                 -> featured destinations, season types, Indian hubs
    plan(dest, ...)           -> forecast + recommended prices + buy plan + KPIs + stress test for one destination
    portfolio(dests, ...)     -> one rupee budget split across several destinations, products and weeks
    radar(dests, ...)         -> ranked opportunities: where, what and when to pre-buy, with the signals behind them
    frontier(dest, ...)       -> best profit at each risk level (the "investment portfolio" curve)
    replay_check(dest, ...)   -> the same weeks one year earlier, scored on what actually sold
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from . import catalog as cat
from .data import FEST_BY_WEEK, history, price_index
from .forecast import fit_predict, sample_scenarios
from .optimize import BLOCK, evaluate, live_availability, solve

N_SCEN = 60
# Risk appetite changes the goal, not just a cap:
#   careful  = protect the downside: worst-5% loss capped 35% below today's, and every rupee of CVaR is penalised
#   balanced = no worse a worst case than today, with a mild penalty on downside risk
#   bold     = chase expected profit: no cap, no penalty
RISK = {"careful": {"cap": -0.35, "w": 1.2}, "balanced": {"cap": 0.0, "w": 0.25}, "bold": {"cap": None, "w": 0.0}}
RISK_LEVELS = {k: v["cap"] for k, v in RISK.items()}
# price elasticity of demand by product (how much demand falls when the price rises 1%); peaks are less elastic
# (B2B travel is a crowded marketplace: agents compare suppliers, so demand reacts strongly to price)
ELASTICITY = {"hotel": 5.0, "flight": 4.5, "activity": 5.5, "transfer": 5.0}
PRICE_GRID = np.array([0.92, 0.95, 0.98, 1.0, 1.03, 1.06, 1.1, 1.15])
STRESS = [-0.3, -0.15, 0.0, 0.15, 0.3]


def next_monday(d: date | None = None) -> pd.Timestamp:
    d = d or date.today()
    return pd.Timestamp(d + timedelta(days=(7 - d.weekday()) % 7 or 7))


def catalog() -> dict:
    from .world import HUBS
    return {"destinations": cat.all_destinations(),
            "hubs": [{"code": k, "city": v[0]} for k, v in HUBS.items()],
            "types": [{"id": k, "label": v["label"], "season": v["m"]} for k, v in cat.SEASONS.items()],
            "default_start": next_monday().strftime("%Y-%m-%d")}


@lru_cache(maxsize=96)
def _history_cached(did: str, dest_key: tuple, until: str) -> pd.DataFrame:
    dest = dict(dest_key)
    return history(dest, cat.products_for(dest), cat.seed_for(did), pd.Timestamp(until))


def _key(dest: dict) -> tuple:
    return tuple(sorted((k, v) for k, v in dest.items() if not isinstance(v, (list, dict))))


def _history(dest: dict, until: pd.Timestamp) -> pd.DataFrame:
    return _history_cached(dest["id"], _key(dest), until.strftime("%Y-%m-%d")).copy()


def _round(x):
    return np.round(np.asarray(x, float) / BLOCK) * BLOCK


def _pricing(items: pd.DataFrame) -> pd.DataFrame:
    """Recommended selling price per product-week: the markup that maximises margin x demand,
    with demand reacting to price (elasticity) and peak weeks reacting less."""
    seg = items["segment"].to_numpy()
    e = np.array([ELASTICITY.get(k, 1.6) for k in items["kind"]]) * np.where(seg == "business", 0.6, 1.0)
    hot = (items["p50"] / np.maximum(items["typical"], 1)).to_numpy()
    e = e * np.where(hot > 1.25, 0.6, np.where(hot < 0.8, 1.3, 1.0))
    list_p, cost = items["sell_list"].to_numpy(float), items["unit_cost"].to_numpy(float)
    m = PRICE_GRID[None, :]
    value = (m * list_p[:, None] - cost[:, None]) * m ** (-e[:, None])
    best = PRICE_GRID[np.argmax(value, axis=1)]
    items["price_mult"] = best
    items["demand_mult"] = best ** (-e)
    items["sell_price"] = np.round(list_p * best / 10) * 10
    return items


def _window(df: pd.DataFrame, start: pd.Timestamp, weeks: int, seed: int, dest: dict):
    """Forecast `weeks` weeks from `start` using only data before it, price it, and build the decision table."""
    end = start + pd.Timedelta(weeks=weeks)
    test = fit_predict(df[df["week"] < end], start.strftime("%Y-%m-%d"))
    items = test.sort_values(["product_id", "week"]).reset_index(drop=True)
    seg = {p["name"]: p["segment"] for p in cat.products_for(dest)}
    items["segment"] = items["product"].map(seg).fillna("leisure")
    last_year = df[(df["week"] < start) & (df["week"] >= start - pd.Timedelta(weeks=52))]
    typical = last_year.groupby("product")["demand"].mean()
    month_avg = last_year.groupby(["product", last_year["week"].dt.month])["demand"].mean()
    items["typical"] = items["product"].map(typical).to_numpy()
    items["q_today"] = _round([month_avg.get((p, m), typical[p]) for p, m in zip(items["product"], items["week"].dt.month)])
    items["avail"] = live_availability(items["p50"].to_numpy(), items["typical"].to_numpy())
    # procurement prices move with the season; only the expected (seasonal) index is known in advance
    items["price_idx"] = [float(price_index(k, [s])[0]) for k, s in zip(items["kind"], items["season_factor"])]
    items["unit_cost"] = np.round(items["unit_cost"] * items["price_idx"] / 10) * 10
    items["live_buy_cost"] = np.round(items["live_buy_cost"] * items["price_idx"] / 10) * 10
    items["sell_list"] = np.round(items["sell_price"] * items["price_idx"] / 10) * 10
    # signals from last year and the last few weeks
    yr = pd.Timedelta(weeks=52)
    look = df.set_index(["product", "week"])
    get = lambda col, p, w, d=None: look[col].get((p, w), d)
    items["last_year"] = [None if get("demand", p, w - yr) is None else int(get("demand", p, w - yr)) for p, w in zip(items["product"], items["week"])]
    items["searches_ly"] = [float(get("searches_6w_ahead", p, w - yr, 0)) for p, w in zip(items["product"], items["week"])]
    items["sold_out_ly"] = [int(get("sold_out", p, w - yr, 0)) for p, w in zip(items["product"], items["week"])]
    recent = df[(df["week"] < start) & (df["week"] >= start - pd.Timedelta(weeks=8))]
    recent_ly = df[(df["week"] < start - yr) & (df["week"] >= start - yr - pd.Timedelta(weeks=8))]
    ltb = recent.groupby("product")["searches_6w_ahead"].sum() / recent.groupby("product")["bookings_gross"].sum().clip(lower=1)
    ltb_ly = recent_ly.groupby("product")["searches_6w_ahead"].sum() / recent_ly.groupby("product")["bookings_gross"].sum().clip(lower=1)
    items["look_to_book"] = items["product"].map(ltb).fillna(0).round(1)
    items["ltb_change"] = items["product"].map(((ltb / ltb_ly) - 1) * 100).fillna(0).round(0)
    canc = last_year.groupby("product")["cancellations"].sum() / last_year.groupby("product")["bookings_gross"].sum().clip(lower=1)
    items["cancel_rate"] = items["product"].map(canc).fillna(0.08)
    items = _pricing(items)
    for c in ("p10", "p50", "p90"):
        items[c + "_list"] = items[c]
        items[c] = items[c] * items["demand_mult"]
    items["max_units"] = np.ceil(items["p90"] * 1.6 + 10)
    items["exp_cancellations"] = np.round(items["p50"] / (1 - items["cancel_rate"]) * items["cancel_rate"])
    rng = np.random.default_rng(seed)
    base = items.assign(p10=items["p10_list"], p50=items["p50_list"], p90=items["p90_list"])
    scen_base = np.vstack([sample_scenarios(r, N_SCEN, rng) for _, r in base.iterrows()]) if len(items) else np.zeros((0, N_SCEN))
    scen = np.round(scen_base * items["demand_mult"].to_numpy()[:, None])
    today = items.assign(sell_price=items["sell_list"])     # today's rule: rate-card price, no repricing
    return items, scen, today, scen_base


@lru_cache(maxsize=64)
def _window_cached(dkey: tuple, start: str, weeks: int, seed: int):
    dest = dict(dkey)
    start_ts = pd.Timestamp(start)
    df = _history(dest, start_ts + pd.Timedelta(weeks=weeks))
    return (df,) + _window(df, start_ts, weeks, seed, dest)


def _get_window(dest: dict, start_ts: pd.Timestamp, weeks: int, kinds=None, year_back: bool = False):
    """Forecast + scenarios for a window, computed once and reused for every risk, budget and module view."""
    s = start_ts - pd.Timedelta(weeks=52) if year_back else start_ts
    seed = cat.seed_for(dest["id"]) % (997 if year_back else 10_000) + (0 if year_back else start_ts.dayofyear)
    df, items, scen, today, scen_base = _window_cached(_key(dest), s.strftime("%Y-%m-%d"), int(weeks), seed)
    if kinds:
        m = items["kind"].isin(kinds).to_numpy()
        if not m.any():
            raise ValueError(f"no {', '.join(kinds)} products for this destination")
        items, scen, today, scen_base = items[m].reset_index(drop=True), scen[m], today[m].reset_index(drop=True), scen_base[m]
    return df, items.copy(), scen, today.copy(), scen_base


def _start(start: str | None) -> pd.Timestamp:
    s = pd.Timestamp(start) if start else next_monday()
    return s - pd.Timedelta(days=s.weekday())


def _today_q(items: pd.DataFrame, budget_inr: float | None) -> np.ndarray:
    """Today's rule, held to the same rupee budget: every line scaled down evenly if it would overspend."""
    q = items["q_today"].to_numpy(float)
    spend = float((items["unit_cost"].to_numpy(float) * q).sum())
    return _round(q * budget_inr / spend) if budget_inr and spend > budget_inr else q


def _optimise(W, budget_pct: float, risk: str, budget_inr: float | None = None, q_today=None):
    items, scen, today_items, scen_base = W
    q_today = _today_q(items, budget_inr) if q_today is None else q_today
    today = evaluate(today_items, q_today, scen_base)
    budget = float(budget_inr) if budget_inr else today["spend"] * budget_pct / 100
    cfg = RISK.get(risk, RISK["balanced"])
    cap = None if cfg["cap"] is None else today["cvar95_loss"] + cfg["cap"] * abs(today["cvar95_loss"])
    w = cfg["w"] or None
    res = None
    for c in (cap, None):
        res = solve(items, scen, budget=budget, risk_cap=c, risk_weight=w, time_limit=8, relax=True)
        if "exp_profit" in res:
            break
    # safety net: the plan must never be worse than today's rule on the same scenarios (it is always feasible)
    if "exp_profit" in res:
        base = evaluate(items, q_today, scen)
        if base["exp_profit"] > res["exp_profit"] and (cap is None or base["cvar95_loss"] <= cap):
            res = {**res, **base, "q": np.asarray(q_today, float), "fallback": True}
    return res, today, budget


def _drivers(r) -> list[str]:
    out = []
    if r["festival"]:
        out.append(r["festival"])
    if r["sold_out_ly"]:
        out.append("sold out this week last year")
    sf = r["season_factor"]
    if sf >= 1.3:
        out.append("peak season")
    elif sf <= 0.7:
        out.append("low season")
    if r["searches_ly"] > 0:
        ch = (r["searches_6w_ahead"] / r["searches_ly"] - 1) * 100
        if abs(ch) >= 12:
            out.append(f"searches {ch:+.0f}% vs last year")
    if abs(r["ltb_change"]) >= 10:
        out.append(f"look-to-book {r['ltb_change']:+.0f}%")
    if r["price_idx"] <= 0.95:
        out.append(f"cheap buy price ({(r['price_idx'] - 1) * 100:+.0f}%)")
    elif r["price_idx"] >= 1.08:
        out.append(f"peak buy price ({(r['price_idx'] - 1) * 100:+.0f}%)")
    if r["avail"] <= 0.45:
        out.append("suppliers likely to sell out")
    return out[:4]


def _decide(r) -> tuple[str, str]:
    q, p50, today = r["q"], r["p50"], r["q_today"]
    unit = {"hotel": "nights", "flight": "seats", "transfer": "seats", "activity": "passes"}[r["kind"]]
    pm = (r["price_mult"] - 1) * 100
    price = f" Sell at ₹{r['sell_price']:,.0f}" + (f" ({pm:+.0f}% vs rate card)." if abs(pm) >= 1 else " (rate card).")
    if q <= 0:
        return "SKIP", f"Buy live instead: margin doesn't cover the risk of {p50:.0f} {unit} going unsold." + price
    if q < 0.6 * p50:
        why = "prices are at a seasonal high" if r["price_idx"] >= 1.08 else "demand is still uncertain"
        return "WAIT", f"Lock {q:.0f} {unit} now and buy the rest live: {why}." + price
    diff = q - today
    tail = f"{abs(diff):.0f} more than today's rule" if diff > 0 else (f"{abs(diff):.0f} fewer than today's rule" if diff < 0 else "same as today's rule")
    return "BUY", f"Pre-buy {q:.0f} {unit} ({tail}); likely demand {p50:.0f} after ~{r['exp_cancellations']:.0f} cancellations." + price


def _kpis(e: dict) -> dict:
    return {"expected_profit": round(e["exp_profit"]), "worst5_loss": round(e["cvar95_loss"]),
            "spend": round(e["spend"]), "unsold_units": round(float(e["unsold_units"]), 1),
            "served_pct": round(100 * float(e["served_units"]) / max(float(e["demand_units"]), 1), 1),
            "lost_units": round(float(e["lost_units"]), 1),
            "roi_pct": round(100 * e["exp_profit"] / max(e["spend"], 1), 1)}


def resolve(dest_id: str | None, custom: dict | None, city: str | None = None, hub: str | None = None) -> dict:
    if custom:
        return cat.custom_destination(**custom)
    if city or (dest_id and str(dest_id).startswith("w")):
        from .world import world
        w = world()
        return w.profile(w.get(city or dest_id), hub)
    d = cat.find(dest_id or "goa")
    if not d:
        raise ValueError(f"unknown destination '{dest_id}'")
    if hub and hub.upper() != d["hub"]:
        d = cat.destination(next(x for x in cat.DESTINATIONS if x[0] == d["id"])[:9] + (hub.upper(),))
    d["type_label"] = cat.SEASONS[d["type"]]["label"]
    return d


def _annotate(items: pd.DataFrame, q) -> pd.DataFrame:
    items["q"] = q
    acts = [(_decide(r), _drivers(r)) for _, r in items.iterrows()]
    items["action"] = [a[0][0] for a in acts]
    items["reason"] = [a[0][1] for a in acts]
    items["drivers"] = [a[1] for a in acts]
    return items


def _week_rows(g: pd.DataFrame) -> list[dict]:
    return [{"week": r.week.strftime("%Y-%m-%d"), "p10": round(r.p10), "p50": round(r.p50), "p90": round(r.p90),
             "last_year": r.last_year, "q": int(r.q), "q_today": int(r.q_today), "action": r.action, "reason": r.reason,
             "drivers": r.drivers, "festival": r.festival, "unit_cost": int(r.unit_cost), "sell_price": int(r.sell_price),
             "sell_list": int(r.sell_list), "price_change_pct": round((r.price_mult - 1) * 100), "price_idx": round(r.price_idx, 3),
             "cancellations": int(r.exp_cancellations), "sold_out_ly": int(r.sold_out_ly)}
            for r in g.itertuples()]


def _stress(items, q, today_items, q_today, scen, scen_base) -> list[dict]:
    """Profit if demand comes in 30% below ... 30% above the forecast, for both plans."""
    out = []
    for s in STRESS:
        a = evaluate(items, q, np.round(scen * (1 + s)))
        b = evaluate(today_items, q_today, np.round(scen_base * (1 + s)))
        out.append({"shock_pct": round(s * 100), "stockshock": round(a["exp_profit"]), "today": round(b["exp_profit"]),
                    "stockshock_unsold": round(float(a["unsold_units"])), "today_unsold": round(float(b["unsold_units"]))})
    return out


def plan(dest: dict, start: str | None = None, weeks: int = 8, budget_pct: float = 100,
         risk: str = "balanced", replay: bool = False, kinds: list | None = None, budget_inr: float | None = None) -> dict:
    t0 = time.time()
    weeks = int(min(max(weeks, 2), 12))
    budget_pct = float(min(max(budget_pct, 40), 160))
    start_ts = _start(start)
    df, items, scen, today_items, scen_base = _get_window(dest, start_ts, weeks, kinds)
    W = (items, scen, today_items, scen_base)
    items["q_today"] = _today_q(items, budget_inr)
    res, today, budget = _optimise(W, budget_pct, risk, budget_inr)
    items = _annotate(items, res["q"])
    compare = {}
    for rk in RISK:
        r2 = res if rk == risk else _optimise(W, budget_pct, rk, budget_inr)[0]
        compare[rk] = {**_kpis(r2), "units": int(np.sum(r2["q"]))}
    dest = {**dest, "type_label": cat.SEASONS[dest["type"]]["label"], "season": cat.SEASONS[dest["type"]]["m"]}
    products = []
    for name, g in items.groupby("product", sort=False):
        products.append({"name": name, "kind": g["kind"].iloc[0], "segment": g["segment"].iloc[0],
                         "unit_cost": int(g["unit_cost"].mean()), "sell_price": int(g["sell_price"].mean()),
                         "cancel_rate": round(float(g["cancel_rate"].iloc[0]) * 100, 1),
                         "look_to_book": float(g["look_to_book"].iloc[0]), "ltb_change": float(g["ltb_change"].iloc[0]),
                         "weeks": _week_rows(g)})
    signals = {"look_to_book": round(float(items["look_to_book"].mean()), 1), "ltb_change": round(float(items["ltb_change"].mean())),
               "cancel_rate": round(float(items["cancel_rate"].mean()) * 100, 1),
               "sold_out_weeks_ly": int(items.groupby("week")["sold_out_ly"].max().sum()),
               "search_momentum": round(float((items["searches_6w_ahead"].sum() / max(items["searches_ly"].sum(), 1) - 1) * 100)),
               "price_idx": [round(float(x), 3) for x in items.groupby("week")["price_idx"].mean()],
               "avg_price_change": round(float((items["price_mult"] - 1).mean() * 100), 1)}
    out = {"destination": dest, "start": start_ts.strftime("%Y-%m-%d"), "weeks": weeks,
           "budget_pct": budget_pct, "risk": risk, "budget": round(budget), "budget_inr": budget_inr, "kinds": kinds or [],
           "kpis": {"stockshock": _kpis(res), "today": _kpis(today)},
           "products": products, "scenarios": N_SCEN, "risk_compare": compare, "signals": signals,
           "stress": _stress(items, res["q"], today_items, items["q_today"].to_numpy(), scen, scen_base)}
    if replay:
        out["replay"] = replay_check(dest, start_ts.strftime("%Y-%m-%d"), weeks, budget_pct, risk, kinds)
    out["seconds"] = round(time.time() - t0, 2)
    return out


def replay_check(dest: dict, start: str | None = None, weeks: int = 8, budget_pct: float = 100,
                 risk: str = "balanced", kinds: list | None = None, budget_inr: float | None = None) -> dict:
    """Same window one year earlier, planned with data available then, scored on what really happened."""
    start_ts = _start(start)
    _, items, scen, today_items, scen_base = _get_window(dest, start_ts, int(weeks), kinds, year_back=True)
    res, _, _ = _optimise((items, scen, today_items, scen_base), float(budget_pct), risk, budget_inr)
    actual_base = items["demand"].to_numpy(float)[:, None]
    actual = np.round(actual_base * items["demand_mult"].to_numpy()[:, None])   # what would have sold at our prices
    ss = evaluate(items, res["q"], actual)
    td = evaluate(today_items, _today_q(items, budget_inr), actual_base)   # same rupee budget for both
    return {"start": (start_ts - pd.Timedelta(weeks=52)).strftime("%Y-%m-%d"), "stockshock": _kpis(ss), "today": _kpis(td),
            "profit_gain": round(ss["exp_profit"] - td["exp_profit"]),
            "unsold_cut_units": round(float(td["unsold_units"] - ss["unsold_units"]), 1)}


def frontier(dest: dict, start: str | None = None, weeks: int = 8, budget_pct: float = 100, kinds: list | None = None,
             budget_inr: float | None = None) -> dict:
    start_ts = _start(start)
    _, items, scen, today_items, scen_base = _get_window(dest, start_ts, int(min(max(weeks, 2), 12)), kinds)
    W = (items, scen, today_items, scen_base)
    today = evaluate(today_items, items["q_today"].to_numpy(), scen_base)
    budget = float(budget_inr) if budget_inr else today["spend"] * float(budget_pct) / 100
    pts, marks = [], {}
    for rk in RISK:
        r = _optimise(W, float(budget_pct), rk, budget_inr)[0]
        if "exp_profit" in r:
            marks[rk] = {"worst5_loss": round(r["cvar95_loss"]), "expected_profit": round(r["exp_profit"])}
            pts.append(dict(marks[rk]))
    for w in (0.5, 2.5, 6.0):
        r = solve(items, scen, budget=budget, risk_cap=None, risk_weight=w, relax=True, time_limit=6)
        if "exp_profit" in r:
            pts.append({"worst5_loss": round(r["cvar95_loss"]), "expected_profit": round(r["exp_profit"])})
    pts.sort(key=lambda p: p["worst5_loss"])
    pareto, best = [], -1e18
    for p in pts:
        if p["expected_profit"] > best:
            pareto.append(p); best = p["expected_profit"]
    return {"points": pareto, "risk_points": marks, "today": {"worst5_loss": round(today["cvar95_loss"]), "expected_profit": round(today["exp_profit"])}}


PF_SCEN = 40


def warm(dests: list[dict] | None = None, weeks: int = 8) -> dict:
    """Pre-compute forecasts so the first Portfolio / Radar / planner click is instant."""
    t0 = time.time()
    from .world import world
    world()
    dests = dests if dests is not None else [resolve(i, None) for i in ("goa", "dubai", "bali", "london")]   # Portfolio defaults
    st = _start(None)
    n = 0
    for d in dests[:8]:
        try:
            _get_window(d, st, weeks); n += 1
        except ValueError:
            pass
    return {"warmed": n, "seconds": round(time.time() - t0, 2)}


# ------------------------------------------------------------------ portfolio: one budget, many destinations
def portfolio(dests: list[dict], budget_inr: float, start: str | None = None, weeks: int = 8, risk: str = "balanced",
              kinds: list | None = None) -> dict:
    """Split one maximum budget (in rupees) across several destinations, products and weeks at once."""
    t0 = time.time()
    if not dests:
        raise ValueError("add at least one destination")
    dests = dests[:8]
    weeks = int(min(max(weeks, 2), 12))
    start_ts = _start(start)
    parts = []
    for d in dests:
        try:
            _, it, sc, td, sb = _get_window(d, start_ts, weeks, kinds)
        except ValueError:
            continue
        it = it.assign(dest_id=d["id"], dest_name=d["name"], cc=d.get("cc", ""), airport=d.get("airport", ""))
        parts.append((it, sc, td, sb))
    if not parts:
        raise ValueError("none of these destinations has the selected products")
    items = pd.concat([p[0] for p in parts], ignore_index=True)
    today_items = pd.concat([p[2] for p in parts], ignore_index=True)
    # 40 of the 60 scenarios per line: the joint solve over many cities stays under ~1 s
    scen, scen_base = np.vstack([p[1][:, :PF_SCEN] for p in parts]), np.vstack([p[3][:, :PF_SCEN] for p in parts])
    # today's rule, held to the same budget: each line scaled down evenly if it would overspend
    q_today = _today_q(items, budget_inr)
    items["q_today"] = q_today
    W = (items, scen, today_items, scen_base)
    order = [risk] + [rk for rk in RISK if rk != risk]
    with ThreadPoolExecutor(len(order)) as ex:     # HiGHS releases the GIL, so the three risk levels solve side by side
        outs = list(ex.map(lambda rk: _optimise(W, 100, rk, budget_inr, q_today), order))
    res, today, budget = outs[0]
    items = _annotate(items, res["q"])
    items["spend"] = items["q"] * items["unit_cost"]
    compare = {rk: {**_kpis(o[0]), "units": int(np.sum(o[0]["q"]))} for rk, o in zip(order, outs)}
    compare = {rk: compare[rk] for rk in RISK}
    by_dest = (items.groupby(["dest_id", "dest_name", "cc"], sort=False)
               .agg(spend=("spend", "sum"), units=("q", "sum")).reset_index())
    by_kind = items.groupby("kind")["spend"].sum()
    by_week = items.groupby(["week", "dest_name"])["spend"].sum().unstack(fill_value=0)
    lines = []
    for r in items[items["q"] > 0].sort_values("spend", ascending=False).itertuples():
        lines.append({"dest_id": r.dest_id, "dest": r.dest_name, "cc": r.cc, "airport": r.airport, "product": r.product,
                      "kind": r.kind, "segment": r.segment, "week": r.week.strftime("%Y-%m-%d"), "q": int(r.q),
                      "q_today": int(r.q_today), "unit_cost": int(r.unit_cost), "sell_price": int(r.sell_price),
                      "price_change_pct": round((r.price_mult - 1) * 100), "spend": int(r.spend), "action": r.action,
                      "reason": r.reason, "drivers": r.drivers, "p50": round(r.p50)})
    return {"budget": round(budget), "start": start_ts.strftime("%Y-%m-%d"), "weeks": weeks, "risk": risk,
            "kpis": {"stockshock": _kpis(res), "today": _kpis(today)}, "risk_compare": compare,
            "by_dest": [{"id": r.dest_id, "name": r.dest_name, "cc": r.cc, "spend": int(r.spend), "units": int(r.units)} for r in by_dest.itertuples()],
            "by_kind": {k: int(v) for k, v in by_kind.items()},
            "by_week": {"weeks": [w.strftime("%Y-%m-%d") for w in by_week.index], "series": {c: [int(v) for v in by_week[c]] for c in by_week.columns}},
            "lines": lines, "stress": _stress(items, res["q"], today_items, q_today, scen, scen_base),
            "scenarios": PF_SCEN, "seconds": round(time.time() - t0, 2)}


# ------------------------------------------------------------------ opportunity radar
def radar(dests: list[dict], start: str | None = None, weeks: int = 8, kinds: list | None = None, limit: int = 25) -> dict:
    """Rank destination x product x week by how attractive a pre-buy looks, from history alone (fast):
    last year's demand in the window, search momentum, look-to-book, sold-outs, buy price and margin."""
    t0 = time.time()
    start_ts = _start(start)
    end = start_ts + pd.Timedelta(weeks=int(weeks))
    yr = pd.Timedelta(weeks=52)
    rows = []
    for d in dests:
        df = _history(d, start_ts)
        prods = {p["name"]: p for p in cat.products_for(d)}
        recent = df[df["week"] >= start_ts - pd.Timedelta(weeks=6)]
        recent_ly = df[(df["week"] >= start_ts - yr - pd.Timedelta(weeks=6)) & (df["week"] < start_ts - yr)]
        ly = df[(df["week"] >= start_ts - yr) & (df["week"] < end - yr)]
        for name, g in ly.groupby("product", sort=False):
            p = prods.get(name)
            if p is None or (kinds and p["kind"] not in kinds):
                continue
            s_now = recent[recent["product"] == name]["searches_6w_ahead"].sum()
            s_ly = recent_ly[recent_ly["product"] == name]["searches_6w_ahead"].sum()
            b_now = recent[recent["product"] == name]["bookings_gross"].sum()
            b_ly = recent_ly[recent_ly["product"] == name]["bookings_gross"].sum()
            momentum = (s_now / max(s_ly, 1) - 1) * 100
            ltb_ch = ((s_now / max(b_now, 1)) / max(s_ly / max(b_ly, 1), 1e-6) - 1) * 100
            best = g.loc[g["demand"].idxmax()]
            pidx = float(price_index(p["kind"], g["season_factor"]).mean())
            margin = (p["sell_price"] - p["unit_cost"] * pidx) / (p["unit_cost"] * pidx)
            demand = float(g["demand"].sum()) * (1 + np.clip(momentum, -40, 60) / 100)
            sold = int(g["sold_out"].sum())
            value = demand * p["unit_cost"] * pidx
            score = margin * value * (1 + 0.25 * sold) * (1 + np.clip(momentum, -40, 60) / 200) / pidx
            why = []
            if momentum >= 10: why.append(f"searches {momentum:+.0f}%")
            if sold: why.append(f"sold out {sold} wk last year")
            if pidx <= 0.96: why.append("cheap buy price")
            if pidx >= 1.08: why.append("peak buy price")
            if ltb_ch <= -10: why.append("lookers converting faster")
            rows.append({"dest_id": d["id"], "dest": d["name"], "country": d.get("country", ""), "cc": d.get("cc", ""),
                         "type": cat.SEASONS[d["type"]]["label"], "product": name, "kind": p["kind"], "segment": p["segment"],
                         "best_week": (best["week"] + yr).strftime("%Y-%m-%d"), "demand": round(demand),
                         "search_momentum": round(momentum), "ltb_change": round(ltb_ch), "sold_out_weeks": sold,
                         "price_idx": round(pidx, 3), "margin_pct": round(margin * 100, 1),
                         "est_return_pct": round(margin * 100 * (1 - 0.12 / (1 + sold)), 1), "value": round(value),
                         "_score": score, "why": why})
    if not rows:
        return {"rows": [], "alerts": []}
    mx = max(r["_score"] for r in rows) or 1
    for r in rows:
        r["score"] = round(100 * max(r.pop("_score"), 0) / mx)
    rows.sort(key=lambda r: -r["score"])
    rows = rows[:limit]
    alerts = []
    for r in rows[:6]:
        u = {"hotel": "nights", "flight": "seats", "activity": "passes", "transfer": "seats"}[r["kind"]]
        lead = "Buy early" if r["price_idx"] < 1.03 else "Lock part now"
        alerts.append({"dest_id": r["dest_id"], "kind": r["kind"], "level": "hot" if r["score"] >= 70 else "watch",
                       "text": f"{lead}: {r['product']} in {r['dest']} — ~{r['demand']:,} {u} expected, "
                               f"{', '.join(r['why'][:2]) or 'steady demand'}; margin {r['margin_pct']:.0f}%."})
    return {"rows": rows, "alerts": alerts, "start": start_ts.strftime("%Y-%m-%d"), "weeks": int(weeks), "scanned": len(dests),
            "seconds": round(time.time() - t0, 2)}
