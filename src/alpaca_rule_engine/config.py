"""
Configuration defaults for the Alpaca Rule Engine.

This module contains a single dictionary, DEFAULT_CONFIG, which
specifies the engine's default behaviour. Tickers, indicator weights,
score thresholds and risk constraints can all be tuned via this
configuration. The structure is intentionally simple so that it can be
loaded from JSON or overridden with environment variables at runtime.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict


DEFAULT_CONFIG = {
    "tickers": [],
    "weights": {
        "sma": 5,
        "ema": 5,
        "rsi": 10,
        "macd": 10,
        "bollinger": 5,
        "atr": 5,
        "adx": 5,
        "stochastic": 5,
        "obv": 5,
        "vwap": 5,
        "roc": 5,
        "cci": 5,
    },
    "thresholds": {
        "buy": 75,
        "sell": 35,
    },
    "risk": {
        "max_position_pct": 0.05,
        "max_notional_trade": 1000.0,
        "max_open_positions": 10,
        "max_daily_loss_pct": 0.02,
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.06,
        "overrides": {},
    },
    "interval_seconds": 60,
    "dry_run": True,
}


def _parse_percent(value: str) -> float:
    parsed = float(value)
    return parsed / 100.0 if parsed > 1 else parsed


def load_config_from_env() -> Dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)

    symbols = os.getenv("WATCHLIST_SYMBOLS") or os.getenv("TRADE_SYMBOLS")
    if symbols:
        config["tickers"] = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]

    buy_threshold = os.getenv("BUY_SCORE_THRESHOLD")
    if buy_threshold:
        try:
            config["thresholds"]["buy"] = float(buy_threshold)
        except ValueError:
            pass

    sell_threshold = os.getenv("SELL_SCORE_THRESHOLD")
    if sell_threshold:
        try:
            config["thresholds"]["sell"] = float(sell_threshold)
        except ValueError:
            pass

    max_positions = os.getenv("MAX_OPEN_POSITIONS")
    if max_positions:
        try:
            config["risk"]["max_open_positions"] = int(max_positions)
        except ValueError:
            pass

    max_size = os.getenv("MAX_POSITION_SIZE")
    if max_size:
        try:
            config["risk"]["max_notional_trade"] = float(max_size)
        except ValueError:
            pass

    stop_loss = os.getenv("STOP_LOSS_PCT")
    if stop_loss:
        try:
            config["risk"]["stop_loss_pct"] = _parse_percent(stop_loss)
        except ValueError:
            pass

    take_profit = os.getenv("TAKE_PROFIT_PCT")
    if take_profit:
        try:
            config["risk"]["take_profit_pct"] = _parse_percent(take_profit)
        except ValueError:
            pass

    daily_loss = os.getenv("MAX_DAILY_LOSS_PCT") or os.getenv("MAX_DAILY_LOSS")
    if daily_loss:
        try:
            config["risk"]["max_daily_loss_pct"] = _parse_percent(daily_loss)
        except ValueError:
            pass

    interval_minutes = os.getenv("ENGINE_INTERVAL_MINUTES")
    if interval_minutes:
        try:
            config["interval_seconds"] = int(float(interval_minutes) * 60)
        except ValueError:
            pass

    interval_seconds = os.getenv("ENGINE_INTERVAL_SECONDS")
    if interval_seconds:
        try:
            config["interval_seconds"] = int(float(interval_seconds))
        except ValueError:
            pass

    return config
