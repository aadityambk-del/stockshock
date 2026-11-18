"""Request handling shared by the FastAPI app (app.py) and the zero-dependency dev server (dev_server.py)."""
from __future__ import annotations

import json
import threading

import numpy as np

from . import service

# the solver is not thread-safe, so heavy requests run one at a time (each takes ~1-2 s)
_LOCK = threading.Lock()
_RADAR: dict = {}


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
    return service.resolve(params.get("dest"), custom, city=params.get("city"),
                           hub=params.get("origin") or params.get("hub"))


KINDS = {"flight", "hotel", "activity", "transfer"}


def _kinds(params: dict):
    k = params.get("kinds")
    if not k:
        return None
    k = k if isinstance(k, list) else str(k).split(",")
    k = [x.strip() for x in k if x.strip() in KINDS]
    return k or None


def _ids(params: dict) -> list:
    v = params.get("ids") or params.get("dests") or ""
    v = v if isinstance(v, list) else str(v).split(",")
    return [x.strip() for x in v if x and x.strip()]


def _resolve_many(ids: list) -> list:
    out = []
    for i in ids[:8]:
        out.append(service.resolve(None if i.startswith("w") else i, None, city=i if i.startswith("w") else None))
    return out


def handle(route: str, params: dict) -> tuple[int, dict]:
    """route: 'catalog' | 'plan' | 'frontier' | 'health'. params: query-string values or JSON body."""
    try:
        if route == "health":
            return 200, {"ok": True}
        if route == "catalog":
            return 200, service.catalog()
        if route == "search":
            from .world import world
            q = str(params.get("q", "")); lim = _num(params.get("limit"), 12, int)
            from .world import fold
            fq = fold(q)
            feat = [{"id": d["id"], "name": d["name"], "region": d["region"], "cc": d.get("cc", ""), "country": d["country"],
                     "lat": d["lat"], "lon": d["lon"], "airport": d["airport"], "airport_name": d.get("airport_name", ""),
                     "featured": True, "type_label": d["type_label"]}
                    for d in service.cat.all_destinations() if fq and len(fq) >= 2 and fold(d["name"]).startswith(fq)]
            res = world().search(q, lim)
            names = {(f["name"].lower(), f["country"]) for f in feat}
            res = [r for r in res if (r["name"].lower(), r["country"]) not in names]
            return 200, {"results": (feat + res)[:lim]}
        if route == "nearest":
            from .world import world
            w = world(); i = w.nearest(_num(params.get("lat"), 0.0), _num(params.get("lon"), 0.0))
            return 200, {"city": w.brief(i) if i is not None else None}
        if route == "city":
            from .world import world
            w = world()
            return 200, w.profile(w.get(params.get("id", "")), params.get("hub"))
        if route == "plan":
            with _LOCK:
                return 200, service.plan(_dest(params), start=params.get("start") or None,
                                     weeks=_num(params.get("weeks"), 8, int),
                                     budget_pct=_num(params.get("budget"), 100),
                                     risk=str(params.get("risk", "balanced")),
                                     replay=str(params.get("replay", "0")) in ("1", "true", "True"),
                                     kinds=_kinds(params), budget_inr=_num(params.get("budget_inr"), None) or None)
        if route == "portfolio":
            with _LOCK:
                return 200, service.portfolio(_resolve_many(_ids(params)), budget_inr=_num(params.get("budget_inr"), 5_000_000),
                                              start=params.get("start") or None, weeks=_num(params.get("weeks"), 8, int),
                                              risk=str(params.get("risk", "balanced")), kinds=_kinds(params))
        if route == "warm":
            ids = _ids(params)
            out = service.warm(_resolve_many(ids) if ids else None, weeks=_num(params.get("weeks"), 8, int))
            if not ids:
                handle("radar", {})          # the Overview's alerts and the Radar tab
            return 200, out
        if route == "radar":
            ids = _ids(params)
            key = (tuple(ids), str(service._start(params.get("start") or None).date()), _num(params.get("weeks"), 8, int),
                   tuple(_kinds(params) or ()), _num(params.get("limit"), 25, int))
            if key not in _RADAR:          # deterministic for a given week, so each answer is computed once
                dests = _resolve_many(ids) if ids else service.cat.all_destinations()
                with _LOCK:
                    _RADAR[key] = service.radar(dests, start=params.get("start") or None, weeks=key[2],
                                                kinds=_kinds(params), limit=key[4])
                if len(_RADAR) > 64:
                    _RADAR.pop(next(iter(_RADAR)))
            return 200, _RADAR[key]
        if route == "replay":
            with _LOCK:
                return 200, service.replay_check(_dest(params), start=params.get("start") or None,
                                             weeks=_num(params.get("weeks"), 8, int),
                                             budget_pct=_num(params.get("budget"), 100),
                                             risk=str(params.get("risk", "balanced")), kinds=_kinds(params),
                                             budget_inr=_num(params.get("budget_inr"), None) or None)
        if route == "frontier":
            with _LOCK:
                return 200, service.frontier(_dest(params), start=params.get("start") or None,
                                         weeks=_num(params.get("weeks"), 8, int),
                                         budget_pct=_num(params.get("budget"), 100), kinds=_kinds(params),
                                         budget_inr=_num(params.get("budget_inr"), None) or None)
        return 404, {"error": f"unknown route '{route}'"}
    except ValueError as e:
        return 400, {"error": str(e)}
