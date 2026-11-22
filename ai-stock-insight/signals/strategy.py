"""Deterministic technical scoring with explicit readiness and normalized weights."""

from dataclasses import dataclass
import math

import pandas as pd


@dataclass(frozen=True)
class ScoreWeights:
    """Nonnegative component weights; scores are normalized to the default -3..+3 scale."""

    trend: float = 1.0
    rsi: float = 1.0
    momentum: float = 1.0

    def __post_init__(self):
        values = (self.trend, self.rsi, self.momentum)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0 for value in values):
            raise ValueError("Scoring weights must be finite nonnegative numbers")
        total_weight = sum(float(value) for value in values)
        if not math.isfinite(total_weight) or total_weight <= 0:
            raise ValueError("At least one scoring weight must be positive")


REQUIRED_INDICATORS = ("MA_SHORT", "MA_LONG", "RSI", "MOMENTUM")


def generate_score(df: pd.DataFrame, weights: ScoreWeights | None = None) -> pd.DataFrame:
    """Score rows only when every required indicator is finite.

    Trend contributes +1/0/-1 for MA_SHORT above/equal/below MA_LONG. RSI contributes
    +1 below 30, -1 above 70, else 0. Momentum contributes its sign. Weighted component
    values are normalized by total weight and scaled to retain the default -3..+3 range,
    so Buy/Sell cutoffs remain meaningful for arbitrary positive weight combinations.
    """
    weights = weights or ScoreWeights()
    missing = set(REQUIRED_INDICATORS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required indicators: {', '.join(sorted(missing))}")
    result = df.copy()
    if "Date" in result:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce")
        result = result.dropna(subset=["Date"]).sort_values("Date")
        result = result.drop_duplicates(subset=["Date"], keep="last").reset_index(drop=True)
    indicators = result[list(REQUIRED_INDICATORS)].apply(pd.to_numeric, errors="coerce")
    if indicators.isin([float("inf"), float("-inf")]).any().any():
        raise ValueError("Indicator values must be finite or missing")
    if ((indicators["RSI"].dropna() < 0) | (indicators["RSI"].dropna() > 100)).any():
        raise ValueError("RSI values must be between 0 and 100")
    result[list(REQUIRED_INDICATORS)] = indicators
    ready = indicators.notna().all(axis=1)
    trend = pd.Series(0.0, index=result.index)
    trend.loc[ready & indicators["MA_SHORT"].gt(indicators["MA_LONG"])] = 1.0
    trend.loc[ready & indicators["MA_SHORT"].lt(indicators["MA_LONG"])] = -1.0
    rsi = pd.Series(0.0, index=result.index)
    rsi.loc[ready & indicators["RSI"].lt(30)] = 1.0
    rsi.loc[ready & indicators["RSI"].gt(70)] = -1.0
    momentum = pd.Series(0.0, index=result.index)
    momentum.loc[ready & indicators["MOMENTUM"].gt(0)] = 1.0
    momentum.loc[ready & indicators["MOMENTUM"].lt(0)] = -1.0
    scale = 3.0 / sum((float(weights.trend), float(weights.rsi), float(weights.momentum)))
    result["SCORE_TREND"] = trend * weights.trend * scale
    result["SCORE_RSI"] = rsi * weights.rsi * scale
    result["SCORE_MOMENTUM"] = momentum * weights.momentum * scale
    result["Score"] = result[["SCORE_TREND", "SCORE_RSI", "SCORE_MOMENTUM"]].sum(axis=1).where(ready)
    result["ScoreBreakdown"] = result.apply(
        lambda row: {
            "trend": float(row["SCORE_TREND"]),
            "rsi": float(row["SCORE_RSI"]),
            "momentum": float(row["SCORE_MOMENTUM"]),
        } if pd.notna(row["Score"]) else None,
        axis=1,
    )
    return result


def generate_signal_label(score):
    if pd.isna(score):
        return "Insufficient Data"
    if score >= 2:
        return "Strong Buy"
    if score >= 1:
        return "Buy"
    if score <= -2:
        return "Strong Sell"
    if score <= -1:
        return "Sell"
    return "Hold"
