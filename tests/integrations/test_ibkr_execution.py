import pytest

import src.integrations.ibkr_execution as ibkr_execution
from src.integrations.ibkr_contract_mapper import ContractOverride
from src.integrations.ibkr_execution import build_order_intents, execute_ibkr_rebalance_trades, format_execution_cash_summary, _extract_order_id, _poll_order_status, _apply_snapshot_prices, OrderIntent, OrderSkip, OrderStatusResult, ResolvedOrder, ExecutionReport
from src.integrations.ibkr_client import IBKRError


class FakeIBKRClient:
    def __init__(self, contracts=None, snapshot=None, batch_preview_response=None, batch_preview_error=None, order_status_responses=None):
        self.preview_calls = []
        self.batch_preview_calls = []
        self.place_calls = []
        self.reply_calls = []
        self.contracts = contracts or {}
        self.snapshot = snapshot or []
        self.batch_preview_response = batch_preview_response
        self.batch_preview_error = batch_preview_error
        self.order_status_responses = order_status_responses or []
        self._order_status_call_count = 0

    def resolve_account_id(self, preferred=None):
        return preferred or "U123"

    def get_stock_contracts(self, symbol):
        return self.contracts.get(symbol, {})

    def search_contracts(self, symbol, sec_type="STK"):
        return []

    def get_marketdata_snapshot(self, conids, fields="31,84,86"):
        return self.snapshot

    def get_contract_rules(self, conid, is_buy, exchange=None):
        # Return a mock response with a default tick size of 0.01
        return {"rules": {"increment": 0.01}}

    def ensure_authenticated(self):
        return None

    def preview_order(self, account_id, order):
        self.preview_calls.append(order)
        return {"order_status": "PreSubmitted"}

    def preview_orders_batch(self, account_id, orders):
        self.batch_preview_calls.append(orders)
        if self.batch_preview_error:
            raise IBKRError(self.batch_preview_error)
        if self.batch_preview_response is not None:
            return self.batch_preview_response
        # Default: return list of success responses for each order
        return [{"order_status": "PreSubmitted"} for _ in orders]

    def place_order(self, account_id, order):
        self.place_calls.append(order)
        return {"order_status": "Submitted"}

    def get_order_status(self, order_id):
        if self._order_status_call_count < len(self.order_status_responses):
            resp = self.order_status_responses[self._order_status_call_count]
            self._order_status_call_count += 1
            return resp
        return {"order_status": "Filled", "filledQuantity": 0, "remainingQuantity": 0, "avgPrice": 0.0}

    def get_orders(self):
        return {"orders": []}

    def reply(self, reply_id, confirmed=True):
        self.reply_calls.append(reply_id)
        return {"status": "confirmed"}


def test_build_order_intents_basic():
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 10, "current_price": 5.0, "currency": "USD"},
        {"ticker": "BBB", "action": "INCREASE", "current_shares": 5, "target_shares": 8, "current_price": 10.0, "currency": "USD"},
        {"ticker": "CCC", "action": "DECREASE", "current_shares": 10, "target_shares": 6, "current_price": 3.0, "currency": "USD"},
        {"ticker": "DDD", "action": "SELL", "current_shares": 4, "target_shares": 0, "current_price": 2.0, "currency": "USD"},
        {"ticker": "EEE", "action": "HOLD", "current_shares": 3, "target_shares": 3, "current_price": 1.0, "currency": "USD"},
    ]

    intents, skipped = build_order_intents(recommendations)

    assert len(intents) == 4
    quantities = {(intent.ticker, intent.side, intent.quantity) for intent in intents}
    assert quantities == {
        ("AAA", "BUY", 10),
        ("BBB", "BUY", 3),
        ("CCC", "SELL", 4),
        ("DDD", "SELL", 4),
    }
    assert any(skip.ticker == "EEE" for skip in skipped)


def test_preview_only_never_places_orders(monkeypatch):
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    # Batch preview is used by default
    assert len(fake.batch_preview_calls) == 1
    assert fake.place_calls == []
    assert report.submissions == []


