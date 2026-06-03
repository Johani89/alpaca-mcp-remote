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
from .config import load_config_from_env
from .signal_diagnostics import latest_indicator_snapshot, setup_quality, weighted_score


app = FastAPI(title="Alpaca Rule Engine Control")

engine: RuleEngine = RuleEngine(config=load_config_from_env())


class TickerUpdate(BaseModel):
    tickers: List[str]


@app.get("/health")
def health() -> dict:
    """Railway health-check endpoint."""
    return {"status": "ok", "service": "alpaca-rule-engine"}


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
    """Replace the tickers the engine monitors.

    Tickers are normalized to uppercase and deduplicated while preserving
    order. There is no hard-coded upper limit here; infrastructure capacity
    should govern practical universe size.
    """
    if not update.tickers:
        raise HTTPException(status_code=400, detail="At least one ticker must be provided.")

    normalized = []
    seen = set()
    for raw_symbol in update.tickers:
        symbol = raw_symbol.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)

    if not normalized:
        raise HTTPException(status_code=400, detail="At least one valid ticker must be provided.")

    engine.tickers = normalized
    engine.config["tickers"] = normalized
    return {"tickers": list(engine.tickers), "count": len(engine.tickers)}


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
