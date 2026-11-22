"""Backtest orchestration; independent from FastAPI."""

from datetime import date, datetime, timezone
import logging
import math

import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.metrics import calculate_performance, compare_benchmark
from backtesting.portfolio import simulate_portfolio
from backtesting.strategy import build_signal_history
from data.errors import BenchmarkUnavailableError, InsufficientWarmupError, NoMarketDataError, ProviderUnavailableError
from data.fetcher import fetch_historical_data, validate_ticker

logger = logging.getLogger("alphawatch.backtest")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _safe_as_date(value):
    if pd.isna(value):
        return None
    try:
        return _as_date(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _clean_history(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Date" not in frame or "Close" not in frame:
        raise NoMarketDataError()
    result = frame.copy()
    result["Date"] = pd.Series([_safe_as_date(value) for value in result["Date"]], dtype=object)
    result = result.dropna(subset=["Date"])
    result["Close"] = pd.to_numeric(result["Close"], errors="coerce")
    result = result.dropna(subset=["Close"])
    result = result[result["Close"].map(lambda value: math.isfinite(float(value)) and value > 0)]
    if "Open" in result:
        result["Open"] = pd.to_numeric(result["Open"], errors="coerce")
        result.loc[~result["Open"].map(lambda value: pd.notna(value) and math.isfinite(float(value)) and value > 0), "Open"] = float("nan")
    result = result.sort_values("Date").drop_duplicates("Date", keep="last").reset_index(drop=True)
    return result


def run_backtest(config: BacktestConfig, data_loader=fetch_historical_data) -> dict:
    """Run the technical strategy and SPY comparison over an inclusive date interval."""
    ticker = validate_ticker(config.ticker)
    logger.info("Backtest started", extra={"operation": "backtest", "ticker": ticker})
    history = data_loader(ticker, config.start_date, config.end_date, warmup_days=config.effective_warmup_days)
    try:
        benchmark = data_loader("SPY", config.start_date, config.end_date, warmup_days=config.effective_warmup_days)
    except (NoMarketDataError, ProviderUnavailableError) as exc:
        raise BenchmarkUnavailableError() from exc
    if history.empty:
        raise NoMarketDataError()
    history = _clean_history(history)
    if history.empty:
        raise NoMarketDataError()
    scored = build_signal_history(history, config.weights, config.indicator_windows)
    scored["Date"] = pd.Series([_as_date(value) for value in scored["Date"]], dtype=object)
    evaluation = scored[(scored["Date"] >= config.start_date) & (scored["Date"] <= config.end_date)].copy().reset_index(drop=True)
    evaluation = evaluation.dropna(subset=["Close"])
    if evaluation.empty:
        raise NoMarketDataError()
    if evaluation["Score"].notna().sum() == 0:
        raise InsufficientWarmupError()
    missing_signal_dates = [date_value.isoformat() for date_value in evaluation.loc[evaluation["Score"].isna(), "Date"]]
    valid_signal_dates = evaluation.loc[evaluation["Score"].notna(), "Date"]
    warmup_observations = int((history["Date"] < config.start_date).sum())
    curve, trades, signals = simulate_portfolio(evaluation, ticker, config)
    equity = curve.set_index("date")["total_equity"]
    metrics = calculate_performance(equity, trades, config.initial_capital)
    try:
        benchmark = _clean_history(benchmark)
    except NoMarketDataError as exc:
        raise BenchmarkUnavailableError() from exc
    if benchmark.empty:
        raise BenchmarkUnavailableError()
    benchmark = benchmark[(benchmark["Date"] >= config.start_date) & (benchmark["Date"] <= config.end_date)]
    benchmark = benchmark.sort_values("Date").drop_duplicates("Date", keep="last")
    if benchmark.empty:
        raise BenchmarkUnavailableError()
    benchmark_comparison, benchmark_curve = compare_benchmark(curve, benchmark, config.initial_capital)
    return {
        "ticker": ticker,
        "configuration": {
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "initial_capital": config.initial_capital,
            "commission_rate": config.commission_rate,
            "slippage_rate": config.slippage_rate,
            "position_size_fraction": config.position_size_fraction,
            "fractional_shares": config.fractional_shares,
            "entry_signals": list(config.strategy.entry_signals),
            "exit_signals": list(config.strategy.exit_signals),
            "score_weights": {"trend": config.weights.trend, "rsi": config.weights.rsi, "momentum": config.weights.momentum},
            "indicator_windows": {
                "ma_short": config.indicator_windows.ma_short,
                "ma_long": config.indicator_windows.ma_long,
                "rsi_period": config.indicator_windows.rsi_period,
                "momentum_period": config.indicator_windows.momentum_period,
            },
            "effective_warmup_calendar_days": config.effective_warmup_days,
            "required_indicator_observations": config.indicator_windows.required_observations,
            "required_preperiod_observations": max(0, config.indicator_windows.required_observations - 1),
            "available_preperiod_observations": warmup_observations,
            "execution": "next session Open; falls back to that session Close if Open is missing or invalid",
            "price_basis": "yfinance OHLC with auto_adjust=False; dividend-adjusted total returns excluded",
        },
        "evaluation_period": {"start_date": _as_date(evaluation["Date"].iloc[0]).isoformat(), "end_date": _as_date(evaluation["Date"].iloc[-1]).isoformat()},
        "signal_coverage": {
            "evaluation_trading_dates": len(evaluation),
            "valid_signal_dates": int(evaluation["Score"].notna().sum()),
            "missing_signal_dates": missing_signal_dates,
            "warmup_status": "complete" if pd.notna(evaluation["Score"].iloc[0]) else "partial",
            "first_valid_signal_date": _as_date(valid_signal_dates.iloc[0]).isoformat(),
        },
        "metrics": metrics,
        "benchmark": benchmark_comparison,
        "equity_curve": [{**item, "date": _as_date(item["date"]).isoformat()} for item in curve.to_dict(orient="records")],
        "benchmark_equity_curve": benchmark_curve,
        "trades": [{**trade, "entry_date": _as_date(trade["entry_date"]).isoformat(), "exit_date": _as_date(trade["exit_date"]).isoformat()} for trade in trades],
        "signals": [{
            **signal,
            "date": _as_date(signal["date"]).isoformat(),
            "execution_date": _as_date(signal["execution_date"]).isoformat() if signal["execution_date"] else None,
            "executed_from_date": _as_date(signal["executed_from_date"]).isoformat() if signal["executed_from_date"] else None,
        } for signal in signals],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "metric_assumptions": {
            "annualization": "252 trading sessions per year",
            "sharpe_risk_free_rate": 0,
            "maximum_drawdown": "minimum equity / prior peak - 1",
            "benchmark": "SPY Close with auto_adjust=False; dividend-adjusted total returns excluded",
            "benchmark_alignment": "strategy and SPY must have identical evaluation dates or comparison fails",
            "equity_gaps": "missing, non-finite, or nonpositive equity observations are rejected",
            "open_positions": "marked to market at final Close; not force-liquidated and excluded from completed-trade statistics",
        },
    }
