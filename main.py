import os
import math
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Literal, Any
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderClass,
)

# ==========================================
# Logging Configuration
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("external_stateful_algo")

# ==========================================
# Environment Configuration
# ==========================================
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "").strip()

PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

ALLOW_LONGS = os.getenv("ALLOW_LONGS", "true").lower() == "true"
ALLOW_SHORTS = os.getenv("ALLOW_SHORTS", "true").lower() == "true"

MAX_ACTIVE_SYMBOLS = int(os.getenv("MAX_ACTIVE_SYMBOLS", "20"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))

# Minimum confirmations for long/short entry
MIN_LONG_CONFIRMATIONS = int(os.getenv("MIN_LONG_CONFIRMATIONS", "3"))
MIN_SHORT_CONFIRMATIONS = int(os.getenv("MIN_SHORT_CONFIRMATIONS", "5"))

ACCOUNT_EQUITY_OVERRIDE = float(os.getenv("ACCOUNT_EQUITY_OVERRIDE", "0"))

# Risk parameters
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.005"))
MAX_LONG_POSITION_PCT = float(os.getenv("MAX_LONG_POSITION_PCT", "0.10"))
MAX_SHORT_POSITION_PCT = float(os.getenv("MAX_SHORT_POSITION_PCT", "0.05"))

LONG_STOP_LOSS_PCT = float(os.getenv("LONG_STOP_LOSS_PCT", "0.03"))
LONG_TAKE_PROFIT_PCT = float(os.getenv("LONG_TAKE_PROFIT_PCT", "0.06"))

SHORT_STOP_LOSS_PCT = float(os.getenv("SHORT_STOP_LOSS_PCT", "0.025"))
SHORT_TAKE_PROFIT_PCT = float(os.getenv("SHORT_TAKE_PROFIT_PCT", "0.05"))

# Ladder configuration
MAX_LADDER_ADDS = int(os.getenv("MAX_LADDER_ADDS", "2"))
LADDER_TRIGGER_PCT = float(os.getenv("LADDER_TRIGGER_PCT", "0.02"))  # 2% profit before adding
LADDER_MINUTES_BETWEEN_ADDS = int(os.getenv("LADDER_MINUTES_BETWEEN_ADDS", "15"))

# Cooldown settings
TRADE_COOLDOWN_MINUTES = int(os.getenv("TRADE_COOLDOWN_MINUTES", "30"))

# Data lookback and interval
MIN_CANDLES = int(os.getenv("MIN_CANDLES", "80"))
BAR_LOOKBACK_DAYS = int(os.getenv("BAR_LOOKBACK_DAYS", "7"))
LOOP_INTERVAL_SECONDS = int(os.getenv("LOOP_INTERVAL_SECONDS", "60"))

MIN_PRICE = float(os.getenv("MIN_PRICE", "2.0"))
MIN_PRICE_FOR_SHORT = float(os.getenv("MIN_PRICE_FOR_SHORT", "5.0"))

# ==========================================
# Alpaca Clients
# ==========================================
if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    logger.warning("Missing Alpaca API credentials. Trading and data calls will fail unless provided via environment variables.")

trading_client = TradingClient(
    api_key=ALPACA_API_KEY,
    secret_key=ALPACA_SECRET_KEY,
    paper=PAPER_TRADING,
)

data_client = StockHistoricalDataClient(
    api_key=ALPACA_API_KEY,
    secret_key=ALPACA_SECRET_KEY,
)

# ==========================================
# FastAPI Models and State
# ==========================================

TradeMode = Literal["long", "short", "both"]

class SymbolFeedRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1)
    mode: TradeMode = "both"
    execute_now: bool = True

class SymbolState(BaseModel):
    status: str = "watching"  # watching, long, short, cooldown
    entry_price: Optional[float] = None
    quantity: int = 0
    ladder_count: int = 0
    last_add_time: Optional[datetime] = None
    max_price: Optional[float] = None
    min_price: Optional[float] = None
    cooldown_until: Optional[datetime] = None

