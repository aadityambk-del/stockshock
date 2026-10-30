# STOCKSHOCK · Inventory Planner

**VoyageHack 4.0 · Inventory Optimization · Team Table For Two (Aaradhya Jain & Aaditya Kore)**

STOCKSHOCK forecasts travel demand and invests a pre-buy budget across hotels, flights, transfers and activities
like a risk-managed portfolio. This repo is the full web app: a REST API plus an animated website.

- 34 ready destinations (India, Gulf, South-East Asia, islands, Europe), or describe **any city** and get a plan
- Low / likely / high demand forecast per product and week (gradient-boosted quantile models)
- Buy plan from an optimiser that tests 60 demand scenarios: max profit within budget, capped worst-5% loss
- BUY / WAIT / SKIP per line with the reason, buyer approval and CSV export
- Proof on every request: the same weeks replayed one year earlier against today's rule
- Risk-return curve ("inventory as an investment portfolio")

Demand history is simulated because TBO's booking data is not public. Swap `stockshock/data.py:history()`
for a reader of TBO's export and everything else keeps working.

## Run it on your computer

```
pip install numpy pandas scipy scikit-learn
python dev_server.py
```
Open http://localhost:8000. (`dev_server.py` needs nothing beyond the four libraries above.)

With FastAPI (adds interactive API docs at /docs):
```
pip install -r requirements.txt
uvicorn app:app --reload
```

## Put it online (free)

**Render (recommended)**
1. Push this folder to a public GitHub repository.
2. On render.com: **New → Blueprint**, pick the repository. Render reads `render.yaml` and deploys.
3. Your site is live at `https://<service-name>.onrender.com`. The free plan sleeps when idle; the first visit
   after a nap takes ~30-50 s, and the site shows "Waking the server up" meanwhile.

**Hugging Face Spaces**: create a Space with the *Docker* SDK and upload this folder; the `Dockerfile` serves on port 7860.

## API

| Method | Path | What it returns |
|---|---|---|
| GET | `/api/catalog` | destinations and season types |
| GET | `/api/plan?dest=goa&weeks=8&budget=100&risk=balanced` | forecast, buy plan, KPIs, last-year replay |
| POST | `/api/plan` | same, for a custom city: `{"custom": {"name": "Coorg", "type": "hills", "popularity": 3}}` |
| GET/POST | `/api/frontier` | best expected profit at each risk level |

`risk` is `careful`, `balanced` or `bold`. `budget` is a % of what today's rule (pre-buy last year's monthly
average) would spend.

## Code map

- `stockshock/catalog.py`: destinations, season patterns, product templates and prices
- `stockshock/data.py`: simulated weekly demand, festivals, search signal
- `stockshock/forecast.py`: quantile gradient boosting with calibrated ranges
- `stockshock/optimize.py`: scenario-based optimiser with CVaR risk cap (HiGHS via SciPy)
- `stockshock/service.py`: plan / replay / frontier logic behind the API
- `app.py` (FastAPI) and `dev_server.py` (standard library): the two ways to serve it
- `static/`: the website (HTML, CSS, vanilla JS, Leaflet map)
