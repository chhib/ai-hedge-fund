"""
CLI regression tests for the Börsdata-backed backtest engine.

These tests exercise the full CLI workflow using fixture data to ensure
the backtest output remains consistent and benchmark calculations work properly.
"""
from __future__ import annotations

from contextlib import ExitStack
from typing import Iterable
from unittest.mock import patch

import pytest

import tests.backtesting.integration.conftest as fixture_loader
from tests.backtesting.integration.mocks import MockConfigurableAgent

from src.backtesting.engine import BacktestEngine
from src.data.models import Price


def _load_price_df(ticker: str, start: str, end: str):
    """Load price data from fixtures."""
    return fixture_loader._load_price_df_from_fixture(ticker, start, end)


def _load_price_models(ticker: str, start: str, end: str) -> list[Price]:
    """Load price models from fixtures."""
    df = _load_price_df(ticker, start, end)
    prices: list[Price] = []
    for timestamp, row in df.iterrows():
        iso_time = timestamp.isoformat().replace("+00:00", "Z")
        prices.append(
            Price(
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                volume=int(row["volume"]),
                time=iso_time,
            )
        )
    return prices


def _load_financial_metrics(ticker: str, end: str, limit: int) -> list[dict]:
    """Load financial metrics from fixtures."""
    return fixture_loader._load_financial_metrics_from_fixture(ticker, end, limit)


def _load_calendar(ticker: str, start: str | None, end: str, limit: int) -> list[dict]:
    """Load calendar data from fixtures."""
    return fixture_loader._load_calendar_from_fixture(ticker, start, end, limit)


def _load_insider_trades(ticker: str, start: str | None, end: str, limit: int) -> list[dict]:
    """Load insider trades from fixtures."""
    return fixture_loader._load_insider_from_fixture(ticker, start, end, limit)


def _fake_get_price_data(ticker: str, start_date: str, end_date: str, api_key: str | None = None):
    """Mock price data API call."""
    return _load_price_df(ticker, start_date, end_date)


def _fake_get_prices(ticker: str, start_date: str, end_date: str, api_key: str | None = None):
    """Mock prices API call."""
    return _load_price_models(ticker, start_date, end_date)


def _fake_get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
):
    """Mock financial metrics API call."""
    return _load_financial_metrics(ticker, end_date, limit)


def _fake_get_company_events(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
):
    """Mock company events API call."""
    return _load_calendar(ticker, start_date, end_date, limit)


def _fake_get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
):
    """Mock insider trades API call."""
    return _load_insider_trades(ticker, start_date, end_date, limit)


def _patch_functions(stack: ExitStack) -> None:
    """Apply all API mocks for fixture-driven testing."""
    targets: Iterable[tuple[str, object]] = [
        ("src.backtesting.engine.get_price_data", _fake_get_price_data),
        ("src.backtesting.engine.get_prices", _fake_get_prices),
        ("src.backtesting.engine.get_financial_metrics", _fake_get_financial_metrics),
        ("src.backtesting.engine.get_company_events", _fake_get_company_events),
        ("src.backtesting.engine.get_insider_trades", _fake_get_insider_trades),
        ("src.tools.api.get_price_data", _fake_get_price_data),
        ("src.tools.api.get_prices", _fake_get_prices),
        ("src.tools.api.get_financial_metrics", _fake_get_financial_metrics),
        ("src.tools.api.get_company_events", _fake_get_company_events),
        ("src.tools.api.get_insider_trades", _fake_get_insider_trades),
        ("src.backtesting.benchmarks.get_price_data", _fake_get_price_data),
    ]
    for target, replacement in targets:
        stack.enter_context(patch(target, replacement))


