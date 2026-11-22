from datetime import date, datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import Date, DateTime, Float, Integer, JSON, String, create_engine, inspect
from sqlalchemy.dialects.postgresql import JSONB, dialect as postgresql_dialect
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-stock-insight"))

from database import BacktestResult, Base, StockAnalysis


def test_models_are_importable_and_registered_in_shared_metadata():
    assert Base.metadata.tables["stock_analyses"] is StockAnalysis.__table__
    assert Base.metadata.tables["backtest_results"] is BacktestResult.__table__


def test_analysis_columns_types_json_and_indexes():
    columns = StockAnalysis.__table__.c
    assert isinstance(columns.id.type, Integer)
    assert isinstance(columns.ticker.type, String)
    assert isinstance(columns.score.type, Float)
    assert isinstance(columns.close.type, Float)
    assert isinstance(columns.market_date.type, Date)
    assert isinstance(columns.retrieved_at.type, DateTime)
    assert columns.retrieved_at.type.timezone
    assert isinstance(columns.breakdown.type, JSON)
    assert isinstance(columns.breakdown.type.dialect_impl(postgresql_dialect()), JSONB)
    assert {"ticker", "market_date"} <= {
        column.name for index in StockAnalysis.__table__.indexes for column in index.columns
    }


def test_backtest_summary_columns_json_types_and_ticker_index():
    columns = BacktestResult.__table__.c
    for name in ("requested_start_date", "requested_end_date", "evaluation_start_date", "evaluation_end_date"):
        assert isinstance(columns[name].type, Date)
    for name in ("initial_capital", "final_portfolio_value", "total_return", "annualized_return", "maximum_drawdown", "sharpe_ratio", "benchmark_return", "benchmark_annualized_return", "benchmark_maximum_drawdown"):
        assert isinstance(columns[name].type, Float)
    assert isinstance(columns.created_at.type, DateTime) and columns.created_at.type.timezone
    assert isinstance(columns.strategy_configuration.type, JSON)
    assert isinstance(columns.results.type, JSON)
    assert "ticker" in {column.name for index in BacktestResult.__table__.indexes for column in index.columns}


def test_sqlite_round_trip_nested_json_and_historical_records():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    breakdown = {"trend": {"score": 1.5, "signals": ["above_short_ma", "above_long_ma"]}, "rsi": {"value": 52.4}}
    payload = {"configuration": {"weights": {"trend": 1}}, "trades": [{"entry": {"date": "2025-01-02", "fees": [1, 2]}}]}
    with Session(engine) as session:
        session.add_all([
            StockAnalysis(ticker="AAPL", signal="Buy", score=1.5, breakdown=breakdown, close=210.0, market_date=date(2025, 1, 2), retrieved_at=datetime(2025, 1, 3, tzinfo=timezone.utc)),
            StockAnalysis(ticker="AAPL", signal="Hold", score=0.0, breakdown={"trend": {"score": 0}}, close=211.0, market_date=date(2025, 1, 3), retrieved_at=datetime(2025, 1, 4, tzinfo=timezone.utc)),
        ])
        session.add(BacktestResult(
            ticker="AAPL", requested_start_date=date(2025, 1, 1), requested_end_date=date(2025, 3, 1),
            evaluation_start_date=date(2025, 1, 2), evaluation_end_date=date(2025, 2, 28),
            initial_capital=10_000.0, final_portfolio_value=10_500.0, total_return=0.05,
            annualized_return=0.1, maximum_drawdown=-0.02, sharpe_ratio=1.2, benchmark_return=0.03,
            benchmark_annualized_return=0.06, benchmark_maximum_drawdown=-0.04,
            strategy_configuration=payload["configuration"], results=payload,
            created_at=datetime(2025, 3, 2, tzinfo=timezone.utc),
        ))
        session.commit()
        assert session.query(StockAnalysis).filter_by(ticker="AAPL").count() == 2
        assert session.query(StockAnalysis).filter_by(ticker="AAPL").order_by(StockAnalysis.id).first().breakdown == breakdown
        saved = session.query(BacktestResult).one()
        assert saved.results == payload
        assert {"backtest_results", "stock_analyses"} <= set(inspect(engine).get_table_names())
    engine.dispose()
