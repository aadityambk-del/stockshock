"""Destinations, their seasons and the inventory TBO could pre-buy there.

Every destination gets a season profile (monthly demand multipliers) from its type,
a popularity scale, a price level and 3-4 products (hotel tiers, a flight block, an activity).
Anyone can add a new city through the API by choosing a type; the same rules generate its products.
"""
from __future__ import annotations

from functools import lru_cache

import hashlib
import re

# monthly demand multipliers (1 = an average month) for each destination type
SEASONS = {
    "beach":     {"label": "Beach",            "m": [1.6, 1.25, 1.05, 0.85, 0.75, 0.5, 0.42, 0.48, 0.55, 0.9, 1.3, 2.1]},
    "hills":     {"label": "Hill station",     "m": [1.2, 0.9, 0.85, 1.05, 1.75, 1.9, 0.65, 0.5, 0.7, 1.0, 0.95, 1.55]},
    "heritage":  {"label": "Heritage city",    "m": [1.45, 1.3, 1.1, 0.8, 0.5, 0.45, 0.55, 0.65, 0.8, 1.3, 1.55, 1.6]},
    "backwater": {"label": "Backwaters",       "m": [1.4, 1.1, 0.95, 0.8, 0.7, 0.55, 0.7, 1.45, 1.2, 0.95, 1.1, 1.7]},
    "snow":      {"label": "Snow & valleys",   "m": [1.5, 1.35, 0.9, 1.3, 1.6, 1.4, 0.7, 0.6, 0.75, 0.85, 0.8, 1.35]},
    "high":      {"label": "High altitude",    "m": [0.2, 0.2, 0.35, 0.6, 1.3, 1.9, 2.1, 2.0, 1.5, 0.9, 0.35, 0.25]},
    "spiritual": {"label": "Pilgrimage",       "m": [1.25, 1.15, 1.3, 1.0, 0.85, 0.8, 0.75, 0.8, 0.95, 1.25, 1.3, 1.2]},
    "metro":     {"label": "Business metro",   "m": [0.95, 1.05, 1.1, 1.0, 0.95, 0.9, 0.95, 1.0, 1.05, 1.05, 1.0, 0.85]},
    "gulf":      {"label": "Gulf city",        "m": [1.5, 1.4, 1.25, 1.0, 0.7, 0.55, 0.55, 0.6, 0.8, 1.05, 1.3, 1.65]},
    "seasia":    {"label": "South-East Asia",  "m": [1.4, 1.25, 1.0, 0.85, 1.15, 1.25, 0.9, 0.85, 0.7, 0.85, 1.05, 1.5]},
    "island":    {"label": "Island escape",    "m": [1.45, 1.4, 1.3, 1.15, 0.8, 0.55, 0.55, 0.6, 0.7, 0.95, 1.2, 1.55]},
    "europe":    {"label": "Europe",           "m": [0.55, 0.6, 0.8, 1.0, 1.55, 1.75, 1.3, 1.1, 1.0, 1.25, 0.75, 1.15]},
    "medbeach":  {"label": "Mediterranean coast", "m": [0.45, 0.5, 0.7, 0.95, 1.3, 1.75, 2.0, 1.95, 1.4, 0.9, 0.5, 0.65]},
    "ski":       {"label": "Alps & ski",       "m": [1.7, 1.75, 1.3, 0.75, 0.55, 0.9, 1.3, 1.25, 0.8, 0.55, 0.65, 1.5]},
    "temperate": {"label": "Temperate city",   "m": [0.65, 0.7, 0.9, 1.0, 1.15, 1.35, 1.45, 1.4, 1.1, 1.0, 0.85, 1.05]},
    "temperate_s": {"label": "Southern hemisphere", "m": [1.45, 1.3, 1.1, 0.95, 0.75, 0.7, 0.8, 0.75, 0.85, 1.0, 1.1, 1.5]},
    "beach_s":   {"label": "Southern beach",   "m": [1.7, 1.45, 1.15, 0.9, 0.65, 0.55, 0.65, 0.6, 0.75, 0.95, 1.2, 1.95]},
    "tropical":  {"label": "Tropical",         "m": [1.35, 1.35, 1.2, 1.05, 0.85, 0.7, 0.75, 0.75, 0.75, 0.9, 1.05, 1.5]},
    "eastasia":  {"label": "East Asia",        "m": [0.8, 0.85, 1.1, 1.45, 1.15, 0.85, 1.0, 1.1, 0.9, 1.3, 1.25, 1.0]},
    "safari":    {"label": "Safari & wildlife", "m": [1.15, 1.0, 0.8, 0.6, 0.65, 0.95, 1.5, 1.75, 1.5, 1.05, 0.9, 1.15]},
}
SEGMENT_LABEL = {"business": "Business", "transit": "Airport & transit", "leisure": "Leisure", "air": "Air", "experience": "Experiences", "ground": "Ground"}

