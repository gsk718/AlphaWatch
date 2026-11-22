"""Pydantic request/response contracts for the backtesting API."""

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SignalName = Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    start_date: date
    end_date: date
    initial_capital: float = Field(default=10_000, gt=0, allow_inf_nan=False)
    commission_rate: float = Field(default=0.001, ge=0, lt=1, allow_inf_nan=False)
    slippage_rate: float = Field(default=0.001, ge=0, lt=1, allow_inf_nan=False)
    position_size_fraction: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)
    fractional_shares: bool = True
    trend_weight: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    rsi_weight: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    momentum_weight: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    ma_short_window: int = Field(default=5, ge=1)
    ma_long_window: int = Field(default=20, ge=2)
    rsi_period: int = Field(default=14, ge=1)
    momentum_period: int = Field(default=10, ge=1)
    entry_signals: list[SignalName] = Field(default_factory=lambda: ["Buy", "Strong Buy"], min_length=1)
    exit_signals: list[SignalName] = Field(default_factory=lambda: ["Sell", "Strong Sell"], min_length=1)

    @model_validator(mode="after")
    def validate_strategy(self):
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if self.end_date > datetime.now(timezone.utc).date():
            raise ValueError("end_date cannot be in the future")
        if self.trend_weight + self.rsi_weight + self.momentum_weight <= 0:
            raise ValueError("At least one scoring weight must be positive")
        if self.ma_short_window >= self.ma_long_window:
            raise ValueError("ma_short_window must be less than ma_long_window")
        if "Hold" in self.entry_signals or "Hold" in self.exit_signals:
            raise ValueError("Hold cannot be an entry or exit signal")
        if set(self.entry_signals) & set(self.exit_signals):
            raise ValueError("Entry and exit signals must not overlap")
        return self


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class BacktestConfiguration(BaseModel):
    start_date: date
    end_date: date
    initial_capital: float
    commission_rate: float
    slippage_rate: float
    position_size_fraction: float
    fractional_shares: bool
    entry_signals: list[str]
    exit_signals: list[str]
    score_weights: dict[str, float]
    indicator_windows: dict[str, int]
    effective_warmup_calendar_days: int
    required_indicator_observations: int
    required_preperiod_observations: int
    available_preperiod_observations: int
    execution: str
    price_basis: str


class PerformanceMetrics(BaseModel):
    initial_capital: float
    final_portfolio_value: float
    total_return: float
    annualized_return: float | None
    average_daily_return: float | None
    maximum_drawdown: float
    annualized_volatility: float | None
    sharpe_ratio: float | None
    downside_deviation: float | None
    completed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None
    average_winning_trade: float | None
    average_losing_trade: float | None
    average_holding_period_sessions: float | None
    profit_factor: float | None


class BenchmarkMetrics(BaseModel):
    evaluation_dates: int
    comparison_start_date: date
    comparison_end_date: date
    strategy_total_return: float
    strategy_annualized_return: float | None
    strategy_maximum_drawdown: float
    benchmark_total_return: float
    benchmark_annualized_return: float | None
    benchmark_maximum_drawdown: float
    benchmark_symbol: str
    benchmark_price_basis: str


class EquityPoint(BaseModel):
    date: date
    cash: float
    shares: float
    position_market_value: float
    total_equity: float
    daily_return: float | None
    cumulative_return: float


class BenchmarkEquityPoint(BaseModel):
    date: date
    strategy_equity: float
    benchmark_equity: float


class TradeRecord(BaseModel):
    ticker: str
    entry_date: date
    exit_date: date
    entry_signal: SignalName
    exit_signal: SignalName
    entry_price: float
    exit_price: float
    quantity: float
    transaction_costs: float
    gross_pnl: float
    net_pnl: float
    return_pct: float | None
    holding_period_sessions: int
    entry_commission: float
    exit_commission: float
    entry_slippage_cost: float
    exit_slippage_cost: float


class SignalRecord(BaseModel):
    date: date
    score: float | None
    signal: str
    action: str
    execution_date: date | None
    execution_action: str
    execution_price_type: str | None
    executed_signal: str | None
    executed_from_date: date | None


class EvaluationPeriod(BaseModel):
    start_date: date
    end_date: date


class SignalCoverage(BaseModel):
    evaluation_trading_dates: int
    valid_signal_dates: int
    missing_signal_dates: list[date]
    warmup_status: Literal["complete", "partial"]
    first_valid_signal_date: date


class BacktestResponse(BaseModel):
    ticker: str
    configuration: BacktestConfiguration
    evaluation_period: EvaluationPeriod
    signal_coverage: SignalCoverage
    metrics: PerformanceMetrics
    benchmark: BenchmarkMetrics
    equity_curve: list[EquityPoint]
    benchmark_equity_curve: list[BenchmarkEquityPoint]
    trades: list[TradeRecord]
    signals: list[SignalRecord]
    retrieved_at: datetime
    metric_assumptions: dict[str, Any]