def test_sequential_preview_failure_keeps_exact_error_reason(monkeypatch):
    class PreviewFailClient(FakeIBKRClient):
        def preview_order(self, account_id, order):
            raise IBKRError("IBKR API error 500: {\"error\":\"No trading permissions.\",\"action\":\"order_cannot_be_created\"}")

    recommendations = [
        {"ticker": "EMBRAC B", "action": "ADD", "current_shares": 0, "target_shares": 1, "current_price": 49.07, "currency": "SEK"},
    ]
    contracts = {
        "EMBRAC.B": [{"contracts": [{"conid": 753729002, "exchange": "SFB", "currency": "SEK"}]}],
    }
    fake = PreviewFailClient(
        contracts=contracts,
        snapshot=[{"conid": "753729002", "84": "49.07"}],
        batch_preview_error="force sequential fallback",
    )

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=False,
        execute=False,
        client=fake,
        skip_swedish_stocks=False,
    )

    assert any("No trading permissions." in warning for warning in report.warnings)
    assert any(skip.ticker == "EMBRAC B" and "No trading permissions." in skip.reason for skip in report.skipped)


def test_skip_swedish_buy_orders_catches_smart_override_before_preview(monkeypatch):
    recommendations = [
        {"ticker": "EMBRAC B", "action": "ADD", "current_shares": 0, "target_shares": 1, "current_price": 49.07, "currency": "SEK"},
    ]
    contracts = {
        "EMBRAC.B": [{"contracts": [{"conid": 753729002, "exchange": "SFB"}]}],
    }
    fake = FakeIBKRClient(contracts=contracts)

    monkeypatch.setattr(
        ibkr_execution,
        "load_contract_overrides",
        lambda: {"EMBRAC B": ContractOverride(conid=753729002, exchange="SMART", currency="SEK")},
    )

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert report.resolved == []
    assert fake.batch_preview_calls == []
    assert any(skip.ticker == "EMBRAC B" and "Swedish stock buy skipped" in skip.reason for skip in report.skipped)


def test_swedish_sell_orders_are_not_auto_skipped(monkeypatch):
    recommendations = [
        {"ticker": "EMBRAC B", "action": "SELL", "current_shares": 2, "target_shares": 0, "current_price": 49.07, "currency": "SEK"},
    ]
    contracts = {
        "EMBRAC.B": [{"contracts": [{"conid": 753729002, "exchange": "SFB"}]}],
    }
    fake = FakeIBKRClient(contracts=contracts)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert len(fake.batch_preview_calls) == 1
    assert len(report.resolved) == 1
    assert report.resolved[0].listing_exchange == "SFB"
    assert all("Swedish stock buy skipped" not in skip.reason for skip in report.skipped)


def test_format_execution_cash_summary_includes_governor_failed_and_pending_buys():
    report = ExecutionReport(
        account_id="U123",
        preview_only=False,
        executed=True,
        intents=[
            OrderIntent(ticker="AAA", ibkr_symbol="AAA", side="BUY", quantity=10, limit_price=10.5, currency="USD", action="ADD"),
            OrderIntent(ticker="BBB", ibkr_symbol="BBB", side="BUY", quantity=3, limit_price=20.0, currency="USD", action="INCREASE"),
        ],
        skipped=[
            OrderSkip(ticker="AAA", action="ADD", reason="Submission error: Limit price too far outside of NBBO"),
        ],
        order_statuses=[
            OrderStatusResult(
                order_id="1",
                ticker="BBB",
                status="Submitted",
                filled_qty=0,
                remaining_qty=2,
                avg_fill_price=0.0,
                total_qty=3,
                elapsed_seconds=5.0,
            )
        ],
    )

    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 10, "current_price": 10.0, "currency": "USD"},
        {"ticker": "BBB", "action": "INCREASE", "current_shares": 1, "target_shares": 4, "current_price": 20.0, "currency": "USD"},
    ]
    current_portfolio = {
        "total_value": 1000.0,
        "home_currency": "USD",
        "exchange_rates": {"USD": 1.0},
    }

    class Governor:
        deployment_ratio = 0.45
        min_cash_buffer = 0.35

    lines = format_execution_cash_summary(report, recommendations, current_portfolio, Governor())

    assert lines == [
        "Cash intentionally reserved by governor: 550.00 USD",
        "Cash not deployed because buy orders failed: 105.00 USD",
        "Cash still pending in open buy orders: 40.00 USD",
    ]


