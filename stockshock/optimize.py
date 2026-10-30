"""Risk-capped pre-buy optimizer (mixed-integer program, solved with HiGHS via SciPy).

For every product-week we choose how many units to pre-buy (in blocks of 5).
Demand is uncertain, so we evaluate each plan on many demand scenarios:

  pre-bought units sold  x[i,s] <= q[i],  x[i,s] <= D[i,s]
  live-bought units sold y[i,s] <= a[i] * (D[i,s] - x[i,s])   (suppliers sell out at peaks)
  profit[s] = sum_i  price*x + (price - live_cost)*y - cost*q + salvage*cost*(q - x)

maximise   average profit over scenarios
subject to total pre-buy spend <= budget
           CVaR_95(loss) <= risk cap      (average of the worst 5% outcomes)

CVaR uses the Rockafellar-Uryasev linear form, so the whole problem stays a MILP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

BLOCK = 5


def live_availability(p50: np.ndarray, typical: np.ndarray) -> np.ndarray:
    """Share of extra demand we can still buy live; low when the market is hot."""
    return np.clip(1.15 - 0.45 * p50 / np.maximum(typical, 1), 0.15, 0.9)


GOODWILL = 0.10   # cost of a lost booking (agent churn), as a share of the sell price


def _avail(items: pd.DataFrame, demand: np.ndarray) -> np.ndarray:
    if "typical" in items:
        return live_availability(demand, items["typical"].to_numpy(float)[:, None])
    return np.broadcast_to(items["avail"].to_numpy(float)[:, None], demand.shape)


def solve(items: pd.DataFrame, scen: np.ndarray, budget: float, risk_cap: float | None,
          beta: float = 0.95, time_limit: float = 20, min_served: float | None = None,
          risk_weight: float | None = None, relax: bool = False) -> dict:
    """items: one row per product-week with unit_cost, sell_price, live_buy_cost, salvage_share,
    avail, max_units.  scen: array (n_items, n_scen) of demand."""
    n, S = scen.shape
    c = items["unit_cost"].to_numpy(float)
    p = items["sell_price"].to_numpy(float)
    l = items["live_buy_cost"].to_numpy(float)
    sv = items["salvage_share"].to_numpy(float) * c
    # live availability depends on how hot each demand scenario is (suppliers sell out at peaks)
    a = _avail(items, scen)
    kmax = np.ceil(items["max_units"].to_numpy(float) / BLOCK)

    # variable layout: k[n] | x[n*S] | y[n*S] | eta | u[S]
    nk, nx = n, n * S
    ix_k = np.arange(nk)
    ix_x = nk + np.arange(nx).reshape(n, S)
    ix_y = nk + nx + np.arange(nx).reshape(n, S)
    ix_eta = nk + 2 * nx
    ix_u = ix_eta + 1 + np.arange(S)
    nv = ix_u[-1] + 1

    # objective (minimise negative expected profit)
    obj = np.zeros(nv)
    obj[ix_k] = -(-c + sv) * BLOCK                # -cost*q + salvage*q, q = BLOCK*k
    g = GOODWILL * p                              # every booking served avoids a goodwill loss
    obj[ix_x] = -((p - sv + g)[:, None] / S)      # price*x - salvage*x
    obj[ix_y] = -((p - l + g)[:, None] / S)

    rows, cols, vals, lo, hi = [], [], [], [], []
    r = 0

    def add(cs, vs, lb, ub):
        nonlocal r
        rows.extend([r] * len(cs)); cols.extend(cs); vals.extend(vs); lo.append(lb); hi.append(ub); r += 1

    for i in range(n):
        for s in range(S):
            add([ix_x[i, s], ix_k[i]], [1, -BLOCK], -np.inf, 0)               # x <= q
            add([ix_y[i, s], ix_x[i, s]], [1, a[i, s]], -np.inf, a[i, s] * scen[i, s])  # y <= a(D - x)
    add(list(ix_k), list(c * BLOCK), -np.inf, budget)                        # budget

    if risk_cap is not None or risk_weight is not None:
        # u_s >= loss_s - eta, loss_s = -profit_s
        for s in range(S):
            cs = [ix_u[s], ix_eta] + list(ix_k) + list(ix_x[:, s]) + list(ix_y[:, s])
            vs = [1, 1] + list((-c + sv) * BLOCK) + list(p - sv) + list(p - l)
            add(cs, vs, 0, np.inf)
        if risk_cap is not None:
            add([ix_eta] + list(ix_u), [1] + [1 / ((1 - beta) * S)] * S, -np.inf, risk_cap)
        if risk_weight is not None:      # trade expected profit against CVaR: max E[profit] - w * CVaR
            obj[ix_eta] += risk_weight
            obj[ix_u] += risk_weight / ((1 - beta) * S)

    if min_served is not None:
        # service level: serve at least as many bookings (on average) as today's plan
        add(list(ix_x.ravel()) + list(ix_y.ravel()), [1 / S] * (2 * nx), min_served, np.inf)

    A = coo_matrix((vals, (rows, cols)), shape=(r, nv))
    lb = np.zeros(nv); ub = np.full(nv, np.inf)
    ub[ix_k] = kmax
    ub[ix_x] = scen
    lb[ix_eta] = -np.inf
    integrality = np.zeros(nv)
    if not relax:
        integrality[ix_k] = 1
    res = milp(obj, constraints=LinearConstraint(A, lo, hi), bounds=Bounds(lb, ub),
               integrality=integrality, options={"time_limit": time_limit, "mip_rel_gap": 1e-3})
    if res.x is None:
        return {"status": res.message, "q": np.zeros(n)}
    q = (np.floor(res.x[ix_k] + 1e-6) if relax else np.round(res.x[ix_k])) * BLOCK
    prof = evaluate(items, q, scen)
    return {"status": res.message, "q": q, **prof}


def evaluate(items: pd.DataFrame, q: np.ndarray, demand: np.ndarray, beta: float = 0.95) -> dict:
    """Profit of a pre-buy plan q on demand (n_items x n_scen, or n_items x 1 for actuals)."""
    c = items["unit_cost"].to_numpy(float)[:, None]
    p = items["sell_price"].to_numpy(float)[:, None]
    l = items["live_buy_cost"].to_numpy(float)[:, None]
    sv = items["salvage_share"].to_numpy(float)[:, None] * c
    a = _avail(items, demand)
    q = np.asarray(q, float)[:, None]
    x = np.minimum(q, demand)
    y = np.floor(a * (demand - x))
    lost = demand - x - y
    unsold = q - x
    profit_items = p * x + (p - l) * y - c * q + sv * unsold
    profit = profit_items.sum(axis=0)
    loss = -profit
    k = max(1, int(np.ceil((1 - beta) * loss.size)))
    cvar = float(np.sort(loss)[-k:].mean())
    return {"exp_profit": float(profit.mean()), "cvar95_loss": cvar,
            "unsold_units": unsold.sum(axis=0).mean(), "unsold_cost": float(((c - sv) * unsold).sum(axis=0).mean()),
            "lost_units": lost.sum(axis=0).mean(), "served_units": (x + y).sum(axis=0).mean(),
            "demand_units": demand.sum(axis=0).mean(), "spend": float((c * q).sum()),
            "per_item_lost": lost.mean(axis=1), "per_item_unsold": unsold.mean(axis=1)}


def decide(row: pd.Series) -> tuple[str, str]:
    """Turn the optimiser's quantity into BUY / WAIT / SKIP with a plain-English reason."""
    q, p50, p10, p90 = row["q"], row["p50"], row["p10"], row["p90"]
    spread = (p90 - p10) / max(p50, 1)
    if q <= 0:
        return "SKIP", f"margin does not cover the risk (range {p10:.0f}-{p90:.0f})"
    if q < 0.6 * p50:
        return "WAIT", f"buy {q:.0f} now, rest live; demand too uncertain (+/-{spread*50:.0f}%)"
    return "BUY", f"{q:.0f} units; likely demand {p50:.0f}, live market tight"
