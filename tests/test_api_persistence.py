from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-stock-insight"))

from app import main
from backtesting.config import BacktestConfig
from backtesting.engine import run_backtest
from database import BacktestResult, Base, StockAnalysis
from database.session import get_db
from data.errors import InsufficientDataError


@pytest.fixture
def db_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sessions = []
    closed = []

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


def rising_prices(count=45):
    dates = pd.date_range("2025-01-01", periods=count)
    return pd.DataFrame({"Date": dates, "Close": [100 + i for i in range(count)]})


def sample_backtest():
    dates = [date(2024, 10, 1) + timedelta(days=i) for i in range(150)]
    values = []
    for idx in range(len(dates)):
        if idx < 102:
            values.append(100 + idx * 0.5)
        elif idx < 120:
            values.append(values[-1] - 1.5)
        else:
            values.append(values[-1] + 0.5)
    frame = pd.DataFrame({"Date": dates, "Open": [v - 1 for v in values], "Close": values})
    config = BacktestConfig(ticker="AAPL", start_date=date(2025, 1, 1), end_date=date(2025, 2, 15))
    return run_backtest(config, data_loader=lambda *args, **kwargs: frame.copy())


def test_analysis_persists_each_successful_request_and_preserves_response(monkeypatch, db_context):
    factory, sessions, closed, _ = db_context
    monkeypatch.setattr(main, "fetch_stock_data", lambda *args, **kwargs: rising_prices())
    with TestClient(main.app) as client:
        first = client.get("/analysis/aapl")
        second = client.get("/analysis/AAPL")
    assert first.status_code == second.status_code == 200
    assert set(first.json()) == {"ticker", "signal", "score", "breakdown", "close", "market_date", "retrieved_at"}
    with factory() as db:
        rows = db.query(StockAnalysis).filter_by(ticker="AAPL").all()
        assert len(rows) == 2
        assert rows[0].breakdown == first.json()["breakdown"]
        assert rows[0].close == first.json()["close"]
    assert len(closed) == len(sessions) == 2


def test_ranking_persists_each_successful_stock_once(monkeypatch, db_context):
    factory, _, _, _ = db_context
    prices = rising_prices()
    monkeypatch.setattr(main, "fetch_many", lambda *args, **kwargs: ({"AAPL": prices}, {}))
    response = TestClient(main.app).post("/ranking", json={"tickers": ["AAPL"]})
    assert response.status_code == 200
    assert set(response.json()) == {"results", "errors", "retrieved_at"}
    with factory() as db:
        assert db.query(StockAnalysis).filter_by(ticker="AAPL").count() == 1


def test_backtest_persists_summary_and_full_json_payload(monkeypatch, db_context):
    factory, _, _, _ = db_context
    result = sample_backtest()
    monkeypatch.setattr(main, "run_backtest", lambda config: result)
    request = {"ticker": "AAPL", "start_date": "2021-01-01", "end_date": "2021-02-01"}
    response = TestClient(main.app).post("/backtest", json=request)
    assert response.status_code == 200
    assert response.json()["ticker"] == result["ticker"]
    with factory() as db:
        saved = db.query(BacktestResult).one()
        assert saved.results == response.json()
        assert saved.results["equity_curve"]
        assert saved.results["trades"]
        assert saved.results["signals"]
        assert saved.strategy_configuration == response.json()["configuration"]


def test_failed_calculations_are_not_persisted(monkeypatch, db_context):
    factory, _, _, _ = db_context
    monkeypatch.setattr(main, "fetch_stock_data", lambda *args, **kwargs: pd.DataFrame({"Date": pd.date_range("2025-01-01", periods=10), "Close": range(100, 110)}))
    monkeypatch.setattr(main, "run_backtest", lambda config: (_ for _ in ()).throw(InsufficientDataError()))
    client = TestClient(main.app)
    assert client.get("/analysis/AAPL").status_code == 422
    backtest = client.post("/backtest", json={"ticker": "AAPL", "start_date": "2021-01-01", "end_date": "2021-02-01"})
    assert backtest.status_code == 422
    with factory() as db:
        assert db.query(StockAnalysis).count() == 0
        assert db.query(BacktestResult).count() == 0


def test_database_failure_rolls_back_returns_controlled_error_and_closes(monkeypatch, db_context):
    factory, sessions, closed, engine = db_context
    monkeypatch.setattr(main, "fetch_stock_data", lambda *args, **kwargs: rising_prices())

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO STOCK_ANALYSES"):
            raise RuntimeError("simulated database failure")

    event.listen(engine, "before_cursor_execute", fail_insert)
    try:
        response = TestClient(main.app).get("/analysis/AAPL")
    finally:
        event.remove(engine, "before_cursor_execute", fail_insert)
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "Internal server error."}}
    assert sessions and len(closed) == len(sessions) == 1
    with factory() as db:
        assert db.query(StockAnalysis).count() == 0
