#!/usr/bin/env python3
from __future__ import annotations

from contextlib import ExitStack
from typing import Iterable
from unittest.mock import patch

import tests.backtesting.integration.conftest as fixture_loader
from tests.backtesting.integration.mocks import MockConfigurableAgent

from src.backtesting.engine import BacktestEngine
from src.data.models import Price


def _load_price_df(ticker: str, start: str, end: str):
    return fixture_loader._load_price_df_from_fixture(ticker, start, end)


def _load_price_models(ticker: str, start: str, end: str) -> list[Price]:
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
    return fixture_loader._load_financial_metrics_from_fixture(ticker, end, limit)


def _load_calendar(ticker: str, start: str | None, end: str, limit: int) -> list[dict]:
    return fixture_loader._load_calendar_from_fixture(ticker, start, end, limit)


def _load_insider_trades(ticker: str, start: str | None, end: str, limit: int) -> list[dict]:
    return fixture_loader._load_insider_from_fixture(ticker, start, end, limit)


def _fake_get_price_data(ticker: str, start_date: str, end_date: str, api_key: str | None = None):
    return _load_price_df(ticker, start_date, end_date)


def _fake_get_prices(ticker: str, start_date: str, end_date: str, api_key: str | None = None):
    return _load_price_models(ticker, start_date, end_date)


def _fake_get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str | None = None,
):
    return _load_financial_metrics(ticker, end_date, limit)


def _fake_get_company_events(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
):
    return _load_calendar(ticker, start_date, end_date, limit)


def _fake_get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str | None = None,
):
    return _load_insider_trades(ticker, start_date, end_date, limit)


def _patch_functions(stack: ExitStack) -> None:
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


def run_backtest_with_fixtures() -> None:
    tickers = ["TTWO", "LUG", "FDEV"]
    decision_sequence = [
        {
            "TTWO": {"action": "buy", "quantity": 100},
            "LUG": {"action": "buy", "quantity": 30},
        },
        {},
        {
            "TTWO": {"action": "sell", "quantity": 30},
        },
        {},
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

    with ExitStack() as stack:
        _patch_functions(stack)
        performance_metrics = engine.run_backtest()

    portfolio_values = engine.get_portfolio_values()
    context_history = engine.get_daily_context()

    print("\nPerformance metrics:")
    for metric, value in performance_metrics.items():
        print(f"  {metric}: {value}")

    print("\nPortfolio value trajectory (last 5 points):")
    for point in portfolio_values[-5:]:
        print(f"  {point['Date'].date()} -> {point['Portfolio Value']:.2f}")

    print("\nLatest daily context excerpt:")
    if context_history:
        latest_context = context_history[-1]
        print(f"  Date: {latest_context['date']}")
        print(f"  Company events tickers: {list(latest_context['company_events'].keys())}")
        print(f"  Insider trade tickers: {list(latest_context['insider_trades'].keys())}")
    else:
        print("  No context available")

    spy_df = _load_price_df("SPY", "2025-09-15", "2025-09-23")
    benchmark_return = (spy_df.iloc[-1]["close"] / spy_df.iloc[0]["close"] - 1) * 100
    print(f"\nBenchmark SPY return over period: {benchmark_return:+.2f}%")


if __name__ == "__main__":
    run_backtest_with_fixtures()
