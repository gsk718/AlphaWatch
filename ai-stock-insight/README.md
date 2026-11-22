# AlphaWatch

**A Python-based stock research and historical backtesting platform built with FastAPI.**

AlphaWatch combines deterministic technical analysis, configurable signal scoring, and historical portfolio simulation to evaluate stock trading strategies using market data.

The project focuses on backend engineering, including modular architecture, API design, input validation, concurrent data retrieval, error handling, and automated testing.

## Features

### Technical Analysis & Signal Generation
- Calculates moving averages, RSI, momentum, and volatility.
- Generates configurable weighted scores from technical indicators.
- Classifies signals as Buy, Sell, Strong Buy, Strong Sell, or Hold.
- Returns indicator-level contribution breakdowns for signal transparency.
- Supports analysis of individual stocks and multi-ticker rankings.

### REST API
- FastAPI endpoints for health checks, stock analysis, and ticker rankings.
- Request validation and normalized ticker inputs.
- Bounded concurrent market-data retrieval.
- Retry logic with exponential backoff and jitter.
- Structured error responses and per-ticker failure isolation.
- Interactive API documentation through OpenAPI and Swagger UI.

### Historical Backtesting
- Simulates long-only trading strategies using historical OHLC data.
- Executes signals on the next eligible trading session rather than the signal day's closing price.
- Supports configurable position sizing, commissions, and slippage.
- Tracks portfolio cash, shares, equity, and completed trades.
- Calculates performance metrics and compares strategy performance against the S&P 500 benchmark (SPY).
- Reports signal coverage, warm-up requirements, and benchmark alignment.

### Performance Metrics
- Total and annualized returns.
- Annualized volatility and Sharpe ratio.
- Maximum drawdown and downside deviation.
- Trade win rate, average winning and losing trade P/L, and profit factor.
- Strategy and benchmark equity curves.

## Tech Stack

| Technology | Purpose |
|---|---|
| Python | Core application and backtesting logic |
| FastAPI | REST API framework |
| Pandas / NumPy | Market data processing and calculations |
| yfinance | Historical stock market data |
| Pydantic | Request validation and response schemas |
| OpenAI API | Optional AI-generated commentary in the CLI |
| Pytest | Automated testing |

## Architecture

AlphaWatch separates data retrieval, indicator calculations, signal scoring, API handling, and backtesting into modular components.

```text
                  Client / CLI
                       |
                       v
                  FastAPI
                       |
          +------------+------------+
          |            |            |
       Analysis     Ranking     Backtesting
          |            |            |
          +------------+------------+
                       |
                       v
                Data Fetcher
                       |
                       v
              Technical Indicators
                       |
                       v
               Signal Scoring
                       |
             +---------+---------+
             |                   |
        API Response       Portfolio Engine
                                 |
                                 v
                         Performance Metrics
                                 |
                                 v
                          SPY Benchmark
```

## Getting Started

### Prerequisites
- Python 3.10+
- pip
- An internet connection for market-data retrieval

### Installation

Clone the repository:

```bash
git clone https://github.com/gsk718/AlphaWatch.git
cd AlphaWatch
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r ai-stock-insight/requirements.txt
```

### Run the API

Navigate to the application directory:

```bash
cd ai-stock-insight
```

Start the development server:

```bash
uvicorn app.main:app --reload
```

The API will be available at:

- API: http://127.0.0.1:8000
- Interactive Swagger documentation: http://127.0.0.1:8000/docs

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Liveness check; returns `{"status":"ok"}` when the application is running |
| GET | `/health/live` | Liveness check; returns `{"status":"ok"}` without accessing the database |
| GET | `/health/ready` | Database readiness check; returns 503 when the database is unavailable |
| GET | `/analysis/{ticker}` | Technical analysis for an individual ticker |
| POST | `/ranking` | Analyze and rank multiple tickers |
| POST | `/backtest` | Run a historical trading strategy simulation |

`/health` and `/health/live` report application liveness and do not check database connectivity. `/health/ready` checks the database connection and returns HTTP 503 when it is unavailable. Configure deployment systems to use readiness to determine whether an instance can receive traffic; liveness should only determine whether the application process is running.