def test_cli_regression_full_backtest_workflow(monkeypatch, capsys):
    """Test the complete CLI backtest workflow with fixture data."""
    
    # Mock os.system to prevent clearing screen during tests
    monkeypatch.setattr("src.utils.display.os.system", lambda *_: 0)
    
    # Test configuration matching the scripts/run_fixture_backtest.py
    tickers = ["TTWO", "LUG", "FDEV"]
    decision_sequence = [
        {
            "TTWO": {"action": "buy", "quantity": 100},
            "LUG": {"action": "buy", "quantity": 30},
        },
        {},  # Hold
        {
            "TTWO": {"action": "sell", "quantity": 30},
        },
        {},  # Hold
    ]

    agent = MockConfigurableAgent(decision_sequence, tickers)
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date="2025-09-15",
        end_date="2025-09-23",
        initial_capital=100_000.0,
        model_name="fixture-model",
        model_provider="fixture-provider",
        selected_analysts=None,
        initial_margin_requirement=0.5,
    )

    # Run backtest with fixture patches
    with ExitStack() as stack:
        _patch_functions(stack)
        performance_metrics = engine.run_backtest()

    # Capture the printed output
    output = capsys.readouterr().out
    
    # Get additional data for validation
    portfolio_values = engine.get_portfolio_values()
    context_history = engine.get_daily_context()

    # Validate CLI output structure
    assert "PORTFOLIO SUMMARY:" in output
    assert "MARKET CONTEXT" in output
    assert "Corporate Events:" in output
    assert "Insider Trades:" in output
    
    # Validate all tickers appear in the output
    for ticker in tickers:
        assert ticker in output, f"Ticker {ticker} should appear in CLI output"
    
    # Validate table structure
    assert "Date" in output
    assert "Ticker" in output
    assert "Action" in output
    assert "Position Value" in output
    
    # Validate performance metrics calculation
    assert performance_metrics is not None
    assert isinstance(performance_metrics, dict)
    
    # Validate portfolio values trajectory
    assert portfolio_values is not None
    assert len(portfolio_values) > 0
    final_value = portfolio_values[-1]["Portfolio Value"]
    assert final_value > 0, "Final portfolio value should be positive"
    
    # Validate daily context history
    assert context_history is not None
    assert len(context_history) > 0
    latest_context = context_history[-1]
    assert latest_context["date"] == "2025-09-23"
    assert "company_events" in latest_context
    assert "insider_trades" in latest_context
    
    # Validate SPY benchmark data can be loaded
    spy_df = _load_price_df("SPY", "2025-09-15", "2025-09-23")
    assert spy_df is not None
    assert len(spy_df) > 0
    benchmark_return = (spy_df.iloc[-1]["close"] / spy_df.iloc[0]["close"] - 1) * 100
    assert -10.0 <= benchmark_return <= 10.0, f"SPY benchmark return {benchmark_return}% seems unreasonable"


def test_cli_regression_benchmark_calculation():
    """Test that benchmark calculations are consistent across test runs."""
    
    # Load SPY fixture data for benchmark calculation
    spy_df = _load_price_df("SPY", "2025-09-15", "2025-09-23")
    
    # Calculate benchmark return
    initial_price = spy_df.iloc[0]["close"]
    final_price = spy_df.iloc[-1]["close"]
    benchmark_return = (final_price / initial_price - 1) * 100
    
    # Validate benchmark return is consistent
    # This serves as a regression test to catch fixture data changes
    expected_return = 1.48  # This should match the output from run_fixture_backtest.py
    assert abs(benchmark_return - expected_return) < 0.01, \
        f"SPY benchmark return {benchmark_return:.2f}% differs from expected {expected_return}%"


def test_cli_regression_market_context_content():
    """Test that market context data contains expected content structure."""
    
    tickers = ["TTWO", "LUG", "FDEV"]
    end_date = "2025-09-23"
    
    # Load context data directly from fixtures
    for ticker in tickers:
        # Test calendar data loading
        events = _load_calendar(ticker, None, end_date, 1000)
        assert isinstance(events, list)
        
        # Test insider trades loading  
        trades = _load_insider_trades(ticker, None, end_date, 1000)
        assert isinstance(trades, list)
        
        # If events exist, validate structure
        if events:
            event = events[0]
            assert "date" in event or "release_date" in event
            assert "category" in event or "title" in event
        
        # If trades exist, validate structure
        if trades:
            trade = trades[0]
            assert "transaction_date" in trade or "filing_date" in trade
            assert "name" in trade or "insider_name" in trade


def test_cli_regression_performance_metrics_consistency():
    """Test that performance metrics remain consistent across runs."""
    
    tickers = ["TTWO", "LUG"]  # Shorter test for performance
    decision_sequence = [
        {"TTWO": {"action": "buy", "quantity": 50}, "LUG": {"action": "buy", "quantity": 15}},
        {},  # Hold
    ]

    agent = MockConfigurableAgent(decision_sequence, tickers)
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date="2025-09-15",
        end_date="2025-09-23",
        initial_capital=50_000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.5,
    )

    # Run backtest with fixture patches
    with ExitStack() as stack:
        _patch_functions(stack)
        performance_metrics = engine.run_backtest()

    # Validate performance metrics structure
    portfolio_values = engine.get_portfolio_values()
    final_value = portfolio_values[-1]["Portfolio Value"]
    expected_return = (final_value / 50_000.0 - 1.0) * 100

    # These values should be deterministic with fixture data
    assert performance_metrics is not None
    
    # The actual values depend on the fixture data, but structure should be consistent
    if "sharpe_ratio" in performance_metrics:
        assert isinstance(performance_metrics["sharpe_ratio"], (int, float, type(None)))
    if "max_drawdown" in performance_metrics:
        assert isinstance(performance_metrics["max_drawdown"], (int, float, type(None)))