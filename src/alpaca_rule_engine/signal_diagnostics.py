"""Signal diagnostics helpers for the Alpaca rule engine.

This module is calculation-only. It does not place, submit, or route orders.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from . import indicators


def latest_indicator_snapshot(df: pd.DataFrame) -> Dict[str, float]:
    """Return latest valid values for every supported indicator."""
    calculated = {
        "sma": indicators.sma(df),
        "ema": indicators.ema(df),
        "rsi": indicators.rsi(df),
        "macd": indicators.macd(df),
        "bollinger": indicators.bollinger_band_position(df),
        "atr": indicators.atr(df),
        "adx": indicators.adx(df),
        "stochastic": indicators.stochastic(df),
        "obv": indicators.obv(df),
        "vwap": indicators.vwap(df),
        "roc": indicators.roc(df),
        "cci": indicators.cci(df),
    }
    snapshot: Dict[str, float] = {}
    for name, series in calculated.items():
        if series is None or series.empty:
            continue
        value = series.iloc[-1]
        if pd.notna(value):
            snapshot[name] = float(value)
    return snapshot


def normalize_signal(name: str, value: float, price: float) -> float:
    """Normalize one indicator to a 0..1 score."""
    if name in {"sma", "ema", "vwap"}:
        return 1.0 if price >= value else 0.0
    if name == "rsi":
        if value < 30:
            return 0.85
        if value > 70:
            return 0.25
        return max(0.0, min(1.0, value / 70.0))
    if name == "macd":
        return max(0.0, min(1.0, 0.5 + value / max(price * 0.02, 1e-9)))
    if name == "bollinger":
        return max(0.0, min(1.0, value))
    if name == "atr":
        return max(0.0, min(1.0, 1.0 - value * 8.0))
    if name == "adx":
        return max(0.0, min(1.0, value / 40.0))
    if name == "stochastic":
        if value < 20:
            return 0.8
        if value > 80:
            return 0.25
        return value / 100.0
    if name == "obv":
        return 1.0 if value > 0 else 0.0
    if name == "roc":
        return max(0.0, min(1.0, 0.5 + value / 20.0))
    if name == "cci":
        return max(0.0, min(1.0, 0.5 + value / 400.0))
    return 0.5


def weighted_score(price: float, snapshot: Dict[str, float], weights: Dict[str, float]) -> float:
    """Return 0..100 weighted signal score from indicator values."""
    weighted_total = 0.0
    total_weight = 0.0
    for name, weight in weights.items():
        value = snapshot.get(name)
        if value is None:
            continue
        weighted_total += float(weight) * normalize_signal(name, float(value), price)
        total_weight += float(weight)
    return round((weighted_total / total_weight) * 100.0, 2) if total_weight else 0.0


def setup_quality(symbol: str, df: pd.DataFrame, base_score: float, config: Dict[str, Any]) -> float:
    """Return setup quality score without executing anything."""
    if df.empty or len(df) < 2:
        return 0.0
    snapshot = latest_indicator_snapshot(df)
    price = float(df["close"].iloc[-1])
    vwap = snapshot.get("vwap", price)
    vwap_score = 100.0 if price >= vwap else max(0.0, 100.0 - abs(price - vwap) / max(price, 1e-9) * 1000.0)
    current_vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].rolling(window=min(len(df), 20)).mean().iloc[-1] or 0.0)
    rel_vol_score = min(current_vol / avg_vol, 2.0) / 2.0 * 100.0 if avg_vol > 0 else 50.0
    trend_score = max(0.0, min(float(snapshot.get("adx", 0.0)) * 2.0, 100.0))
    rsi_value = float(snapshot.get("rsi", 50.0))
    rsi_score = max(0.0, 100.0 - max(abs(rsi_value - 50.0) - 10.0, 0.0) * 1.5)
    first_close = float(df["close"].iloc[0])
    gap_ratio = abs(price - first_close) / max(first_close, 1e-9)
    gap_penalty = min(gap_ratio * 100.0, 100.0)
    catalyst_bonus = float(config.get("catalysts", {}).get(symbol, 0.0))
    market_bonus = float(config.get("market_regime_bonus", 0.0))
    final = 0.25 * vwap_score + 0.20 * rel_vol_score + 0.20 * trend_score + 0.15 * rsi_score + 0.20 * base_score + catalyst_bonus + market_bonus - gap_penalty
    return max(0.0, min(final, 100.0))
