"""ORM models for retained AlphaWatch analysis and backtest results."""

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Date, DateTime, Float, Index, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class StockAnalysis(Base):
    """One point-in-time analysis; repeated analyses are retained separately."""

    __tablename__ = "stock_analyses"
    __table_args__ = (
        Index("ix_stock_analyses_ticker", "ticker"),
        Index("ix_stock_analyses_market_date", "market_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    signal: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(_JSON_TYPE, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestResult(Base):
    """A completed backtest, with queryable summary metrics and full response."""

    __tablename__ = "backtest_results"
    __table_args__ = (Index("ix_backtest_results_ticker", "ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    requested_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    evaluation_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    evaluation_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    final_portfolio_value: Mapped[float] = mapped_column(Float, nullable=False)
    total_return: Mapped[float] = mapped_column(Float, nullable=False)
    annualized_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return: Mapped[float] = mapped_column(Float, nullable=False)
    benchmark_annualized_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_maximum_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    strategy_configuration: Mapped[dict[str, Any]] = mapped_column(_JSON_TYPE, nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(_JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
