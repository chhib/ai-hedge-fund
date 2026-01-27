from datetime import datetime

import pytest

from src.integrations.ibkr_client import IBKRClient, IBKRError


def test_fetch_portfolio_transforms_positions_and_cash(monkeypatch):
    client = IBKRClient(base_url="https://example.com")

    responses = {
        ("GET", "/v1/api/portfolio/accounts"): [{"accountId": "U123"}],
        ("GET", "/v1/api/portfolio/U123/positions/0"): [
            {"symbol": "AAPL", "position": 10, "avgCost": 150.0, "currency": "USD"},
            {"symbol": "ERIC B", "position": 5, "avgCost": "95.5", "currency": "SEK"},
            {"symbol": None, "conid": 999, "position": 1, "avgCost": 1.0, "currency": "USD"},
        ],
        ("GET", "/v1/api/portfolio/U123/ledger"): {
            "USD": {"cashbalance": 1250.0},
            "SEK": {"cashbalance": "900"},
            "BASE": {"cashbalance": 0.0},
        },
    }

    def _fake_request(method, path):
        return responses[(method, path)]

    monkeypatch.setattr(client, "_request", _fake_request)

    portfolio = client.fetch_portfolio()

    assert len(portfolio.positions) == 3
    tickers = {pos.ticker for pos in portfolio.positions}
    assert tickers == {"AAPL", "ERIC B", "999"}
    assert portfolio.cash_holdings == {"USD": 1250.0, "SEK": 900.0}
    assert isinstance(portfolio.last_updated, datetime)


def test_fetch_portfolio_raises_when_no_accounts(monkeypatch):
    client = IBKRClient(base_url="https://example.com")
    monkeypatch.setattr(client, "_request", lambda method, path: [])

    with pytest.raises(IBKRError):
        client.fetch_portfolio()


def test_resolve_account_id_prefers_selected(monkeypatch):
    client = IBKRClient(base_url="https://example.com")

    def _fake_request(method, path, params=None, json=None):
        if path == "/iserver/accounts":
            return {"accounts": ["U111", "U222"], "selectedAccount": "U222"}
        if path == "/v1/api/portfolio/accounts":
            return [{"accountId": "U123"}]
        return []

    monkeypatch.setattr(client, "_request", _fake_request)

    assert client.resolve_account_id() == "U222"


def test_resolve_account_id_falls_back_to_portfolio_accounts(monkeypatch):
    client = IBKRClient(base_url="https://example.com")

    def _fake_request(method, path, params=None, json=None):
        if path == "/iserver/accounts":
            return {}
        if path == "/v1/api/portfolio/accounts":
            return [{"accountId": "U999"}]
        return []

    monkeypatch.setattr(client, "_request", _fake_request)

    assert client.resolve_account_id() == "U999"


def test_request_prefixes_iserver_paths(monkeypatch):
    client = IBKRClient(base_url="https://example.com")

    seen = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {}

    def _fake_request(method, url, timeout=None, params=None, json=None):
        seen["url"] = url
        return DummyResponse()

    monkeypatch.setattr(client.session, "request", _fake_request)

    client._request("GET", "/iserver/accounts")

    assert seen["url"] == "https://example.com/v1/api/iserver/accounts"
