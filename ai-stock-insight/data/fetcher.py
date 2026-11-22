"""Throttled, bounded market data retrieval with retry and per-symbol isolation."""

import logging
import math
import os
import random
import re
import threading
import time
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from data.errors import InvalidRequestError, InvalidTickerError, NoMarketDataError, ProviderUnavailableError

logger = logging.getLogger("alphawatch.provider")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,14}$")
_throttle_lock = threading.Lock()
_last_request = 0.0


def validate_ticker(ticker: str) -> str:
    if not isinstance(ticker, str):
        raise InvalidTickerError()
    normalized = ticker.strip().upper()
    if not TICKER_RE.fullmatch(normalized):
        raise InvalidTickerError()
    return normalized


def _throttle(interval: float, deadline=None, monotonic=None, sleep=None):
    global _last_request
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    def remaining():
        return None if deadline is None else deadline - monotonic()

    if interval <= 0:
        if deadline is not None and remaining() <= 0:
            raise ProviderUnavailableError()
        return
    # Acquire only within the remaining budget. Reserve the next slot while holding
    # the lock, then release it before sleeping so concurrent callers cannot bypass spacing.
    timeout = remaining()
    acquired = _throttle_lock.acquire() if timeout is None else _throttle_lock.acquire(timeout=max(0.0, timeout))
    if not acquired:
        raise ProviderUnavailableError()
    try:
        now = monotonic()
        left = None if deadline is None else deadline - now
        if left is not None and left <= 0:
            raise ProviderUnavailableError()
        slot = max(now, _last_request + interval)
        wait = max(0.0, slot - now)
        if left is not None and wait >= left:
            failed_wait = left
        else:
            failed_wait = None
            _last_request = slot
    finally:
        _throttle_lock.release()
    if failed_wait is not None:
        sleep(failed_wait)
        raise ProviderUnavailableError()
    if wait:
        left = remaining()
        if left is not None and left <= 0:
            raise ProviderUnavailableError()
        sleep(wait if left is None else min(wait, left))
        if deadline is not None and remaining() <= 0:
            raise ProviderUnavailableError()
    # Record actual completion time while preserving any later slot reserved by a
    # concurrent caller.
    with _throttle_lock:
        _last_request = max(_last_request, monotonic())


