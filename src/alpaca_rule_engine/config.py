"""
Configuration defaults for the Alpaca Rule Engine.

This module contains a single dictionary, DEFAULT_CONFIG, which
specifies the engine's default behaviour.  Tickers, indicator
weights, score thresholds and risk constraints can all be tuned via
this configuration.  The structure is intentionally simple so that it
can be loaded from a JSON file or overridden with environment
variables at runtime.
"""

DEFAULT_CONFIG = {
    # List of tickers to monitor.  Up to 100 tickers are supported
    # without modification to the engine.  Each symbol will be
    # processed independently at the configured interval.
    "tickers": ["TSLA", "AAPL", "NVDA"],

    # Scoring weights for the supported indicators.  All values
    # contribute to a final score on a 0–100 scale.  Increasing a
    # weight raises the influence of the corresponding indicator on
    # trading decisions.  Removing an entry disables the indicator.
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

    # Thresholds for turning a score into an action.  If the score is
    # greater than or equal to the buy threshold a long entry will be
    # attempted.  If the score is less than or equal to the sell
    # threshold a short entry (or exit from a long) will be
    # attempted.  Otherwise the engine will hold.
    "thresholds": {
        "buy": 75,
        "sell": 35,
    },

    # Risk management parameters.  These settings enforce prudent
    # position sizing and stop‑loss / take profit exits.  They are
    # specified as fractions or absolute dollar values.  Symbol‑
    # specific overrides can be added in the `overrides` section.
    "risk": {
        "max_position_pct": 0.05,       # 5 % of account equity per trade
        "max_notional_trade": 1000.0,   # USD maximum per trade
        "max_open_positions": 10,       # limit simultaneous positions
        "max_daily_loss_pct": 0.02,     # 2 % daily drawdown kill switch
        "stop_loss_pct": 0.03,          # default stop loss 3 %
        "take_profit_pct": 0.06,        # default take profit 6 %
        "overrides": {
            "TSLA": {
                "stop_loss_pct": 0.035,
                "take_profit_pct": 0.07,
                "max_notional_trade": 500.0,
            }
        },
    },

    # Interval in seconds between recalculations.  A value of 60
    # seconds means the engine will evaluate market data and trading
    # rules once per minute for each ticker.
    "interval_seconds": 60,

    # Dry run mode.  When true the engine will simulate order
    # placement without actually sending orders to Alpaca.  Set this
    # flag to False only after you have thoroughly tested your
    # configuration.
    "dry_run": True,
}
