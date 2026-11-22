from datetime import date
import threading
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from data import fetcher
from data.errors import InsufficientDataError, InvalidTickerError, NoMarketDataError, ProviderUnavailableError
from signals.indicators import add_momentum, add_moving_averages, add_rsi, add_volatility
from signals.strategy import ScoreWeights, generate_score, generate_signal_label


client = TestClient(main.app)


def prices(values, dates=None):
    dates = dates if dates is not None else pd.date_range("2025-01-01", periods=len(values))
    return pd.DataFrame({"Date": dates, "Close": values})


def complete_pipeline(frame):
    frame = add_moving_averages(frame)
    frame = add_rsi(frame)
    frame = add_momentum(frame)
    frame = add_volatility(frame)
    return generate_score(frame)


def test_indicator_windows_and_rsi_edge_values():
    rising = prices([10 + i for i in range(30)])
    enriched = add_rsi(add_moving_averages(rising))
    assert pd.isna(enriched.loc[18, "MA_LONG"])
    assert enriched.loc[19, "MA_LONG"] == pytest.approx(sum(range(10, 30)) / 20)
    assert enriched.loc[14, "RSI"] == 100
    flat = add_rsi(prices([10] * 20))
    assert flat.loc[14, "RSI"] == 50
    # Exactly 30 and 70 are neutral by the documented strict threshold rule.
    assert generate_score(pd.DataFrame({"MA_SHORT": [1, 1], "MA_LONG": [1, 1], "RSI": [30, 70], "MOMENTUM": [0, 0]}))["SCORE_RSI"].tolist() == [0, 0]


def test_equal_moving_averages_and_configurable_weight_normalization():
    frame = pd.DataFrame({"MA_SHORT": [2, 1], "MA_LONG": [2, 2], "RSI": [50, 50], "MOMENTUM": [0, 0]})
    scored = generate_score(frame)
    assert scored.loc[0, "SCORE_TREND"] == 0
    assert scored.loc[1, "SCORE_TREND"] == -1
    weighted = generate_score(pd.DataFrame({"MA_SHORT": [2], "MA_LONG": [1], "RSI": [50], "MOMENTUM": [-1]}), ScoreWeights(10, 0, 0))
    assert weighted.loc[0, "Score"] == 3
    assert weighted.loc[0, "ScoreBreakdown"]["trend"] == 3
    assert generate_signal_label(weighted.loc[0, "Score"]) == "Strong Buy"
    for values in ((-1, 1, 1), (float("inf"), 0, 0), (float("nan"), 1, 1), (0, 0, 0)):
        with pytest.raises(ValueError):
            generate_score(frame, ScoreWeights(*values))


def test_missing_momentum_nan_and_infinite_values():
    with pytest.raises(ValueError, match="Missing required indicators"):
        generate_score(pd.DataFrame({"MA_SHORT": [1], "MA_LONG": [1], "RSI": [50]}))
    missing = generate_score(pd.DataFrame({"MA_SHORT": [1, 1], "MA_LONG": [1, 1], "RSI": [50, float("nan")], "MOMENTUM": [0, 0]}))
    assert pd.isna(missing.loc[1, "Score"])
    with pytest.raises(ValueError, match="finite"):
        generate_score(pd.DataFrame({"MA_SHORT": [float("inf")], "MA_LONG": [1], "RSI": [50], "MOMENTUM": [0]}))
    with pytest.raises(ValueError, match="finite"):
        add_rsi(prices([10, float("inf"), 12]))


def test_future_price_changes_do_not_change_prior_indicators_scores_or_signals():
    frame = prices([100 + (i % 7) * 2 + i for i in range(60)])
    changed = frame.copy()
    changed.loc[59, "Close"] = 1000
    original = complete_pipeline(frame)
    perturbed = complete_pipeline(changed)
    for column in ("RSI", "MOMENTUM", "VOLATILITY", "Score"):
        pd.testing.assert_series_equal(original.loc[:58, column], perturbed.loc[:58, column], check_names=False)
    assert [generate_signal_label(x) for x in original.loc[:58, "Score"]] == [generate_signal_label(x) for x in perturbed.loc[:58, "Score"]]


def test_insufficient_history_unsorted_dates_and_duplicate_dates():
    short = complete_pipeline(prices(list(range(10, 25))))
    assert short["Score"].isna().all()
    dates = pd.to_datetime(["2025-01-03", "2025-01-01", "2025-01-02", "2025-01-02"])
    normalized = add_moving_averages(prices([30, 10, 20, 21], dates), short=2, long=3)
    assert normalized["Date"].is_monotonic_increasing
    assert not normalized["Date"].duplicated().any()
    assert normalized.iloc[0]["Close"] == 10
    assert normalized.iloc[1]["Close"] == 21


