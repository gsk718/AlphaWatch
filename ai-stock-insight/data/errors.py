"""Stable domain errors shared by market data and API layers."""


class AlphaWatchError(Exception):
    code = "alphawatch_error"
    status_code = 500
    public_message = "The request could not be completed."


class InvalidTickerError(AlphaWatchError, ValueError):
    code = "invalid_ticker"
    status_code = 422
    public_message = "Ticker syntax is invalid."


class InvalidRequestError(AlphaWatchError, ValueError):
    code = "invalid_request"
    status_code = 422
    public_message = "Request parameters are invalid."


class InsufficientDataError(AlphaWatchError):
    code = "insufficient_data"
    status_code = 422
    public_message = "There is not enough historical data to calculate an analysis."


class InsufficientWarmupError(InsufficientDataError):
    code = "insufficient_warmup"
    public_message = "Pre-period history is insufficient to initialize the requested indicators."


class NoMarketDataError(AlphaWatchError):
    code = "no_market_data"
    status_code = 404
    public_message = "No market data is available for this ticker and period."


class ProviderUnavailableError(AlphaWatchError):
    code = "provider_unavailable"
    status_code = 502
    public_message = "The market data provider is temporarily unavailable."


class BenchmarkUnavailableError(AlphaWatchError):
    code = "benchmark_unavailable"
    status_code = 502
    public_message = "Benchmark data is unavailable for the requested period."


class IncompleteBenchmarkDataError(BenchmarkUnavailableError):
    code = "benchmark_incomplete"
    public_message = "Strategy and SPY prices must contain the same evaluation trading dates for daily benchmark metrics."