# Global state mapping symbols to their status
STATE: Dict[str, SymbolState] = {}
ACTIVE_MODE: TradeMode = "both"
LAST_RESULTS: List[Dict[str, Any]] = []
STATE_LOCK = threading.Lock()

# ==========================================
# Utility Functions
# ==========================================

def clean_symbols(symbols: List[str]) -> List[str]:
    cleaned: List[str] = []
    for sym in symbols:
        s = str(sym).upper().strip()
        if not s:
            continue
        s = s.replace("$", "")
        # Allow alphanumeric with dots and dashes
        if not s.replace(".", "").replace("-", "").isalnum():
            continue
        if s not in cleaned:
            cleaned.append(s)
    return cleaned[:MAX_ACTIVE_SYMBOLS]


def get_account_equity() -> float:
    if ACCOUNT_EQUITY_OVERRIDE > 0:
        return ACCOUNT_EQUITY_OVERRIDE
    try:
        account = trading_client.get_account()
        return float(account.equity)
    except Exception:
        return 0.0


def fetch_minute_bars(symbol: str) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=BAR_LOOKBACK_DAYS)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
    )
    bars = data_client.get_stock_bars(request)
    df = bars.df
    if df is None or df.empty:
        raise ValueError(f"No bar data returned for {symbol}")
    # MultiIndex check
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level=0)
    df = df.reset_index()
    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing {col} in bar data for {symbol}")
    return df[required].copy()


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()
    # Ensure numeric
    for col in required_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    if len(df) < MIN_CANDLES:
        raise ValueError(f"Not enough candles: {len(df)} available, require {MIN_CANDLES}")

    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df["ema_12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema_26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    df["bb_mid"] = df["close"].rolling(20).mean()
    df["bb_std"] = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + (2 * df["bb_std"])
    df["bb_lower"] = df["bb_mid"] - (2 * df["bb_std"])

    low_14 = df["low"].rolling(14).min()
    high_14 = df["high"].rolling(14).max()
    stoch_den = (high_14 - low_14).replace(0, np.nan)
    df["stoch_k"] = 100 * ((df["close"] - low_14) / stoch_den)
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    volume_sum = df["volume"].cumsum().replace(0, np.nan)
    df["vwap"] = (typical_price * df["volume"]).cumsum() / volume_sum

    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(14).mean()

    df["momentum"] = df["close"] - df["close"].shift(10)

    direction = np.sign(df["close"].diff()).fillna(0)
    df["obv"] = (direction * df["volume"]).cumsum()
    df["obv_sma"] = df["obv"].rolling(20).mean()

    clean = df.dropna()
    if len(clean) < 2:
        raise ValueError("Not enough clean indicator rows")
    return clean


def evaluate_signals(indicators: pd.DataFrame) -> Dict[str, Any]:
    latest = indicators.iloc[-1]
    previous = indicators.iloc[-2]
    price = float(latest["close"])
    long_signals = {
        "sma_trend": latest["sma_20"] > latest["sma_50"],
        "price_above_sma_20": latest["close"] > latest["sma_20"],
        "ema_trend": latest["ema_12"] > latest["ema_26"],
        "macd_bullish": latest["macd"] > latest["macd_signal"],
        "rsi_healthy": 40 < latest["rsi"] < 70,
        "bollinger_rebound": latest["close"] > latest["bb_lower"],
        "stoch_bullish": latest["stoch_k"] > latest["stoch_d"],
        "price_above_vwap": latest["close"] > latest["vwap"],
        "atr_valid": latest["atr"] > 0,
        "momentum_positive": latest["momentum"] > 0,
        "obv_bullish": latest["obv"] > latest["obv_sma"],
        "close_strength": latest["close"] > previous["close"],
    }
    short_signals = {
        "sma_downtrend": latest["sma_20"] < latest["sma_50"],
        "price_below_sma_20": latest["close"] < latest["sma_20"],
        "ema_downtrend": latest["ema_12"] < latest["ema_26"],
        "macd_bearish": latest["macd"] < latest["macd_signal"],
        "rsi_weak": latest["rsi"] < 45,
        "bollinger_rejection": latest["close"] < latest["bb_upper"],
        "stoch_bearish": latest["stoch_k"] < latest["stoch_d"],
        "price_below_vwap": latest["close"] < latest["vwap"],
        "atr_valid": latest["atr"] > 0,
        "momentum_negative": latest["momentum"] < 0,
        "obv_bearish": latest["obv"] < latest["obv_sma"],
        "close_weakness": latest["close"] < previous["close"],
    }
    long_confirmations = sum(bool(v) for v in long_signals.values())
    short_confirmations = sum(bool(v) for v in short_signals.values())
    return {
        "price": price,
        "long_signals": long_signals,
        "short_signals": short_signals,
        "long_confirmations": long_confirmations,
        "short_confirmations": short_confirmations,
    }


def calculate_quantity(price: float, direction: Literal["long", "short"], equity: float) -> int:
    if price <= 0 or equity <= 0:
        return 0
    if direction == "long":
        stop_pct = LONG_STOP_LOSS_PCT
        max_pos_pct = MAX_LONG_POSITION_PCT
    else:
        stop_pct = SHORT_STOP_LOSS_PCT
        max_pos_pct = MAX_SHORT_POSITION_PCT

    max_risk = equity * RISK_PER_TRADE_PCT
    risk_per_share = price * stop_pct
    if risk_per_share <= 0:
        return 0
    risk_qty = math.floor(max_risk / risk_per_share)
    pos_qty = math.floor((equity * max_pos_pct) / price)
    return max(0, min(risk_qty, pos_qty))


def build_order_plan(symbol: str, action: str, price: float, equity: float) -> Dict[str, Any]:
    if action == "LONG":
        qty = calculate_quantity(price, "long", equity)
        stop_price = round(price * (1 - LONG_STOP_LOSS_PCT), 2)
        take_price = round(price * (1 + LONG_TAKE_PROFIT_PCT), 2)
        side = OrderSide.BUY
    elif action == "SHORT":
        qty = calculate_quantity(price, "short", equity)
        stop_price = round(price * (1 + SHORT_STOP_LOSS_PCT), 2)
        take_price = round(price * (1 - SHORT_TAKE_PROFIT_PCT), 2)
        side = OrderSide.SELL
    else:
        raise ValueError(f"Unsupported action {action}")
    return {
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "entry": round(price, 2),
        "stop": stop_price,
        "take": take_price,
        "action": action,
    }


def risk_check(order: Dict[str, Any], open_positions: Dict[str, Any]) -> None:
    symbol = order["symbol"]
    if order["quantity"] <= 0:
        raise ValueError("Position size zero after risk sizing")
    if symbol in open_positions:
        raise ValueError(f"Position already open for {symbol}")
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        raise ValueError("Max open positions reached")
    if order["action"] == "LONG" and not ALLOW_LONGS:
        raise ValueError("Long trading disabled")
    if order["action"] == "SHORT" and not ALLOW_SHORTS:
        raise ValueError("Short trading disabled")


def submit_bracket_order(order: Dict[str, Any]) -> Dict[str, Any]:
    symbol = order["symbol"]
    qty = order["quantity"]
    side = order["side"]
    stop_price = order["stop"]
    take_price = order["take"]
    # Create unique client_order_id
    client_order_id = f"stateful-{symbol.lower()}-{datetime.now().timestamp():.0f}"
    request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=take_price),
        stop_loss=StopLossRequest(stop_price=stop_price),
        client_order_id=client_order_id,
    )
    if DRY_RUN:
        logger.info(f"DRY_RUN order: {order}")
        return {
            "status": "dry_run",
            "client_order_id": client_order_id,
            "order": order,
        }
    try:
        resp = trading_client.submit_order(order_data=request)
        return {
            "status": "submitted",
            "id": str(resp.id),
            "client_order_id": client_order_id,
            "symbol": symbol,
            "qty": qty,
            "side": str(side),
            "take": take_price,
            "stop": stop_price,
        }
    except Exception as e:
        raise RuntimeError(f"Order submission failed: {e}")


