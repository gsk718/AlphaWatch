"""FastAPI persistence and history behavior against PostgreSQL."""

from datetime import date, timedelta
import json
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from backtesting.api_schemas import BacktestResponse
from test_api_persistence import sample_backtest


pytestmark = pytest.mark.postgres


def unique_ticker():
    return f"T{uuid4().hex[:10].upper()}"


def rising_prices():
    dates = pd.date_range("2025-01-01", periods=60)
    closes = [100.0 + index for index in range(len(dates))]
    return pd.DataFrame({"Date": dates, "Open": [value - 1 for value in closes], "Close": closes})


def test_analysis_persists_jsonb_across_http_requests(monkeypatch, postgres_dependency_override):
    ticker = unique_ticker()
    monkeypatch.setattr(main, "fetch_stock_data", lambda *args, **kwargs: rising_prices())
    client = TestClient(postgres_dependency_override)

    analysis = client.get(f"/analysis/{ticker.lower()}")
    assert analysis.status_code == 200
    body = analysis.json()
    assert set(body) == {"ticker", "signal", "score", "breakdown", "close", "market_date", "retrieved_at"}
    assert body["ticker"] == ticker
    assert isinstance(body["breakdown"], dict)

    history = client.get(f"/history/analyses/{ticker}")
    assert history.status_code == 200
    saved = history.json()
    assert saved["total"] == 1
    item = saved["items"][0]
    assert {key: item[key] for key in ("ticker", "signal", "score", "breakdown", "close", "market_date")} == {
        key: body[key] for key in ("ticker", "signal", "score", "breakdown", "close", "market_date")
    }
    assert item["breakdown"] == body["breakdown"]


def test_backtest_persists_response_jsonb_and_history_detail(monkeypatch, postgres_dependency_override):
    ticker = unique_ticker()
    result = sample_backtest()
    result["ticker"] = ticker
    monkeypatch.setattr(main, "run_backtest", lambda config: result)
    client = TestClient(postgres_dependency_override)

    response = client.post("/backtest", json={
        "ticker": ticker,
        "start_date": "2021-01-01",
        "end_date": "2021-02-01",
    })
    assert response.status_code == 200
    body = response.json()
    expected = json.loads(BacktestResponse.model_validate(result).model_dump_json())
    assert body == expected
    assert {"ticker", "configuration", "evaluation_period", "signal_coverage", "metrics", "benchmark",
            "equity_curve", "benchmark_equity_curve", "trades", "signals", "retrieved_at",
            "metric_assumptions"} == set(body)

    listed = client.get(f"/history/backtests?ticker={ticker}")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    summary = listed.json()["items"][0]
    assert summary["ticker"] == ticker
    assert summary["final_portfolio_value"] == body["metrics"]["final_portfolio_value"]
    assert summary["total_return"] == body["metrics"]["total_return"]
    assert "results" not in summary

    detail = client.get(f"/history/backtests/{summary['id']}")
    assert detail.status_code == 200
    assert detail.json() == body
    assert detail.json()["equity_curve"] == body["equity_curve"]
    assert detail.json()["trades"] == body["trades"]


def test_postgres_backtest_history_filter_pagination_and_missing_id(
    monkeypatch, postgres_dependency_override
):
    client = TestClient(postgres_dependency_override)
    ticker = unique_ticker()
    other_ticker = unique_ticker()
    result_template = sample_backtest()

    for requested_ticker, final_value in zip((ticker, ticker, ticker, other_ticker), (11000.0, 12000.0, 13000.0, 14000.0)):
        result = dict(result_template)
        result["ticker"] = requested_ticker
        result["metrics"] = dict(result_template["metrics"])
        result["metrics"]["final_portfolio_value"] = final_value
        monkeypatch.setattr(main, "run_backtest", lambda config, value=result: value)
        response = client.post("/backtest", json={
            "ticker": requested_ticker,
            "start_date": "2021-01-01",
            "end_date": "2021-02-01",
        })
        assert response.status_code == 200

    first = client.get(f"/history/backtests?ticker={ticker}&limit=1&offset=0")
    second = client.get(f"/history/backtests?ticker={ticker}&limit=1&offset=1")
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 3
    assert first.json()["items"][0]["ticker"] == ticker
    assert first.json()["items"][0]["final_portfolio_value"] == 13000.0
    assert second.json()["items"][0]["final_portfolio_value"] == 12000.0
    assert client.get(f"/history/backtests?ticker={other_ticker}").json()["total"] == 1
    assert client.get("/history/backtests/2147483647").status_code == 404


def test_analysis_history_pagination_and_inclusive_date_filter(monkeypatch, postgres_dependency_override):
    client = TestClient(postgres_dependency_override)
    ticker = unique_ticker()
    for shift in range(3):
        dates = pd.date_range(date(2025, 1, 1) + timedelta(days=shift), periods=60)
        closes = [100.0 + index for index in range(len(dates))]
        frame = pd.DataFrame({"Date": dates, "Open": [v - 1 for v in closes], "Close": closes})
        monkeypatch.setattr(main, "fetch_stock_data", lambda *args, data=frame, **kwargs: data)
        response = client.get(f"/analysis/{ticker}")
        assert response.status_code == 200

    page = client.get(f"/history/analyses/{ticker}?limit=1&offset=1")
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1
    filtered = client.get(f"/history/analyses/{ticker}?start_date=2025-03-01&end_date=2025-03-01")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
