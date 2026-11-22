"""PostgreSQL model and migration integration coverage."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

from database.models import BacktestResult, StockAnalysis


pytestmark = pytest.mark.postgres


def test_alembic_schema_tables_indexes_and_jsonb(postgres_engine):
    inspector = inspect(postgres_engine)

    assert {"stock_analyses", "backtest_results"} <= set(inspector.get_table_names())
    assert {"ix_stock_analyses_ticker", "ix_stock_analyses_market_date"} <= {
        index["name"] for index in inspector.get_indexes("stock_analyses")
    }
    assert {"ix_backtest_results_ticker"} <= {
        index["name"] for index in inspector.get_indexes("backtest_results")
    }

    stock_columns = {column["name"]: column["type"] for column in inspector.get_columns("stock_analyses")}
    backtest_columns = {
        column["name"]: column["type"] for column in inspector.get_columns("backtest_results")
    }
    assert isinstance(stock_columns["breakdown"], JSONB)
    assert isinstance(backtest_columns["strategy_configuration"], JSONB)
    assert isinstance(backtest_columns["results"], JSONB)


def test_stock_analysis_insert_read_and_timezone_round_trip(postgres_session):
    timestamp = datetime(2025, 7, 8, 9, 10, 11, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    row = StockAnalysis(
        ticker=f"T{uuid4().hex[:10].upper()}",
        signal="Buy",
        score=1.25,
        breakdown={"trend": 1.0, "nested": {"source": "integration"}},
        close=123.45,
        market_date=date(2025, 7, 8),
        retrieved_at=timestamp,
    )
    postgres_session.add(row)
    postgres_session.flush()

    loaded = postgres_session.get(StockAnalysis, row.id)
    assert loaded is not None
    assert loaded.ticker == row.ticker
    assert loaded.breakdown == {"trend": 1.0, "nested": {"source": "integration"}}
    assert loaded.retrieved_at.tzinfo is not None
    assert loaded.retrieved_at.astimezone(timezone.utc) == timestamp.astimezone(timezone.utc)


def test_backtest_result_insert_read_nested_json_and_timezone(postgres_session):
    timestamp = datetime(2024, 2, 3, 4, 5, 6, 789012, tzinfo=timezone.utc)
    payload = {
        "equity_curve": [{"date": "2024-02-03", "value": 10125.5, "meta": {"drawdown": 0.01}}],
        "trades": [{"entry": {"price": 100.0, "signal": {"name": "Buy"}}}],
    }
    row = BacktestResult(
        ticker=f"T{uuid4().hex[:10].upper()}",
        requested_start_date=date(2024, 1, 1),
        requested_end_date=date(2024, 3, 1),
        evaluation_start_date=date(2024, 1, 2),
        evaluation_end_date=date(2024, 2, 29),
        initial_capital=10000.0,
        final_portfolio_value=10125.5,
        total_return=0.01255,
        annualized_return=0.02,
        maximum_drawdown=0.01,
        sharpe_ratio=1.2,
        benchmark_return=0.01,
        benchmark_annualized_return=0.016,
        benchmark_maximum_drawdown=0.02,
        strategy_configuration={"strategy": {"name": "test", "parameters": {"window": 20}}},
        results=payload,
        created_at=timestamp,
    )
    postgres_session.add(row)
    postgres_session.flush()

    loaded = postgres_session.get(BacktestResult, row.id)
    assert loaded is not None
    assert loaded.strategy_configuration == {"strategy": {"name": "test", "parameters": {"window": 20}}}
    assert loaded.results == payload
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.astimezone(timezone.utc) == timestamp.astimezone(timezone.utc)


def test_api_dependency_commit_is_rolled_back_on_teardown(postgres_dependency_override, postgres_engine):
    from database.session import get_db
    from sqlalchemy.orm import Session

    ticker = f"T{uuid4().hex[:10].upper()}"
    dependency = postgres_dependency_override.dependency_overrides[get_db]()
    db = next(dependency)
    db.add(
        StockAnalysis(
            ticker=ticker,
            signal="Buy",
            score=1.0,
            breakdown={"source": "dependency override"},
            close=100.0,
            market_date=date(2025, 7, 8),
            retrieved_at=datetime(2025, 7, 8, tzinfo=timezone.utc),
        )
    )
    db.commit()
    dependency.close()

    with Session(postgres_engine) as check_session:
        assert check_session.query(StockAnalysis).filter_by(ticker=ticker).first() is None


def test_request_session_rollback_preserves_outer_transaction_and_prior_commit(postgres_dependency_override):
    from database.session import get_db
    from sqlalchemy import text

    ticker = f"T{uuid4().hex[:10].upper()}"
    override = postgres_dependency_override.dependency_overrides[get_db]

    first_request = override()
    first_db = next(first_request)
    first_db.add(
        StockAnalysis(
            ticker=ticker,
            signal="Buy",
            score=1.0,
            breakdown={"source": "first request"},
            close=100.0,
            market_date=date(2025, 7, 8),
            retrieved_at=datetime(2025, 7, 8, tzinfo=timezone.utc),
        )
    )
    first_db.commit()
    first_request.close()

    rollback_request = override()
    rollback_db = next(rollback_request)
    rollback_db.add(
        StockAnalysis(
            ticker=f"T{uuid4().hex[:10].upper()}",
            signal="Sell",
            score=0.0,
            breakdown={"source": "rolled back request"},
            close=90.0,
            market_date=date(2025, 7, 9),
            retrieved_at=datetime(2025, 7, 9, tzinfo=timezone.utc),
        )
    )
    rollback_db.flush()
    rollback_db.rollback()
    rollback_request.close()

    subsequent_request = override()
    subsequent_db = next(subsequent_request)
    try:
        assert subsequent_db.query(StockAnalysis).filter_by(ticker=ticker).one().breakdown == {
            "source": "first request"
        }
        assert subsequent_db.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        subsequent_request.close()
