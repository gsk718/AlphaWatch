from datetime import date

import pandas as pd
import pytest

from data import fetcher
from data.errors import InvalidRequestError, ProviderUnavailableError


@pytest.fixture(autouse=True)
def clear_timeout_environment(monkeypatch):
    monkeypatch.setattr(fetcher, "_last_request", 0.0)
    for name in (
        "DATA_REQUEST_TIMEOUT_SECONDS",
        "DATA_FETCH_DEADLINE_SECONDS",
        "DATA_RETRIES",
        "DATA_RETRY_BACKOFF_SECONDS",
        "DATA_RETRY_JITTER_SECONDS",
        "DATA_REQUEST_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_configured_timeout_is_passed_to_standard_download(monkeypatch):
    monkeypatch.setenv("DATA_REQUEST_TIMEOUT_SECONDS", "8.5")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    seen = {}

    def download(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2025-01-01"]))

    monkeypatch.setattr(fetcher.yf, "download", download)
    fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)
    assert seen["timeout"] == 8.5


def test_configured_timeout_is_passed_to_historical_download(monkeypatch):
    monkeypatch.setenv("DATA_REQUEST_TIMEOUT_SECONDS", "6")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    seen = {}

    def download(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Open": [9], "Close": [10]}, index=pd.to_datetime(["2025-01-02"]))

    monkeypatch.setattr(fetcher.yf, "download", download)
    fetcher.fetch_historical_data("AAPL", date(2025, 1, 1), date(2025, 1, 3), warmup_days=0)
    assert seen["timeout"] == 6


def test_default_timeout_is_used_when_environment_variable_is_absent(monkeypatch):
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    seen = {}

    def download(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2025-01-01"]))

    monkeypatch.setattr(fetcher.yf, "download", download)
    fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)
    assert seen["timeout"] == 15


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number", "nan", "inf", "-inf"])
def test_invalid_timeout_configuration_is_rejected(monkeypatch, value):
    monkeypatch.setenv("DATA_REQUEST_TIMEOUT_SECONDS", value)
    with pytest.raises(InvalidRequestError, match="DATA_REQUEST_TIMEOUT_SECONDS"):
        fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)


def test_timeout_errors_follow_retry_policy_and_exhaust_to_provider_error(monkeypatch):
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    attempts = []

    def timeout(*args, **kwargs):
        attempts.append(kwargs["timeout"])
        raise TimeoutError("request timed out")

    monkeypatch.setattr(fetcher.yf, "download", timeout)
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data(
            "AAPL", retries=2, backoff=0, jitter=0, request_interval=0,
            sleep=lambda _: None, random_uniform=lambda low, high: 0,
        )
    assert attempts == [15, 15, 15]


def test_fetch_deadline_defaults_to_30_and_rejects_invalid_values(monkeypatch):
    assert fetcher._fetch_deadline_seconds() == 30
    for value in ("0", "-1", "bad", "nan", "inf", "-inf"):
        monkeypatch.setenv("DATA_FETCH_DEADLINE_SECONDS", value)
        with pytest.raises(InvalidRequestError, match="DATA_FETCH_DEADLINE_SECONDS"):
            fetcher._fetch_deadline_seconds()


def _fake_clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(fetcher.time, "monotonic", lambda: now[0])
    def sleep(seconds):
        now[0] += seconds
    return now, sleep


def test_expired_before_first_attempt_does_not_call_provider(monkeypatch):
    ticks = iter([0.0, 31.0])
    monkeypatch.setattr(fetcher.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    calls = []
    monkeypatch.setattr(fetcher.yf, "download", lambda *a, **k: calls.append(1))
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)
    assert calls == []


def test_deadline_exhausted_during_throttle_does_not_call_provider(monkeypatch):
    now, sleep = _fake_clock(monkeypatch)
    monkeypatch.setenv("DATA_FETCH_DEADLINE_SECONDS", "1")
    fetcher._last_request = 2.0
    monkeypatch.setattr(fetcher.time, "sleep", sleep)
    calls = []
    monkeypatch.setattr(fetcher.yf, "download", lambda *a, **k: calls.append(1))
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=0, request_interval=5, sleep=sleep)
    assert calls == []
    assert now[0] == 1


