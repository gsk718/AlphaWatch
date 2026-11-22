"""Point-in-time indicators. RSI uses the simple rolling-mean method (not Wilder smoothing)."""

from dataclasses import dataclass
import math

import pandas as pd


@dataclass(frozen=True)
class IndicatorWindows:
    ma_short: int = 5
    ma_long: int = 20
    rsi_period: int = 14
    momentum_period: int = 10

    def __post_init__(self):
        values = (self.ma_short, self.ma_long, self.rsi_period, self.momentum_period)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("Indicator window sizes must be integers")
        if self.ma_short < 1 or self.ma_long <= self.ma_short:
            raise ValueError("Moving average windows must satisfy 1 <= short < long")
        if self.rsi_period < 1 or self.momentum_period < 1:
            raise ValueError("RSI and momentum periods must be positive")

    @property
    def required_observations(self) -> int:
        # RSI and percent-change momentum need one more close than their change window.
        return max(self.ma_long, self.rsi_period + 1, self.momentum_period + 1)

    @property
    def warmup_calendar_days(self) -> int:
        # Approximate sessions-to-calendar conversion plus two weeks for weekends/holidays.
        return max(90, math.ceil(self.required_observations * 7 / 5) + 14)


DEFAULT_INDICATOR_WINDOWS = IndicatorWindows()


def _close(df: pd.DataFrame) -> pd.Series:
    if "Close" not in df:
        raise ValueError("Price data must contain a Close column")
    values = pd.to_numeric(df["Close"], errors="coerce")
    if values.empty or (values.dropna() <= 0).any() or values.isin([float("inf"), float("-inf")]).any():
        raise ValueError("Close prices must be positive finite numbers or missing")
    return values


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if "Date" in result:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
        result = result.dropna(subset=["Date"]).sort_values("Date")
        result = result.drop_duplicates(subset=["Date"], keep="last").reset_index(drop=True)
    return result


def add_moving_averages(df: pd.DataFrame, short: int = DEFAULT_INDICATOR_WINDOWS.ma_short, long: int = DEFAULT_INDICATOR_WINDOWS.ma_long) -> pd.DataFrame:
    if short < 1 or long < 1 or short >= long:
        raise ValueError("Moving average windows must satisfy 1 <= short < long")
    result = _prepare(df)
    close = _close(result)
    result["MA_SHORT"] = close.rolling(short, min_periods=short).mean()
    result["MA_LONG"] = close.rolling(long, min_periods=long).mean()
    return result


def add_rsi(df: pd.DataFrame, period: int = DEFAULT_INDICATOR_WINDOWS.rsi_period) -> pd.DataFrame:
    if period < 1:
        raise ValueError("RSI period must be positive")
    result = _prepare(df)
    close = _close(result)
    # A period needs `period` price changes, so the first valid value is at row `period`.
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    rs = gain.div(loss.where(loss.ne(0)))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((loss == 0) & (gain == 0), 50)
    result["RSI"] = rsi
    return result


def add_momentum(df: pd.DataFrame, period: int = DEFAULT_INDICATOR_WINDOWS.momentum_period) -> pd.DataFrame:
    if period < 1:
        raise ValueError("Momentum period must be positive")
    result = _prepare(df)
    close = _close(result)
    result["MOMENTUM"] = close.pct_change(period, fill_method=None)
    return result


def add_volatility(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    if period < 2:
        raise ValueError("Volatility period must be at least 2")
    result = _prepare(df)
    close = _close(result)
    returns = close.pct_change(fill_method=None)
    result["VOLATILITY"] = returns.rolling(period, min_periods=period).std(ddof=1)
    return result
