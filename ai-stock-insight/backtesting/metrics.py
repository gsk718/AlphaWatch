"""Return, risk, trade, and benchmark metric calculations."""

import math

import numpy as np
import pandas as pd

from data.errors import BenchmarkUnavailableError, IncompleteBenchmarkDataError

TRADING_DAYS_PER_YEAR = 252


def _return_metrics(equity: pd.Series, initial_capital: float) -> dict:
    if equity.empty:
        raise ValueError("Equity curve must contain at least one observation")
    equity = pd.to_numeric(equity, errors="coerce").astype(float)
    if equity.isna().any() or not np.isfinite(equity.to_numpy()).all() or (equity <= 0).any():
        raise ValueError("Equity observations must be positive finite values without gaps")
    final_value = float(equity.iloc[-1])
    total_return = final_value / initial_capital - 1.0
    daily_returns = equity.pct_change(fill_method=None).dropna()
    observations = len(daily_returns)
    annualized_return = (final_value / initial_capital) ** (TRADING_DAYS_PER_YEAR / observations) - 1.0 if observations >= 2 else None
    drawdown = equity / equity.cummax() - 1.0
    volatility = float(daily_returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR)) if observations >= 2 else None
    daily_std = daily_returns.std(ddof=1) if observations >= 2 else 0.0
    sharpe = float(daily_returns.mean() / daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)) if observations >= 2 and daily_std > 0 else None
    downside = np.minimum(daily_returns.to_numpy(), 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(TRADING_DAYS_PER_YEAR)) if observations else None
    return {
        "final_portfolio_value": final_value,
        "total_return": float(total_return),
        "annualized_return": float(annualized_return) if annualized_return is not None else None,
        "average_daily_return": float(daily_returns.mean()) if observations else None,
        "maximum_drawdown": float(drawdown.min()),
        "annualized_volatility": volatility,
        "sharpe_ratio": sharpe,
        "downside_deviation": downside_deviation,
    }


def calculate_performance(equity: pd.Series, trades: list[dict], initial_capital: float) -> dict:
    """Metrics use 252 sessions/year, zero risk-free rate, and net completed trade P/L."""
    metrics = _return_metrics(equity, initial_capital)
    wins = [trade["net_pnl"] for trade in trades if trade["net_pnl"] > 0]
    losses = [trade["net_pnl"] for trade in trades if trade["net_pnl"] < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (None if not wins else None)
    metrics.update({
        "initial_capital": float(initial_capital),
        "completed_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / len(trades) if trades else None,
        "average_winning_trade": float(np.mean(wins)) if wins else None,
        "average_losing_trade": float(np.mean(losses)) if losses else None,
        "average_holding_period_sessions": float(np.mean([t["holding_period_sessions"] for t in trades])) if trades else None,
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
    })
    return metrics


def compare_benchmark(strategy_curve: pd.DataFrame, benchmark_prices: pd.DataFrame, initial_capital: float) -> tuple[dict, list[dict]]:
    """Compare only complete date-aligned daily series; reject any missing benchmark session."""
    strategy = strategy_curve.set_index("date")["total_equity"].astype(float).sort_index()
    benchmark = benchmark_prices.set_index("Date")["Close"].astype(float).sort_index()
    if strategy.empty:
        raise BenchmarkUnavailableError()
    if strategy.index.has_duplicates or benchmark.index.has_duplicates:
        raise IncompleteBenchmarkDataError()
    start_date, end_date = strategy.index.min(), strategy.index.max()
    benchmark = benchmark[(benchmark.index >= start_date) & (benchmark.index <= end_date)]
    if not strategy.index.equals(benchmark.index):
        raise IncompleteBenchmarkDataError()
    aligned = benchmark.reindex(strategy.index)
    if aligned.isna().any() or (aligned <= 0).any() or not np.isfinite(aligned.to_numpy()).all():
        raise IncompleteBenchmarkDataError()
    common = pd.DataFrame({"strategy": strategy, "benchmark_close": aligned}, index=strategy.index)
    common_strategy = initial_capital * common["strategy"] / common["strategy"].iloc[0]
    benchmark_equity = initial_capital * common["benchmark_close"] / common["benchmark_close"].iloc[0]
    strategy_metrics = _return_metrics(common_strategy, initial_capital)
    benchmark_metrics = _return_metrics(benchmark_equity, initial_capital)
    result = {
        "evaluation_dates": len(common),
        "comparison_start_date": common.index[0].isoformat() if hasattr(common.index[0], "isoformat") else str(common.index[0]),
        "comparison_end_date": common.index[-1].isoformat() if hasattr(common.index[-1], "isoformat") else str(common.index[-1]),
        "strategy_total_return": strategy_metrics["total_return"],
        "strategy_annualized_return": strategy_metrics["annualized_return"],
        "strategy_maximum_drawdown": strategy_metrics["maximum_drawdown"],
        "benchmark_total_return": benchmark_metrics["total_return"],
        "benchmark_annualized_return": benchmark_metrics["annualized_return"],
        "benchmark_maximum_drawdown": benchmark_metrics["maximum_drawdown"],
        "benchmark_symbol": "SPY",
        "benchmark_price_basis": "SPY Close with auto_adjust=False; dividend-adjusted total returns excluded",
    }
    curve = [{"date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx), "strategy_equity": float(common_strategy.loc[idx]), "benchmark_equity": float(benchmark_equity.loc[idx])} for idx in common.index]
    return result, curve