def test_throttle_deadline_does_not_commit_failed_reservation(monkeypatch):
    now, clock_sleep = _fake_clock(monkeypatch)
    fetcher._last_request = 0.0
    sleeps = []

    def record_sleep(seconds):
        sleeps.append(seconds)
        clock_sleep(seconds)

    with pytest.raises(ProviderUnavailableError):
        fetcher._throttle(5.0, deadline=1.0, monotonic=lambda: now[0], sleep=record_sleep)

    assert fetcher._last_request == 0.0
    assert sleeps == [1.0]
    fetcher._throttle(0.5, deadline=2.0, monotonic=lambda: now[0], sleep=record_sleep)
    assert sleeps == [1.0]
    assert fetcher._last_request == 1.0


def test_provider_timeout_is_capped_by_remaining_deadline(monkeypatch):
    now, _ = _fake_clock(monkeypatch)
    monkeypatch.setenv("DATA_FETCH_DEADLINE_SECONDS", "4")
    monkeypatch.setenv("DATA_REQUEST_TIMEOUT_SECONDS", "15")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    seen = {}
    def download(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2025-01-01"]))
    monkeypatch.setattr(fetcher.yf, "download", download)
    fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)
    assert seen["timeout"] == 4
    assert now[0] == 0


def test_provider_failure_consuming_deadline_prevents_retry(monkeypatch):
    now, _ = _fake_clock(monkeypatch)
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        now[0] = 30
        raise TimeoutError("timed out")
    monkeypatch.setattr(fetcher.yf, "download", fail)
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=3, request_interval=0)
    assert len(calls) == 1


def test_backoff_is_capped_at_remaining_budget(monkeypatch):
    now, sleep = _fake_clock(monkeypatch)
    monkeypatch.setenv("DATA_FETCH_DEADLINE_SECONDS", "1")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    calls, delays = [], []
    def fail(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("timed out")
    monkeypatch.setattr(fetcher.yf, "download", fail)
    def record_sleep(delay):
        delays.append(delay)
        sleep(delay)
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=2, backoff=2, jitter=0, request_interval=0, sleep=record_sleep)
    assert delays == [1]
    assert len(calls) == 1


def test_retry_succeeds_within_budget_and_late_result_is_discarded(monkeypatch):
    now, sleep = _fake_clock(monkeypatch)
    monkeypatch.setenv("DATA_FETCH_DEADLINE_SECONDS", "5")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    calls = []
    raw = pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2025-01-01"]))
    def then_succeed(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return raw
    monkeypatch.setattr(fetcher.yf, "download", then_succeed)
    fetcher.fetch_stock_data("AAPL", retries=1, backoff=1, jitter=0, request_interval=0, sleep=sleep)
    assert len(calls) == 2
    now[0] = 0
    def late(*args, **kwargs):
        now[0] = 5
        return raw
    monkeypatch.setattr(fetcher.yf, "download", late)
    with pytest.raises(ProviderUnavailableError):
        fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)


def test_historical_fetch_uses_same_total_deadline(monkeypatch):
    now, _ = _fake_clock(monkeypatch)
    monkeypatch.setenv("DATA_FETCH_DEADLINE_SECONDS", "2")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval, **kwargs: None)
    seen = {}
    def historical(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Open": [9], "Close": [10]}, index=pd.to_datetime(["2025-01-02"]))
    monkeypatch.setattr(fetcher.yf, "download", historical)
    fetcher.fetch_historical_data("AAPL", date(2025, 1, 1), date(2025, 1, 3), warmup_days=0)
    assert seen["timeout"] == 2
