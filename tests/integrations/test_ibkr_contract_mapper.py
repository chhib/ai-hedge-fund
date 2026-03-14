"""Tests for ibkr_contract_mapper validation helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.integrations.ibkr_client import IBKRError
from src.integrations.ibkr_contract_mapper import (
    ContractOverride,
    ValidationResult,
    validate_all_contracts,
    validate_contract,
)


def _make_override(conid: int = 265598, exchange: str = "NASDAQ", description: str = "APPLE INC") -> ContractOverride:
    return ContractOverride(conid=conid, exchange=exchange, description=description)


class TestValidateContract:
    def test_valid(self):
        client = MagicMock()
        client.get_contract_info.return_value = {"exchange": "NASDAQ", "company_name": "APPLE INC"}
        override = _make_override()

        result = validate_contract(client, "AAPL", override)

        assert result.status == "valid"
        assert result.ticker == "AAPL"
        assert result.conid == 265598
        assert result.live_exchange == "NASDAQ"
        assert result.live_description == "APPLE INC"

    def test_invalid_ibkr_error(self):
        client = MagicMock()
        client.get_contract_info.side_effect = IBKRError("conid not found")
        override = _make_override()

        result = validate_contract(client, "AAPL", override)

        assert result.status == "invalid"
        assert "conid not found" in result.error

    def test_invalid_empty_response(self):
        client = MagicMock()
        client.get_contract_info.return_value = None
        override = _make_override()

        result = validate_contract(client, "AAPL", override)

        assert result.status == "invalid"
        assert "empty response" in result.error

    def test_exchange_changed(self):
        client = MagicMock()
        client.get_contract_info.return_value = {"exchange": "NYSE", "company_name": "APPLE INC"}
        override = _make_override(exchange="NASDAQ")

        result = validate_contract(client, "AAPL", override)

        assert result.status == "exchange_changed"
        assert result.stored_exchange == "NASDAQ"
        assert result.live_exchange == "NYSE"

    def test_generic_error(self):
        client = MagicMock()
        client.get_contract_info.side_effect = ConnectionError("timeout")
        override = _make_override()

        result = validate_contract(client, "AAPL", override)

        assert result.status == "error"
        assert "timeout" in result.error

    def test_valid_no_stored_exchange(self):
        """When no stored exchange, any live exchange is fine (no exchange_changed)."""
        client = MagicMock()
        client.get_contract_info.return_value = {"exchange": "NYSE", "company_name": "APPLE INC"}
        override = _make_override(exchange=None)

        result = validate_contract(client, "AAPL", override)

        assert result.status == "valid"


class TestValidateAllContracts:
    def test_iterates_all(self):
        client = MagicMock()
        client.get_contract_info.return_value = {"exchange": "NASDAQ", "company_name": "TEST"}

        overrides = {
            "AAPL": _make_override(conid=100),
            "MSFT": _make_override(conid=200, exchange="NASDAQ", description="MICROSOFT"),
            "GOOG": _make_override(conid=300, exchange="NASDAQ", description="ALPHABET"),
        }

        results = validate_all_contracts(client, overrides, delay=0)

        assert len(results) == 3
        assert all(r.status == "valid" for r in results)
        assert client.get_contract_info.call_count == 3

    def test_progress_callback(self):
        client = MagicMock()
        client.get_contract_info.return_value = {"exchange": "NASDAQ", "company_name": "TEST"}

        overrides = {"AAPL": _make_override(), "MSFT": _make_override(conid=200)}
        calls = []

        def cb(ticker, result):
            calls.append((ticker, result.status))

        validate_all_contracts(client, overrides, delay=0, progress_cb=cb)

        assert len(calls) == 2
        assert calls[0][0] == "AAPL"
        assert calls[1][0] == "MSFT"

    def test_mixed_results(self):
        client = MagicMock()

        def side_effect(conid):
            if conid == 100:
                return {"exchange": "NASDAQ", "company_name": "OK"}
            raise IBKRError("dead conid")

        client.get_contract_info.side_effect = side_effect

        overrides = {
            "AAPL": _make_override(conid=100),
            "DEAD": _make_override(conid=999),
        }

        results = validate_all_contracts(client, overrides, delay=0)

        assert results[0].status == "valid"
        assert results[1].status == "invalid"
