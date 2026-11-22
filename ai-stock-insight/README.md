# AlphaWatch

AlphaWatch is a Python stock research prototype that combines historical market data, deterministic technical indicators, optional OpenAI commentary, and a historical backtesting API. Persistent storage, authentication, fundamentals, news, and a web frontend are not implemented yet.

## Phase 1 backend

- Point-in-time moving averages, RSI, momentum, and volatility.
- Configurable weighted scoring with an indicator contribution breakdown.
- Input validation and normalization for tickers and retrieval periods.
- Bounded concurrent ticker retrieval with per-symbol failure isolation and exponential retry delay.
- FastAPI endpoints at `/health`, `/analysis/{ticker}`, and `/ranking`; interactive OpenAPI docs are at `/docs`.
- Stable API error bodies distinguish invalid ticker syntax, insufficient history, missing market data, provider failure, and internal errors.
- `market_date` is an exchange-local calendar date. `retrieved_at` is a separate UTC time recorded by the API process, not a market close timestamp.
- CLI workflow remains available and only calls OpenAI when `OPENAI_API_KEY` is set.

RSI uses simple rolling means of gains and losses (not Wilder smoothing), requires `period` price changes, and assigns RSI 50 to a fully flat window. Scoring requires MA_SHORT, MA_LONG, RSI, and MOMENTUM. Equal moving averages contribute zero. Default weights are 1:1:1; custom nonnegative finite weights are normalized to the same score range so signal thresholds remain comparable.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run from this directory (`ai-stock-insight`). Set `OPENAI_API_KEY` only if AI commentary is needed by the CLI. The API endpoints return deterministic technical analysis and do not require an OpenAI key.

## API examples

```bash
curl http://127.0.0.1:8000/analysis/AAPL
curl -X POST http://127.0.0.1:8000/ranking \
  -H 'Content-Type: application/json' \
  -d '{"tickers":["AAPL","MSFT"],"period":"6mo"}'
```

