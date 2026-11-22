"""AlphaWatch API and retained command-line entry point."""

import logging
import json
import os
import time
from datetime import date, datetime, timezone
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import OpenAI
from pydantic import BaseModel, Field

from backtesting.api_schemas import BacktestRequest, BacktestResponse
from backtesting.config import BacktestConfig, StrategyRules
from backtesting.engine import run_backtest
from signals.strategy import ScoreWeights
from signals.indicators import IndicatorWindows
from data.errors import (
    AlphaWatchError,
    InsufficientDataError,
    InvalidRequestError,
    NoMarketDataError,
    ProviderUnavailableError,
)
from data.fetcher import fetch_many, fetch_stock_data, validate_ticker
from signals.indicators import add_momentum, add_moving_averages, add_rsi, add_volatility
from signals.strategy import generate_score, generate_signal_label

load_dotenv()


class JsonLogFormatter(logging.Formatter):
    """Emit a small, safe set of structured context fields without exception payloads."""

    context_fields = ("operation", "endpoint", "method", "status_code", "duration_ms", "ticker", "attempt", "attempts", "retry_delay_seconds", "error_code", "error_type")

    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.context_fields:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, default=str)


base_logger = logging.getLogger("alphawatch")
base_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
base_logger.propagate = False
if not any(getattr(handler, "_alphawatch_json", False) for handler in base_logger.handlers):
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonLogFormatter())
    stream_handler._alphawatch_json = True
    base_logger.addHandler(stream_handler)
logger = logging.getLogger("alphawatch.api")

app = FastAPI(title="AlphaWatch API", version="1.1.0", description="Point-in-time technical stock analysis API")


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AnalysisResponse(BaseModel):
    ticker: str
    signal: str
    score: float
    breakdown: dict[str, float]
    close: float
    market_date: date = Field(description="Exchange-local trading date; not a UTC timestamp")
    retrieved_at: datetime = Field(description="UTC time this API process retrieved the data")


class RankingRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=50)
    period: Literal["1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"] = "6mo"


class RankingItem(BaseModel):
    ticker: str
    score: float
    signal: str
    market_date: date


class RankingResponse(BaseModel):
    results: list[RankingItem]
    errors: dict[str, ErrorDetail]
    retrieved_at: datetime


@app.middleware("http")
async def log_request(request: Request, call_next):
    started = time.monotonic()
    try:
        response = await call_next(request)
        logger.info("API request completed", extra={
            "operation": "http_request", "endpoint": request.url.path,
            "method": request.method, "status_code": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        })
        return response
    except Exception:
        logger.exception("API request failed", extra={"operation": "http_request", "endpoint": request.url.path, "method": request.method})
        raise


@app.exception_handler(AlphaWatchError)
async def domain_exception_handler(request: Request, exc: AlphaWatchError):
    logger.info("API domain error", extra={"operation": "http_request", "endpoint": request.url.path, "error_code": exc.code})
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.public_message}})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError):
    logger.info("API request validation failed", extra={"operation": "http_request", "endpoint": request.url.path})
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Request parameters are invalid."}})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API failure", extra={"operation": "http_request", "endpoint": request.url.path})
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Internal server error."}})


def _scored_data(ticker: str, period: str):
    frame = fetch_stock_data(ticker, period=period)
    frame = add_moving_averages(frame)
    frame = add_rsi(frame)
    frame = add_momentum(frame)
    frame = add_volatility(frame)
    scored = generate_score(frame)
    available = scored.dropna(subset=["Score"])
    if available.empty:
        raise InsufficientDataError()
    return available


def analyze(ticker: str, period: str = "6mo") -> AnalysisResponse:
    ticker = validate_ticker(ticker)
    if period not in {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}:
        raise InvalidRequestError()
    df = _scored_data(ticker, period)
    row = df.iloc[-1]
    market_date = row["Date"]
    if isinstance(market_date, datetime):
        market_date = market_date.date()
    return AnalysisResponse(
        ticker=ticker,
        signal=generate_signal_label(row["Score"]),
        score=float(row["Score"]),
        breakdown=row["ScoreBreakdown"],
        close=float(row["Close"]),
        market_date=market_date,
        retrieved_at=datetime.now(timezone.utc),
    )