def get_open_positions_map() -> Dict[str, Any]:
    try:
        positions = trading_client.get_all_positions()
        return {p.symbol.upper(): p for p in positions}
    except Exception:
        return {}


def update_state_on_entry(symbol: str, action: str, qty: int, price: float) -> None:
    now = datetime.now(timezone.utc)
    state = STATE.get(symbol, SymbolState())
    state.status = "long" if action == "LONG" else "short"
    state.entry_price = price
    state.quantity = qty
    state.ladder_count = 0
    state.last_add_time = now
    state.max_price = price if action == "LONG" else None
    state.min_price = price if action == "SHORT" else None
    state.cooldown_until = None
    STATE[symbol] = state


def enter_position(symbol: str, action: str, price: float) -> Dict[str, Any]:
    equity = get_account_equity()
    order_plan = build_order_plan(symbol, action, price, equity)
    open_positions = get_open_positions_map()
    risk_check(order_plan, open_positions)
    order_result = submit_bracket_order(order_plan)
    update_state_on_entry(symbol, action, order_plan["quantity"], price)
    return {
        "symbol": symbol,
        "action": action,
        "order_plan": order_plan,
        "order_result": order_result,
    }


def exit_position(symbol: str, current_price: float, reason: str) -> Dict[str, Any]:
    state = STATE.get(symbol)
    if not state or state.status not in ["long", "short"]:
        return {"status": "no_position", "symbol": symbol}
    # For exit we submit market order to close position; determine side
    qty = state.quantity
    side = OrderSide.SELL if state.status == "long" else OrderSide.BUY
    client_order_id = f"exit-{symbol.lower()}-{datetime.now().timestamp():.0f}"
    request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
    )
    if DRY_RUN:
        logger.info(f"DRY_RUN exit: {symbol}, side={side}, qty={qty}, price={current_price}, reason={reason}")
        status = "dry_run"
    else:
        try:
            trading_client.submit_order(order_data=request)
            status = "submitted"
        except Exception as e:
            status = f"error:{e}"
    # Set cooldown
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=TRADE_COOLDOWN_MINUTES)
    new_state = SymbolState(status="cooldown", cooldown_until=cooldown_until)
    STATE[symbol] = new_state
    return {
        "status": status,
        "symbol": symbol,
        "side": str(side),
        "quantity": qty,
        "reason": reason,
        "cooldown_until": cooldown_until.isoformat(),
    }