### Example Requests

Retrieve analysis for Apple:

```bash
curl http://127.0.0.1:8000/analysis/AAPL
```

Rank multiple stocks:

```bash
curl -X POST http://127.0.0.1:8000/ranking \
  -H 'Content-Type: application/json' \
  -d '{"tickers":["AAPL","MSFT"],"period":"6mo"}'
```

Run a historical backtest:

```bash
curl -X POST http://127.0.0.1:8000/backtest \
  -H 'Content-Type: application/json' \
  -d '{
    "ticker": "AAPL",
    "start_date": "2021-01-01",
    "end_date": "2026-01-01",
    "initial_capital": 10000,
    "commission_rate": 0.001,
    "slippage_rate": 0.001
  }'
```

## Backtesting Methodology

The backtesting engine uses AlphaWatch's existing indicator and scoring functions to generate historical trading signals.

The default strategy:
- Enters a position on Buy or Strong Buy signals.
- Exits a position on Sell or Strong Sell signals.
- Holds the existing position or remains in cash on Hold signals.
- Does not use short selling.

Signals generated from a trading session's closing data are eligible for execution on the next available trading session. The engine uses the next session's Open price when valid, otherwise it falls back to that session's Close and records the fallback.

Portfolio equity is calculated from available cash and the market value of open positions. Positions are marked to market at each session's closing price. Open positions are not automatically liquidated at the end of a backtest.

### Transaction Costs

The simulation accounts for:
- Commission on buy and sell transactions.
- Slippage applied to execution prices.
- Configurable position sizing.
- Fractional-share or whole-share execution.

### Benchmark Comparison

Strategy performance is compared against SPY over matching evaluation trading dates. Both equity curves use the same initial capital.

Benchmark returns use unadjusted closing prices (`auto_adjust=False`), so dividends and other distributions are excluded.

### Important Assumptions

- Annualized calculations assume 252 trading sessions per year.
- Sharpe ratio assumes a zero risk-free rate.
- Incomplete benchmark date alignment is rejected rather than treated as daily data.
- Indicator warm-up observations are excluded from the evaluation period.
- Missing trading sessions are not synthesized.

Backtested results are simulations based on historical data and documented assumptions. They do not guarantee future performance and are not investment recommendations.

## Configuration

Optional environment variables include:

```env
OPENAI_API_KEY=your_api_key_here
STOCK_API_KEY=your_api_key_here
```

OpenAI commentary is optional and used by the CLI. The deterministic analysis API does not require an OpenAI API key.

Market-data retrieval can be configured using:

- `DATA_MAX_WORKERS`
- `DATA_RETRIES`
- `DATA_RETRY_BACKOFF_SECONDS`
- `DATA_RETRY_JITTER_SECONDS`
- `DATA_REQUEST_INTERVAL_SECONDS`
- `DATA_REQUEST_TIMEOUT_SECONDS` (per-download provider timeout in seconds; defaults to `15` and must be finite and greater than zero)
- `DATA_FETCH_DEADLINE_SECONDS` (total time budget for one fetch lifecycle in seconds; defaults to `30`, must be finite and greater than zero, and includes throttling and retry waits)

`DATA_REQUEST_TIMEOUT_SECONDS` sets the timeout for each provider download. Each download's timeout is capped by the time remaining under `DATA_FETCH_DEADLINE_SECONDS`.

## Running Tests

Run the test suite from the repository root:

```bash
pytest -q
```

Market data is mocked during testing, so live market-data access and OpenAI credentials are not required.

## Current Scope & Limitations

AlphaWatch is an actively developed research prototype.

The current implementation does not include:
- Persistent database storage.
- User authentication or account management.
- Fundamental financial statement analysis.
- Financial news integration.
- A web-based frontend.

The market-data integration uses yfinance for prototyping. Provider terms and data licensing should be reviewed before production use.

## Disclaimer

AlphaWatch is an educational stock research and backtesting project. Technical signals and historical simulations are not financial advice, investment recommendations, or guarantees of future returns.