# id, name, region, country, lat, lon, type, popularity (1-5), price level (0.6-2.5), flight hub
DESTINATIONS = [
    ("goa", "Goa", "West India", "India", 15.30, 74.12, "beach", 5, 1.0, "DEL"),
    ("andaman", "Andaman Islands", "Bay of Bengal", "India", 11.62, 92.73, "island", 3, 1.4, "MAA"),
    ("pondicherry", "Puducherry", "South India", "India", 11.94, 79.81, "beach", 2, 0.8, "BLR"),
    ("gokarna", "Gokarna", "Karnataka", "India", 14.55, 74.32, "beach", 2, 0.7, "BOM"),
    ("manali", "Manali", "Himachal Pradesh", "India", 32.24, 77.19, "hills", 5, 0.8, "DEL"),
    ("shimla", "Shimla", "Himachal Pradesh", "India", 31.10, 77.17, "hills", 4, 0.75, "DEL"),
    ("mussoorie", "Mussoorie", "Uttarakhand", "India", 30.46, 78.07, "hills", 3, 0.8, "DEL"),
    ("darjeeling", "Darjeeling", "West Bengal", "India", 27.04, 88.26, "hills", 3, 0.7, "CCU"),
    ("jaipur", "Jaipur", "Rajasthan", "India", 26.91, 75.79, "heritage", 5, 0.9, "BOM"),
    ("udaipur", "Udaipur", "Rajasthan", "India", 24.59, 73.71, "heritage", 4, 1.2, "DEL"),
    ("jaisalmer", "Jaisalmer", "Rajasthan", "India", 26.92, 70.91, "heritage", 3, 0.9, "DEL"),
    ("agra", "Agra", "Uttar Pradesh", "India", 27.18, 78.01, "heritage", 4, 0.8, "BOM"),
    ("alleppey", "Alleppey", "Kerala", "India", 9.50, 76.34, "backwater", 4, 1.1, "BLR"),
    ("munnar", "Munnar", "Kerala", "India", 10.09, 77.06, "backwater", 3, 0.9, "BOM"),
    ("srinagar", "Srinagar", "Jammu & Kashmir", "India", 34.08, 74.80, "snow", 4, 1.0, "DEL"),
    ("gulmarg", "Gulmarg", "Jammu & Kashmir", "India", 34.05, 74.38, "snow", 3, 1.2, "DEL"),
    ("leh", "Leh-Ladakh", "Ladakh", "India", 34.15, 77.58, "high", 4, 1.0, "DEL"),
    ("varanasi", "Varanasi", "Uttar Pradesh", "India", 25.32, 83.01, "spiritual", 4, 0.7, "BOM"),
    ("rishikesh", "Rishikesh", "Uttarakhand", "India", 30.09, 78.27, "spiritual", 3, 0.7, "BOM"),
    ("amritsar", "Amritsar", "Punjab", "India", 31.63, 74.87, "spiritual", 3, 0.7, "BOM"),
    ("mumbai", "Mumbai", "Maharashtra", "India", 19.08, 72.88, "metro", 5, 1.3, "DEL"),
    ("delhi", "New Delhi", "Delhi", "India", 28.61, 77.21, "metro", 5, 1.1, "BOM"),
    ("bengaluru", "Bengaluru", "Karnataka", "India", 12.97, 77.59, "metro", 4, 1.1, "DEL"),
    ("dubai", "Dubai", "UAE", "UAE", 25.20, 55.27, "gulf", 5, 2.0, "DEL"),
    ("abudhabi", "Abu Dhabi", "UAE", "UAE", 24.45, 54.38, "gulf", 3, 1.9, "BOM"),
    ("bangkok", "Bangkok", "Thailand", "Thailand", 13.76, 100.50, "seasia", 5, 1.3, "DEL"),
    ("phuket", "Phuket", "Thailand", "Thailand", 7.88, 98.39, "seasia", 4, 1.5, "BOM"),
    ("bali", "Bali", "Indonesia", "Indonesia", -8.41, 115.19, "seasia", 4, 1.7, "BOM"),
    ("singapore", "Singapore", "Singapore", "Singapore", 1.35, 103.82, "seasia", 5, 2.2, "BOM"),
    ("maldives", "Maldives", "Indian Ocean", "Maldives", 3.20, 73.22, "island", 4, 2.5, "BOM"),
    ("mauritius", "Mauritius", "Indian Ocean", "Mauritius", -20.35, 57.55, "island", 3, 2.2, "BOM"),
    ("paris", "Paris", "France", "France", 48.86, 2.35, "europe", 4, 2.4, "DEL"),
    ("london", "London", "United Kingdom", "UK", 51.51, -0.13, "europe", 4, 2.5, "BOM"),
    ("interlaken", "Swiss Alps (Interlaken)", "Switzerland", "Switzerland", 46.69, 7.86, "europe", 3, 2.5, "BOM"),
]