def test_tick_size_uses_increment_rules(monkeypatch):
    class TickRulesClient(FakeIBKRClient):
        def get_contract_rules(self, conid, is_buy, exchange=None):
            return {
                "rules": {
                    "incrementRules": [
                        {"lowerEdge": 0, "increment": 0.01},
                        {"lowerEdge": 10, "increment": 0.005},
                    ]
                }
            }

    recommendations = [
        {"ticker": "AAA", "action": "SELL", "current_shares": 5, "target_shares": 0, "current_price": 17.758, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    fake = TickRulesClient(contracts=contracts)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert len(fake.batch_preview_calls) == 1
    assert fake.batch_preview_calls[0][0]["price"] == 17.76
    assert report.skipped == []


def test_skips_orders_without_trading_permissions(monkeypatch):
    class NoPermissionClient(FakeIBKRClient):
        def get_contract_rules(self, conid, is_buy, exchange=None):
            return {"rules": {"canTradeAcctIds": ["U999"]}}

    recommendations = [
        {"ticker": "AAA", "action": "SELL", "current_shares": 2, "target_shares": 0, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    fake = NoPermissionClient(contracts=contracts)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert fake.batch_preview_calls == []
    assert any(skip.reason == "No trading permissions" for skip in report.skipped)


def test_preview_only_defers_buys_until_sells(monkeypatch):
    recommendations = [
        {"ticker": "SELL1", "action": "SELL", "current_shares": 5, "target_shares": 0, "current_price": 10.0, "currency": "USD"},
        {"ticker": "BUY1", "action": "ADD", "current_shares": 0, "target_shares": 3, "current_price": 20.0, "currency": "USD"},
    ]
    contracts = {
        "SELL1": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
        "BUY1": [{"contracts": [{"conid": 222, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "10.10"}, {"conid": "222", "84": "20.20"}]
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert len(fake.batch_preview_calls) == 1
    assert len(fake.batch_preview_calls[0]) == 1
    assert fake.batch_preview_calls[0][0]["side"] == "SELL"
    assert any(skip.ticker == "BUY1" and "Deferred" in skip.reason for skip in report.skipped)


def test_execute_requires_confirmation(monkeypatch):
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=True,
        confirm=lambda _: False,
        client=fake,
    )

    # Batch preview is used by default
    assert len(fake.batch_preview_calls) == 1
    assert fake.place_calls == []
    assert any(skip.reason == "User declined" for skip in report.skipped)


def test_execute_places_orders_with_confirmation(monkeypatch):
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=True,
        confirm=lambda _: True,
        client=fake,
    )

    # Batch preview is used by default
    assert len(fake.batch_preview_calls) == 1
    assert len(fake.place_calls) == 1
    assert report.submissions
    assert report.final_submissions


def test_skips_ambiguous_contracts(monkeypatch):
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "NYSE", "currency": "USD"}, {"conid": 222, "exchange": "NASDAQ", "currency": "USD"}]}],
    }
    fake = FakeIBKRClient(contracts=contracts)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert report.resolved == []
    assert any("Multiple contract matches" in skip.reason for skip in report.skipped)


def test_contract_override_resolves_match(monkeypatch):
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}, {"conid": 222, "exchange": "NYSE", "currency": "USD"}]}],
    }
    fake = FakeIBKRClient(contracts=contracts)

    monkeypatch.setattr(
        ibkr_execution,
        "load_contract_overrides",
        lambda: {"AAA": ContractOverride(conid=222, exchange="NYSE", currency="USD")},
    )

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert report.resolved
    assert report.resolved[0].conid == 222


def test_selects_smart_contract_when_unique(monkeypatch):
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}, {"conid": 222, "exchange": "NYSE", "currency": "USD"}]}],
    }
    fake = FakeIBKRClient(contracts=contracts)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert report.resolved
    assert report.resolved[0].conid == 111


def test_execute_handles_multi_step_reply(monkeypatch):
    class MultiReplyClient(FakeIBKRClient):
        def __init__(self, contracts=None, snapshot=None):
            super().__init__(contracts=contracts, snapshot=snapshot)
            self.reply_count = 0

        def place_order(self, account_id, order):
            self.place_calls.append(order)
            return {"id": "1", "message": ["First warning"]}

        def reply(self, reply_id, confirmed=True):
            self.reply_calls.append(reply_id)
            self.reply_count += 1
            if self.reply_count == 1:
                return {"id": "2", "message": "Second warning"}
            return {"order_id": "123", "order_status": "Submitted"}

    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]
    fake = MultiReplyClient(contracts=contracts, snapshot=snapshot)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=True,
        confirm=lambda _: True,
        client=fake,
    )

    assert len(fake.place_calls) == 1
    assert len(fake.reply_calls) == 2
    assert report.final_submissions
    assert report.final_submissions[0]["response"]["order_status"] == "Submitted"


