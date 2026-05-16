"""
HTTP control interface for the Alpaca Rule Engine.

This module exposes the engine via a FastAPI application.  Endpoints
include:

* ``POST /start``: begin the periodic evaluation loop.
* ``POST /stop``: halt the loop.
* ``GET /status``: retrieve running status and configuration details.
* ``GET /tickers``: return the list of active tickers.
* ``POST /tickers``: update the list of tickers.
* ``POST /run-once``: execute a single evaluation cycle immediately.

The API is designed to be light weight and easily integrated with the
MCP server or external automation.  All routes return JSON
structures.
"""

from __future__ import annotations

from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import RuleEngine
from .config import DEFAULT_CONFIG


app = FastAPI(title="Alpaca Rule Engine Control")

# Create a global engine instance.  In a production deployment this
# could be replaced with dependency injection or passed via context.
engine: RuleEngine = RuleEngine(config=DEFAULT_CONFIG)


class TickerUpdate(BaseModel):
    tickers: List[str]


@app.post("/start")
def start() -> dict:
    """Start the engine's evaluation loop."""
    engine.start()
    return engine.status()


@app.post("/stop")
def stop() -> dict:
    """Stop the engine's evaluation loop."""
    engine.stop()
    return engine.status()


@app.get("/status")
def status() -> dict:
    """Return current status of the engine."""
    return engine.status()


@app.get("/tickers")
def get_tickers() -> dict:
    """Get the current list of tickers."""
    return {"tickers": list(engine.tickers)}


@app.post("/tickers")
def set_tickers(update: TickerUpdate) -> dict:
    """Replace the tickers the engine monitors."""
    if not update.tickers or len(update.tickers) > 100:
        raise HTTPException(status_code=400, detail="Tickers list must contain between 1 and 100 symbols.")
    engine.tickers = update.tickers
    return {"tickers": list(engine.tickers)}


@app.post("/run-once")
def run_once() -> dict:
    """Execute a single evaluation cycle without affecting the running loop."""
    engine.run_once()
    return {"message": "completed"}