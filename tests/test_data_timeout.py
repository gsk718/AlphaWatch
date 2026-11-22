from datetime import date

import pandas as pd
import pytest

from data import fetcher
from data.errors import InvalidRequestError, ProviderUnavailableError


@pytest.fixture(autouse=True)
def clear_timeout_environment(monkeypatch):
    for name in (
        "DATA_REQUEST_TIMEOUT_SECONDS",
        "DATA_RETRIES",
        "DATA_RETRY_BACKOFF_SECONDS",
        "DATA_RETRY_JITTER_SECONDS",
        "DATA_REQUEST_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_configured_timeout_is_passed_to_standard_download(monkeypatch):
    monkeypatch.setenv("DATA_REQUEST_TIMEOUT_SECONDS", "8.5")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
    seen = {}

    def download(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2025-01-01"]))

    monkeypatch.setattr(fetcher.yf, "download", download)
    fetcher.fetch_stock_data("AAPL", retries=0, request_interval=0)
    assert seen["timeout"] == 8.5


def test_configured_timeout_is_passed_to_historical_download(monkeypatch):
    monkeypatch.setenv("DATA_REQUEST_TIMEOUT_SECONDS", "6")
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
    seen = {}

    def download(*args, **kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"Open": [9], "Close": [10]}, index=pd.to_datetime(["2025-01-02"]))

    monkeypatch.setattr(fetcher.yf, "download", download)
    fetcher.fetch_historical_data("AAPL", date(2025, 1, 1), date(2025, 1, 3), warmup_days=0)
    assert seen["timeout"] == 6


def test_default_timeout_is_used_when_environment_variable_is_absent(monkeypatch):
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
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
    monkeypatch.setattr(fetcher, "_throttle", lambda interval: None)
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
