"""Next-session order execution and cash/share/equity accounting."""

import math

import pandas as pd

from backtesting.config import BacktestConfig
from backtesting.strategy import action_for_signal


def _valid_price(value) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _execution_reference(row) -> tuple[float, str]:
    if "Open" in row and _valid_price(row["Open"]):
        return float(row["Open"]), "open"
    return float(row["Close"]), "close_fallback"


def simulate_portfolio(
    evaluation_data: pd.DataFrame,
    ticker: str,
    config: BacktestConfig,
) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """Execute close-generated signals at the next session open (close fallback).

    Fractional all-in sizing is the default. Commissions are charged on fill notional;
    slippage worsens fills by the configured fraction. Positions are marked at Close.
    Open positions are not force-liquidated at the end and are marked to market.
    """
    data = evaluation_data.reset_index(drop=True)
    cash = float(config.initial_capital)
    quantity = 0.0
    active = None
    pending = None
    trades, timeline, curve = [], [], []
    for index, row in data.iterrows():
        day = row["Date"]
        execution_action = "none"
        execution_price_type = None
        executed_signal = pending["signal"] if pending is not None else None
        executed_from_date = pending["signal_date"] if pending is not None else None
        if pending is not None:
            reference, execution_price_type = _execution_reference(row)
            if pending["action"] == "buy" and quantity == 0:
                fill = reference * (1 + config.slippage_rate)
                budget = cash * config.position_size_fraction
                shares = budget / (fill * (1 + config.commission_rate))
                if not config.fractional_shares:
                    shares = math.floor(shares)
                if shares > 0:
                    commission = shares * fill * config.commission_rate
                    slippage_cost = shares * (fill - reference)
                    cash -= shares * fill + commission
                    if abs(cash) < 1e-8:
                        cash = 0.0
                    quantity = shares
                    active = {
                        "entry_date": day,
                        "entry_signal": pending["signal"],
                        "entry_price": fill,
                        "entry_reference": reference,
                        "entry_commission": commission,
                        "entry_slippage": slippage_cost,
                        "entry_index": index,
                        "quantity": shares,
                    }
                    execution_action = "buy"
                else:
                    execution_action = "buy_rejected_insufficient_cash"
            elif pending["action"] == "sell" and quantity > 0 and active is not None:
                fill = reference * (1 - config.slippage_rate)
                commission = quantity * fill * config.commission_rate
                slippage_cost = quantity * (reference - fill)
                cash += quantity * fill - commission
                gross_pnl = (reference - active["entry_reference"]) * quantity
                costs = active["entry_commission"] + active["entry_slippage"] + commission + slippage_cost
                net_pnl = gross_pnl - costs
                entry_basis = active["entry_reference"] * quantity + active["entry_commission"] + active["entry_slippage"]
                trades.append({
                    "ticker": ticker,
                    "entry_date": active["entry_date"],
                    "exit_date": day,
                    "entry_signal": active["entry_signal"],
                    "exit_signal": pending["signal"],
                    "entry_price": active["entry_price"],
                    "exit_price": fill,
                    "quantity": quantity,
                    "transaction_costs": costs,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "return_pct": net_pnl / entry_basis if entry_basis else None,
                    "holding_period_sessions": index - active["entry_index"],
                    "entry_commission": active["entry_commission"],
                    "exit_commission": commission,
                    "entry_slippage_cost": active["entry_slippage"],
                    "exit_slippage_cost": slippage_cost,
                })
                quantity, active = 0.0, None
                execution_action = "sell"

        signal = row["Signal"]
        requested_action = action_for_signal(signal, quantity > 0, config.strategy)
        next_date = data.iloc[index + 1]["Date"] if index + 1 < len(data) else None
        timeline.append({
            "date": day,
            "score": float(row["Score"]) if pd.notna(row["Score"]) else None,
            "signal": signal,
            "action": requested_action,
            "execution_date": next_date,
            "execution_action": execution_action,
            "execution_price_type": execution_price_type,
            "executed_signal": executed_signal,
            "executed_from_date": executed_from_date,
        })
        close = float(row["Close"])
        market_value = quantity * close
        equity = cash + market_value
        curve.append({
            "date": day,
            "cash": cash,
            "shares": quantity,
            "position_market_value": market_value,
            "total_equity": equity,
            "daily_return": None,
            "cumulative_return": equity / config.initial_capital - 1,
        })
        pending = {"action": requested_action, "signal": signal, "signal_date": day} if requested_action in {"buy", "sell"} and next_date is not None else None
    for index in range(1, len(curve)):
        curve[index]["daily_return"] = curve[index]["total_equity"] / curve[index - 1]["total_equity"] - 1
    return pd.DataFrame(curve), trades, timeline