AIRPORT = {"goa": "GOI", "andaman": "IXZ", "pondicherry": "PNY", "gokarna": "GOI", "manali": "KUU", "shimla": "SLV",
           "mussoorie": "DED", "darjeeling": "IXB", "jaipur": "JAI", "udaipur": "UDR", "jaisalmer": "JSA",
           "agra": "AGR", "alleppey": "COK", "munnar": "COK", "srinagar": "SXR", "gulmarg": "SXR", "leh": "IXL",
           "varanasi": "VNS", "rishikesh": "DED", "amritsar": "ATQ", "mumbai": "BOM", "delhi": "DEL",
           "bengaluru": "BLR", "dubai": "DXB", "abudhabi": "AUH", "bangkok": "BKK", "phuket": "HKT", "bali": "DPS",
           "singapore": "SIN", "maldives": "MLE", "mauritius": "MRU", "paris": "CDG", "london": "LHR",
           "interlaken": "ZRH"}

# product templates per destination type: (label, kind, share of destination demand, base nightly cost in Rs)
PRODUCT_TEMPLATES = {
    "beach":     [("Beachfront 5★ resort", "hotel", 0.30, 9000), ("Boutique 3★ hotel", "hotel", 0.45, 3200),
                  ("{hub}→{apt} seat block", "flight", 0.9, 5200), ("Water-sports & cruise pass", "activity", 0.8, 1400)],
    "island":    [("Overwater villa", "hotel", 0.25, 26000), ("Island 4★ resort", "hotel", 0.45, 9500),
                  ("{hub}→{apt} seat block", "flight", 0.9, 14000), ("Snorkel & ferry pass", "activity", 0.7, 2600)],
    "hills":     [("Valley-view 4★ resort", "hotel", 0.35, 4800), ("Cottage stay", "hotel", 0.45, 2400),
                  ("Volvo coach seats from {hub}", "transfer", 0.8, 1500), ("Snow point & rafting pass", "activity", 0.9, 950)],
    "snow":      [("Lake-view 4★ hotel", "hotel", 0.35, 5600), ("Houseboat / chalet", "hotel", 0.35, 4200),
                  ("{hub}→{apt} seat block", "flight", 0.85, 6500), ("Gondola & ski pass", "activity", 0.8, 2200)],
    "high":      [("Heritage 3★ hotel", "hotel", 0.4, 4200), ("Desert camp", "hotel", 0.35, 3600),
                  ("{hub}→{apt} seat block", "flight", 0.9, 7800), ("Bike & permit package", "activity", 0.6, 3500)],
    "heritage":  [("Palace 5★ hotel", "hotel", 0.25, 12000), ("Haveli 3★ hotel", "hotel", 0.45, 3400),
                  ("{hub}→{apt} seat block", "flight", 0.8, 4800), ("Fort & city tour pass", "activity", 0.9, 900)],
    "backwater": [("Premium houseboat", "hotel", 0.3, 9000), ("Plantation resort", "hotel", 0.4, 4600),
                  ("{hub}→{apt} seat block", "flight", 0.85, 5200), ("Kathakali & spice tour", "activity", 0.6, 800)],
    "spiritual": [("Riverside 4★ hotel", "hotel", 0.35, 4200), ("Ashram & guest house", "hotel", 0.5, 1600),
                  ("{hub}→{apt} seat block", "flight", 0.75, 4800), ("Aarti & temple tour pass", "activity", 0.9, 600)],
    "metro":     [("Boutique city hotel", "hotel", 0.4, 6200), ("Airport 3★ hotel", "hotel", 0.4, 4200),
                  ("{hub}→{apt} seat block", "flight", 1.0, 5600), ("City sightseeing pass", "activity", 0.4, 900)],
    "gulf":      [("Downtown 5★ hotel", "hotel", 0.3, 14000), ("City 4★ hotel", "hotel", 0.45, 7800),
                  ("{hub}→{apt} seat block", "flight", 0.9, 17500), ("Desert safari & theme parks", "activity", 0.85, 4200)],
    "seasia":    [("Resort 5★ hotel", "hotel", 0.3, 11000), ("City 3★ hotel", "hotel", 0.45, 4600),
                  ("{hub}→{apt} seat block", "flight", 0.9, 16000), ("Islands & attractions pass", "activity", 0.8, 3200)],
    "europe":    [("Central 4★ hotel", "hotel", 0.35, 17000), ("Boutique 3★ hotel", "hotel", 0.4, 11000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 52000), ("Rail & attractions pass", "activity", 0.7, 9000)],
}