def test_preview_error_does_not_place_orders(monkeypatch):
    class ErrorPreviewClient(FakeIBKRClient):
        def preview_order(self, account_id, order):
            self.preview_calls.append(order)
            raise IBKRError("IBKR API error 500: no trading permissions")

        def preview_orders_batch(self, account_id, orders):
            # Batch preview fails, triggering fallback to sequential
            raise IBKRError("IBKR API error 500: batch failed")

    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    fake = ErrorPreviewClient(contracts=contracts)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    assert len(fake.preview_calls) == 1
    assert fake.place_calls == []
    assert any("Preview failed" in skip.reason for skip in report.skipped)


def test_batch_preview_success(monkeypatch):
    """Test that batch preview is used and processes multiple orders correctly."""
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
        {"ticker": "BBB", "action": "ADD", "current_shares": 0, "target_shares": 3, "current_price": 10.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
        "BBB": [{"contracts": [{"conid": 222, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}, {"conid": "222", "84": "10.20"}]
    batch_response = [
        {"order_status": "PreSubmitted", "equity": {"current": 10000}},
        {"order_status": "PreSubmitted", "equity": {"current": 9970}},
    ]
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot, batch_preview_response=batch_response)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    # Verify batch preview was called with both orders
    assert len(fake.batch_preview_calls) == 1
    assert len(fake.batch_preview_calls[0]) == 2
    # Sequential preview should NOT be called when batch succeeds
    assert len(fake.preview_calls) == 0
    # Both previews should be recorded
    assert len(report.previews) == 2
    assert report.skipped == []


def test_batch_preview_fallback_to_sequential(monkeypatch):
    """Test that sequential preview is used as fallback when batch preview fails."""
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]
    # Batch preview will throw error, triggering fallback
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot, batch_preview_error="Batch endpoint unavailable")

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    # Batch preview was attempted
    assert len(fake.batch_preview_calls) == 1
    # Sequential preview was used as fallback
    assert len(fake.preview_calls) == 1
    # Preview should be recorded
    assert len(report.previews) == 1


def test_batch_preview_partial_error(monkeypatch):
    """Test that partial errors in batch response are handled correctly."""
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
        {"ticker": "BBB", "action": "ADD", "current_shares": 0, "target_shares": 3, "current_price": 10.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
        "BBB": [{"contracts": [{"conid": 222, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}, {"conid": "222", "84": "10.20"}]
    # First order succeeds, second has an error
    batch_response = [
        {"order_status": "PreSubmitted"},
        {"error": "Insufficient buying power"},
    ]
    fake = FakeIBKRClient(contracts=contracts, snapshot=snapshot, batch_preview_response=batch_response)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=False,
        client=fake,
    )

    # Batch preview was used
    assert len(fake.batch_preview_calls) == 1
    # Both previews recorded
    assert len(report.previews) == 2
    # One order should be skipped due to error
    assert len(report.skipped) == 1
    assert "BBB" in report.skipped[0].ticker
    assert "Insufficient buying power" in report.skipped[0].reason


def test_order_status_polling_filled(monkeypatch):
    """After execution, order_statuses is populated when order_id is returned."""
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]

    class FilledClient(FakeIBKRClient):
        def place_order(self, account_id, order):
            self.place_calls.append(order)
            return {"order_id": "777", "order_status": "Submitted"}

        def get_order_status(self, order_id):
            return {"order_status": "Filled", "filledQuantity": 2, "remainingQuantity": 0, "avgPrice": 5.10}

    fake = FilledClient(contracts=contracts, snapshot=snapshot)
    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})
    monkeypatch.setattr("src.integrations.ibkr_execution.time.sleep", lambda _: None)

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=True,
        confirm=lambda _: True,
        client=fake,
    )

    assert len(report.order_statuses) == 1
    assert report.order_statuses[0].order_id == "777"
    assert report.order_statuses[0].status == "Filled"
    assert report.order_statuses[0].filled_qty == 2


def test_partial_fill_warning(monkeypatch):
    """Partial fill generates a warning in the report."""
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 10, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]

    class PartialFillClient(FakeIBKRClient):
        def place_order(self, account_id, order):
            self.place_calls.append(order)
            return {"order_id": "888", "order_status": "Submitted"}

        def get_order_status(self, order_id):
            return {"order_status": "Filled", "filledQuantity": 3, "remainingQuantity": 7, "avgPrice": 5.05}

    fake = PartialFillClient(contracts=contracts, snapshot=snapshot)
    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})
    monkeypatch.setattr("src.integrations.ibkr_execution.time.sleep", lambda _: None)

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=True,
        confirm=lambda _: True,
        client=fake,
    )

    assert len(report.order_statuses) == 1
    assert report.order_statuses[0].status == "PartialFill"
    assert any("Partial fill" in w for w in report.warnings)


