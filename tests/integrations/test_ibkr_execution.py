import src.integrations.ibkr_execution as ibkr_execution
from src.integrations.ibkr_contract_mapper import ContractOverride
from src.integrations.ibkr_execution import build_order_intents, execute_ibkr_rebalance_trades
from src.integrations.ibkr_client import IBKRError


class FakeIBKRClient:
    def __init__(self, contracts=None, snapshot=None, batch_preview_response=None, batch_preview_error=None):
        self.preview_calls = []
        self.batch_preview_calls = []
        self.place_calls = []
        self.reply_calls = []
        self.contracts = contracts or {}
        self.snapshot = snapshot or []
        self.batch_preview_response = batch_preview_response
        self.batch_preview_error = batch_preview_error

    def resolve_account_id(self, preferred=None):
        return preferred or "U123"

    def get_stock_contracts(self, symbol):
        return self.contracts.get(symbol, {})

    def search_contracts(self, symbol, sec_type="STK"):
        return []

    def get_marketdata_snapshot(self, conids, fields="31,84,86"):
        return self.snapshot

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