PRODUCT_TEMPLATES.update({
    "medbeach":  [("Seafront 4★ hotel", "hotel", 0.4, 13000), ("Boutique guesthouse", "hotel", 0.4, 8000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 42000), ("Islands & boat-trip pass", "activity", 0.8, 5500)],
    "ski":       [("Alpine 4★ chalet hotel", "hotel", 0.4, 19000), ("Mountain guesthouse", "hotel", 0.4, 11000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 50000), ("Ski & cable-car pass", "activity", 0.9, 7500)],
    "temperate": [("City-centre 4★ hotel", "hotel", 0.4, 14000), ("Boutique 3★ hotel", "hotel", 0.4, 9000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 55000), ("City attractions pass", "activity", 0.75, 6000)],
    "temperate_s": [("City-centre 4★ hotel", "hotel", 0.4, 12000), ("Boutique 3★ hotel", "hotel", 0.4, 8000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 60000), ("Wine, coast & city pass", "activity", 0.75, 5500)],
    "beach_s":   [("Beachfront 4★ hotel", "hotel", 0.4, 11000), ("Boutique 3★ hotel", "hotel", 0.4, 7000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 48000), ("Coast & winelands pass", "activity", 0.8, 4500)],
    "tropical":  [("Resort 4★ hotel", "hotel", 0.4, 8000), ("City 3★ hotel", "hotel", 0.45, 4200),
                  ("{hub}→{apt} seat block", "flight", 0.85, 24000), ("Nature & culture pass", "activity", 0.8, 3000)],
    "eastasia":  [("City 4★ hotel", "hotel", 0.4, 12500), ("Business-class ryokan / boutique", "hotel", 0.35, 9000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 32000), ("Rail & sights pass", "activity", 0.8, 6500)],
    "safari":    [("Safari lodge", "hotel", 0.4, 18000), ("City 4★ hotel", "hotel", 0.4, 7000),
                  ("{hub}→{apt} seat block", "flight", 0.85, 36000), ("Game-drive & park pass", "activity", 0.9, 9000)],
})

