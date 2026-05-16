"""
Technical indicator calculations for the Alpaca Rule Engine.

This module uses the `pandas` and `ta` libraries to compute a
collection of commonly used indicators.  Each function expects a
``pandas.DataFrame`` with at least the following columns:

* ``open``
* ``high``
* ``low``
* ``close``
* ``volume``

The return values are ``pandas.Series`` objects aligned with the
input index.  Missing values are left unfilled to ensure the engine
waits for sufficient lookback before acting on signals.
"""

import pandas as pd
try:
    import ta
except ImportError as exc:
    raise ImportError(
        "The 'ta' package is required for indicator calculations. "
        "Add 'ta' to your requirements and install it via pip."
    ) from exc


def sma(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Simple Moving Average of closing prices."""
    return df["close"].rolling(window=window).mean()


def ema(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Exponential Moving Average of closing prices."""
    return df["close"].ewm(span=window, adjust=False).mean()


def rsi(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Relative Strength Index."""
    indicator = ta.momentum.RSIIndicator(close=df["close"], window=window)
    return indicator.rsi()


def macd(df: pd.DataFrame) -> pd.Series:
    """Moving Average Convergence Divergence signal line minus MACD line.

    A positive value suggests bullish momentum, a negative value
    indicates bearish momentum.
    """
    indicator = ta.trend.MACD(close=df["close"])
    return indicator.macd_diff()


def bollinger_band_position(df: pd.DataFrame, window: int = 20, std: int = 2) -> pd.Series:
    """Normalized position of price within Bollinger Bands.

    Returns a value between 0 and 1 representing how close the closing
    price is to the upper band (1) or lower band (0).  NaNs are
    returned until enough data points are available.
    """
    bb = ta.volatility.BollingerBands(close=df["close"], window=window, window_dev=std)
    upper = bb.bollinger_hband()
    lower = bb.bollinger_lband()
    return (df["close"] - lower) / (upper - lower)


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range as a fraction of price.

    Returns ATR divided by close to provide a relative volatility measure.
    """
    indicator = ta.volatility.AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=window)
    atr_values = indicator.average_true_range()
    return atr_values / df["close"]


def adx(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average Directional Index indicating trend strength."""
    indicator = ta.trend.ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=window)
    return indicator.adx()


def stochastic(df: pd.DataFrame, window: int = 14, smooth_window: int = 3) -> pd.Series:
    """Stochastic oscillator %K line."""
    indicator = ta.momentum.StochasticOscillator(high=df["high"], low=df["low"], close=df["close"], window=window, smooth_window=smooth_window)
    return indicator.stoch()


def obv(df: pd.DataFrame) -> pd.Series:
    """On Balance Volume."""
    return ta.volume.OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"]).on_balance_volume()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume Weighted Average Price."""
    return ta.volume.VolumeWeightedAveragePrice(high=df["high"], low=df["low"], close=df["close"], volume=df["volume"]).volume_weighted_average_price()


def roc(df: pd.DataFrame, window: int = 12) -> pd.Series:
    """Rate of Change (percentage)."""
    return ta.momentum.ROCIndicator(close=df["close"], window=window).roc()


def cci(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    return ta.trend.CCIIndicator(high=df["high"], low=df["low"], close=df["close"], window=window).cci()