def manage_position(symbol: str, indicators: pd.DataFrame) -> Optional[Dict[str, Any]]:
    state = STATE.get(symbol)
    if not state:
        return None
    latest = indicators.iloc[-1]
    price = float(latest["close"])
    now = datetime.now(timezone.utc)
    if state.status == "long":
        # update max_price
        if state.max_price is None or price > state.max_price:
            state.max_price = price
        # stop loss
        if price <= state.entry_price * (1 - LONG_STOP_LOSS_PCT):
            return exit_position(symbol, price, "long_stop_loss")
        # take profit
        if price >= state.entry_price * (1 + LONG_TAKE_PROFIT_PCT):
            return exit_position(symbol, price, "long_take_profit")
        # trailing stop: if price drops more than stop pct from max price
        if state.max_price and price <= state.max_price * (1 - LONG_STOP_LOSS_PCT):
            return exit_position(symbol, price, "long_trailing_stop")
        # Ladder: add if price > entry_price * (1 + ladder_trigger * (ladder_count+1))
        if state.ladder_count < MAX_LADDER_ADDS:
            target_gain = LADDER_TRIGGER_PCT * (state.ladder_count + 1)
            if price >= state.entry_price * (1 + target_gain):
                # time check
                if not state.last_add_time or (now - state.last_add_time) >= timedelta(minutes=LADDER_MINUTES_BETWEEN_ADDS):
                    equity = get_account_equity()
                    qty_add = calculate_quantity(price, "long", equity)
                    if qty_add > 0:
                        side = OrderSide.BUY
                        client_order_id = f"add-long-{symbol.lower()}-{now.timestamp():.0f}"
                        request = MarketOrderRequest(
                            symbol=symbol,
                            qty=qty_add,
                            side=side,
                            time_in_force=TimeInForce.DAY,
                        )
                        if DRY_RUN:
                            logger.info(f"DRY_RUN ladder add long: {symbol} qty {qty_add}")
                        else:
                            try:
                                trading_client.submit_order(order_data=request)
                            except Exception as e:
                                logger.error(f"Ladder add long order failed: {e}")
                        # update state
                        state.quantity += qty_add
                        state.last_add_time = now
                        state.ladder_count += 1
        return None
    elif state.status == "short":
        # update min_price
        if state.min_price is None or price < state.min_price:
            state.min_price = price
        # stop loss (for short, price goes up)
        if price >= state.entry_price * (1 + SHORT_STOP_LOSS_PCT):
            return exit_position(symbol, price, "short_stop_loss")
        # take profit
        if price <= state.entry_price * (1 - SHORT_TAKE_PROFIT_PCT):
            return exit_position(symbol, price, "short_take_profit")
        # trailing stop: if price rises more than stop from min price
        if state.min_price and price >= state.min_price * (1 + SHORT_STOP_LOSS_PCT):
            return exit_position(symbol, price, "short_trailing_stop")
        # Ladder for short: add if price <= entry_price * (1 - ladder_trigger*(ladder_count+1))
        if state.ladder_count < MAX_LADDER_ADDS:
            target_gain = LADDER_TRIGGER_PCT * (state.ladder_count + 1)
            if price <= state.entry_price * (1 - target_gain):
                if not state.last_add_time or (now - state.last_add_time) >= timedelta(minutes=LADDER_MINUTES_BETWEEN_ADDS):
                    equity = get_account_equity()
                    qty_add = calculate_quantity(price, "short", equity)
                    if qty_add > 0:
                        side = OrderSide.SELL
                        client_order_id = f"add-short-{symbol.lower()}-{now.timestamp():.0f}"
                        request = MarketOrderRequest(
                            symbol=symbol,
                            qty=qty_add,
                            side=side,
                            time_in_force=TimeInForce.DAY,
                        )
                        if DRY_RUN:
                            logger.info(f"DRY_RUN ladder add short: {symbol} qty {qty_add}")
                        else:
                            try:
                                trading_client.submit_order(order_data=request)
                            except Exception as e:
                                logger.error(f"Ladder add short order failed: {e}")
                        state.quantity += qty_add
                        state.last_add_time = now
                        state.ladder_count += 1
        return None
    return None