# demand pattern of business trips: steady, dips in holiday weeks
BUSINESS_CURVE = [0.9, 1.05, 1.12, 1.02, 0.98, 0.95, 0.92, 0.95, 1.08, 1.1, 1.04, 0.75]
DEFAULT_BUSINESS = {"metro": 0.65, "gulf": 0.4, "seasia": 0.3, "europe": 0.35, "temperate": 0.35, "eastasia": 0.4,
                    "heritage": 0.2, "temperate_s": 0.3, "tropical": 0.2, "spiritual": 0.1}

MARGIN = {"hotel": (1.32, 1.24, 0.0), "flight": (1.18, 1.15, 0.15), "transfer": (1.3, 1.22, 0.1), "activity": (1.42, 1.36, 0.0)}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "city"


def destination(d: tuple) -> dict:
    did, name, region, country, lat, lon, typ, pop, price, hub = d
    return {"id": did, "name": name, "region": region, "country": country, "lat": lat, "lon": lon, "type": typ,
            "type_label": SEASONS[typ]["label"], "popularity": pop, "price_level": price, "hub": hub,
            "airport": AIRPORT.get(did, (name[:3]).upper()), "business": DEFAULT_BUSINESS.get(typ, 0.12),
            "featured": True, **_air(AIRPORT.get(did), hub)}


def _air(iata: str | None, hub: str) -> dict:
    """Airport size and flight distance for the hand-picked destinations, from the world airport table."""
    try:
        from .world import km, world
        w = world(); a = w.airports[w.iata[iata]]; h = w.origin(hub) or w.origin("DEL")
        return {"airport_name": a[1], "airport_size": a[6], "airport_lat": a[4], "airport_lon": a[5],
                "flight_km": round(km(h[1], h[2], a[4], a[5])), "hub_city": h[0], "cc": a[3],
                "hub_cc": h[3], "hub_lat": h[1], "hub_lon": h[2], "hub_weight": h[4]}
    except Exception:
        return {"flight_km": 1200}


@lru_cache(maxsize=1)
def _featured() -> tuple:
    return tuple(destination(d) for d in DESTINATIONS)


def all_destinations() -> list[dict]:
    return [dict(d) for d in _featured()]


def find(did: str) -> dict | None:
    return next((d for d in all_destinations() if d["id"] == did), None)


def custom_destination(name: str, typ: str, popularity: int = 3, price_level: float = 1.0,
                       hub: str = "DEL", lat: float | None = None, lon: float | None = None,
                       airport: str | None = None) -> dict:
    if typ not in SEASONS:
        raise ValueError(f"type must be one of {sorted(SEASONS)}")
    popularity = int(min(max(popularity, 1), 5))
    price_level = float(min(max(price_level, 0.4), 3.0))
    clean = re.sub(r"[^A-Za-z]", "", name).upper()
    return {"id": "custom-" + slug(name), "name": name.strip()[:40] or "New city", "region": "Custom destination",
            "country": "", "lat": lat, "lon": lon, "type": typ, "type_label": SEASONS[typ]["label"],
            "popularity": popularity, "price_level": price_level, "hub": hub.upper()[:3] or "DEL",
            "airport": (airport or clean[:3] or "NEW").upper()[:3], "custom": True}


