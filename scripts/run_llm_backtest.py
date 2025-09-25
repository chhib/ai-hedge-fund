#!/usr/bin/env python3
from __future__ import annotations

import sys
from contextlib import ExitStack
from typing import Iterable, Dict, Any, Optional
from unittest.mock import patch

import tests.backtesting.integration.conftest as fixture_loader
from src.backtesting.cli import main as run_cli
from src.data.borsdata_client import BorsdataAPIError
from src.data.models import Price, FinancialMetrics
from src.utils.llm import call_llm


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
) -> list[FinancialMetrics]:
    metrics_data = _load_financial_metrics(ticker, end_date, limit)
    return [FinancialMetrics(**metric) for metric in metrics_data]


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

def _fake_get_instrument(self, ticker: str, *, api_key: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
    if ticker == "TTWO":
        return {"insId": 12134}
    elif ticker == "FDEV":
        return {"insId": 39716}
    elif ticker == "LUG":
        return {"insId": 11111} # Placeholder
    elif ticker == "SPY":
        return {"insId": 22222} # Placeholder
    else:
        raise BorsdataAPIError(f"Ticker '{ticker}' not found in fake_get_instrument")

def _fake_call_llm(prompt: any, pydantic_model: type, agent_name: str | None = None, state: any | None = None, max_retries: int = 3, default_factory=None) -> any:
    if default_factory:
        return default_factory()
    return None

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
        ("src.data.borsdata_client.BorsdataClient.get_instrument", _fake_get_instrument),
        ("src.utils.llm.call_llm", _fake_call_llm),
    ]
    for target, replacement in targets:
        stack.enter_context(patch(target, replacement))


def run_backtest_with_llm() -> None:
    with ExitStack() as stack:
        _patch_functions(stack)
        
        # Mock sys.argv to run the CLI non-interactively
        with patch.object(sys, 'argv', [
            'backtester',
            '--tickers', 'TTWO,LUG,FDEV',
            '--start-date', '2025-09-23',
            '--end-date', '2025-09-23',
            '--analysts-all',
            '--model-name', 'gpt-5',
            '--model-provider', 'OpenAI',
        ]):
            run_cli()


if __name__ == "__main__":
    run_backtest_with_llm()