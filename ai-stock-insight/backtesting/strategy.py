"""Adapt the shared technical scoring engine into long-only trade intentions."""

from dataclasses import dataclass

import pandas as pd

from backtesting.config import StrategyRules
from signals.indicators import DEFAULT_INDICATOR_WINDOWS, IndicatorWindows, add_momentum, add_moving_averages, add_rsi
from signals.strategy import ScoreWeights, generate_score, generate_signal_label


@dataclass(frozen=True)
class SignalDecision:
    market_date: object
    score: float | None
    signal: str


def build_signal_history(
    prices: pd.DataFrame,
    weights: ScoreWeights | None = None,
    windows: IndicatorWindows = DEFAULT_INDICATOR_WINDOWS,
) -> pd.DataFrame:
    """Calculate indicators and the canonical AlphaWatch score over all warm-up + test rows."""
    frame = add_moving_averages(prices, short=windows.ma_short, long=windows.ma_long)
    frame = add_rsi(frame, period=windows.rsi_period)
    frame = add_momentum(frame, period=windows.momentum_period)
    scored = generate_score(frame, weights=weights)
    scored["Signal"] = scored["Score"].map(generate_signal_label)
    return scored


def action_for_signal(signal: str, invested: bool, rules: StrategyRules) -> str:
    if not invested and signal in rules.entry_signals:
        return "buy"
    if invested and signal in rules.exit_signals:
        return "sell"
    return "hold"