def _blend(a: list, b: list, w: float) -> list:
    return [round(x * (1 - w) + y * w, 3) for x, y in zip(a, b)]


def _r50(x: float) -> int:
    return int(round(x / 50) * 50)


def flight_cost(dest: dict) -> int:
    km = float(dest.get("flight_km") or 1200)
    domestic = dest.get("cc", "IN") == dest.get("hub_cc", "IN")
    fare = 1900 + 4.1 * km if domestic else 5200 + 4.4 * km
    return _r50(min(fare, 95000))


def products_for(dest: dict) -> list[dict]:
    """The pre-buyable products for a destination: business, airport and leisure hotels, a flight block
    from the Indian hub, and an experience pass, each with its own price, size and season."""
    typ = dest["type"]
    leisure = SEASONS[typ]["m"]
    b = float(dest.get("business", DEFAULT_BUSINESS.get(typ, 0.12)))
    base = {1: 25, 2: 40, 3: 60, 4: 85, 5: 115}[dest["popularity"]]
    price = dest["price_level"]
    tpl = PRODUCT_TEMPLATES.get(typ, PRODUCT_TEMPLATES["temperate"])
    hotels = [t for t in tpl if t[1] == "hotel"]
    act = next(t for t in tpl if t[1] == "activity")
    apt, hub = dest.get("airport", "NEW"), dest.get("hub", "DEL")
    city = dest["name"].split(" (")[0]
    out = []

    def add(name, kind, segment, weekly, cost, season, fest, noise=0.18):
        sell_m, live_m, salvage = MARGIN[kind]
        cost = _r50(cost)
        out.append({"name": name, "kind": kind, "segment": segment, "base": max(8, round(weekly)), "unit_cost": cost,
                    "sell_price": _r50(cost * sell_m), "live_buy_cost": _r50(cost * live_m), "salvage_share": salvage,
                    "season": season, "fest": fest, "noise": noise})

    if b >= 0.18:
        add(f"{city} business 4★ hotel" if typ != "metro" else f"{city} business 5★ hotel", "hotel", "business",
            base * (0.25 + 0.75 * b), 6800 * price * (1.15 if typ == "metro" else 1), BUSINESS_CURVE, -0.35, 0.12)
    if dest.get("airport_size", 3) >= 2 and (b >= 0.3 or dest.get("airport_km", 99) <= 25):
        add(f"Airport hotel · {apt}", "hotel", "transit", base * (0.14 + 0.32 * b), 4300 * price,
            _blend(leisure, BUSINESS_CURVE, 0.55), 0.15, 0.14)
    lt = hotels[0]
    add(lt[0], "hotel", "leisure", base * lt[2] * (1.25 - b), lt[3] * price, leisure, None)
    if b < 0.18 and len(hotels) > 1:
        add(hotels[1][0], "hotel", "leisure", base * hotels[1][2] * 1.1, hotels[1][3] * price, leisure, None)
    if float(dest.get("flight_km") or 1000) > 300:
        add(f"{hub}→{apt} seat block", "flight", "air", base * 1.35 * float(dest.get("hub_weight", 1.0)), flight_cost(dest), _blend(leisure, BUSINESS_CURVE, 0.3 + 0.4 * b), 0.8)
    else:
        add(f"Rail & coach seats from {dest.get('hub_city', hub)}", "transfer", "ground", base * 1.2, 1500 * max(price, 0.8),
            _blend(leisure, BUSINESS_CURVE, 0.3), 0.8)
    if len(out) < 5:
        add(act[0], "activity", "experience", base * act[2] * 1.5 * (1 - 0.5 * b), act[3] * price, leisure, None)
    return out


def seed_for(did: str) -> int:
    return int(hashlib.sha256(did.encode()).hexdigest()[:8], 16)
