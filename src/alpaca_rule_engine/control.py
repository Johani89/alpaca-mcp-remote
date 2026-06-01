"""
HTTP control interface for the Alpaca Rule Engine.

This module exposes the engine via a FastAPI application. Endpoints include:

* ``POST /start``: begin the periodic evaluation loop.
* ``POST /stop``: halt the loop.
* ``GET /status``: retrieve running status and configuration details.
* ``GET /tickers``: return the list of active tickers.
* ``POST /tickers``: update the list of tickers.
* ``POST /run-once``: execute a single evaluation cycle immediately.
* ``GET /diagnostics``: inspect recent market data and indicator readiness.
"""

from __future__ import annotations

from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .engine import RuleEngine
from .config import DEFAULT_CONFIG
from .signal_diagnostics import latest_indicator_snapshot, setup_quality, weighted_score


app = FastAPI(title="Alpaca Rule Engine Control")

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
    return {"message": "completed", "status": engine.status()}


@app.get("/diagnostics")
def diagnostics() -> dict:
    """Return per-ticker market-data and indicator diagnostics without execution."""
    results = []
    for symbol in engine.tickers:
        item = {"symbol": symbol}
        try:
            df = engine._get_bars(symbol, lookback=390)
            item["rows"] = int(len(df))
            item["has_bars"] = not df.empty
            if df.empty:
                item["reason"] = "no bars returned from Alpaca data API"
                results.append(item)
                continue
            item["first_datetime"] = str(df["datetime"].iloc[0]) if "datetime" in df.columns else None
            item["last_datetime"] = str(df["datetime"].iloc[-1]) if "datetime" in df.columns else None
            item["last_close"] = float(df["close"].iloc[-1])
            snapshot = latest_indicator_snapshot(df)
            item["indicator_count"] = len(snapshot)
            item["indicators"] = {name: round(value, 4) for name, value in snapshot.items()}
            score = weighted_score(item["last_close"], snapshot, engine.weights)
            item["score"] = score
            item["setup_quality"] = round(setup_quality(symbol, df, score, engine.config), 2)
        except Exception as exc:
            item["error"] = str(exc)
        results.append(item)
    return {"running": engine.status().get("running"), "tickers": list(engine.tickers), "results": results}