def test_order_status_timeout(monkeypatch):
    """Order polling times out when status stays non-terminal."""
    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]

    class StuckClient(FakeIBKRClient):
        def place_order(self, account_id, order):
            self.place_calls.append(order)
            return {"order_id": "999", "order_status": "Submitted"}

        def get_order_status(self, order_id):
            return {"order_status": "PreSubmitted", "filledQuantity": 0, "remainingQuantity": 2, "avgPrice": 0.0}

    fake = StuckClient(contracts=contracts, snapshot=snapshot)
    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})
    monkeypatch.setattr("src.integrations.ibkr_execution.time.sleep", lambda _: None)

    # Use a very short timeout so the test doesn't hang
    original_poll = ibkr_execution._poll_order_status

    def fast_poll(ibkr, order_id, ticker, total_qty, poll_interval=2.0, poll_timeout=30.0):
        return original_poll(ibkr, order_id, ticker, total_qty, poll_interval=0.0, poll_timeout=0.0)

    monkeypatch.setattr(ibkr_execution, "_poll_order_status", fast_poll)

    report = execute_ibkr_rebalance_trades(
        recommendations,
        base_url="https://example.com",
        account_id="U123",
        preview_only=True,
        execute=True,
        confirm=lambda _: True,
        client=fake,
    )

    assert len(report.order_statuses) == 1
    assert report.order_statuses[0].status == "Timeout"
    assert any("timed out" in w for w in report.warnings)


def test_extract_order_id_from_list_and_nested():
    assert _extract_order_id([{"order_id": "42"}]) == "42"
    assert _extract_order_id({"orders": [{"orderId": "99"}]}) == "99"
    assert _extract_order_id({"status": "ok"}) is None
    assert _extract_order_id([]) is None


def test_poll_order_status_ibkr_error_breaks():
    class ErrorClient(FakeIBKRClient):
        def get_order_status(self, order_id):
            raise IBKRError("gateway down")

    result = _poll_order_status(ErrorClient(), "123", "AAA", 10, poll_interval=0, poll_timeout=5)
    assert result.status == "Unknown"


def test_order_status_timeout_via_monotonic(monkeypatch):
    clock = [0.0]

    def fake_monotonic():
        clock[0] += 100
        return clock[0]

    monkeypatch.setattr("src.integrations.ibkr_execution.time.monotonic", fake_monotonic)
    monkeypatch.setattr("src.integrations.ibkr_execution.time.sleep", lambda _: None)

    class StuckClient(FakeIBKRClient):
        def get_order_status(self, order_id):
            return {"order_status": "PreSubmitted", "filledQuantity": 0, "remainingQuantity": 5, "avgPrice": 0.0}

    result = _poll_order_status(StuckClient(), "123", "AAA", 5, poll_interval=2, poll_timeout=30)
    assert result.status == "Timeout"


def test_execute_surfaces_authentication_error_before_submission(monkeypatch):
    class AuthExpiredClient(FakeIBKRClient):
        def ensure_authenticated(self):
            raise IBKRError("IBKR Gateway session expired or is not authenticated. Open https://localhost:5001 and log in again, then rerun the command.")

    recommendations = [
        {"ticker": "AAA", "action": "ADD", "current_shares": 0, "target_shares": 2, "current_price": 5.0, "currency": "USD"},
    ]
    contracts = {
        "AAA": [{"contracts": [{"conid": 111, "exchange": "SMART", "currency": "USD"}]}],
    }
    snapshot = [{"conid": "111", "84": "5.10"}]
    fake = AuthExpiredClient(contracts=contracts, snapshot=snapshot)

    monkeypatch.setattr(ibkr_execution, "load_contract_overrides", lambda: {})

    with pytest.raises(IBKRError, match="log in again"):
        execute_ibkr_rebalance_trades(
            recommendations,
            base_url="https://example.com",
            account_id="U123",
            preview_only=True,
            execute=True,
            confirm=lambda _: True,
            client=fake,
        )

    assert fake.place_calls == []


def test_apply_snapshot_prices_fallback_to_last():
    intent = OrderIntent(ticker="AAA", ibkr_symbol="AAA", side="BUY", quantity=5, limit_price=0.0, currency="USD", action="ADD")
    order = ResolvedOrder(intent=intent, conid=111, exchange="SMART", currency="USD")
    report = ExecutionReport(account_id="U123", preview_only=True, executed=False)
    snapshot = [{"conid": "111", "31": "0", "84": "0", "86": "12.50"}]

    _apply_snapshot_prices([order], snapshot, report)

    assert order.intent.limit_price == 12.50
    assert report.skipped == []
