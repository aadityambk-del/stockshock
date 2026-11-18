"""Every city in the world: search, nearest city to a map click, and a destination profile.

Data (built by tools/build_world.py from GeoNames, Natural Earth and OurAirports) lives in stockshock/geo.
A profile turns a city into what the planner needs: a season pattern, how much of its travel is business
vs leisure, a price level, the nearest scheduled airport (no codes to type) and the Indian hub to fly from.
"""
from __future__ import annotations

import bisect
import gzip
import math
import os
import unicodedata
from functools import lru_cache

GEO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo")
HUBS = {"DEL": ("New Delhi", 28.5562, 77.1000), "BOM": ("Mumbai", 19.0896, 72.8656),
        "BLR": ("Bengaluru", 13.1986, 77.7066), "MAA": ("Chennai", 12.9941, 80.1709),
        "CCU": ("Kolkata", 22.6547, 88.4467), "HYD": ("Hyderabad", 17.2403, 78.4294)}


def fold(s: str) -> str:
    if s.isascii():
        return s.lower().strip()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()


def km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(a)))


class World:
    def __init__(self):
        self.countries = {}
        for ln in open(os.path.join(GEO, "countries.tsv"), encoding="utf-8"):
            cc, name, cont = ln.rstrip("\n").split("\t")
            self.countries[cc] = (name, cont)
        self.airports = []
        for ln in open(os.path.join(GEO, "airports.tsv"), encoding="utf-8"):
            iata, name, city, cc, lat, lon, size = ln.rstrip("\n").split("\t")
            self.airports.append((iata, name, city, cc, float(lat), float(lon), int(size)))
        self.iata = {a[0]: i for i, a in enumerate(self.airports)}
        self.cities = []
        with gzip.open(os.path.join(GEO, "cities.tsv.gz"), "rt", encoding="utf-8") as f:
            for ln in f:
                n, a1, cc, lat, lon, pop, tier, cap, ai, ak, ck = ln.rstrip("\n").split("\t")
                self.cities.append((n, a1, cc, float(lat), float(lon), int(pop), int(tier), int(cap), int(ai), int(ak), int(ck)))
        # search index: (folded name, rank, id), sorted by name
        def rank(c):
            return -(c[6] * 1e9 + c[5] + c[7] * 2e5)
        self.index = sorted((fold(c[0]), rank(c), i) for i, c in enumerate(self.cities))
        self.keys = [k[0] for k in self.index]
        # coarse grid for nearest-city lookups
        self.grid = {}
        for i, c in enumerate(self.cities):
            self.grid.setdefault((int(c[3] // 2), int(c[4] // 2)), []).append(i)

    # ---------- lookups ----------
    def search(self, q: str, limit: int = 12) -> list[dict]:
        q = fold(q)
        if not q:
            return []
        for old, new in ALIASES.items():
            if q.startswith(old) or (len(q) >= 3 and old.startswith(q)):
                q = new
                break
        parts = [p.strip() for p in q.split(",")]
        name, rest = parts[0], (parts[1] if len(parts) > 1 else "")
        out = []
        lo = bisect.bisect_left(self.keys, name)
        hi = bisect.bisect_left(self.keys, name + "￿")
        hits = self.index[lo:hi]
        if rest:
            hits = [h for h in hits if rest in fold(self.cities[h[2]][1] + " " + self.countries.get(self.cities[h[2]][2], ("",))[0] + " " + self.cities[h[2]][2])]
        hits = sorted(hits, key=lambda h: h[1] - (5e8 if h[0] == name else 0))[: limit * 3]
        seen = set()
        for h in hits:
            c = self.cities[h[2]]
            key = (fold(c[0]), c[2], c[1])
            if key in seen:
                continue
            seen.add(key)
            out.append(self.brief(h[2]))
            if len(out) >= limit:
                break
        if len(out) < limit and len(q) >= 3 and len(parts) == 1:   # airport code or airport/city name
            a = self.iata.get(q.upper())
            if a is not None:
                i = self.nearest(self.airports[a][4], self.airports[a][5], prefer_big=True)
                if i is not None and all(o["id"] != i for o in out):
                    out.insert(0, self.brief(i))
        return out[:limit]

    def nearest(self, lat: float, lon: float, prefer_big: bool = False) -> int | None:
        best, bs = None, 1e18
        gy, gx = int(lat // 2), int(lon // 2)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for i in self.grid.get((gy + dy, gx + dx), ()):
                    c = self.cities[i]
                    d = km(lat, lon, c[3], c[4])
                    # a click lands on the place people mean: a big city 20 km away beats a village next door
                    s = d - (c[6] * 8 + math.log10(c[5] + 10) * 6 if prefer_big else c[6] * 4 + math.log10(c[5] + 10) * 3)
                    if s < bs:
                        best, bs = i, s
        return best

    def origin(self, code: str):
        """(city, lat, lon, country) for an origin airport: one of the six Indian hubs or any scheduled IATA airport."""
        code = (code or "").upper()
        if code in HUBS:
            h = HUBS[code]
            return (h[0], h[1], h[2], "IN", 1.0)
        a = self.iata.get(code)
        if a is None:
            return None
        ap = self.airports[a]
        # demand on a route scales with the origin: a big hub fills a seat block, a small airport fills a few seats
        return (ap[2] or ap[1], ap[4], ap[5], ap[3], {3: 0.75, 2: 0.35, 1: 0.15}[ap[6]])

    def brief(self, i: int) -> dict:
        c = self.cities[i]
        a = self.airports[c[8]]
        return {"id": f"w{i}", "name": c[0], "region": c[1], "cc": c[2],
                "country": self.countries.get(c[2], (c[2],))[0], "lat": c[3], "lon": c[4], "population": c[5],
                "airport": a[0], "airport_name": a[1], "airport_km": c[9]}

    def get(self, wid: str) -> int:
        try:
            i = int(str(wid).lstrip("w"))
            self.cities[i]
            return i
        except (ValueError, IndexError):
            raise ValueError(f"unknown city '{wid}'")

    # ---------- profile ----------
    def profile(self, i: int, hub: str | None = None) -> dict:
        n, a1, cc, lat, lon, pop, tier, cap, ai, akm, ckm = self.cities[i]
        cont = self.countries.get(cc, ("", "AS"))[1]
        apt = self.airports[ai]
        typ = infer_type(n, a1, cc, cont, lat, lon, pop, ckm)
        pop_est = pop or (30000 if tier >= 2 else 6000)
        business = business_weight(pop_est, cap, typ)
        popularity = 5 if pop_est >= 5e6 else 4 if pop_est >= 1.5e6 else 3 if pop_est >= 4e5 else 2 if pop_est >= 8e4 else 1
        if typ in RESORT_TYPES | {"spiritual", "heritage"} and popularity < 3:
            popularity += 1                       # small resort, hill and pilgrimage towns still pull visitors
        price = price_level(cc, cont, pop_est)
        hub = (hub or "").upper()
        h = self.origin(hub) if hub else None
        if h is None:
            hub = pick_hub(cc, lat, lon); h = self.origin(hub)
        flight_km = km(h[1], h[2], apt[4], apt[5])
        return {
            "id": f"w{i}", "name": n, "region": a1 or self.countries.get(cc, ("",))[0], "country": self.countries.get(cc, (cc,))[0],
            "cc": cc, "lat": lat, "lon": lon, "type": typ, "popularity": popularity, "price_level": price, "hub": hub,
            "hub_city": h[0], "airport": apt[0], "airport_name": apt[1], "airport_km": akm, "airport_size": apt[6],
            "airport_lat": apt[4], "airport_lon": apt[5], "flight_km": round(flight_km), "business": round(business, 2),
            "hub_cc": h[3], "hub_lat": h[1], "hub_lon": h[2], "hub_weight": h[4],
            "coast_km": ckm, "population": pop, "world": True,
        }


ALIASES = {"gurgaon": "gurugram", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata", "bangalore": "bengaluru",
           "panaji": "panjim", "nyc": "new york city", "new york": "new york city", "cochin": "kochi", "trivandrum": "thiruvananthapuram",
           "pondicherry": "puducherry", "benares": "varanasi", "banaras": "varanasi", "saigon": "ho chi minh",
           "peking": "beijing", "la ": "los angeles", "sf": "san francisco", "rome": "rome", "mysore": "mysuru"}

RESORT_TYPES = {"beach", "island", "hills", "snow", "high", "backwater", "safari", "ski"}

GULF = {"AE", "QA", "SA", "OM", "BH", "KW", "JO"}
DESERT = {"EG", "MA", "TN", "DZ", "LY", "IL", "PS"}
SEASIA = {"TH", "MY", "ID", "VN", "PH", "KH", "LA", "MM", "SG", "BN", "TL"}
SOUTH_ASIA_TROP = {"LK", "BD", "NP", "BT", "PK"}
EAST_ASIA = {"JP", "KR", "CN", "TW", "HK", "MO", "MN", "KP"}
SAFARI = {"KE", "TZ", "UG", "RW", "BW", "NA", "ZW", "ZM", "ZA"}
ISLANDS = {"MV", "MU", "SC", "FJ", "PF", "BS", "BB", "JM", "LC", "AG", "KN", "VC", "GD", "TC", "KY", "VG", "VI", "AW", "CW",
           "MP", "GU", "PW", "MH", "CK", "WS", "TO", "NC", "RE", "KM", "CV", "ST", "VU", "SB", "KI", "TV", "NR", "MQ", "GP",
           "BM", "BQ", "SX", "MF", "BL", "AI", "MS", "DM", "YT", "MT", "CY"}
CARIB_COAST = {"MX", "DO", "CU", "PR", "BZ", "CR", "PA", "CO", "HN", "GT", "NI", "HT"}
ALPINE = {"CH", "AT", "LI", "AD"}
PILGRIM = {"varanasi", "rishikesh", "haridwar", "amritsar", "tirupati", "shirdi", "puri", "madurai", "rameswaram",
           "bodh gaya", "ayodhya", "mathura", "vrindavan", "ujjain", "dwarka", "somnath", "katra", "pushkar", "ajmer",
           "kedarnath", "badrinath", "nashik", "guruvayur", "kanchipuram", "mecca", "makkah", "medina", "lourdes",
           "jerusalem", "vatican city", "lumbini"}
HILL_STATES = {"himachal pradesh", "uttarakhand", "sikkim", "meghalaya", "arunachal pradesh", "nagaland", "mizoram"}


def infer_type(name, admin1, cc, cont, lat, lon, pop, coast_km) -> str:
    f, a = fold(name), fold(admin1)
    if f in PILGRIM:
        return "spiritual"
    if cc == "IN":
        if lat > 32.3 and lon > 75.3 and "ladakh" in a or (lat > 33.6 and lon > 76):
            return "high"
        if "kashmir" in a or "jammu" in a:
            return "snow" if lat > 33.5 else "hills"
        if a in HILL_STATES or (a == "west bengal" and lat > 26.8) or (a == "tamil nadu" and f in ("ooty", "ootacamund", "kodaikanal")):
            return "hills"
        if a == "kerala":
            return "beach" if coast_km <= 3 and f in ("kovalam", "varkala") else "backwater"
        if a == "rajasthan" or f in ("agra", "khajuraho", "hampi", "mysore", "mysuru", "aurangabad", "orchha"):
            return "heritage"
        if coast_km <= 8 and pop < 3e6:
            return "beach"
        if pop >= 1.5e5:
            return "metro"
        return "heritage"
    if cc in ISLANDS:
        return "island"
    if cc in GULF:
        return "gulf"
    if cc in DESERT:
        return "gulf"
    if cc in SEASIA:
        return "seasia"
    if cc in SOUTH_ASIA_TROP:
        return "hills" if (cc in ("NP", "BT") or lat > 33) else "tropical"
    if cc in EAST_ASIA:
        return "eastasia"
    if cc in SAFARI:
        return "beach_s" if (cc == "ZA" and coast_km <= 15) else "safari"
    if cc in ALPINE or (cont == "EU" and cc in ("FR", "IT", "DE") and 45.5 <= lat <= 47.8 and 5.8 <= lon <= 13.5 and coast_km > 120):
        return "ski"
    if cont == "EU" or cc in ("TR", "GE", "AM", "AZ", "RU", "UA", "BY", "KZ", "UZ", "KG", "TJ", "TM"):
        if coast_km <= 15 and lat < 44 and cont == "EU":
            return "medbeach"
        return "europe"
    if cc in CARIB_COAST and coast_km <= 25:
        return "island"
    if cont == "NA":
        if lat < 31 and coast_km <= 25:
            return "island"
        return "temperate"
    if cont == "SA":
        return "temperate_s" if lat < -20 else "tropical"
    if cont == "OC":
        if lat > -23:
            return "tropical" if coast_km > 25 else "island"
        return "temperate_s"
    if cont == "AF":
        return "tropical" if abs(lat) < 18 else ("temperate_s" if lat < 0 else "gulf")
    if abs(lat) < 20:
        return "tropical" if coast_km > 10 else "beach"
    return "temperate" if lat > 0 else "temperate_s"


def business_weight(pop: int, cap: int, typ: str) -> float:
    b = 0.75 if pop >= 8e6 else 0.65 if pop >= 3e6 else 0.5 if pop >= 1e6 else 0.36 if pop >= 3e5 else 0.24 if pop >= 1e5 else 0.12
    b += 0.1 if cap == 2 else 0.04 if cap == 1 else 0
    if typ in RESORT_TYPES or typ == "spiritual":
        b *= 0.55
    if typ == "metro":
        b = max(b, 0.6)
    return min(b, 0.85)


PRICE = {"IN": 1.0, "NP": 0.8, "LK": 0.9, "BD": 0.8, "PK": 0.8, "BT": 1.4, "MV": 2.5, "TH": 1.25, "VN": 1.0, "ID": 1.3,
         "MY": 1.2, "PH": 1.2, "KH": 1.0, "LA": 0.9, "SG": 2.2, "HK": 2.2, "JP": 2.0, "KR": 1.8, "CN": 1.5, "TW": 1.6,
         "AE": 2.0, "QA": 2.1, "SA": 1.8, "OM": 1.7, "BH": 1.7, "KW": 1.8, "JO": 1.5, "EG": 1.1, "TR": 1.4, "IL": 2.3,
         "GB": 2.5, "FR": 2.3, "DE": 2.2, "IT": 2.2, "ES": 2.0, "PT": 1.8, "NL": 2.3, "BE": 2.2, "CH": 2.8, "AT": 2.3,
         "IE": 2.4, "IS": 2.8, "NO": 2.7, "SE": 2.4, "DK": 2.5, "FI": 2.3, "GR": 1.9, "CZ": 1.7, "PL": 1.6, "HU": 1.6,
         "HR": 1.8, "RU": 1.5, "US": 2.4, "CA": 2.2, "MX": 1.6, "BR": 1.6, "AR": 1.5, "CL": 1.6, "PE": 1.4, "CO": 1.4,
         "AU": 2.3, "NZ": 2.2, "ZA": 1.5, "KE": 1.6, "TZ": 1.8, "MA": 1.3, "MU": 2.2, "SC": 2.6, "FJ": 2.0}
CONT_PRICE = {"EU": 2.0, "NA": 2.2, "OC": 2.1, "AS": 1.3, "AF": 1.4, "SA": 1.4, "AN": 2.5}


def price_level(cc: str, cont: str, pop: int) -> float:
    p = PRICE.get(cc, CONT_PRICE.get(cont, 1.4))
    return round(p * (1.12 if pop >= 3e6 else 1.0), 2)


def pick_hub(cc: str, lat: float, lon: float) -> str:
    if cc == "IN":
        d = {h: km(v[1], v[2], lat, lon) for h, v in HUBS.items()}
        far = [h for h in ("DEL", "BOM", "BLR") if d[h] > 450]
        return far[0] if far else "HYD"
    if 10 <= lat <= 40 and 30 <= lon <= 62:      # Gulf, Middle East, East Africa coast: busiest from Mumbai
        return "BOM"
    if lon > 88 and lat < 30:                    # South-East Asia: Kolkata/Chennai side
        return "MAA" if lat < 8 else "CCU" if lat > 18 else "BOM"
    return "DEL"


@lru_cache(maxsize=1)
def world() -> World:
    return World()
