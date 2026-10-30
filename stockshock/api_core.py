"""Request handling shared by the FastAPI app (app.py) and the zero-dependency dev server (dev_server.py)."""
from __future__ import annotations

import json
import threading

import numpy as np

from . import service

# the solver is not thread-safe, so heavy requests run one at a time (each takes ~1-2 s)
_LOCK = threading.Lock()


def _num(v, default, cast=float):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def dumps(obj) -> bytes:
    return json.dumps(obj, default=_jsonable, ensure_ascii=False).encode("utf-8")


def _dest(params: dict):
    custom = params.get("custom")
    if custom:
        custom = {"name": str(custom.get("name", "New city")), "typ": str(custom.get("type", "beach")),
                  "popularity": _num(custom.get("popularity"), 3, int),
                  "price_level": _num(custom.get("price_level"), 1.0),
                  "hub": str(custom.get("hub", "DEL")),
                  "lat": _num(custom.get("lat"), None), "lon": _num(custom.get("lon"), None),
                  "airport": custom.get("airport")}
    return service.resolve(params.get("dest"), custom)


def handle(route: str, params: dict) -> tuple[int, dict]:
    """route: 'catalog' | 'plan' | 'frontier' | 'health'. params: query-string values or JSON body."""
    try:
        if route == "health":
            return 200, {"ok": True}
        if route == "catalog":
            return 200, service.catalog()
        if route == "plan":
            with _LOCK:
                return 200, service.plan(_dest(params), start=params.get("start") or None,
                                     weeks=_num(params.get("weeks"), 8, int),
                                     budget_pct=_num(params.get("budget"), 100),
                                     risk=str(params.get("risk", "balanced")),
                                     replay=str(params.get("replay", "1")) not in ("0", "false"))
        if route == "frontier":
            with _LOCK:
                return 200, service.frontier(_dest(params), start=params.get("start") or None,
                                         weeks=_num(params.get("weeks"), 8, int),
                                         budget_pct=_num(params.get("budget"), 100))
        return 404, {"error": f"unknown route '{route}'"}
    except ValueError as e:
        return 400, {"error": str(e)}
