"""STOCKSHOCK web app: REST API + website.

Run locally:   uvicorn app:app --reload        then open http://localhost:8000
API docs:      http://localhost:8000/docs
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stockshock.api_core import dumps, handle

app = FastAPI(
    title="STOCKSHOCK API",
    version="1.0",
    description="Forecasts travel demand and builds a risk-capped pre-buy plan for hotels, flights, "
                "transfers and activities in any destination. Demand history is simulated "
                "(TBO data is not public); swap in a CSV export to run on real bookings.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

Risk = Literal["careful", "balanced", "bold"]
SeasonType = Literal["beach", "hills", "heritage", "backwater", "snow", "high", "spiritual", "metro", "gulf",
                     "seasia", "island", "europe"]


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
    dest: Optional[str] = Field("goa", description="Destination id from /api/catalog (ignored if custom is set)")
    custom: Optional[CustomCity] = None
    start: Optional[str] = Field(None, description="First week (YYYY-MM-DD); defaults to next Monday")
    weeks: int = Field(8, ge=2, le=12)
    budget: float = Field(100, ge=40, le=160, description="Budget as % of what today's rule would spend")
    risk: Risk = "balanced"
    replay: bool = True


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


@app.get("/api/plan", tags=["planner"], summary="Forecast + buy plan for a catalog destination")
def get_plan(dest: str = "goa", start: Optional[str] = None, weeks: int = 8, budget: float = 100,
             risk: Risk = "balanced", replay: bool = True):
    return _send(*handle("plan", {"dest": dest, "start": start, "weeks": weeks, "budget": budget,
                                  "risk": risk, "replay": replay}))


@app.post("/api/plan", tags=["planner"], summary="Forecast + buy plan for any destination, including your own city")
def post_plan(req: PlanRequest):
    body = req.model_dump()
    return _send(*handle("plan", body))


@app.get("/api/frontier", tags=["planner"], summary="Best expected profit at each risk level")
def get_frontier(dest: str = "goa", start: Optional[str] = None, weeks: int = 8, budget: float = 100):
    return _send(*handle("frontier", {"dest": dest, "start": start, "weeks": weeks, "budget": budget}))


@app.post("/api/frontier", tags=["planner"], summary="Risk-return frontier for any destination")
def post_frontier(req: PlanRequest):
    return _send(*handle("frontier", req.model_dump()))


app.mount("/", StaticFiles(directory="static", html=True), name="site")
