# AlphaWatch

**A full-stack stock research and historical backtesting platform built with FastAPI and React.**

[**Open the live demo**](https://alphawatch.gauravdevport.com) · [GitHub repository](https://github.com/gsk718/AlphaWatch)

AlphaWatch is a stock research dashboard for analyzing individual tickers, comparing technical signals across a watchlist, and simulating historical trading strategies. It also saves analysis and backtest results so they can be reviewed later. Market data is retrieved on demand through Yahoo Finance.

The project focuses on backend engineering, including modular architecture, REST API design, input validation, concurrent data retrieval, error handling, portfolio simulation, and automated testing.

## Features

- Stock analysis with technical indicators and transparent signal contributions.
- Stock rankings for comparing signal strength across multiple tickers.
- Configurable historical backtesting with strategy and SPY benchmark results.
- Persistent analysis history and backtest history with detailed result inspection.

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
| React, TypeScript, Vite | Browser dashboard |
| Recharts, Tailwind CSS, Lucide | Financial charts, styling, and iconography |

## Screenshots

| Screenshot | Feature |
|---|---|
| ![AlphaWatch overview dashboard with quick analysis and recent activity](assets/screenshots/screenshot-1.png) | **Overview dashboard** — quick analysis, connection status, and recent analysis and backtest activity. |
| ![AAPL stock analysis with signal score and technical indicator contributions](assets/screenshots/screenshot-2.png) | **Stock analysis** — latest signal, composite score, and trend, RSI, and momentum contributions. |
| ![Stock rankings leaderboard comparing AAPL, COST, NVDA, and SNAP](assets/screenshots/screenshot-3.png) | **Stock rankings** — a scored leaderboard with technical signals for the selected tickers. |
| ![AAPL historical backtest results with portfolio metrics and equity curve](assets/screenshots/screenshot-4.png) | **Backtesting** — strategy configuration, portfolio metrics, and historical equity curve. |

## Architecture

The production dashboard sends API requests to the FastAPI service. The backend retrieves market data and reads or writes analysis and backtest records in PostgreSQL.

```mermaid
flowchart LR
    Browser[React / TypeScript / Vite frontend<br/>Vercel]
    API[FastAPI / Python backend<br/>Render]
    DB[(PostgreSQL database<br/>Supabase)]
    Market[Yahoo Finance market data]

    Browser -->|HTTPS API requests| API
    API -->|SQL queries and result persistence| DB
    API -->|Market data requests| Market
```

## Production Deployment

- **Frontend:** React, TypeScript, and Vite dashboard hosted on Vercel.
- **Backend:** FastAPI and Python API hosted on Render.
- **Database:** PostgreSQL hosted on Supabase.

The browser dashboard calls the Render API over HTTPS. The API retrieves market data on demand and connects to Supabase PostgreSQL using `DATABASE_URL` to persist analyses and backtests and serve their history. The backend's `CORS_ORIGINS` setting allows the deployed dashboard origin to make browser requests.

The application architecture also separates data retrieval, indicator calculations, signal scoring, API handling, and backtesting into modular components.

## Getting Started

### Prerequisites

- Python 3.10+
- pip
- PostgreSQL (required for the API's persistent database)
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

From the repository root, install dependencies:

```bash
pip install -r ai-stock-insight/requirements.txt
```

The nested `ai-stock-insight/requirements.txt` contains the FastAPI application's dependencies, including SQLAlchemy, Psycopg 3, and Alembic. The root `requirements.txt` is a separate, pinned dependency list for the repository-root scripts; it does not replace the application's requirements file.

### Configure PostgreSQL

Start PostgreSQL, then, if a local development database named `alphawatch` does not already exist, create it (for example, using the PostgreSQL command-line utility):

```bash
createdb alphawatch
```

The application reads its `.env` file from `ai-stock-insight/.env`, alongside `alembic.ini`. The checked-in `.env.example` is at the repository root; from the repository root, copy it into the application directory and edit it there:

```bash
cp .env.example ai-stock-insight/.env
```

Set `DATABASE_URL` in `ai-stock-insight/.env` to a PostgreSQL URL for the `alphawatch` database. For a local PostgreSQL role that can connect over TCP, use this shape and replace the placeholders with your local role and password:

```env
DATABASE_URL=postgresql+psycopg://<username>:<password>@localhost:5432/alphawatch
```

Do not commit local credentials. If PostgreSQL is configured for local Unix-socket authentication under the current OS user, the application default is `postgresql+psycopg:///alphawatch`; in that case `DATABASE_URL` can be omitted.

Apply the schema migrations from the application directory:

```bash
cd ai-stock-insight
alembic upgrade head
```

### Run the API

If you have not already changed directories for migrations, navigate to the application directory:

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

The command assumes the virtual environment created above is active. Stop the server with Ctrl+C.

### Run the dashboard

In another terminal, from the repository root:

```bash
cd frontend
npm install
npm run dev
```

The dashboard runs at http://localhost:5173 and uses `http://127.0.0.1:8000` by default. To use another API URL, create `frontend/.env.local` (do not overwrite any existing env file) with:

```env
VITE_API_URL=http://127.0.0.1:8000
```

Start the API and dashboard in separate terminals. The API allows the local Vite origins on port 5173 for browser requests. The frontend build can be checked with `npm run build` from `frontend/`.

### Dashboard functionality

The dashboard includes an overview, single-stock analysis, multi-ticker rankings, configurable backtesting with strategy and benchmark equity curves, analysis history, and backtest history with detailed inspection. The API's current analysis response contains only the latest close and indicator breakdown, not a historical price series or AI commentary; the dashboard does not fabricate either. Historical activity requires the configured PostgreSQL database.

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
| GET | `/health` | Basic process health |
| GET | `/health/live` | Liveness probe; no database access |
| GET | `/health/ready` | Database readiness probe |
| GET | `/analysis/{ticker}` | Calculate and persist a ticker's latest technical analysis |
| POST | `/ranking` | Analyze, rank, and persist successful ticker results |
| POST | `/backtest` | Run and persist a historical strategy simulation |
| GET | `/history/analyses` | List saved analyses with optional ticker/date filters |
| GET | `/history/analyses/{ticker}` | List saved analyses for one ticker with optional date filters |
| GET | `/history/backtests` | List saved backtest summaries, optionally filtered by ticker |
| GET | `/history/backtests/{backtest_id}` | Retrieve a complete saved backtest by ID |

Interactive OpenAPI documentation is available at `/docs` (for example, `http://127.0.0.1:8000/docs`). Examples use illustrative tickers and dates; market data and returned values change over time.

`/health` and `/health/live` return `{"status":"ok"}` without checking the database. `/health/ready` runs `SELECT 1`; it returns `{"status":"ok"}` on success and HTTP 503 with `{"status":"unavailable"}` if the database cannot be reached.

### Request and response reference

- **GET `/analysis/{ticker}`** — Path parameter `ticker` is trimmed, uppercased, and must match `[A-Z0-9][A-Z0-9.\-^=]{0,14}` after normalization; optional query `period` defaults to `6mo` and must be `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, or `max`. Response: `{ticker, signal, score, breakdown, close, market_date, retrieved_at}`. `market_date` is an exchange-local date; `retrieved_at` is UTC.
- **POST `/ranking`** — JSON body: required `tickers` list (1–50 strings); optional `period` with the choices above, default `6mo`. Response: `{results:[{ticker,score,signal,market_date}], errors:{ticker:{code,message}}, retrieved_at}`. Partial per-ticker failures can accompany successful results. Results sort by descending score, then ticker.
- **POST `/backtest`** — JSON body requires `ticker` (trimmed and uppercased; must follow the same syntax as tickers accepted by the other endpoints: `[A-Z0-9][A-Z0-9.\-^=]{0,14}` after normalization), `start_date`, `end_date` (ISO dates; start must precede end and end cannot be future). Optional fields/defaults: `initial_capital` 10000 (>0); `commission_rate` and `slippage_rate` 0.001 (each >=0 and <1); `position_size_fraction` 1.0 (>0 and <=1); `fractional_shares` true; `trend_weight`, `rsi_weight`, `momentum_weight` each 1.0 (>=0, finite, and at least one must be positive); `ma_short_window` 5 (>=1 and less than long window); `ma_long_window` 20 (>=2); `rsi_period` 14 and `momentum_period` 10 (each >=1); `entry_signals` defaults to `["Buy","Strong Buy"]`, `exit_signals` to `["Sell","Strong Sell"]`. Both signal lists must be nonempty, use `Strong Buy`, `Buy`, `Hold`, `Sell`, or `Strong Sell`, exclude `Hold`, and have no overlap. Unknown body fields are rejected. Response top-level fields: `ticker`, `configuration`, `evaluation_period`, `signal_coverage`, `metrics`, `benchmark`, `equity_curve`, `benchmark_equity_curve`, `trades`, `signals`, `retrieved_at`, `metric_assumptions`; `/docs` shows nested fields.
- **GET `/history/analyses`** — Optional query `ticker` (same normalization/syntax), `start_date`, `end_date`; date bounds are ISO `YYYY-MM-DD`, inclusive on `market_date`, and start must be on or before end. `limit` defaults to 20 (1–100); `offset` defaults to 0 (>=0). Response: `{items:[{id,ticker,signal,score,breakdown,close,market_date,retrieved_at}],limit,offset,total}`. Items sort newest market date and retrieval first.
- **GET `/history/analyses/{ticker}`** — Path ticker plus the same inclusive date filters and pagination as the collection route; response has the same page shape.
- **GET `/history/backtests`** — Optional query `ticker` (same normalization/syntax); `limit` defaults to 20 (1–100), `offset` defaults to 0 (>=0). No date filters are implemented. Response: `{items,limit,offset,total}`. Each item contains `id`, `ticker`, `requested_start_date`, `requested_end_date`, `evaluation_start_date`, `evaluation_end_date`, `initial_capital`, `final_portfolio_value`, `total_return`, nullable `annualized_return`, `maximum_drawdown`, nullable `sharpe_ratio`, `benchmark_return`, nullable `benchmark_annualized_return`, `benchmark_maximum_drawdown`, and `created_at`; newest first.
- **GET `/history/backtests/{backtest_id}`** — Integer path parameter `backtest_id`; returns the complete backtest response shape described above.

Successful analyses and successful ranking items are stored when calculated. Backtests store summary columns for listing and the full response JSON for detail retrieval. History endpoints read these records from the configured database. Analysis date filters apply inclusively to `market_date`; pagination is limit/offset based.

### Representative requests

```bash
# Single-stock analysis
curl 'http://127.0.0.1:8000/analysis/AAPL?period=1y'

# Stock ranking
curl -X POST http://127.0.0.1:8000/ranking -H 'Content-Type: application/json' \
  -d '{"tickers":["AAPL","MSFT"],"period":"6mo"}'

# Backtesting (other request fields use their documented defaults)
curl -X POST http://127.0.0.1:8000/backtest -H 'Content-Type: application/json' \
  -d '{"ticker":"AAPL","start_date":"2022-01-01","end_date":"2025-12-31"}'

# List historical analyses with inclusive date filtering and pagination
curl 'http://127.0.0.1:8000/history/analyses?ticker=AAPL&start_date=2025-01-01&end_date=2025-12-31&limit=20&offset=0'

# Retrieve historical analyses for a ticker
curl 'http://127.0.0.1:8000/history/analyses/AAPL?limit=10&offset=0'

# List historical backtest summaries
curl 'http://127.0.0.1:8000/history/backtests?ticker=AAPL&limit=20&offset=0'

# Retrieve a full backtest (replace 42 with an ID from the list)
curl 'http://127.0.0.1:8000/history/backtests/42'
```

### HTTP errors

Handled domain errors, request-schema validation errors, and database failures generally return `{"error":{"code":"...","message":"..."}}`. Examples include 422 `invalid_ticker` or `invalid_request`, 404 `no_market_data`, 502 provider or benchmark errors, and 500 `database_error` or `internal_error`. A missing backtest ID is HTTP 404 with FastAPI's `{"detail":"Backtest 42 not found"}` shape. Reversed analysis-history dates are HTTP 422 with `{"detail":"start_date must be on or before end_date"}`. Readiness failure uses its separate 503 `{"status":"unavailable"}` response. Ranking may instead return HTTP 200 with per-ticker failures under `errors`. Error formats therefore vary by handler.

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

PostgreSQL integration tests are opt-in and require an explicitly configured, dedicated `alphawatch_test` database; follow the separate integration-test instructions above.

## Current Scope & Limitations

AlphaWatch is an actively developed research prototype.

The current implementation does not include:

- User authentication or account management.
- Fundamental financial statement analysis.
- Financial news integration.

The market-data integration uses yfinance for prototyping. Provider terms and data licensing should be reviewed before production use.
