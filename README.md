# STOCKSHOCK v4 · inventory command centre · Inventory Planner

**VoyageHack 4.0 · Inventory Optimization · Team Table For Two (Aaradhya Jain & Aaditya Kore)**

STOCKSHOCK forecasts travel demand and invests a pre-buy budget across hotels, flights, transfers and activities
like a risk-managed portfolio. This repo is the full web app: a REST API plus an animated website.

- **Command centre**: a landing page with a draggable globe, then a console with separate Flights (any origin → any destination), Hotels (business / airport / leisure), Experiences and Orders modules
- **Fast**: one forecast per city window, cached; risk, budget and module switches re-solve in ~0.1 s
- **Every city on Earth**: 171,567 cities (GeoNames + Natural Earth) with instant search by name, old name or airport code
- **No airport codes**: the nearest scheduled airport (4,010 from OurAirports) and the best Indian hub are picked automatically
- **Per-city profile**: season pattern from climate/region, business vs leisure mix from population and capital status, price level by country
- **Five products per city**: business hotel, airport hotel, leisure hotel/resort, hub→airport flight block (fare from distance), experience pass
- Low / likely / high demand forecast per product and week (gradient-boosted quantile models); business demand dips in holiday weeks, leisure peaks
- **Risk appetite that really changes the plan**: careful / balanced / bold compared side by side on every request
- Buy plan from an optimiser that tests 60 demand scenarios: max profit within budget, capped worst-5% loss
- BUY / WAIT / SKIP per line with the reason, and one-click booking into an Orders desk (confirm / cancel)
- Proof on every request: the same weeks replayed one year earlier against today's rule
- Risk-return curve ("inventory as an investment portfolio")

**New in v4 (covers every objective in TBO's brief, plus more)**
- **Portfolio optimiser**: one maximum budget in ₹ split across up to 8 destinations, products and weeks in a single solve, with ROI, spend by destination and by week, and a one-click "book whole portfolio"
- **Opportunity radar**: every featured destination ranked by profit opportunity and risk, with live alerts (sell-outs last year, search surges, cheap buy weeks)
- **Rupee budgets**: plan to a hard ₹ ceiling (or % of today's spend); today's rule is held to the same ceiling for a fair comparison
- **Market signals**: search momentum, look-to-book ratio, cancellation rate, last year's sell-out weeks, buy-price index
- **Dynamic pricing**: recommended sell price per product-week from price elasticity (premium in hot weeks, discount in quiet ones), shown against the rate card
- **Buy-price timing**: seasonal procurement prices, with the cheapest week to buy each product
- **Cancellations netted out** of demand (per product type, higher for business travel)
- **Stress test**: profit if demand lands 30% below to 30% above the forecast, against today's rule
- **Safety net**: if a solve would ever do worse than today's rule on the same scenarios, the engine falls back to it
- Actions read as BUY / LOCK+LIVE (lock part now, buy the rest live) / LIVE ONLY (buy nothing in advance)

Demand history is simulated because TBO's booking data is not public. Swap `stockshock/data.py:history()`
for a reader of TBO's export and everything else keeps working.

## Run it on your computer

```
pip install numpy pandas scipy scikit-learn
python backend/dev_server.py
```
Open http://localhost:8000. (`dev_server.py` needs nothing beyond the four libraries above.)

With FastAPI (adds interactive API docs at /docs):
```
pip install -r requirements.txt
uvicorn app:app --reload
```

## Put it online (free)

**Vercel**: push to GitHub; Vercel picks up the root `app.py` (which loads `backend/main.py`) and `requirements.txt`.

**Render**
1. Copy `others/render.yaml` to the repo root and push to GitHub.
2. On render.com: **New → Blueprint**, pick the repository. Render reads `render.yaml` and deploys.
3. Your site is live at `https://<service-name>.onrender.com`. The free plan sleeps when idle; the first visit
   after a nap takes ~30-50 s, and the site shows "Waking the server up" meanwhile.

**Docker / Hugging Face Spaces**: `docker build -f others/Dockerfile .`; it serves on port 7860.

## API

| Method | Path | What it returns |
|---|---|---|
| GET | `/api/catalog` | featured destinations, season types, Indian hubs |
| GET | `/api/search?q=kyoto` | any city (or airport code), ranked by size |
| GET | `/api/nearest?lat=46&lon=7.7` | the city nearest to a coordinate |
| GET | `/api/city?id=w95441` | destination profile: season, business mix, airport, hub, prices |
| GET | `/api/plan?city=w95441&risk=bold&kinds=hotel` | plan for any city; `kinds` = flight, hotel, activity, transfer; `origin=LHR` sets the flight origin |
| GET | `/api/replay?city=w95441` | proof: same weeks a year earlier, scored on what sold |
| GET | `/api/plan?dest=goa&weeks=8&budget=100&risk=balanced` | forecast, buy plan, KPIs, last-year replay |
| POST | `/api/plan` | same, for a custom city: `{"custom": {"name": "Coorg", "type": "hills", "popularity": 3}}` |
| GET/POST | `/api/frontier` | best expected profit at each risk level |
| GET | `/api/portfolio?ids=goa,dubai,w95441&budget_inr=30000000&risk=balanced` | one ₹ budget across several destinations |
| GET | `/api/radar?kinds=hotel` | destinations ranked by opportunity, plus alerts |

Plan, replay and frontier also take `budget_inr` (a hard ₹ cap) and `kinds`.

`risk` is `careful`, `balanced` or `bold`. `budget` is a % of what today's rule (pre-buy last year's monthly
average) would spend.

## Folder layout

```
app.py              entry point for Vercel / uvicorn (loads backend/main.py)
requirements.txt    Python dependencies
frontend/           the website: index.html, style.css, app.js, data/ (globe + top cities)
backend/            main.py (FastAPI), dev_server.py (standard library), stockshock/ (engine + geo data)
others/             build_world.py (rebuilds geo data), Dockerfile, render.yaml
```

## Code map

- `backend/stockshock/world.py`: world city search, nearest city, destination profiling (type, business mix, airport, hub)
- `backend/stockshock/geo/`: city, airport and country tables built by `others/build_world.py` from open data
- `backend/stockshock/catalog.py`: featured destinations, season patterns, product generator and prices
- `backend/stockshock/data.py`: simulated weekly demand, festivals, search signal, cancellations, buy prices
- `backend/stockshock/forecast.py`: gradient boosting with calibrated low / likely / high ranges
- `backend/stockshock/optimize.py`: scenario-based optimiser with CVaR risk cap (HiGHS via SciPy)
- `backend/stockshock/service.py`: plan / replay / frontier / portfolio / radar logic behind the API
- `backend/main.py` (FastAPI) and `backend/dev_server.py` (standard library): the two ways to serve it
- `frontend/`: the website (HTML, CSS, vanilla JS; no external libraries)
