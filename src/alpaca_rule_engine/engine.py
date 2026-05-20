"""
Core rule engine for algorithmic trading via Alpaca.

This engine is responsible for pulling market data, calculating
technical indicators, computing a weighted score for each symbol,
evaluating risk constraints and assembling order instructions for
execution.  It is designed to operate autonomously at a fixed
interval, but exposes methods to run a single cycle (``run_once``)
or to start/stop the recurring loop.

Orders are not sent directly from this module; instead the
``submit_order`` callable must be provided.  This decouples the
decision logic from the transport layer (e.g. MCP server) and makes
the engine safe to test in isolation.

The engine relies on the ``alpaca-py`` SDK for market data.  API
credentials should be configured via environment variables or
explicitly passed when constructing the Alpaca client.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, Optional

import pandas as pd

from .config import DEFAULT_CONFIG
from . import indicators

from alpaca.data.enums import DataFeed

try:
    from alpaca.data import StockHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame
except ImportError as exc:
    raise ImportError(
        "The 'alpaca-py' package is required for the rule engine."
    ) from exc


class RuleEngine:
    """Rule based trading engine implementing a periodic evaluation loop."""

    def __init__(
        self,
        config: Optional[Dict] = None,
        submit_order: Optional[Callable[[Dict[str, any]], None]] = None,
    ) -> None:
        # Load configuration or fall back to defaults
        self.config = config.copy() if config is not None else DEFAULT_CONFIG.copy()
        self.tickers: Iterable[str] = self.config.get("tickers", [])
        self.weights: Dict[str, float] = self.config.get("weights", {})
        self.thresholds: Dict[str, float] = self.config.get("thresholds", {})
        self.risk: Dict[str, any] = self.config.get("risk", {})
        self.interval: int = int(self.config.get("interval_seconds", 60))
        self.dry_run: bool = bool(self.config.get("dry_run", True))
        # Execution callback.  A no-op default prevents accidental order placement.
        self.submit_order = submit_order or (lambda order: print("[DRY RUN] order", order))
        # Internal state
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Setup Alpaca client using env vars if present
                # Cooldown minutes and state tracking
        self.cooldown_minutes: int = self.config.get("cooldown_minutes", 30)
        self.last_trade_times: Dict[str, datetime] = {}
        self.active_positions: Dict[str, bool] = {}

        self.data_client = self._init_data_client()

    def _init_data_client(self) -> StockHistoricalDataClient:
        """Initialise the Alpaca data client from environment variables."""
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        base_url = os.getenv("ALPACA_BASE_URL")
        # For data client base_url does not differentiate paper/live
        return StockHistoricalDataClient(
            api_key=key,
            secret_key=secret,
        )

    # ------------------------------------------------------------------
    # Data retrieval
    # ------------------------------------------------------------------
    def _get_bars(self, symbol: str, lookback: int = 50) -> pd.DataFrame:
        """Fetch minute bars for a symbol over a lookback window.

        The method returns a DataFrame with open, high, low, close and volume
        columns indexed by datetime.  If the API call fails an empty
        DataFrame is returned.
        """
        end = datetime.utcnow()
        start = end - timedelta(minutes=lookback)
        try:
            # The Alpaca data client now requires a StockBarsRequest when
            # specifying symbols.  Using the previous signature with
            # ``symbols=[symbol]`` triggers an unexpected keyword error.
            # Build the request and fetch the bars.
            from alpaca.data.requests import StockBarsRequest
            

            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Minute,
                start=start,
                feed=DataFeed.IEX,

                end=end,
            )
            bars = self.data_client.get_stock_bars(request).df
            # When requesting multiple symbols the API returns a multi-index
            # with symbol as level 0.  If present we drop it.
            if isinstance(bars.index, pd.MultiIndex):
                bars = bars.xs(symbol, level="symbol")
            return bars.reset_index(drop=False).rename(columns={"timestamp": "datetime"})
        except Exception as exc:
            print(f"Failed to fetch bars for {symbol}: {exc}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Indicator calculation and scoring
    # ------------------------------------------------------------------
    def _compute_indicators(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Compute all configured indicators for a dataframe."""
        return {
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

    def _latest_score(self, df: pd.DataFrame) -> float:
        """Compute a weighted score for the most recent row of data."""
        ind = self._compute_indicators(df)
        score = 0.0
        total_weight = 0.0
        for name, weight in self.weights.items():
            series = ind.get(name)
            if series is None or series.empty:
                continue
            value = series.iloc[-1]
            if pd.isna(value):
                continue
            # Normalize each indicator onto [0, 1] or [-1, 1] where sensible
            norm_value = self._normalize_indicator(name, value)
            score += weight * norm_value
            total_weight += weight
        return (score / total_weight) * 100.0 if total_weight > 0 else 0.0

    def _normalize_indicator(self, name: str, value: float) -> float:
        """Normalize indicator values into a common scale between 0 and 1.

        For oscillators already in [0, 100] (e.g. RSI), divide by 100.
        For values that can be negative (e.g. MACD, ROC), map to 0–1 via
        the arctangent function.
        """
        if name in {"sma", "ema", "vwap"}:
            # Price relative to itself is not informative; treat the signal
            # as bullish (1) if above last close and bearish (0) if below.
            return 1.0 if value > 0 else 0.0
        if name == "rsi":
            return value / 100.0
        if name == "macd":
            return 0.5 + (value / 20.0)  # approximate normalisation
        if name == "bollinger":
            return max(0.0, min(1.0, value))
        if name == "atr":
            return min(1.0, value * 10)  # large ATR => high volatility
        if name == "adx":
            return min(1.0, value / 50.0)
        if name == "stochastic":
            return value / 100.0
        if name == "obv":
            # OBV is cumulative; sign indicates trend
            return 1.0 if value > 0 else 0.0
        if name == "roc":
            return 0.5 + (value / 20.0)
        if name == "cci":
            # CCI around zero; scale down
            return 0.5 + (value / 400.0)
        return 0.5

    # ------------------------------------------------------------------
    # Risk evaluation
    # ------------------------------------------------------------------
    def _risk_allowed(self, symbol: str) -> bool:
        """Determine whether a trade is allowed under risk constraints.

        This method can be extended to query account equity, open
        positions, daily P&L etc.  For now it simply returns True.  A
        full implementation would require an AlpacaTradingClient and
        account summary fetch.
        """
        # TODO: implement account checks: position sizing, open count, daily loss
        return True

    # ------------------------------------------------------------------
    # Decision logic and order construction
    # ------------------------------------------------------------------
    def _decision_and_order(self, symbol: str, price: float, score: float) -> Optional[Dict[str, any]]:
        """Construct an order dict if the score crosses thresholds."""
        buy_threshold = self.thresholds.get("buy", 70)
        sell_threshold = self.thresholds.get("sell", 30)
        if score >= buy_threshold:
            side = "buy"
        elif score <= sell_threshold:
            side = "sell"
        else:
            return None
        # Determine notional or quantity.  Without account equity we use notional = max_notional_trade.
        symbol_risk = self.risk.get("overrides", {}).get(symbol, {})
        notional = symbol_risk.get("max_notional_trade", self.risk.get("max_notional_trade", 1000.0))
        qty = max(1, int(notional / price))
        # Determine stop loss and take profit
        sl_pct = symbol_risk.get("stop_loss_pct", self.risk.get("stop_loss_pct", 0.03))
        tp_pct = symbol_risk.get("take_profit_pct", self.risk.get("take_profit_pct", 0.06))
        stop_price = price * (1 - sl_pct) if side == "buy" else price * (1 + tp_pct)
        take_price = price * (1 + tp_pct) if side == "buy" else price * (1 - sl_pct)
        return {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": round(take_price, 2)},
            "stop_loss": {"stop_price": round(stop_price, 2)},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_once(self) -> None:
        """Execute a single evaluation cycle for all tickers."""
        for symbol in self.tickers:
                    now = datetime.utcnow()
        # Skip symbol if cooldown period has not elapsed
        last_time = self.last_trade_times.get(symbol)
        if last_time and (now - last_time).total_seconds() < self.cooldown_minutes * 60:
            continue
        # Skip if we already have an open position for this symbol
        if self.active_positions.get(symbol):
            continue

            df = self._get_bars(symbol)
            if df.empty or len(df) < 5:
                continue
            price = df["close"].iloc[-1]
            score = self._latest_score(df)
            order = self._decision_and_order(symbol, price, score)
            if order and self._risk_allowed(symbol):
                if self.dry_run:
                    print(f"[DRY RUN] would submit order: {order}")
                else:
                    self.submit_order(order)
                                # Record trade time and mark position as active
                self.last_trade_times[symbol] = now
            self.active_positions[symbol] = True

            self.active_positions[symbol] = True


    def _loop(self) -> None:
        """Internal thread loop executing run_once at the configured interval."""
        while not self._stop_event.is_set():
            start_time = time.time()
            try:
                self.run_once()
            except Exception as exc:
                print(f"Error in rule engine loop: {exc}")
            # Sleep for the remainder of the interval
            elapsed = time.time() - start_time
            delay = max(0.0, self.interval - elapsed)
            time.sleep(delay)

    def start(self) -> None:
        """Start the periodic evaluation loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("Rule engine started")

    def stop(self) -> None:
        """Stop the periodic evaluation loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval)
            self._thread = None
        print("Rule engine stopped")

    def status(self) -> Dict[str, any]:
        """Return status information about the engine."""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "tickers": list(self.tickers),
            "interval_seconds": self.interval,
            "dry_run": self.dry_run,
        }
