"""Build STOCKSHOCK's world data (run once; outputs are committed).

Inputs (open data, cloned into ../ds):
  GeoNames cities via lutangar/cities.json (CC-BY 4.0), GeoNames cities >15k via datasets/world-cities,
  Natural Earth populated places + coastline (public domain), OurAirports (public domain).
Outputs:
  backend/stockshock/geo/cities.tsv.gz   every city: name, admin1, country, lat, lon, population estimate, tier,
                                 capital flag, nearest scheduled airport and distance, distance to coast
  backend/stockshock/geo/airports.tsv    scheduled-service airports with an IATA code
  backend/stockshock/geo/countries.tsv   ISO code, name, continent
  frontend/data/top.json           the ~3,000 biggest cities, for the map and instant search
"""
import csv, gzip, json, os, sys, unicodedata
import numpy as np
from scipy.spatial import cKDTree

DS = sys.argv[1] if len(sys.argv) > 1 else "../ds"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "backend", "stockshock", "geo"); os.makedirs(OUT, exist_ok=True)
R = 6371.0

def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]

def chord_km(d):
    return 2 * R * np.arcsin(np.clip(d / 2, 0, 1))

def ascii_(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()

# countries
countries = {r["code"]: (r["name"], r["continent"]) for r in csv.DictReader(open(f"{DS}/oa/countries.csv", encoding="utf-8"))}

# airports with scheduled service and an IATA code
SIZE = {"large_airport": 3, "medium_airport": 2, "small_airport": 1}
apts = []
for r in csv.DictReader(open(f"{DS}/oa/airports.csv", encoding="utf-8")):
    if r["scheduled_service"] == "yes" and len(r["iata_code"]) == 3 and r["type"] in SIZE:
        apts.append((r["iata_code"], r["name"], r["municipality"], r["iso_country"],
                     float(r["latitude_deg"]), float(r["longitude_deg"]), SIZE[r["type"]]))
apts.sort(key=lambda a: (-a[6], a[0]))
A = np.array([[a[4], a[5]] for a in apts]); A_size = np.array([a[6] for a in apts])
atree = cKDTree(xyz(A[:, 0], A[:, 1]))
print("airports", len(apts))

# cities
admin1 = {r["code"]: r["name"] for r in json.load(open(f"{DS}/lc/admin1.json", encoding="utf-8"))}
raw = json.load(open(f"{DS}/lc/cities.json", encoding="utf-8"))
cities = []
for c in raw:
    try:
        cities.append([c["name"], admin1.get(f'{c["country"]}.{c["admin1"]}', ""), c["country"], float(c["lat"]), float(c["lng"]), 0, 1, 0])
    except (ValueError, KeyError):
        pass
print("geonames cities", len(cities))

# cities over 15k people (tier 2)
name2cc = {v[0]: k for k, v in countries.items()}
name2cc.update({"Bolivia, Plurinational State of": "BO", "Brunei Darussalam": "BN", "Cabo Verde": "CV", "Congo": "CG",
                "Congo, The Democratic Republic of the": "CD", "Czechia": "CZ", "Iran, Islamic Republic of": "IR",
                "Korea, Democratic People's Republic of": "KP", "Korea, Republic of": "KR", "Lao People's Democratic Republic": "LA",
                "Macao": "MO", "Moldova, Republic of": "MD", "Palestine, State of": "PS", "Russian Federation": "RU",
                "Syrian Arab Republic": "SY", "Taiwan, Province of China": "TW", "Tanzania, United Republic of": "TZ",
                "Türkiye": "TR", "Venezuela, Bolivarian Republic of": "VE", "Viet Nam": "VN", "Micronesia, Federated States of": "FM",
                "Sao Tome and Principe": "ST", "Virgin Islands, British": "VG", "Virgin Islands, U.S.": "VI"})
big = set()
for r in csv.DictReader(open(f"{DS}/wc/data/world-cities.csv", encoding="utf-8")):
    cc = name2cc.get(r["country"])
    if cc:
        big.add((ascii_(r["name"]), cc))
for c in cities:
    if (ascii_(c[0]), c[2]) in big:
        c[6] = 2; c[5] = 30000

# Natural Earth places: real populations and capitals (tier 3)
C = np.array([[c[3], c[4]] for c in cities]); ctree = cKDTree(xyz(C[:, 0], C[:, 1]))
ne = json.load(open(f"{DS}/ne/geojson/ne_10m_populated_places_simple.geojson", encoding="utf-8"))["features"]
added = 0
for f in ne:
    p = f["properties"]; lat, lon = p["latitude"], p["longitude"]
    cap = 2 if p["adm0cap"] else (1 if p["featurecla"] and "Admin-1 capital" in p["featurecla"] else 0)
    pop = int(p["pop_max"] or 0)
    ds, ix = ctree.query(xyz([lat], [lon])[0], k=250)
    b = ascii_(p["nameascii"] or p["name"])
    near = [(chord_km(d), i) for d, i in zip(ds, ix) if chord_km(d) <= 40]
    best = next((i for k, i in near if ascii_(cities[i][0]) == b), None)
    if best is None:
        best = next((i for k, i in near if k <= 25 and (ascii_(cities[i][0]).startswith(b) or b.startswith(ascii_(cities[i][0])))), None)
    if best is None and near and near[0][0] < 6:
        best = near[0][1]
    if best is not None:
        c = cities[best]; c[5] = max(c[5], pop); c[6] = 3; c[7] = max(c[7], cap)
    else:
        cities.append([p["name"], p["adm1name"] or "", p["iso_a2"] if p["iso_a2"] and p["iso_a2"] != "-99" else "", lat, lon, pop, 3, cap]); added += 1
print("natural earth added", added)

C = np.array([[c[3], c[4]] for c in cities]); X = xyz(C[:, 0], C[:, 1])

# nearest scheduled airport, preferring bigger ones that are still close
dd, ii = atree.query(X, k=12)
apt_ix, apt_km = [], []
for drow, irow in zip(dd, ii):
    km = chord_km(drow)
    best, bscore = int(irow[0]), 1e9
    for k, i in zip(km, irow):
        s = A_size[i]
        lim = {3: 140, 2: 90, 1: 60}[s]
        score = k + {3: 0, 2: 45, 1: 80}[s] if k <= lim else 1e6 + k
        if score < bscore: best, bscore = int(i), score
    apt_ix.append(best); apt_km.append(round(float(chord_km(np.linalg.norm(X[len(apt_km)] - xyz([A[best, 0]], [A[best, 1]])[0]))), 0))

# distance to the coastline
pts = []
for f in json.load(open(f"{DS}/ne/geojson/ne_10m_coastline.geojson", encoding="utf-8"))["features"]:
    g = f["geometry"]; lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
    for ln in lines:
        arr = np.array(ln)
        pts.append(arr)
P = np.vstack(pts); coast = cKDTree(xyz(P[:, 1], P[:, 0]))
coast_km = chord_km(coast.query(X)[0])
print("coast points", len(P))

with gzip.open(os.path.join(OUT, "cities.tsv.gz"), "wt", encoding="utf-8", compresslevel=9) as f:
    for c, ai, ak, ck in zip(cities, apt_ix, apt_km, coast_km):
        name = c[0].replace("\t", " ")
        f.write(f"{name}\t{c[1]}\t{c[2]}\t{c[3]:.4f}\t{c[4]:.4f}\t{c[5]}\t{c[6]}\t{c[7]}\t{ai}\t{int(ak)}\t{int(round(ck))}\n")
with open(os.path.join(OUT, "airports.tsv"), "w", encoding="utf-8") as f:
    for a in apts:
        f.write("\t".join(map(str, a)) + "\n")
with open(os.path.join(OUT, "countries.tsv"), "w", encoding="utf-8") as f:
    for k, (n, cont) in sorted(countries.items()):
        f.write(f"{k}\t{n}\t{cont}\n")

order = sorted(range(len(cities)), key=lambda i: (-cities[i][6], -cities[i][5]))
top = []
for i in order[:3200]:
    c = cities[i]
    top.append([i, c[0], c[2], round(c[3], 3), round(c[4], 3), c[5], apts[apt_ix[i]][0]])
os.makedirs(os.path.join(ROOT, "frontend", "data"), exist_ok=True)
json.dump(top, open(os.path.join(ROOT, "frontend", "data", "top.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("cities", len(cities), "top", len(top))

# land dots for the hero globe (every ~1.8 degrees, latitude-corrected spacing)
from matplotlib.path import Path
land = json.load(open(f"{DS}/ne/geojson/ne_110m_land.geojson", encoding="utf-8"))["features"]
polys = []
for f in land:
    g = f["geometry"]; rings = g["coordinates"] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
    if g["type"] == "Polygon": rings = [rings[0]]
    for r in rings: polys.append(Path(np.array(r)))
dots = []
step = 1.8
for lat in np.arange(-58, 84, step):
    n = max(1, int(360 * np.cos(np.radians(lat)) / step))
    lons = np.linspace(-180, 180, n, endpoint=False)
    P = np.c_[lons, np.full(n, lat)]
    inside = np.zeros(n, bool)
    for pth in polys: inside |= pth.contains_points(P)
    dots += [[round(float(lat), 1), round(float(lo), 1)] for lo in lons[inside]]
json.dump(dots, open(os.path.join(ROOT, "frontend", "data", "globe.json"), "w"), separators=(",", ":"))
print("globe dots", len(dots))