@app.get("/health", response_model=HealthResponse, responses={500: {"model": ErrorResponse}})
def health():
    return HealthResponse(status="ok")


@app.get("/analysis/{ticker}", response_model=AnalysisResponse, responses={
    404: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
    502: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
})
def get_analysis(ticker: str, period: str = "6mo"):
    return analyze(ticker, period)


@app.post("/ranking", response_model=RankingResponse, responses={
    404: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
    502: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
})
def ranking(request: RankingRequest):
    tickers = [validate_ticker(item) for item in request.tickers]
    data, fetch_errors = fetch_many(tickers, period=request.period)
    ranked, errors = [], {}
    for ticker, error in fetch_errors.items():
        if isinstance(error, AlphaWatchError):
            errors[ticker] = ErrorDetail(code=error.code, message=error.public_message)
        else:
            errors[ticker] = ErrorDetail(code="provider_unavailable", message=ProviderUnavailableError.public_message)
    for ticker, frame in data.items():
        try:
            scored = generate_score(add_momentum(add_rsi(add_moving_averages(frame))))
            available = scored.dropna(subset=["Score"])
            if available.empty:
                raise InsufficientDataError()
            row = available.iloc[-1]
            market_date = row["Date"]
            if isinstance(market_date, datetime):
                market_date = market_date.date()
            ranked.append(RankingItem(ticker=ticker, score=float(row["Score"]), signal=generate_signal_label(row["Score"]), market_date=market_date))
        except InsufficientDataError as exc:
            errors[ticker] = ErrorDetail(code=exc.code, message=exc.public_message)
    if not ranked and errors:
        codes = {error.code for error in errors.values()}
        if "provider_unavailable" in codes:
            raise ProviderUnavailableError()
        if "no_market_data" in codes:
            raise NoMarketDataError()
        raise InsufficientDataError()
    ranked.sort(key=lambda item: (-item.score, item.ticker))
    return RankingResponse(results=ranked, errors=errors, retrieved_at=datetime.now(timezone.utc))


@app.post("/backtest", response_model=BacktestResponse, responses={
    404: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
    502: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
})
def backtest(request: BacktestRequest):
    ticker = validate_ticker(request.ticker)
    try:
        config = BacktestConfig(
            ticker=ticker,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            commission_rate=request.commission_rate,
            slippage_rate=request.slippage_rate,
            position_size_fraction=request.position_size_fraction,
            fractional_shares=request.fractional_shares,
            weights=ScoreWeights(request.trend_weight, request.rsi_weight, request.momentum_weight),
            strategy=StrategyRules(tuple(request.entry_signals), tuple(request.exit_signals)),
            indicator_windows=IndicatorWindows(
                ma_short=request.ma_short_window,
                ma_long=request.ma_long_window,
                rsi_period=request.rsi_period,
                momentum_period=request.momentum_period,
            ),
        )
    except ValueError as exc:
        raise InvalidRequestError() from exc
    return run_backtest(config)


def run(ticker):
    """CLI workflow; AI commentary is optional when OPENAI_API_KEY is configured."""
    from visualization.plotter import plot_stock

    normalized = validate_ticker(ticker)
    df = fetch_stock_data(normalized)
    df = add_momentum(add_volatility(add_rsi(add_moving_averages(df))))
    df = generate_score(df).dropna(subset=["Score"])
    if df.empty:
        raise ValueError("Insufficient historical data to calculate a score")
    latest_score = df["Score"].iloc[-1]
    signal = generate_signal_label(latest_score)
    api_key = os.getenv("OPENAI_API_KEY")
    insight = "Set OPENAI_API_KEY to enable AI commentary."
    if api_key:
        client = OpenAI(api_key=api_key)
        from ai.insight_engine import get_ai_insight
        insight = get_ai_insight(client, normalized, df, latest_score, signal)
    plot_stock(df, normalized, insight)


if __name__ == "__main__":
    tickers = input("Enter tickers (comma separated): ").split(",")
    for ticker in tickers:
        try:
            run(ticker.strip())
        except Exception as exc:
            logger.error("Analysis failed for %s: %s", ticker.strip(), exc)
