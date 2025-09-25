from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from src.tools.api import CompanyEvent, get_company_events


def _make_iso(date_str: str) -> str:
    """Utility to ensure ISO-8601 date strings are valid."""
    datetime.fromisoformat(date_str)
    return date_str


@patch("src.tools.api._cache")
@patch("src.tools.api._get_borsdata_client")
def test_get_company_events_transforms_and_filters(mock_get_client: Mock, mock_cache: Mock) -> None:
    mock_cache.get_company_events.return_value = None

    stub_client = Mock()
    stub_client.get_instrument.return_value = {"insId": 42}
    stub_client.get_report_calendar.return_value = [
        {"releaseDate": "2024-03-05T00:00:00", "reportType": "Q1"},
        {"releaseDate": "2024-03-12T00:00:00", "reportType": "Q2"},  # outside end date
        {"releaseDate": "2024-02-17T00:00:00", "reportType": "Q4"},  # before start date
    ]
    stub_client.get_dividend_calendar.return_value = [
        {
            "excludingDate": "2024-03-07T00:00:00",
            "amountPaid": "1.5",
            "currencyShortName": "USD",
            "distributionFrequency": 4,
            "dividendType": 1,
        },
        {
            "excludingDate": "2024-01-01T00:00:00",
            "amountPaid": "2.0",
            "currencyShortName": "USD",
        },
    ]
    mock_get_client.return_value = stub_client

    events = get_company_events(
        ticker="TTWO",
        end_date=_make_iso("2024-03-10"),
        start_date=_make_iso("2024-03-01"),
        limit=2,
        api_key="dummy",
    )

    assert len(events) == 2
    for event in events:
        assert isinstance(event, CompanyEvent)
        assert event.ticker == "TTWO"

    dividend_event = events[0]
    assert dividend_event.category == "dividend"
    assert dividend_event.date == "2024-03-07"
    assert dividend_event.title == "Dividend 1.50 USD"
    assert dividend_event.amount == pytest.approx(1.5)
    assert dividend_event.currency == "USD"
    assert dividend_event.event_id == "dividend:42:2024-03-07:1.5:USD"

    report_event = events[1]
    assert report_event.category == "report"
    assert report_event.date == "2024-03-05"
    assert report_event.title == "Report release (Q1)"
    assert report_event.report_type == "Q1"
    assert report_event.event_id == "report:42:2024-03-05:Q1"

    mock_get_client.assert_called_once_with("dummy")
    mock_cache.set_company_events.assert_called_once()
    cache_key, cache_payload = mock_cache.set_company_events.call_args.args
    assert cache_key == "TTWO_2024-03-01_2024-03-10_2"
    assert len(cache_payload) == 2


@patch("src.tools.api._cache")
@patch("src.tools.api._get_borsdata_client")
def test_get_company_events_returns_cached_events(mock_get_client: Mock, mock_cache: Mock) -> None:
    cached_events = [
        {
            "ticker": "LUG",
            "date": "2024-03-03",
            "category": "report",
            "title": "Report release",
            "description": "Cached report",
            "event_id": "report:7:2024-03-03",
        }
    ]
    mock_cache.get_company_events.return_value = cached_events

    events = get_company_events(
        ticker="LUG",
        end_date="2024-03-10",
        start_date=None,
        limit=5,
        api_key="unused",
    )

    assert len(events) == 1
    assert events[0].title == "Report release"
    assert events[0].description == "Cached report"

    mock_get_client.assert_not_called()
    mock_cache.set_company_events.assert_not_called()
