"""Backtest configuration and strategy rules, independent of the web API."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import math

from signals.indicators import DEFAULT_INDICATOR_WINDOWS, IndicatorWindows
from signals.strategy import ScoreWeights

ALLOWED_SIGNALS = {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}


@dataclass(frozen=True)
class StrategyRules:
    entry_signals: tuple[str, ...] = ("Buy", "Strong Buy")
    exit_signals: tuple[str, ...] = ("Sell", "Strong Sell")

    def __post_init__(self):
        if not self.entry_signals or not self.exit_signals:
            raise ValueError("Entry and exit signal sets must not be empty")
        if not set(self.entry_signals) <= ALLOWED_SIGNALS or not set(self.exit_signals) <= ALLOWED_SIGNALS:
            raise ValueError("Strategy contains an unknown signal")
        if set(self.entry_signals) & set(self.exit_signals):
            raise ValueError("Entry and exit signals must not overlap")
        if "Hold" in self.entry_signals or "Hold" in self.exit_signals:
            raise ValueError("Hold cannot be an entry or exit signal")


@dataclass(frozen=True)
class BacktestConfig:
    ticker: str
    start_date: date
    end_date: date
    initial_capital: float = 10_000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.001
    position_size_fraction: float = 1.0
    fractional_shares: bool = True
    weights: ScoreWeights = ScoreWeights()
    strategy: StrategyRules = StrategyRules()
    indicator_windows: IndicatorWindows = DEFAULT_INDICATOR_WINDOWS
    warmup_days: int | None = None

    @property
    def effective_warmup_days(self) -> int:
        return self.warmup_days if self.warmup_days is not None else self.indicator_windows.warmup_calendar_days

    def __post_init__(self):
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if self.end_date > datetime.now(timezone.utc).date():
            raise ValueError("end_date cannot be in the future")
        if not math.isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive and finite")
        for name in ("commission_rate", "slippage_rate"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must be finite and in [0, 1)")
        if not math.isfinite(self.position_size_fraction) or not 0 < self.position_size_fraction <= 1:
            raise ValueError("position_size_fraction must be in (0, 1]")
        if self.warmup_days is not None and (
            isinstance(self.warmup_days, bool) or not isinstance(self.warmup_days, int) or self.warmup_days < 0
        ):
            raise ValueError("warmup_days must be a nonnegative integer")