# ==========================================
# Symbol Processing
# ==========================================

def process_symbol(symbol: str, mode: TradeMode) -> Dict[str, Any]:
    state = STATE.get(symbol, SymbolState())
    # Check cooldown
    now = datetime.now(timezone.utc)
    if state.status == "cooldown" and state.cooldown_until:
        if now < state.cooldown_until:
            return {"symbol": symbol, "status": "cooldown", "cooldown_until": state.cooldown_until.isoformat()}
        else:
            # Cooldown expired
            state.status = "watching"
            state.cooldown_until = None
            STATE[symbol] = state
    try:
        df = fetch_minute_bars(symbol)
        indicators = calculate_indicators(df)
    except Exception as e:
        return {"symbol": symbol, "status": "error", "reason": str(e)}
    # Manage existing position
    if state.status in ["long", "short"]:
        exit_result = manage_position(symbol, indicators)
        return {
            "symbol": symbol,
            "status": state.status,
            "entry_price": state.entry_price,
            "quantity": state.quantity,
            "max_price": state.max_price,
            "min_price": state.min_price,
            "ladder_count": state.ladder_count,
            "exit_action": exit_result,
        }
    # Evaluate entry
    signals = evaluate_signals(indicators)
    price = signals["price"]
    long_conf = signals["long_confirmations"]
    short_conf = signals["short_confirmations"]
    can_long = (mode in ("long", "both")) and ALLOW_LONGS and price >= MIN_PRICE
    can_short = (mode in ("short", "both")) and ALLOW_SHORTS and price >= MIN_PRICE_FOR_SHORT
    action: Optional[str] = None
    if can_long and long_conf >= MIN_LONG_CONFIRMATIONS:
        action = "LONG"
    elif can_short and short_conf >= MIN_SHORT_CONFIRMATIONS:
        action = "SHORT"
    if action:
        try:
            entry_result = enter_position(symbol, action, price)
            return {
                "symbol": symbol,
                "status": action.lower(),
                "entry": entry_result,
                "signals": signals,
            }
        except Exception as e:
            return {
                "symbol": symbol,
                "status": "entry_failed",
                "reason": str(e),
                "signals": signals,
            }
    return {
        "symbol": symbol,
        "status": "watching",
        "signals": signals,
    }

