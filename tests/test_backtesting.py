from datetime import date, timedelta
import math

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from backtesting.config import BacktestConfig
from backtesting.engine import run_backtest
from backtesting.metrics import calculate_performance, compare_benchmark
from backtesting.portfolio import simulate_portfolio
from data import fetcher
from data.errors import BenchmarkUnavailableError, IncompleteBenchmarkDataError, InsufficientDataError, InsufficientWarmupError, NoMarketDataError, ProviderUnavailableError
from signals.indicators import IndicatorWindows


def config(**kwargs):
    defaults = dict(ticker="TEST", start_date=date(2025, 1, 1), end_date=date(2025, 1, 5), initial_capital=10_000, commission_rate=0.01, slippage_rate=0.01)
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def synthetic_ohlc(start=date(2024, 10, 1), count=100, close_values=None):
    dates = [start + timedelta(days=i) for i in range(count)]
    if close_values is None:
        close_values = [100 + i for i in range(count)]
    return pd.DataFrame({"Date": dates, "Open": [value - 1 for value in close_values], "Close": close_values})


def test_next_session_execution_costs_cash_and_realized_profit():
    frame = pd.DataFrame({
        "Date": [date(2025, 1, i) for i in range(1, 5)],
        "Open": [99, 110, 129, 140],
        "Close": [100, 120, 130, 135],
        "Score": [2, 0, -2, 0],
        "Signal": ["Strong Buy", "Hold", "Strong Sell", "Hold"],
    })
    curve, trades, timeline = simulate_portfolio(frame, "TEST", config())
    assert timeline[0]["execution_action"] == "none"
    assert timeline[0]["execution_date"] == date(2025, 1, 2)
    assert timeline[1]["execution_action"] == "buy"
    assert timeline[1]["execution_price_type"] == "open"
    assert timeline[2]["execution_action"] == "none"
    assert timeline[3]["execution_action"] == "sell"
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_date"] == date(2025, 1, 2)
    assert trade["exit_date"] == date(2025, 1, 4)
    assert trade["entry_price"] == pytest.approx(111.1)
    assert trade["exit_price"] == pytest.approx(138.6)
    assert trade["quantity"] == pytest.approx(10_000 / (111.1 * 1.01))
    quantity = trade["quantity"]
    assert trade["entry_commission"] == pytest.approx(quantity * 111.1 * 0.01)
    assert trade["exit_commission"] == pytest.approx(quantity * 138.6 * 0.01)
    assert trade["entry_slippage_cost"] == pytest.approx(quantity * (111.1 - 110))
    assert trade["exit_slippage_cost"] == pytest.approx(quantity * (140 - 138.6))
    assert trade["transaction_costs"] == pytest.approx(
        trade["entry_commission"] + trade["exit_commission"] + trade["entry_slippage_cost"] + trade["exit_slippage_cost"]
    )
    assert trade["gross_pnl"] == pytest.approx((140 - 110) * trade["quantity"])
    assert trade["net_pnl"] == pytest.approx(trade["gross_pnl"] - trade["transaction_costs"])
    assert curve.iloc[0]["cash"] == 10_000
    assert curve.iloc[1]["cash"] == pytest.approx(0, abs=1e-7)
    assert curve.iloc[-1]["shares"] == 0
    assert curve.iloc[-1]["total_equity"] == pytest.approx(10_000 + trade["net_pnl"])
    closes = frame["Close"].tolist()
    for idx, row in curve.iterrows():
        assert row["cash"] >= -1e-7
        assert row["position_market_value"] == pytest.approx(row["shares"] * closes[idx])
        assert row["total_equity"] == pytest.approx(row["cash"] + row["shares"] * closes[idx])
    assert curve.iloc[3]["total_equity"] - curve.iloc[0]["total_equity"] == pytest.approx(trade["net_pnl"])
    assert curve.iloc[1]["total_equity"] == pytest.approx(quantity * 120)
    entry_costs = trade["entry_commission"] + trade["entry_slippage_cost"]
    assert curve.iloc[1]["total_equity"] - 10_000 == pytest.approx(quantity * (120 - 110) - entry_costs)