def test_fetch_validates_ticker_and_normalizes_provider_frame(monkeypatch):
    with pytest.raises(InvalidTickerError):
        fetcher.validate_ticker("BAD TICKER!")
    raw = pd.DataFrame({("Close", "AAPL"): [11, 10, 12]}, index=pd.to_datetime(["2025-01-03", "2025-01-01", "2025-01-02"]))
    monkeypatch.setattr(fetcher.yf, "download", lambda *a, **k: raw)
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
    out = fetcher.fetch_stock_data("aapl", retries=0, request_interval=0)
    assert out.Date.tolist() == [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    assert out.Close.tolist() == [10, 12, 11]


def test_fetch_retries_with_exponential_backoff_and_jitter(monkeypatch):
    attempts, delays = [], []
    raw = pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2025-01-01"]))
    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("429 rate limit")
        return raw
    monkeypatch.setattr(fetcher.yf, "download", flaky)
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
    fetcher.fetch_stock_data("AAPL", retries=2, backoff=0.5, jitter=0.2, request_interval=0, sleep=delays.append, random_uniform=lambda a, b: b)
    assert len(attempts) == 3
    assert delays == [0.7, 1.2]


def test_retry_exhaustion_and_nonretryable_provider_error(monkeypatch):
    calls = []
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
    monkeypatch.setattr(fetcher.yf, "download", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(RuntimeError("503 temporarily unavailable")))
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=1, request_interval=0, backoff=0, jitter=0, sleep=lambda _: None)
    assert len(calls) == 2
    calls.clear()
    monkeypatch.setattr(fetcher.yf, "download", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(RuntimeError("bad request")))
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=4, request_interval=0)
    assert len(calls) == 1
    monkeypatch.setattr(fetcher.yf, "download", lambda *a, **k: pd.DataFrame())
    with pytest.raises(NoMarketDataError):
        fetcher.fetch_stock_data("AAPL", retries=3, request_interval=0)


def test_fetch_many_bounds_concurrency_deduplicates_and_preserves_order(monkeypatch):
    active = maximum = 0
    lock = threading.Lock()
    def fetch(ticker, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        if ticker == "BAD":
            raise ProviderUnavailableError()
        return ticker
    monkeypatch.setattr(fetcher, "fetch_stock_data", fetch)
    results, errors = fetcher.fetch_many(["C", "BAD", "A", "C", "B"], max_workers=2)
    assert maximum <= 2
    assert list(results) == ["C", "A", "B"]
    assert list(errors) == ["BAD"]


def test_request_throttle_spaces_provider_calls(monkeypatch):
    clock = iter([1.0, 1.0, 1.1, 1.5])
    waits = []
    monkeypatch.setattr(fetcher.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(fetcher.time, "sleep", waits.append)
    fetcher._last_request = 0.0
    fetcher._throttle(0.5)
    fetcher._throttle(0.5)
    assert waits == pytest.approx([0.4])


def test_api_health_analysis_errors_and_date_schema(monkeypatch):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health").status_code == 200
    assert client.get("/analysis/bad ticker!").json()["error"]["code"] == "invalid_ticker"
    assert client.get("/analysis/AAPL?period=bad").status_code == 422
    monkeypatch.setattr(main, "fetch_stock_data", lambda *a, **k: prices([100 + i for i in range(40)]))
    response = client.get("/analysis/aapl")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["market_date"] == "2025-02-09"
    assert "T" not in body["market_date"]
    assert body["retrieved_at"].endswith("Z") or "+00:00" in body["retrieved_at"]
    assert set(body["breakdown"]) == {"trend", "rsi", "momentum"}
    monkeypatch.setattr(main, "fetch_stock_data", lambda *a, **k: prices(list(range(10, 25))))
    assert client.get("/analysis/AAPL").json()["error"]["code"] == "insufficient_data"
    monkeypatch.setattr(main, "fetch_stock_data", lambda *a, **k: (_ for _ in ()).throw(NoMarketDataError()))
    assert client.get("/analysis/AAPL").status_code == 404
    monkeypatch.setattr(main, "fetch_stock_data", lambda *a, **k: (_ for _ in ()).throw(ProviderUnavailableError()))
    assert client.get("/analysis/AAPL").status_code == 502


def test_api_ranking_success_validation_partial_and_complete_failures(monkeypatch):
    enough = prices([100 + i for i in range(40)])
    monkeypatch.setattr(main, "fetch_many", lambda tickers, **kw: ({"AAPL": enough}, {}))
    response = client.post("/ranking", json={"tickers": ["AAPL"], "period": "6mo"})
    assert response.status_code == 200
    assert response.json()["results"][0]["ticker"] == "AAPL"
    assert "market_date" in response.json()["results"][0]
    assert client.post("/ranking", json={"tickers": ["bad ticker!"]}).json()["error"]["code"] == "invalid_ticker"
    assert client.post("/ranking", json={"tickers": ["AAPL"], "period": "bad"}).status_code == 422
    monkeypatch.setattr(main, "fetch_many", lambda tickers, **kw: ({"AAPL": enough}, {"MSFT": ProviderUnavailableError()}))
    partial = client.post("/ranking", json={"tickers": ["AAPL", "MSFT"]})
    assert partial.status_code == 200
    assert partial.json()["errors"]["MSFT"]["code"] == "provider_unavailable"
    monkeypatch.setattr(main, "fetch_many", lambda tickers, **kw: ({}, {"MSFT": ProviderUnavailableError()}))
    complete = client.post("/ranking", json={"tickers": ["MSFT"]})
    assert complete.status_code == 502
    assert complete.json()["error"]["code"] == "provider_unavailable"
    monkeypatch.setattr(main, "fetch_many", lambda tickers, **kw: ({}, {"MSFT": InsufficientDataError()}))
    assert client.post("/ranking", json={"tickers": ["MSFT"]}).status_code == 422
    openapi = client.get("/openapi.json").json()
    assert "RankingResponse" in openapi["components"]["schemas"]
    assert "HealthResponse" in openapi["components"]["schemas"]