`/ranking` returns successful symbols in deterministic score/ticker order and reports retrieval or data errors separately. Supported periods are `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, and `max`. Provider controls can be set with `DATA_MAX_WORKERS`, `DATA_RETRIES`, `DATA_RETRY_BACKOFF_SECONDS`, `DATA_RETRY_JITTER_SECONDS`, and `DATA_REQUEST_INTERVAL_SECONDS`.

## Tests

From the repository root run `pytest`. Market data is mocked in tests; no live provider or OpenAI credentials are needed.

## Historical backtesting

Backtesting evaluates the existing AlphaWatch indicator and scoring functions on historical OHLC data. The default long-only rules enter on `Buy` or `Strong Buy`, exit on `Sell` or `Strong Sell`, and remain in cash/position on `Hold`. It does not short stocks. Entry and exit signal sets, scoring weights, position sizing, commissions, and slippage can be configured in the request.

The engine derives its calendar warm-up from the configured indicator lookbacks: it estimates the required sessions as the maximum of MA-long, RSI period plus one close, and momentum period plus one close, converts sessions to calendar days, adds a two-week holiday/weekend buffer, and keeps a 90-day minimum. With the defaults (MA20, RSI14, momentum10), this remains 90 calendar days. Warm-up rows do not produce evaluation-period signals or trades. The response reports the effective warm-up, required and available pre-period observations, signal coverage, and any evaluation trading dates without a valid score. If no evaluation date has a valid score, the API returns `insufficient_warmup`.

Indicators are calculated over chronological history, then only the inclusive requested evaluation dates are simulated. A signal calculated from a session close can only execute on the next available trading row. It uses that row's Open; if Open is absent, non-finite, or nonpositive, it falls back to that same next session's Close. The fallback delays execution until the close and is disclosed in the signal timeline. No order executes at the signal day's close. Missing sessions are not synthesized.

The default position sizing invests all available cash (fractional shares enabled). A configured size fraction invests that fraction of current cash. Whole-share mode floors quantity and rejects an entry if it cannot buy one share. Buys pay `reference price * (1 + slippage)` and sells receive `reference price * (1 - slippage)`; commission is applied to fill notional on each side. `transaction_costs` includes commission and slippage. Gross P/L uses reference prices before costs; net P/L subtracts both costs. Portfolio value is cash plus shares marked at each day's Close. An open position is marked to market on the final day and is not force-liquidated; only completed trades appear in trade statistics.

### Metrics and benchmark assumptions

- Total return: `final equity / initial capital - 1`.
- Annualized return: `(final equity / initial capital) ** (252 / daily return observations) - 1`; it is omitted with fewer than two return observations.
- Daily returns use consecutive complete portfolio equity observations; missing, non-finite, or nonpositive equity values are rejected rather than forward-filled. Annualized volatility is sample standard deviation times `sqrt(252)`. Sharpe uses zero risk-free return and is omitted when volatility is zero or observations are insufficient.
- Maximum drawdown is the minimum of `equity / prior running peak - 1`. Downside deviation is the annualized root mean square of negative daily returns (nonnegative returns contribute zero).
- Trade win rate, mean winning/losing net P/L, holding period in trading sessions, and profit factor use completed trades only. Profit factor is omitted when there are no losing trades; trade averages and win rate are omitted when there are no completed trades.
- SPY and the strategy must have the same evaluation trading dates; incomplete date alignment raises `benchmark_incomplete` and no daily benchmark metrics are returned. This prevents multi-session returns from being mislabeled as daily observations. Each curve is rebased to the same initial capital at the first evaluation date. Both use yfinance prices with `auto_adjust=False`; benchmark returns exclude dividend-adjusted total returns. A total-return series would be needed to include distributions.

Backtested returns describe this simulation and its assumptions. They do not guarantee future results.

### API

```http
POST /backtest
Content-Type: application/json
```

```json
{
  "ticker": "AAPL",
  "start_date": "2021-01-01",
  "end_date": "2026-01-01",
  "initial_capital": 10000,
  "commission_rate": 0.001,
  "slippage_rate": 0.001
}
```

The response contains `configuration`, `evaluation_period`, `signal_coverage`, `metrics`, `benchmark`, `equity_curve`, `benchmark_equity_curve`, `trades`, `signals`, `retrieved_at`, and `metric_assumptions`. Optional `ma_short_window`, `ma_long_window`, `rsi_period`, and `momentum_period` request fields configure the lookbacks; the effective warm-up is returned in `configuration`. Each signal records its next eligible execution date and the execution source (`open` or `close_fallback`). Invalid ticker syntax returns 422, no requested-period data returns 404, insufficient indicator history returns 422, incomplete benchmark alignment/provider failures return 502, and unexpected errors return a generic 500 response.

Example response shape (angle-bracketed values are placeholders, not a literal API response):

```text
{
  "ticker": "AAPL",
  "configuration": {"...": "..."},
  "evaluation_period": {"start_date": "<first trading date>", "end_date": "<last trading date>"},
  "signal_coverage": {"evaluation_trading_dates": "<count>", "valid_signal_dates": "<count>", "missing_signal_dates": [], "warmup_status": "complete", "first_valid_signal_date": "<trading date>"},
  "metrics": {"initial_capital": "<configured amount>", "final_portfolio_value": "<computed amount>", "total_return": "<computed fraction>", "completed_trades": "<count>", "win_rate": "<fraction or null>"},
  "benchmark": {"benchmark_symbol": "SPY", "benchmark_total_return": "<computed fraction>", "benchmark_price_basis": "SPY Close with auto_adjust=False; dividend-adjusted total returns excluded"},
  "equity_curve": [{"date": "<trading date>", "cash": "<computed amount>", "shares": "<computed quantity>", "position_market_value": "<computed amount>", "total_equity": "<computed amount>", "daily_return": "<fraction or null>", "cumulative_return": "<fraction>"}],
  "benchmark_equity_curve": [],
  "trades": [],
  "signals": [],
  "retrieved_at": "<UTC retrieval timestamp>",
  "metric_assumptions": {"annualization": "252 trading sessions per year"}
}
```

The example contains no claimed performance results for any ticker. A live response is calculated from data retrieved for that request.

## Current data flow

```text
CLI or FastAPI -> yfinance fetcher -> technical indicators -> score + breakdown
                                            `-> optional OpenAI commentary (CLI only)
```

The technical score is a deterministic research aid, not a prediction or investment recommendation. The backtest models next-session execution, commissions, slippage, and portfolio equity using the assumptions documented above. The yfinance interface is used for prototyping; provider terms and data licensing should be reviewed before production use. Backtested performance does not guarantee future results.