# ==========================================
# FastAPI App and Endpoints
# ==========================================

app = FastAPI(title="External Stateful Rotation Algo")

@app.get("/")
def root():
    return {
        "service": "external_stateful_algo",
        "status": "online",
        "paper_trading": PAPER_TRADING,
        "dry_run": DRY_RUN,
        "allow_longs": ALLOW_LONGS,
        "allow_shorts": ALLOW_SHORTS,
    }

@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/symbols")
def get_symbols():
    with STATE_LOCK:
        states = {sym: STATE[sym].dict() for sym in STATE}
        return {
            "active_mode": ACTIVE_MODE,
            "states": states,
            "last_results": LAST_RESULTS,
        }

@app.post("/symbols")
def feed_symbols(payload: SymbolFeedRequest):
    symbols = clean_symbols(payload.symbols)
    if not symbols:
        raise HTTPException(status_code=400, detail="No valid symbols provided")
    if len(symbols) > MAX_ACTIVE_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Too many symbols; max {MAX_ACTIVE_SYMBOLS}")
    with STATE_LOCK:
        global ACTIVE_MODE
        ACTIVE_MODE = payload.mode
        # Initialize state for new symbols and remove extra
        new_state: Dict[str, SymbolState] = {}
        for sym in symbols:
            if sym in STATE:
                new_state[sym] = STATE[sym]
            else:
                new_state[sym] = SymbolState()
        # Replace global state
        STATE.clear()
        STATE.update(new_state)
    results = []
    if payload.execute_now:
        results = process_active_symbols()
    return {
        "status": "accepted",
        "symbols": symbols,
        "mode": payload.mode,
        "executed": payload.execute_now,
        "results": results,
    }

# ==========================================
# Background Loop
# ==========================================

def process_active_symbols() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    with STATE_LOCK:
        symbols = list(STATE.keys())
        mode = ACTIVE_MODE
    for sym in symbols:
        result = process_symbol(sym, mode)
        results.append(result)
    with STATE_LOCK:
        global LAST_RESULTS
        LAST_RESULTS = results
    return results

def background_loop() -> None:
    while True:
        try:
            with STATE_LOCK:
                has_active = any(STATE)
            if has_active:
                process_active_symbols()
        except Exception as e:
            logger.exception(f"Background loop error: {e}")
        time.sleep(LOOP_INTERVAL_SECONDS)

@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()
    logger.info("Background loop started")
