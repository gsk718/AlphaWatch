from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-stock-insight"))

from app import main
from backtesting.api_schemas import BacktestResponse
from database import BacktestResult, Base
from database.session import get_db
from test_api_persistence import sample_backtest


@pytest.fixture
def db_context():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sessions, closed = [], []

    def override_get_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()
            closed.append(session)

    main.app.dependency_overrides[get_db] = override_get_db
    yield factory, sessions, closed, engine
    main.app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def saved_backtest(ticker="AAPL", created_at=None, value=12_000.0, results=None):
    return BacktestResult(
        ticker=ticker,
        requested_start_date=date(2024, 1, 1), requested_end_date=date(2024, 12, 31),
        evaluation_start_date=date(2024, 2, 1), evaluation_end_date=date(2024, 12, 31),
        initial_capital=10_000.0, final_portfolio_value=value, total_return=0.2,
        annualized_return=0.2, maximum_drawdown=-0.1, sharpe_ratio=1.2,
        benchmark_return=0.1, benchmark_annualized_return=0.1,
        benchmark_maximum_drawdown=-0.15, strategy_configuration={"sample": True},
        results=results or {}, created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def seed(factory, *records):
    with factory() as db:
        db.add_all(records)
        db.commit()
        return [record.id for record in records]


def test_empty_page_and_summary_excludes_full_payload(db_context):
    factory, *_ = db_context
    client = TestClient(main.app)
    assert client.get("/history/backtests").json() == {"items": [], "limit": 20, "offset": 0, "total": 0}
    seed(factory, saved_backtest(results={"large": ["payload"]}))
    response = client.get("/history/backtests")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item) == {
        "id", "ticker", "requested_start_date", "requested_end_date", "evaluation_start_date",
        "evaluation_end_date", "initial_capital", "final_portfolio_value", "total_return",
        "annualized_return", "maximum_drawdown", "sharpe_ratio", "benchmark_return",
        "benchmark_annualized_return", "benchmark_maximum_drawdown", "created_at",
    }
    assert "results" not in item and "large" not in response.text


def test_list_query_does_not_select_results_json_column(db_context):
    _, _, _, engine = db_context
    statements = []

    def capture_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_select)
    try:
        response = TestClient(main.app).get("/history/backtests")
    finally:
        event.remove(engine, "before_cursor_execute", capture_select)

    assert response.status_code == 200
    list_selects = [
        statement for statement in statements
        if "FROM backtest_results" in statement and "COUNT(" not in statement.upper()
    ]
    assert len(list_selects) == 1
    selected_columns = list_selects[0].split("FROM", 1)[0].lower()
    assert "backtest_results.results" not in selected_columns


def test_multiple_records_filter_normalization_pagination_and_total(db_context):
    factory, *_ = db_context
    at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    seed(factory, saved_backtest("AAPL", at, 1), saved_backtest("MSFT", at, 2), saved_backtest("AAPL", at, 3))
    client = TestClient(main.app)
    first = client.get("/history/backtests?ticker=aApL&limit=1")
    second = client.get("/history/backtests?ticker=AAPL&limit=1&offset=1")
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 2
    # Equal creation times are ordered by descending database ID.
    assert first.json()["items"][0]["final_portfolio_value"] == 3
    assert second.json()["items"][0]["final_portfolio_value"] == 1
    assert client.get("/history/backtests?ticker=NOPE").json()["total"] == 0


def test_detail_returns_complete_saved_backtest_and_404(db_context):
    factory, *_ = db_context
    payload = json.loads(BacktestResponse.model_validate(sample_backtest()).model_dump_json())
    record = saved_backtest(payload["ticker"], results=payload)
    backtest_id = seed(factory, record)[0]
    client = TestClient(main.app)
    response = client.get(f"/history/backtests/{backtest_id}")
    assert response.status_code == 200
    assert response.json() == payload
    missing = client.get("/history/backtests/9999")
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"].lower()


def test_invalid_pagination_and_session_cleanup(db_context):
    _, sessions, closed, _ = db_context
    client = TestClient(main.app)
    for params in ("limit=0", "limit=101", "offset=-1"):
        assert client.get(f"/history/backtests?{params}").status_code == 422
    assert client.get("/history/backtests").status_code == 200
    assert len(sessions) == len(closed) == 4