def _normalize_market_frame(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if df.empty:
        raise NoMarketDataError()
    if isinstance(df.columns, pd.MultiIndex):
        if "Close" in df.columns.get_level_values(0):
            df.columns = df.columns.get_level_values(0)
        elif "Close" in df.columns.get_level_values(-1):
            df.columns = df.columns.get_level_values(-1)
    if "Close" not in df.columns:
        raise NoMarketDataError()
    df = df[["Close"]].copy()
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    if df.empty:
        raise NoMarketDataError()
    # Preserve the provider's exchange-local trading date; this is a calendar date, not UTC.
    idx = pd.to_datetime(df.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx
    df = df.loc[~df.index.isna()].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df


def _request_timeout_seconds() -> float:
    """Read and validate the configured per-request provider timeout."""
    raw = os.getenv("DATA_REQUEST_TIMEOUT_SECONDS", "15")
    try:
        timeout = float(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("DATA_REQUEST_TIMEOUT_SECONDS must be a finite positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise InvalidRequestError("DATA_REQUEST_TIMEOUT_SECONDS must be a finite positive number")
    return timeout


def _fetch_deadline_seconds() -> float:
    """Read and validate the total market-data fetch budget."""
    raw = os.getenv("DATA_FETCH_DEADLINE_SECONDS", "30")
    try:
        deadline = float(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("DATA_FETCH_DEADLINE_SECONDS must be a finite positive number") from exc
    if not math.isfinite(deadline) or deadline <= 0:
        raise InvalidRequestError("DATA_FETCH_DEADLINE_SECONDS must be a finite positive number")
    return deadline


def fetch_stock_data(
    ticker,
    period="6mo",
    interval="1d",
    retries=None,
    backoff=None,
    jitter=None,
    request_interval=None,
    sleep=time.sleep,
    random_uniform=random.uniform,
):
    ticker = validate_ticker(ticker)
    if period not in {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}:
        raise InvalidRequestError("Unsupported period")
    if interval not in {"1d", "1wk", "1mo"}:
        raise InvalidRequestError("Unsupported interval")
    retries = int(os.getenv("DATA_RETRIES", "2")) if retries is None else retries
    backoff = float(os.getenv("DATA_RETRY_BACKOFF_SECONDS", "0.5")) if backoff is None else backoff
    jitter = float(os.getenv("DATA_RETRY_JITTER_SECONDS", "0.25")) if jitter is None else jitter
    request_interval = float(os.getenv("DATA_REQUEST_INTERVAL_SECONDS", "0.1")) if request_interval is None else request_interval
    request_timeout = _request_timeout_seconds()
    fetch_budget = _fetch_deadline_seconds()
    if retries < 0 or backoff < 0 or jitter < 0 or request_interval < 0:
        raise InvalidRequestError("Retry and throttle settings must be nonnegative")

    deadline = time.monotonic() + fetch_budget
    frame = _download_with_retries(
        ticker, {"period": period, "interval": interval, "timeout": request_timeout}, retries, backoff, jitter,
        request_interval, sleep, random_uniform, deadline=deadline, monotonic=time.monotonic,
    )
    return _normalize_market_frame(frame, ticker)


def _download_with_retries(ticker, params, retries, backoff, jitter, request_interval, sleep, random_uniform, deadline=None, monotonic=None):
    monotonic = monotonic or time.monotonic
    last_error = None
    for attempt in range(retries + 1):
        try:
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                raise ProviderUnavailableError()
            _throttle(request_interval, deadline=deadline, monotonic=monotonic, sleep=sleep)
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                raise ProviderUnavailableError()
            logger.info("Fetching market data", extra={"ticker": ticker, "operation": "fetch", "attempt": attempt + 1})
            call_params = dict(params)
            if remaining is not None:
                call_params["timeout"] = min(call_params["timeout"], remaining)
            result = yf.download(ticker, progress=False, auto_adjust=False, **call_params)
            if deadline is not None and monotonic() >= deadline:
                raise ProviderUnavailableError()
            return result
        except Exception as exc:
            if isinstance(exc, ProviderUnavailableError):
                raise
            if deadline is not None and monotonic() >= deadline:
                raise ProviderUnavailableError() from (None if isinstance(exc, ProviderUnavailableError) else exc)
            last_error = exc
            message = str(exc).lower()
            retryable = any(token in message for token in ("rate limit", "too many requests", "429", "timeout", "timed out", "temporar", "503", "502", "connection"))
            if not retryable:
                logger.warning("Non-retryable provider failure", extra={"ticker": ticker, "operation": "fetch", "attempt": attempt + 1})
                raise ProviderUnavailableError() from exc
            if attempt < retries:
                delay = backoff * (2 ** attempt) + random_uniform(0.0, jitter)
                logger.warning("Retrying provider request", extra={"ticker": ticker, "operation": "fetch", "attempt": attempt + 1, "retry_delay_seconds": delay})
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    raise ProviderUnavailableError() from exc
                if remaining is not None and delay >= remaining:
                    sleep(remaining)
                    raise ProviderUnavailableError() from exc
                sleep(delay)
                if deadline is not None and monotonic() >= deadline:
                    raise ProviderUnavailableError() from exc
    logger.error("Provider retries exhausted", extra={"ticker": ticker, "operation": "fetch", "attempts": retries + 1})
    raise ProviderUnavailableError() from last_error


def fetch_historical_data(ticker: str, start_date: date, end_date: date, warmup_days: int = 90) -> pd.DataFrame:
    """Fetch unadjusted OHLC history; end_date is inclusive and warmup is excluded by caller."""
    ticker = validate_ticker(ticker)
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if start_date >= end_date:
        raise InvalidRequestError("start_date must be before end_date")
    if warmup_days < 0:
        raise InvalidRequestError("warmup_days must be nonnegative")
    retries = int(os.getenv("DATA_RETRIES", "2"))
    backoff = float(os.getenv("DATA_RETRY_BACKOFF_SECONDS", "0.5"))
    jitter = float(os.getenv("DATA_RETRY_JITTER_SECONDS", "0.25"))
    interval = float(os.getenv("DATA_REQUEST_INTERVAL_SECONDS", "0.1"))
    request_timeout = _request_timeout_seconds()
    fetch_budget = _fetch_deadline_seconds()
    deadline = time.monotonic() + fetch_budget
    raw = _download_with_retries(ticker, {
        "start": (start_date - timedelta(days=warmup_days)).isoformat(),
        "end": (end_date + timedelta(days=1)).isoformat(),
        "interval": "1d",
        "timeout": request_timeout,
    }, retries, backoff, jitter, interval, time.sleep, random.uniform, deadline=deadline, monotonic=time.monotonic)
    if raw.empty:
        raise NoMarketDataError()
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            raw.columns = raw.columns.get_level_values(0)
        elif "Close" in raw.columns.get_level_values(-1):
            raw.columns = raw.columns.get_level_values(-1)
    if "Close" not in raw:
        raise NoMarketDataError()
    columns = [column for column in ("Open", "Close") if column in raw]
    frame = raw[columns].copy()
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    if "Open" in frame:
        frame["Open"] = pd.to_numeric(frame["Open"], errors="coerce")
    frame = frame.dropna(subset=["Close"])
    frame = frame[frame["Close"] > 0]
    index = pd.to_datetime(frame.index, errors="coerce")
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    frame.index = index
    frame = frame.loc[~frame.index.isna()].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.reset_index().rename(columns={frame.index.name or "index": "Date"})
    if "Date" not in frame:
        frame = frame.rename(columns={frame.columns[0]: "Date"})
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.date
    return frame


def fetch_many(tickers, period="6mo", interval="1d", max_workers=None, **fetch_options):
    """Return unique successful tickers and errors in first-seen input order."""
    normalized = list(dict.fromkeys(validate_ticker(t) for t in tickers))
    if max_workers is None:
        max_workers = int(os.getenv("DATA_MAX_WORKERS", "4"))
    if max_workers < 1:
        raise InvalidRequestError("max_workers must be positive")
    results, errors = {}, {}
    if not normalized:
        return results, errors
    with ThreadPoolExecutor(max_workers=min(max_workers, len(normalized))) as pool:
        futures = {
            pool.submit(fetch_stock_data, ticker, period=period, interval=interval, **fetch_options): ticker
            for ticker in normalized
        }
        completed = {}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                completed[ticker] = (True, future.result())
            except Exception as exc:
                logger.error("Ticker retrieval failed", extra={"ticker": ticker, "operation": "fetch_many", "error_type": type(exc).__name__})
                completed[ticker] = (False, exc)
        for ticker in normalized:
            success, value = completed[ticker]
            (results if success else errors)[ticker] = value
    return results, errors
