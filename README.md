# AlphaWatch

**A Python-based stock research and historical backtesting platform built with FastAPI.**

AlphaWatch combines technical analysis, configurable signal scoring, and historical portfolio simulation to evaluate stock trading strategies using market data.

The project focuses on backend engineering, including modular architecture, REST API design, input validation, concurrent data retrieval, error handling, portfolio simulation, and automated testing.

## Features

### Technical Analysis & Signal Generation

- Calculates moving averages, RSI, momentum, and volatility.
- Generates configurable weighted scores from technical indicators.
- Classifies signals as Buy, Sell, Strong Buy, Strong Sell, or Hold.
- Returns indicator-level contribution breakdowns for signal transparency.
- Supports individual stock analysis and multi-ticker rankings.

### REST API

- FastAPI endpoints for health checks, stock analysis, ticker rankings, and historical backtesting.
- Request validation and normalized ticker inputs.
- Bounded concurrent market-data retrieval.
- Retry logic with exponential backoff and jitter.
- Structured error responses and per-ticker failure isolation.
- Interactive API documentation through OpenAPI and Swagger UI.

### Historical Backtesting

- Simulates long-only trading strategies using historical OHLC data.
- Executes signals on the next eligible trading session rather than the signal day's closing price.
- Supports configurable position sizing, commissions, and slippage.
- Supports fractional-share and whole-share execution.
- Tracks portfolio cash, shares, equity, and completed trades.
- Calculates portfolio performance metrics.
- Compares strategy performance against the S&P 500 benchmark (SPY).
- Reports signal coverage, warm-up requirements, and benchmark date alignment.

### Performance Metrics

- Total and annualized returns.
- Annualized volatility and Sharpe ratio.
- Maximum drawdown and downside deviation.
- Trade win rate and average winning and losing trade P/L.
- Profit factor and average holding period.
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

### PostgreSQL integration tests

PostgreSQL integration tests are skipped during ordinary `pytest` runs. They only run when explicitly enabled with `RUN_POSTGRES_TESTS=1` and a valid `TEST_DATABASE_URL`. The URL validator restricts the target database to `alphawatch_test` and local/approved hosts; the normal `DATABASE_URL` and `alphawatch` database are not used for these tests.

With PostgreSQL running locally and the dedicated `alphawatch_test` database already created, run from the repository root:

```bash
RUN_POSTGRES_TESTS=1 \
TEST_DATABASE_URL='postgresql+psycopg://localhost/alphawatch_test' \
pytest -q tests/integration
```

If local PostgreSQL requires a username or password, provide them in `TEST_DATABASE_URL` (for example, `postgresql+psycopg://myuser:mypassword@localhost/alphawatch_test`). Keep credentials out of checked-in files. The fixture applies `alembic upgrade head` to the validated test database before tests and rolls each test's data transaction back afterward. It does not create or reset the database.

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

**Retrieve technical analysis for Apple:**

```bash
curl http://127.0.0.1:8000/analysis/AAPL
```

Example response:

```json
{
  "ticker": "AAPL",
  "signal": "Strong Buy",
  "score": 2.0,
  "breakdown": {
    "trend": 1.0,
    "rsi": 0.0,
    "momentum": 1.0
  },
  "close": 342.55999755859375,
  "market_date": "2026-11-20",
  "retrieved_at": "2026-11-22T19:45:42.919349Z"
}
```

*Sample output from a live API request. Market data and signals change over time.*

**Rank multiple stocks:**

```bash
curl -X POST http://127.0.0.1:8000/ranking \
  -H 'Content-Type: application/json' \
  -d '{"tickers":["AAPL","MSFT"],"period":"6mo"}'
```

**Run a historical backtest:**

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

Example backtest response summary:

```json
{
  "evaluation_period": {
    "start_date": "2021-01-04",
    "end_date": "2025-12-31"
  },
  "signal_coverage": {
    "evaluation_trading_dates": 1255,
    "valid_signal_dates": 1255,
    "missing_signal_dates": [],
    "warmup_status": "complete",
    "first_valid_signal_date": "2021-01-04"
  },
  "metrics": {
    "initial_capital": 10000.0,
    "final_portfolio_value": 14472.94,
    "total_return": 0.4473,
    "annualized_return": 0.0771,
    "maximum_drawdown": -0.3065,
    "annualized_volatility": 0.1855,
    "sharpe_ratio": 0.4934,
    "completed_trades": 35,
    "winning_trades": 13,
    "losing_trades": 22,
    "win_rate": 0.3714,
    "profit_factor": 1.3791
  },
  "benchmark": {
    "benchmark_symbol": "SPY",
    "strategy_total_return": 0.4473,
    "benchmark_total_return": 0.8491,
    "strategy_annualized_return": 0.0771,
    "benchmark_annualized_return": 0.1315,
    "strategy_maximum_drawdown": -0.3065,
    "benchmark_maximum_drawdown": -0.2536
  }
}
```

The backtesting engine returns a detailed response containing configuration, evaluation period, signal coverage, performance metrics, benchmark data, equity curves, trade history, and individual trading signals.

*Sample output from a five-year AAPL backtest using $10,000 initial capital. Results are historical simulations, not predictions.*

## Backtesting Methodology

The backtesting engine uses AlphaWatch's existing indicator and scoring functions to generate historical trading signals.

### Default Strategy

- Enters a position on Buy or Strong Buy signals.
- Exits a position on Sell or Strong Sell signals.
- Holds the existing position or remains in cash on Hold signals.
- Does not use short selling.

Signals generated from a trading session's closing data are eligible for execution on the next available trading session. The engine uses the next session's Open price when valid, otherwise falling back to that session's Close and recording the fallback.

### Portfolio Accounting

Portfolio equity is calculated from available cash and the market value of open positions.

- Positions are marked to market at each session's closing price.
- Open positions are not automatically liquidated at the end of a backtest.
- Completed-trade statistics exclude positions that remain open.

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
- Annualized returns require at least two daily return observations.

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
- `DATA_REQUEST_TIMEOUT_SECONDS` (per-download provider timeout; defaults to `15` seconds and is capped by the remaining total deadline)
- `DATA_FETCH_DEADLINE_SECONDS` (defaults to `30` seconds; limits one fetch lifecycle including throttling and retry waits)

## Running Tests

Run the test suite from the repository root:

```bash
pytest -q
```

Market data is mocked during testing, so live market-data access and OpenAI credentials are not required.

PostgreSQL integration tests are opt-in and require an explicitly configured, dedicated `alphawatch_test` database. Setup instructions will be added in a later phase.

## Current Scope & Limitations

AlphaWatch is an actively developed research prototype.

The current implementation does not include:

- Persistent database storage.
- User authentication or account management.
- Fundamental financial statement analysis.
- Financial news integration.
- A web-based frontend.

The market-data integration uses yfinance for prototyping. Provider terms and data licensing should be reviewed before production use.
