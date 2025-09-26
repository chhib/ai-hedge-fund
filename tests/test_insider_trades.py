from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from src.tools.api import InsiderTrade, get_insider_trades


@patch("src.tools.api._cache")
@patch("src.tools.api._get_borsdata_client")
def test_get_insider_trades_transforms_and_filters(mock_get_client: Mock, mock_cache: Mock) -> None:
    mock_cache.get_insider_trades.return_value = None

    stub_client = Mock()
    stub_client.get_instrument.return_value = {"insId": 99, "name": "Lundin Gold"}
    stub_client.get_insider_holdings.return_value = [
        {
            "transactionDate": None,
            "verificationDate": "2024-03-10T15:30:00",
            "shares": "250",
            "transactionType": 0,
            "price": "5.25",
            "amount": "1312.5",
            "ownerPosition": "Independent Director",
            "ownerName": "Bob Insider",
        },
        {
            "transactionDate": "2024-03-08T00:00:00",
            "verificationDate": "2024-03-09T08:00:00",
            "shares": "1200",
            "transactionType": 3,
            "price": "14.5",
            "amount": "17400",
            "ownerPosition": "Chief Financial Officer",
            "ownerName": "Alice Example",
        },
        {
            "transactionDate": "2024-02-27T00:00:00",
            "verificationDate": "2024-02-28T00:00:00",
            "shares": "100",
            "transactionType": 1,
            "price": "4.5",
            "amount": "450",
            "ownerPosition": "Board Member",
            "ownerName": "Too Early",
        },
        {
            "transactionDate": "2024-03-05T00:00:00",
            "verificationDate": "2024-03-06T00:00:00",
            "shares": None,
            "transactionType": 1,
            "price": "3.5",
            "amount": "350",
            "ownerPosition": "Director",
            "ownerName": "Missing Shares",
        },
    ]
    mock_get_client.return_value = stub_client

    trades = get_insider_trades(
        ticker="LUG",
        end_date="2024-03-10",
        start_date="2024-03-01",
        limit=2,
        api_key="token",
    )

    assert len(trades) == 2
    for trade in trades:
        assert isinstance(trade, InsiderTrade)
        assert trade.ticker == "LUG"
        assert trade.issuer == "Lundin Gold"
        assert trade.shares_owned_before_transaction is None
        assert trade.shares_owned_after_transaction is None
        assert trade.security_title is None

    latest = trades[0]
    assert latest.transaction_date == "2024-03-10"
    assert latest.filing_date == "2024-03-10"
    assert latest.transaction_shares == pytest.approx(250.0)
    assert latest.transaction_price_per_share == pytest.approx(5.25)
    assert latest.transaction_value == pytest.approx(1312.5)
    assert latest.is_board_director is True
    assert latest.name == "Bob Insider"
    assert latest.title == "Independent Director"

    second = trades[1]
    assert second.transaction_date == "2024-03-08"
    assert second.filing_date == "2024-03-09"
    assert second.transaction_shares == pytest.approx(-1200.0)
    assert second.transaction_price_per_share == pytest.approx(14.5)
    assert second.transaction_value == pytest.approx(17400.0)
    assert second.is_board_director is False
    assert second.name == "Alice Example"
    assert second.title == "Chief Financial Officer"

    mock_get_client.assert_called_once_with("token")
    stub_client.get_instrument.assert_called_once_with("LUG", api_key="token", use_global=False)
    stub_client.get_insider_holdings.assert_called_once_with([99], api_key="token")
    mock_cache.get_insider_trades.assert_called_once_with("LUG_2024-03-01_2024-03-10_2")
    mock_cache.set_insider_trades.assert_called_once()
    cache_key, payload = mock_cache.set_insider_trades.call_args.args
    assert cache_key == "LUG_2024-03-01_2024-03-10_2"
    assert len(payload) == 2


@patch("src.tools.api._cache")
@patch("src.tools.api._get_borsdata_client")
def test_get_insider_trades_uses_cache_when_available(mock_get_client: Mock, mock_cache: Mock) -> None:
    cached = [
        {
            "ticker": "TTWO",
            "issuer": "Take-Two Interactive",
            "name": "Jane Doe",
            "title": "Director",
            "is_board_director": True,
            "transaction_date": "2024-03-05",
            "transaction_shares": 150.0,
            "transaction_price_per_share": 12.5,
            "transaction_value": 1875.0,
            "shares_owned_before_transaction": None,
            "shares_owned_after_transaction": None,
            "security_title": None,
            "filing_date": "2024-03-06",
        }
    ]
    mock_cache.get_insider_trades.return_value = cached

    trades = get_insider_trades(
        ticker="TTWO",
        end_date="2024-03-10",
        start_date="2024-03-01",
        limit=5,
        api_key="unused",
    )

    assert len(trades) == 1
    assert trades[0].name == "Jane Doe"
    assert trades[0].issuer == "Take-Two Interactive"

    mock_get_client.assert_not_called()
    mock_cache.set_insider_trades.assert_not_called()
