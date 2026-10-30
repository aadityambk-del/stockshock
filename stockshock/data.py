"""Simulated TBO-style weekly demand for any destination.

TBO's booking history is not public, so we generate a realistic stand-in for each destination:
weekly room-nights / seats / passes per product since Jan 2023, with the destination's seasons,
Indian festival and holiday peaks, yearly growth, random shocks (concerts, cricket, cyclones),
last-minute noise, and an early search signal (people search ~6 weeks before they travel).

To use real data, replace `history()` with a reader for TBO's export with the same columns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# week-start (Monday) dates of the weeks each festival or holiday lifts leisure travel
FESTIVALS = {
    "Diwali": ["2023-11-06", "2024-10-28", "2025-10-20", "2026-11-02"],
    "Holi": ["2023-03-06", "2024-03-25", "2025-03-10", "2026-03-02"],
    "Christmas & New Year": ["2022-12-26", "2023-12-25", "2024-12-23", "2024-12-30", "2025-12-22", "2025-12-29",
                             "2026-12-21", "2026-12-28"],
    "Summer holidays": ["2023-05-22", "2023-05-29", "2023-06-05", "2024-05-20", "2024-05-27", "2024-06-03",
                        "2025-05-19", "2025-05-26", "2025-06-02", "2026-05-18", "2026-05-25", "2026-06-01"],
    "Puja holidays": ["2023-10-16", "2024-10-07", "2025-09-29", "2026-10-19"],
    "Republic Day long weekend": ["2024-01-22", "2025-01-27", "2026-01-26", "2027-01-25"],
}
FEST_BY_WEEK = {pd.Timestamp(d): name for name, ds in FESTIVALS.items() for d in ds}
# how strongly each destination type reacts to Indian holidays
FEST_SENSITIVITY = {"metro": 0.25, "europe": 0.6, "gulf": 0.8}

HISTORY_START = "2023-01-02"


def season_curve(monthly: list[float], dates: pd.DatetimeIndex) -> np.ndarray:
    """Smooth week-by-week season factor from 12 monthly values."""
    doy = dates.dayofyear.to_numpy()
    centers = np.array([15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349])
    xs = np.concatenate([centers - 365, centers, centers + 365])
    ys = np.tile(monthly, 3)
    return np.interp(doy, xs, ys)


def history(dest: dict, products: list[dict], seed: int, until: pd.Timestamp) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(HISTORY_START, until, freq="W-MON")
    n = len(dates)
    sens = FEST_SENSITIVITY.get(dest["type"], 1.0)
    fest = np.array([d in FEST_BY_WEEK for d in dates])
    t = np.arange(n) / 52
    growth = 1 + rng.uniform(0.06, 0.13) * t
    # destination-wide shocks hit every product in that week
    shock = np.ones(n)
    for _ in range(rng.integers(4, 8)):
        w = rng.integers(0, n)
        shock[w] *= rng.choice([rng.uniform(1.5, 2.1), rng.uniform(0.35, 0.6)])
    rows = []
    for pid, p in enumerate(products):
        season = season_curve(p["season"], dates)
        lift = np.where(fest, 1 + sens * rng.uniform(0.25, 0.6), 1.0)
        mean = p["base"] * season * growth * lift * shock
        late = rng.lognormal(0, 0.18, n)
        demand = rng.negative_binomial(n=10, p=10 / (10 + mean * late))
        seen = np.where(rng.random(n) < 0.7, shock, 1.0)
        early = p["base"] * season * growth * lift * seen
        searches = rng.poisson(early * rng.uniform(6.0, 13.0, n) + 40)
        rows.append(pd.DataFrame({
            "week": dates, "product": p["name"], "kind": p["kind"], "product_id": pid, "demand": demand,
            "searches_6w_ahead": searches, "festival_week": fest.astype(int),
            "festival": [FEST_BY_WEEK.get(d, "") for d in dates], "season_factor": season,
            "unit_cost": p["unit_cost"], "sell_price": p["sell_price"], "live_buy_cost": p["live_buy_cost"],
            "salvage_share": p["salvage_share"]}))
    return pd.concat(rows, ignore_index=True)
