from datetime import date, datetime, timezone
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-stock-insight"))

from app import main
from database import Base, StockAnalysis
from database.session import get_db


@pytest.fixture
def db_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def record(ticker, market_date, retrieved_at, score=1.0):
    return StockAnalysis(
        ticker=ticker,
        signal="Buy",
        score=score,
        breakdown={"trend": score},
        close=100.0 + score,
        market_date=market_date,
        retrieved_at=retrieved_at,
    )


def seed(factory, *records):
    with factory() as db:
        db.add_all(records)
        db.commit()


def test_history_empty_returns_empty_page(db_context):
    response = TestClient(main.app).get("/history/analyses")
    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 20, "offset": 0, "total": 0}


def test_history_filters_ticker_case_and_inclusive_dates(db_context):
    factory, *_ = db_context
    seed(factory,
         record("AAPL", date(2025, 1, 1), datetime(2025, 1, 1, tzinfo=timezone.utc)),
         record("AAPL", date(2025, 1, 2), datetime(2025, 1, 2, tzinfo=timezone.utc), 2),
         record("AAPL", date(2025, 1, 3), datetime(2025, 1, 3, tzinfo=timezone.utc), 3),
         record("MSFT", date(2025, 1, 2), datetime(2025, 1, 2, tzinfo=timezone.utc), 4))
    response = TestClient(main.app).get(
        "/history/analyses/aApL?start_date=2025-01-01&end_date=2025-01-02"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["ticker"] for item in body["items"]} == {"AAPL"}
    assert {item["market_date"] for item in body["items"]} == {"2025-01-01", "2025-01-02"}
    assert set(body["items"][0]) == {
        "id", "ticker", "signal", "score", "breakdown", "close", "market_date", "retrieved_at"
    }
    filtered = TestClient(main.app).get("/history/analyses?ticker=aapl")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 3
    assert {item["ticker"] for item in filtered.json()["items"]} == {"AAPL"}


def test_history_pagination_total_and_deterministic_ties(db_context):
    factory, *_ = db_context
    at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    seed(factory,
         record("AAPL", date(2025, 1, 2), at, 1),
         record("AAPL", date(2025, 1, 2), at, 2),
         record("MSFT", date(2025, 1, 3), at, 3))
    client = TestClient(main.app)
    first = client.get("/history/analyses?limit=2")
    second = client.get("/history/analyses?limit=2&offset=1")
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == 3
    assert [item["score"] for item in first.json()["items"]] == [3, 2]
    assert [item["score"] for item in second.json()["items"]] == [2, 1]


def test_history_rejects_invalid_date_ranges_and_pagination(db_context):
    client = TestClient(main.app)
    assert client.get("/history/analyses?start_date=2025-02-02&end_date=2025-02-01").status_code == 422
    assert client.get("/history/analyses?limit=0").status_code == 422
    assert client.get("/history/analyses?limit=101").status_code == 422
    assert client.get("/history/analyses?offset=-1").status_code == 422


def test_history_uses_and_closes_database_session(db_context):
    _, sessions, closed, _ = db_context
    response = TestClient(main.app).get("/history/analyses")
    assert response.status_code == 200
    assert len(sessions) == len(closed) == 1