def test_partial_position_sizing_reconciles_cash_and_equity():
    frame = pd.DataFrame({
        "Date": [date(2025, 1, i) for i in range(1, 4)],
        "Open": [99, 110, 120],
        "Close": [100, 115, 125],
        "Score": [2, 0, 0],
        "Signal": ["Buy", "Hold", "Hold"],
    })
    cfg = config(position_size_fraction=0.4, commission_rate=0.02, slippage_rate=0.01)
    curve, _, _ = simulate_portfolio(frame, "TEST", cfg)
    expected_shares = (10_000 * 0.4) / (111.1 * 1.02)
    expected_cash = 10_000 * 0.6
    assert curve.loc[1, "shares"] == pytest.approx(expected_shares)
    assert curve.loc[1, "cash"] == pytest.approx(expected_cash)
    for idx, row in curve.iterrows():
        assert row["cash"] >= -1e-7
        assert row["total_equity"] == pytest.approx(row["cash"] + row["shares"] * frame.loc[idx, "Close"])


def test_hold_no_duplicate_entries_open_fallback_and_no_same_day_execution():
    frame = pd.DataFrame({
        "Date": [date(2025, 2, i) for i in range(1, 5)],
        "Open": [None, None, 100, None],
        "Close": [50, 55, 60, 65],
        "Score": [2, 2, 0, 0],
        "Signal": ["Buy", "Buy", "Hold", "Hold"],
    })
    curve, trades, timeline = simulate_portfolio(frame, "TEST", config(commission_rate=0, slippage_rate=0))
    assert timeline[0]["execution_action"] == "none"
    assert timeline[1]["execution_action"] == "buy"
    assert timeline[1]["execution_price_type"] == "close_fallback"
    assert timeline[2]["action"] == "hold"
    assert len(trades) == 0
    assert curve.iloc[-1]["shares"] > 0
    assert curve.iloc[-1]["total_equity"] == pytest.approx(curve.iloc[-1]["cash"] + curve.iloc[-1]["shares"] * 65)


def test_insufficient_cash_for_whole_shares_and_unexecuted_final_signal():
    frame = pd.DataFrame({"Date": [date(2025, 3, i) for i in range(1, 4)], "Open": [100, 200, 200], "Close": [100, 200, 200], "Score": [2, 2, 2], "Signal": ["Buy", "Hold", "Hold"]})
    curve, trades, timeline = simulate_portfolio(frame, "TEST", config(initial_capital=100, commission_rate=0, slippage_rate=0, fractional_shares=False))
    assert curve["shares"].max() == 0
    assert not trades
    assert timeline[-1]["execution_date"] is None
    assert timeline[-1]["execution_action"] == "none"


def test_performance_metrics_and_zero_volatility_zero_trade_cases():
    equity = pd.Series([100.0, 110.0, 99.0, 120.0], index=pd.date_range("2025-01-01", periods=4))
    metrics = calculate_performance(equity, [], 100)
    assert metrics["total_return"] == pytest.approx(0.2)
    assert metrics["maximum_drawdown"] == pytest.approx(-0.1)
    assert metrics["completed_trades"] == 0
    assert metrics["win_rate"] is None
    assert metrics["profit_factor"] is None
    assert metrics["sharpe_ratio"] is not None
    flat = calculate_performance(pd.Series([100.0, 100.0, 100.0]), [], 100)
    assert flat["annualized_volatility"] == 0
    assert flat["sharpe_ratio"] is None
    assert flat["annualized_return"] == 0
    assert metrics["annualized_return"] == pytest.approx(1.2 ** (252 / 3) - 1)


def test_hand_calculated_annualized_volatility_sharpe_and_empty_returns():
    daily_returns = [0.01, -0.02, 0.03]
    equity = pd.Series([100.0, 101.0, 101.0 * 0.98, 101.0 * 0.98 * 1.03])
    metrics = calculate_performance(equity, [], 100)
    sample_variance = 19 / 30_000
    daily_std = math.sqrt(sample_variance)
    expected_volatility = daily_std * math.sqrt(252)
    expected_sharpe = (sum(daily_returns) / len(daily_returns)) / daily_std * math.sqrt(252)
    assert metrics["annualized_volatility"] == pytest.approx(expected_volatility)
    assert metrics["sharpe_ratio"] == pytest.approx(expected_sharpe)
    one_observation = calculate_performance(pd.Series([100.0]), [], 100)
    assert one_observation["total_return"] == 0
    assert one_observation["annualized_return"] is None
    assert one_observation["average_daily_return"] is None
    assert one_observation["annualized_volatility"] is None
    assert one_observation["sharpe_ratio"] is None
    assert one_observation["downside_deviation"] is None
    with pytest.raises(ValueError, match="at least one"):
        calculate_performance(pd.Series(dtype=float), [], 100)


