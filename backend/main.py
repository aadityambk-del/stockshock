"""STOCKSHOCK web app: REST API + website.

Run locally (from the repo root):   uvicorn app:app --reload  (or: cd backend && uvicorn main:app)       then open http://localhost:8000
API docs:      http://localhost:8000/docs
"""
from __future__ import annotations

import os
import threading

from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stockshock.api_core import dumps, handle

app = FastAPI(
    title="STOCKSHOCK API",
    version="4.0",
    description="Forecasts travel demand and builds a risk-capped pre-buy plan for flights (any origin to any destination), "
                "business, airport and leisure hotels, and experiences in any of 171,567 cities. Real cities, airports and "
                "distances; demand is modelled because TBO's booking history is not public.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024)

# load the city index and the first forecasts in the background, so the first visitor does not wait for them
threading.Thread(target=lambda: handle("warm", {}), daemon=True).start()

Risk = Literal["careful", "balanced", "bold"]
SeasonType = Literal["beach", "hills", "heritage", "backwater", "snow", "high", "spiritual", "metro", "gulf",
                     "seasia", "island", "europe", "medbeach", "ski", "temperate", "temperate_s", "beach_s", "tropical",
                     "eastasia", "safari"]


class CustomCity(BaseModel):
    name: str = Field(..., examples=["Coorg"])
    type: SeasonType = Field("hills", description="Season pattern to use for this destination")
    popularity: int = Field(3, ge=1, le=5, description="1 = niche, 5 = mass market")
    price_level: float = Field(1.0, ge=0.4, le=3.0, description="1 = typical Indian domestic prices")
    hub: str = Field("DEL", description="Origin airport for the flight block")
    airport: Optional[str] = Field(None, description="Destination airport code")
    lat: Optional[float] = None
    lon: Optional[float] = None


class PlanRequest(BaseModel):
    dest: Optional[str] = Field("goa", description="Featured destination id from /api/catalog")
    city: Optional[str] = Field(None, description="Any city id from /api/search (e.g. w12345); overrides dest")
    hub: Optional[str] = Field(None, description="Origin airport (any IATA code); auto Indian hub if empty")
    origin: Optional[str] = Field(None, description="Same as hub: origin airport IATA code for the Flights module")
    kinds: Optional[str] = Field(None, description="Module filter: comma list of flight, hotel, activity, transfer")
    custom: Optional[CustomCity] = None
    start: Optional[str] = Field(None, description="First week (YYYY-MM-DD); defaults to next Monday")
    weeks: int = Field(8, ge=2, le=12)
    budget: float = Field(100, ge=40, le=160, description="Budget as % of what today's rule would spend")
    budget_inr: Optional[float] = Field(None, description="Maximum budget in rupees; overrides the % budget")
    risk: Risk = "balanced"
    replay: bool = False


def _send(code: int, body: dict):
    if code != 200:
        raise HTTPException(status_code=code, detail=body.get("error"))
    return Response(content=dumps(body), media_type="application/json")


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True}


@app.get("/api/catalog", tags=["planner"], summary="Destinations and season types")
def get_catalog():
    return _send(*handle("catalog", {}))


@app.get("/api/search", tags=["world"], summary="Search any of 171k cities (or an airport code)")
def search(q: str, limit: int = 12):
    return _send(*handle("search", {"q": q, "limit": limit}))


@app.get("/api/nearest", tags=["world"], summary="The city closest to a coordinate")
def nearest(lat: float, lon: float):
    return _send(*handle("nearest", {"lat": lat, "lon": lon}))


@app.get("/api/city", tags=["world"], summary="Destination profile: season, business mix, airport, hub, prices")
def city(id: str, hub: Optional[str] = None):
    return _send(*handle("city", {"id": id, "hub": hub}))


@app.get("/api/plan", tags=["planner"], summary="Forecast + buy plan for a featured destination or any city")
def get_plan(dest: str = "goa", city: Optional[str] = None, hub: Optional[str] = None, origin: Optional[str] = None,
             kinds: Optional[str] = None, start: Optional[str] = None, weeks: int = 8, budget: float = 100,
             budget_inr: Optional[float] = None, risk: Risk = "balanced", replay: bool = False):
    return _send(*handle("plan", {"dest": dest, "city": city, "hub": hub, "origin": origin, "kinds": kinds, "start": start,
                                  "weeks": weeks, "budget": budget, "budget_inr": budget_inr, "risk": risk, "replay": replay}))


@app.get("/api/portfolio", tags=["planner"], summary="Split one rupee budget across up to 8 destinations, products and weeks")
def get_portfolio(ids: str, budget_inr: float = 30_000_000, kinds: Optional[str] = None, start: Optional[str] = None,
                  weeks: int = 8, risk: Risk = "balanced"):
    return _send(*handle("portfolio", {"ids": ids, "budget_inr": budget_inr, "kinds": kinds, "start": start, "weeks": weeks, "risk": risk}))


@app.get("/api/warm", tags=["planner"], summary="Pre-compute forecasts for these destinations so later requests are instant")
def get_warm(ids: Optional[str] = None, weeks: int = 8):
    return _send(*handle("warm", {"ids": ids, "weeks": weeks}))


@app.get("/api/radar", tags=["planner"], summary="Ranked pre-buy opportunities with the signals behind each one")
def get_radar(ids: Optional[str] = None, kinds: Optional[str] = None, start: Optional[str] = None, weeks: int = 8, limit: int = 25):
    return _send(*handle("radar", {"ids": ids, "kinds": kinds, "start": start, "weeks": weeks, "limit": limit}))


@app.get("/api/replay", tags=["planner"], summary="Proof: the same weeks one year earlier, scored on what actually sold")
def get_replay(dest: str = "goa", city: Optional[str] = None, hub: Optional[str] = None, origin: Optional[str] = None,
               kinds: Optional[str] = None, start: Optional[str] = None, weeks: int = 8, budget: float = 100,
               budget_inr: Optional[float] = None, risk: Risk = "balanced"):
    return _send(*handle("replay", {"dest": dest, "city": city, "hub": hub, "origin": origin, "kinds": kinds, "start": start,
                                    "weeks": weeks, "budget": budget, "budget_inr": budget_inr, "risk": risk}))


@app.post("/api/plan", tags=["planner"], summary="Forecast + buy plan for any destination, including your own city")
def post_plan(req: PlanRequest):
    body = req.model_dump()
    return _send(*handle("plan", body))


@app.get("/api/frontier", tags=["planner"], summary="Best expected profit at each risk level")
def get_frontier(dest: str = "goa", city: Optional[str] = None, hub: Optional[str] = None, origin: Optional[str] = None,
                 kinds: Optional[str] = None, start: Optional[str] = None, weeks: int = 8, budget: float = 100,
                 budget_inr: Optional[float] = None):
    return _send(*handle("frontier", {"dest": dest, "city": city, "hub": hub, "origin": origin, "kinds": kinds,
                                      "start": start, "weeks": weeks, "budget": budget, "budget_inr": budget_inr}))


@app.post("/api/frontier", tags=["planner"], summary="Risk-return frontier for any destination")
def post_frontier(req: PlanRequest):
    return _send(*handle("frontier", req.model_dump()))


FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="site")
