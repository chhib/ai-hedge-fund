import asyncio
from datetime import date

import pytest

from src.data.models import CompanyEvent, FinancialMetrics, InsiderTrade, LineItem, Price
from src.data.prefetch_store import PrefetchParameters, PrefetchStore
from src.data.parallel_api_wrapper import parallel_fetch_ticker_data


def _sample_metrics(ticker: str) -> FinancialMetrics:
    base_values = {
        name: None for name in FinancialMetrics.model_fields.keys()
    }
    base_values.update(
        {
            "ticker": ticker,
            "report_period": "2025-Q1",
            "period": "ttm",
            "currency": "USD",
            "market_cap": 1_000_000.0,
        }
    )
    return FinancialMetrics(**base_values)


def _sample_payload(ticker: str) -> dict:
    return {
        "prices": [
            Price(open=10.0, close=11.0, high=11.5, low=9.5, volume=1000, time="2025-01-01T00:00:00Z")
        ],
        "metrics": [
            _sample_metrics(ticker)
        ],
        "line_items": [
            LineItem(ticker=ticker, report_period="2025-Q1", period="ttm", currency="USD")
        ],
        "insider_trades": [
            InsiderTrade(
                ticker=ticker,
                issuer="Example Corp",
                name="Jane Doe",
                title="CFO",
                is_board_director=False,
                transaction_date="2024-12-15",
                transaction_shares=100,
                transaction_price_per_share=10.0,
                transaction_value=1_000.0,
                shares_owned_before_transaction=1_000,
                shares_owned_after_transaction=1_100,
                security_title="Common Stock",
                filing_date="2024-12-16",
            )
        ],
        "events": [
            CompanyEvent(
                ticker=ticker,
                date="2025-03-01",
                category="report",
                title="Q4 Earnings",
                event_id="report:123",
            )
        ],
        "market_cap": 1_000_000.0,
    }


def test_prefetch_store_roundtrip(tmp_path):
    db_path = tmp_path / "cache.db"
    payload = _sample_payload("AAPL")
    params = PrefetchParameters.build(
        end_date="2025-01-02",
        start_date="2024-12-02",
        required_fields={"prices", "metrics", "line_items", "insider_trades", "events", "market_cap"},
    )

    with PrefetchStore(db_path=db_path) as store:
        store.store_batch({"AAPL": payload}, params)
        loaded = store.load_batch(["AAPL"], params)

    assert "AAPL" in loaded
    cached = loaded["AAPL"]
    assert isinstance(cached["prices"][0], Price)
    assert isinstance(cached["metrics"][0], FinancialMetrics)
    assert isinstance(cached["line_items"][0], LineItem)
    assert isinstance(cached["insider_trades"][0], InsiderTrade)
    assert isinstance(cached["events"][0], CompanyEvent)
    assert cached["market_cap"] == pytest.approx(1_000_000.0)


def test_parallel_fetch_fills_and_uses_cache(monkeypatch, tmp_path):
    # Ensure the sqlite cache lives under the test temp directory
    cache_path = tmp_path / "prefetch_cache.db"
    monkeypatch.setattr("src.data.prefetch_store._DEFAULT_DB_PATH", cache_path)

    ticker = "AAPL"
    payload = _sample_payload(ticker)

    call_counts = {"prices": 0, "metrics": 0, "line_items": 0, "insider_trades": 0, "events": 0}

    async def _run_once():
        return await parallel_fetch_ticker_data(
            [ticker],
            end_date="2025-01-02",
            start_date="2024-12-02",
            include_prices=True,
            include_metrics=True,
            include_line_items=True,
            include_insider_trades=True,
            include_events=True,
            include_market_caps=True,
        )

    def _make_returner(key):
        def _return(*args, **kwargs):
            call_counts[key] += 1
            return payload[key]

        return _return

    monkeypatch.setattr("src.data.parallel_api_wrapper.get_prices", _make_returner("prices"))
    monkeypatch.setattr("src.data.parallel_api_wrapper.get_financial_metrics", _make_returner("metrics"))
    monkeypatch.setattr("src.data.parallel_api_wrapper.search_line_items", _make_returner("line_items"))
    monkeypatch.setattr("src.data.parallel_api_wrapper.get_insider_trades", _make_returner("insider_trades"))
    monkeypatch.setattr("src.data.parallel_api_wrapper.get_company_events", _make_returner("events"))

    first_result = asyncio.run(_run_once())

    # Ensure the first run hit every fetcher
    assert all(count == 1 for count in call_counts.values())
    assert ticker in first_result
    assert first_result[ticker]["market_cap"] == payload["market_cap"]

    # Swap out the fetchers with fail-fast versions to ensure cache is used
    def _fail(*args, **kwargs):
        pytest.fail("Fetcher should not be called when cache is warm")

    monkeypatch.setattr("src.data.parallel_api_wrapper.get_prices", _fail)
    monkeypatch.setattr("src.data.parallel_api_wrapper.get_financial_metrics", _fail)
    monkeypatch.setattr("src.data.parallel_api_wrapper.search_line_items", _fail)
    monkeypatch.setattr("src.data.parallel_api_wrapper.get_insider_trades", _fail)
    monkeypatch.setattr("src.data.parallel_api_wrapper.get_company_events", _fail)

    second_result = asyncio.run(_run_once())
    assert ticker in second_result
    cached = second_result[ticker]
    assert isinstance(cached["prices"][0], Price)
    assert isinstance(cached["metrics"][0], FinancialMetrics)
    assert cached["market_cap"] == pytest.approx(payload["market_cap"])