def test_missing_equity_values_are_rejected_instead_of_forward_filled():
    with pytest.raises(ValueError, match="without gaps"):
        calculate_performance(pd.Series([100.0, float("nan"), 110.0]), [], 100)


def test_trade_metrics_profit_factor_and_benchmark_alignment():
    trades = [{"net_pnl": 20, "holding_period_sessions": 3}, {"net_pnl": -10, "holding_period_sessions": 1}]
    metrics = calculate_performance(pd.Series([100.0, 110.0, 105.0]), trades, 100)
    assert metrics["win_rate"] == 0.5
    assert metrics["profit_factor"] == 2
    strategy_curve = pd.DataFrame({"date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)], "total_equity": [100, 110, 105]})
    spy = pd.DataFrame({"Date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)], "Close": [400, 420, 440]})
    comp, curve = compare_benchmark(strategy_curve, spy, 100)
    assert comp["evaluation_dates"] == 3
    assert comp["benchmark_total_return"] == pytest.approx(0.1)
    assert comp["benchmark_annualized_return"] == pytest.approx(1.1 ** (252 / 2) - 1)
    assert curve[0]["strategy_equity"] == pytest.approx(100)
    assert curve[0]["benchmark_equity"] == pytest.approx(100)
    assert curve[-1]["benchmark_equity"] == 110
    with pytest.raises(BenchmarkUnavailableError):
        compare_benchmark(strategy_curve, spy.assign(Date=[date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]), 100)


def test_benchmark_missing_middle_date_rejects_annualized_daily_metrics():
    strategy_curve = pd.DataFrame({
        "date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4)],
        "total_equity": [100, 110, 105, 120],
    })
    spy = pd.DataFrame({"Date": [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 4)], "Close": [400, 420, 440]})
    with pytest.raises(IncompleteBenchmarkDataError):
        compare_benchmark(strategy_curve, spy, 100)


def test_historical_fetch_uses_warmup_and_inclusive_end(monkeypatch):
    calls = []
    raw = pd.DataFrame({("Open", "TEST"): [9, 10], ("Close", "TEST"): [10, 11]}, index=pd.to_datetime(["2024-12-31", "2025-01-01"]))
    monkeypatch.setattr(fetcher, "_download_with_retries", lambda ticker, params, *args, **kwargs: calls.append((ticker, params)) or raw)
    result = fetcher.fetch_historical_data("TEST", date(2025, 1, 1), date(2025, 1, 5), warmup_days=90)
    assert calls[0][1]["start"] == "2024-10-03"
    assert calls[0][1]["end"] == "2025-01-06"
    assert result.columns.tolist() == ["Date", "Open", "Close"]
    assert result.Date.tolist() == [date(2024, 12, 31), date(2025, 1, 1)]
    with pytest.raises(ValueError):
        fetcher.fetch_historical_data("TEST", date(2025, 1, 5), date(2025, 1, 5))


def test_engine_warmup_filtered_and_lookahead_free():
    data = synthetic_ohlc(count=102)
    start, end = date(2025, 1, 1), date(2025, 1, 10)
    def loader(ticker, start_date, end_date, warmup_days):
        assert warmup_days == 90
        return data.copy()
    result = run_backtest(config(start_date=start, end_date=end), data_loader=loader)
    assert result["evaluation_period"] == {"start_date": "2025-01-01", "end_date": "2025-01-10"}
    assert result["configuration"]["effective_warmup_calendar_days"] == 90
    assert result["signal_coverage"]["warmup_status"] == "complete"
    assert not result["signal_coverage"]["missing_signal_dates"]
    assert all(trade["entry_date"] >= start for trade in result["trades"])
    assert all(date.fromisoformat(signal["date"]) >= start for signal in result["signals"])
    assert all(signal["execution_date"] is None or signal["execution_date"] > signal["date"] for signal in result["signals"])
    changed = data.copy()
    changed.loc[changed.Date > end, "Close"] = 1000
    changed.loc[changed.Date > end, "Open"] = 999
    altered = run_backtest(config(start_date=start, end_date=end), data_loader=lambda *args, **kwargs: changed.copy())
    prefix = [x["signal"] for x in result["signals"]]
    assert prefix == [x["signal"] for x in altered["signals"]]


def test_future_change_inside_evaluation_cannot_change_earlier_decisions_or_equity():
    history = synthetic_ohlc(count=150)
    # Create a rise and a decline so the requested interval has an actual completed trade.
    values = []
    for idx in range(len(history)):
        if idx < 102:
            values.append(100 + idx * 0.5)
        elif idx < 120:
            values.append(values[-1] - 1.5)
        else:
            values.append(values[-1] + 0.5)
    history["Close"] = values
    history["Open"] = [value - 0.2 for value in values]
    start, end = date(2025, 1, 1), date(2025, 2, 15)
    changed_at = date(2025, 1, 20)
    cfg = config(start_date=start, end_date=end)
    original = run_backtest(cfg, data_loader=lambda *args, **kwargs: history.copy())
    changed = history.copy()
    changed.loc[changed["Date"] == changed_at, "Close"] += 200
    altered = run_backtest(cfg, data_loader=lambda *args, **kwargs: changed.copy())
    assert any(trade["exit_date"] < changed_at.isoformat() for trade in original["trades"])
    before_original = [row for row in original["signals"] if row["date"] < changed_at.isoformat()]
    before_altered = [row for row in altered["signals"] if row["date"] < changed_at.isoformat()]
    assert before_original == before_altered
    earlier_trades = lambda result: [trade for trade in result["trades"] if trade["exit_date"] < changed_at.isoformat()]
    assert earlier_trades(original) == earlier_trades(altered)
    prior_equity_original = [row for row in original["equity_curve"] if row["date"] < changed_at.isoformat()]
    prior_equity_altered = [row for row in altered["equity_curve"] if row["date"] < changed_at.isoformat()]
    pd.testing.assert_frame_equal(pd.DataFrame(prior_equity_original), pd.DataFrame(prior_equity_altered), check_exact=True)


def test_engine_insufficient_and_missing_benchmark():
    short = synthetic_ohlc(start=date(2024, 12, 1), count=18)
    def loader(ticker, *args, **kwargs):
        return short.copy() if ticker != "SPY" else short.copy()
    with pytest.raises(InsufficientDataError):
        run_backtest(config(start_date=date(2024, 12, 10), end_date=date(2024, 12, 18)), data_loader=loader)
    longer = synthetic_ohlc(start=date(2024, 10, 1), count=130)
    def no_spy(ticker, *args, **kwargs):
        if ticker == "SPY":
            return pd.DataFrame(columns=["Date", "Open", "Close"])
        return longer
    with pytest.raises(BenchmarkUnavailableError):
        run_backtest(config(start_date=date(2025, 1, 1), end_date=date(2025, 1, 10)), data_loader=no_spy)


def test_warmup_scales_with_indicator_windows_and_partial_history_is_reported():
    windows = IndicatorWindows(ma_short=5, ma_long=60, rsi_period=40, momentum_period=45)
    cfg = config(indicator_windows=windows)
    assert windows.required_observations == 60
    assert cfg.effective_warmup_days == windows.warmup_calendar_days
    assert cfg.effective_warmup_days > 90

    start = date(2025, 1, 1)
    partial_history = synthetic_ohlc(start=start - timedelta(days=10), count=40)
    short_warmup_config = config(start_date=start, end_date=start + timedelta(days=29), warmup_days=10)
    def loader(ticker, start_date, end_date, warmup_days):
        assert warmup_days == 10
        return partial_history.copy()
    result = run_backtest(short_warmup_config, data_loader=loader)
    coverage = result["signal_coverage"]
    assert coverage["warmup_status"] == "partial"
    assert coverage["missing_signal_dates"]
    assert coverage["first_valid_signal_date"] > start.isoformat()
    assert result["configuration"]["available_preperiod_observations"] == 10

    longer_windows = IndicatorWindows(ma_short=5, ma_long=120, rsi_period=14, momentum_period=10)
    longer_config = config(start_date=start, end_date=start + timedelta(days=45), indicator_windows=longer_windows)
    longer_history = synthetic_ohlc(count=150)
    requested_warmups = []
    def longer_loader(ticker, start_date, end_date, warmup_days):
        requested_warmups.append(warmup_days)
        return longer_history.copy()
    longer_result = run_backtest(longer_config, data_loader=longer_loader)
    assert requested_warmups == [longer_windows.warmup_calendar_days] * 2
    assert longer_result["configuration"]["required_indicator_observations"] == 120
    assert longer_result["signal_coverage"]["missing_signal_dates"]


def test_no_valid_evaluation_signals_returns_explicit_warmup_error():
    start = date(2025, 1, 1)
    history = synthetic_ohlc(start=start - timedelta(days=5), count=15)
    cfg = config(start_date=start, end_date=start + timedelta(days=9), warmup_days=5)
    with pytest.raises(InsufficientWarmupError):
        run_backtest(cfg, data_loader=lambda *args, **kwargs: history.copy())


def test_engine_sorts_deduplicates_and_skips_invalid_prices():
    clean = synthetic_ohlc(count=102)
    messy = pd.concat([clean.iloc[::-1], clean.iloc[[5]], pd.DataFrame({"Date": [date(2025, 1, 5)], "Open": [1], "Close": [float("nan")]})], ignore_index=True)
    def loader(ticker, *args, **kwargs):
        return messy.copy()
    result = run_backtest(config(start_date=date(2025, 1, 1), end_date=date(2025, 1, 10)), data_loader=loader)
    dates = [row["date"] for row in result["equity_curve"]]
    assert dates == sorted(set(dates))


def test_backtest_api_validation_and_response(monkeypatch):
    client = TestClient(main.app)
    payload = {"ticker": "AAPL", "start_date": "2021-01-01", "end_date": "2021-02-01", "initial_capital": 10000}
    sample = run_backtest(config(ticker="AAPL", start_date=date(2025, 1, 1), end_date=date(2025, 1, 5)), data_loader=lambda *a, **k: synthetic_ohlc())
    monkeypatch.setattr(main, "run_backtest", lambda config: sample)
    response = client.post("/backtest", json=payload)
    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"
    assert response.json()["benchmark"]["benchmark_symbol"] == "SPY"
    assert response.json()["equity_curve"]
    assert response.json()["signal_coverage"]["warmup_status"] == "complete"
    assert response.json()["configuration"]["effective_warmup_calendar_days"] == 90
    assert client.post("/backtest", json={**payload, "ticker": "bad ticker!"}).json()["error"]["code"] == "invalid_ticker"
    assert client.post("/backtest", json={**payload, "start_date": "2022-01-01", "end_date": "2021-01-01"}).status_code == 422
    assert client.post("/backtest", json={**payload, "end_date": "2999-01-01"}).status_code == 422
    captured = {}
    def capture_config(backtest_config):
        captured["config"] = backtest_config
        return sample
    monkeypatch.setattr(main, "run_backtest", capture_config)
    configured = client.post("/backtest", json={**payload, "ma_long_window": 120})
    assert configured.status_code == 200
    assert captured["config"].indicator_windows.ma_long == 120
    assert captured["config"].effective_warmup_days > 90
    defaults = client.post("/backtest", json=payload)
    assert defaults.status_code == 200
    assert captured["config"].indicator_windows.ma_short == 5
    assert captured["config"].indicator_windows.ma_long == 20
    invalid_windows = client.post("/backtest", json={**payload, "ma_short_window": 20, "ma_long_window": 5})
    assert invalid_windows.status_code == 422
    monkeypatch.setattr(main, "run_backtest", lambda config: (_ for _ in ()).throw(InsufficientDataError()))
    assert client.post("/backtest", json=payload).json()["error"]["code"] == "insufficient_data"
    monkeypatch.setattr(main, "run_backtest", lambda config: (_ for _ in ()).throw(InsufficientWarmupError()))
    assert client.post("/backtest", json=payload).json()["error"]["code"] == "insufficient_warmup"
    monkeypatch.setattr(main, "run_backtest", lambda config: (_ for _ in ()).throw(ProviderUnavailableError()))
    assert client.post("/backtest", json=payload).status_code == 502
    monkeypatch.setattr(main, "run_backtest", lambda config: (_ for _ in ()).throw(NoMarketDataError()))
    no_data = client.post("/backtest", json=payload)
    assert no_data.status_code == 404
    assert no_data.json()["error"]["code"] == "no_market_data"
    assert "BacktestResponse" in client.get("/openapi.json").json()["components"]["schemas"]
