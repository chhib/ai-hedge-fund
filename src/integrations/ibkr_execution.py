"""Translate rebalance recommendations into IBKR orders with safety gates."""

from __future__ import annotations

import logging
import time

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

from src.integrations.ibkr_client import IBKRClient, IBKRError
from src.integrations.ibkr_contract_mapper import ContractOverride, load_contract_overrides
from src.integrations.ticker_mapper import map_borsdata_to_ibkr


@dataclass(slots=True)
class OrderIntent:
    ticker: str
    ibkr_symbol: str
    side: str
    quantity: int
    limit_price: float
    currency: str
    action: str
    pricing_source: str | None = None


@dataclass(slots=True)
class OrderSkip:
    ticker: str
    action: str
    reason: str


@dataclass(slots=True)
class ContractCandidate:
    conid: int
    exchange: Optional[str]
    currency: Optional[str]
    symbol: Optional[str]
    local_symbol: Optional[str]
    description: Optional[str]


@dataclass(slots=True)
class ResolvedOrder:
    intent: OrderIntent
    conid: int
    exchange: Optional[str]
    currency: Optional[str]


@dataclass(slots=True)
class OrderStatusResult:
    order_id: str
    ticker: str
    status: str  # Filled, Cancelled, Inactive, PartialFill, Timeout, Unknown
    filled_qty: int
    remaining_qty: int
    avg_fill_price: float
    total_qty: int
    elapsed_seconds: float


@dataclass(slots=True)
class ExecutionReport:
    account_id: Optional[str]
    preview_only: bool
    executed: bool
    intents: List[OrderIntent] = field(default_factory=list)
    resolved: List[ResolvedOrder] = field(default_factory=list)
    previews: List[Dict[str, Any]] = field(default_factory=list)
    submissions: List[Dict[str, Any]] = field(default_factory=list)
    final_submissions: List[Dict[str, Any]] = field(default_factory=list)
    order_statuses: List[OrderStatusResult] = field(default_factory=list)
    skipped: List[OrderSkip] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    aborted: bool = False


def build_order_intents(recommendations: List[Dict[str, Any]]) -> tuple[List[OrderIntent], List[OrderSkip]]:
    intents: List[OrderIntent] = []
    skipped: List[OrderSkip] = []

    for rec in recommendations:
        action = rec.get("action") or "HOLD"
        ticker = rec.get("ticker", "")

        if action == "HOLD":
            skipped.append(OrderSkip(ticker=ticker, action=action, reason="Hold action"))
            continue

        current_shares = _to_int(rec.get("current_shares", 0))
        target_shares = _to_int(rec.get("target_shares", 0))

        if action == "SELL":
            qty = current_shares
        elif action == "DECREASE":
            qty = max(0, current_shares - target_shares)
        elif action == "ADD":
            qty = target_shares
        elif action == "INCREASE":
            qty = max(0, target_shares - current_shares)
        else:
            skipped.append(OrderSkip(ticker=ticker, action=action, reason="Unknown action"))
            continue

        if qty <= 0:
            skipped.append(OrderSkip(ticker=ticker, action=action, reason="Zero quantity"))
            continue

        side = "BUY" if action in {"ADD", "INCREASE"} else "SELL"
        limit_price = float(rec.get("current_price") or 0.0)
        if limit_price <= 0:
            skipped.append(OrderSkip(ticker=ticker, action=action, reason="Missing limit price"))
            continue

        currency = rec.get("currency") or "USD"
        ibkr_symbol = map_borsdata_to_ibkr(ticker)

        intents.append(
            OrderIntent(
                ticker=ticker,
                ibkr_symbol=ibkr_symbol,
                side=side,
                quantity=qty,
                limit_price=limit_price,
                currency=currency,
                action=action,
                pricing_source=rec.get("pricing_source"),
            )
        )

    return intents, skipped


def execute_ibkr_rebalance_trades(
    recommendations: List[Dict[str, Any]],
    *,
    base_url: str,
    account_id: Optional[str],
    verify_ssl: bool = False,
    timeout: float = 30.0,
    preview_only: bool = True,
    execute: bool = False,
    confirm: Optional[Callable[[str], bool]] = None,
    client: Optional[IBKRClient] = None,
) -> ExecutionReport:
    """Preview and optionally execute IBKR orders based on rebalance recommendations."""

    intents, skipped = build_order_intents(recommendations)
    report = ExecutionReport(
        account_id=account_id,
        preview_only=preview_only,
        executed=execute,
        intents=intents,
        skipped=skipped,
    )

    if not intents:
        return report

    confirm_callback = confirm or (lambda _: False)
    ibkr = client or IBKRClient(base_url=base_url, verify_ssl=verify_ssl, timeout=timeout)

    resolved_account = ibkr.resolve_account_id(account_id)
    report.account_id = resolved_account
    if not resolved_account:
        raise IBKRError("No IBKR trading account resolved for execution")

    resolved_orders, resolution_skips = _resolve_contracts(ibkr, intents, load_contract_overrides())
    report.resolved = resolved_orders
    report.skipped.extend(resolution_skips)

    if not resolved_orders:
        return report

    snapshot = ibkr.get_marketdata_snapshot([order.conid for order in resolved_orders])
    _apply_snapshot_prices(resolved_orders, snapshot, report)

    # Fetch contract rules for tick size rounding + trading permissions
    tick_sizes: Dict[int, Optional[float]] = {}
    filtered_orders: List[ResolvedOrder] = []
    for resolved in resolved_orders:
        rules_response: Any = None
        try:
            rules_response = ibkr.get_contract_rules(
                resolved.conid,
                is_buy=(resolved.intent.side == "BUY"),
                exchange=resolved.exchange,
            )
        except IBKRError as exc:
            report.warnings.append(f"{resolved.intent.ticker}: Unable to fetch contract rules ({exc})")

        rules_payload = _extract_rules_payload(rules_response)
        if rules_payload and not _can_trade_account(rules_payload, resolved_account):
            report.warnings.append(f"{resolved.intent.ticker}: No trading permissions for account {resolved_account}")
            report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="No trading permissions"))
            continue

        tick_sizes[resolved.conid] = _get_tick_size(rules_payload or rules_response, resolved.intent.limit_price)
        filtered_orders.append(resolved)

    resolved_orders = filtered_orders
    report.resolved = resolved_orders

    if not resolved_orders:
        return report

    # Build all order payloads upfront
    order_payloads = [_build_order_payload(resolved, resolved_account, tick_sizes.get(resolved.conid)) for resolved in resolved_orders]

    # Sequence sells before buys to ensure cash is freed up before purchases
    sell_pairs: List[tuple[ResolvedOrder, Dict[str, Any]]] = []
    buy_pairs: List[tuple[ResolvedOrder, Dict[str, Any]]] = []
    for resolved, payload in zip(resolved_orders, order_payloads):
        if resolved.intent.side == "SELL":
            sell_pairs.append((resolved, payload))
        else:
            buy_pairs.append((resolved, payload))

    if preview_only and not execute and sell_pairs and buy_pairs:
        report.warnings.append("Buy previews deferred until sell orders execute; rerun after sells to fund purchases.")
        for resolved, _ in buy_pairs:
            report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="Deferred until sells executed"))
        resolved_orders = [resolved for resolved, _ in sell_pairs]
        order_payloads = [payload for _, payload in sell_pairs]
    else:
        resolved_orders = [resolved for resolved, _ in sell_pairs] + [resolved for resolved, _ in buy_pairs]
        order_payloads = [payload for _, payload in sell_pairs] + [payload for _, payload in buy_pairs]

    # Try batch preview first to avoid cash depletion issue
    batch_preview_results = _run_batch_preview(ibkr, resolved_account, resolved_orders, order_payloads, report)

    # Process preview results and handle execution
    for i, resolved in enumerate(resolved_orders):
        preview_result = batch_preview_results.get(i)
        if preview_result is None:
            # Already handled in _run_batch_preview (skipped or error)
            continue

        preview_response, order_payload = preview_result

        warning = _extract_reply(preview_response)
        if warning:
            report.warnings.append(f"{resolved.intent.ticker}: {warning[1]}")

        if preview_only and not execute:
            continue

        if not execute:
            continue

        if warning:
            if not confirm_callback(f"IBKR warning for {resolved.intent.ticker}: {warning[1]} Approve?"):
                report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="Warning not approved"))
                continue
            ibkr.reply(warning[0], confirmed=True)

        if not confirm_callback(_format_confirm_message(resolved.intent)):
            report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="User declined"))
            continue

        _process_submission(
            ibkr=ibkr,
            account_id=resolved_account,
            order_payload=order_payload,
            intent=resolved.intent,
            confirm_callback=confirm_callback,
            report=report,
        )

    return report


def _run_batch_preview(
    ibkr: IBKRClient,
    account_id: str,
    resolved_orders: List[ResolvedOrder],
    order_payloads: List[Dict[str, Any]],
    report: ExecutionReport,
) -> Dict[int, tuple]:
    """Run batch preview and return mapping of order index to (preview_response, order_payload).

    Returns None for orders that failed or were skipped.
    Falls back to sequential previews if batch preview fails entirely.
    """
    results: Dict[int, tuple] = {}

    # Try batch preview first
    try:
        batch_response = ibkr.preview_orders_batch(account_id, order_payloads)
    except IBKRError as exc:
        message = str(exc)
        if _is_permission_error(message):
            report.warnings.append(f"IBKR trading permissions missing: {message}")
            report.aborted = True
            for resolved in resolved_orders:
                report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="Permission error"))
            return results
        # Fall back to sequential preview on batch failure
        return _run_sequential_preview(ibkr, account_id, resolved_orders, order_payloads, report)

    # Process batch response
    # IBKR batch response can be a list of order results or a dict with error
    if isinstance(batch_response, dict):
        error_message = _extract_error_message(batch_response)
        if error_message:
            if _is_permission_error(error_message):
                report.warnings.append(f"IBKR trading permissions missing: {error_message}")
                report.aborted = True
                for resolved in resolved_orders:
                    report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="Permission error"))
                return results
            # Fall back to sequential preview
            return _run_sequential_preview(ibkr, account_id, resolved_orders, order_payloads, report)

    # Parse batch response - it may be a list of results or nested structure
    preview_items = _extract_batch_preview_items(batch_response, len(resolved_orders))

    for i, resolved in enumerate(resolved_orders):
        order_payload = order_payloads[i]
        preview_response = preview_items[i] if i < len(preview_items) else None

        if preview_response is None:
            report.warnings.append(f"{resolved.intent.ticker}: No preview response in batch")
            report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="No preview response"))
            continue

        report.previews.append({"intent": resolved.intent, "response": preview_response})

        error_message = _extract_error_message(preview_response)
        if error_message:
            report.warnings.append(f"{resolved.intent.ticker}: Preview error ({error_message})")
            report.skipped.append(
                OrderSkip(
                    ticker=resolved.intent.ticker,
                    action=resolved.intent.action,
                    reason=f"Preview error: {error_message}",
                )
            )
            continue

        results[i] = (preview_response, order_payload)

    return results


def _run_sequential_preview(
    ibkr: IBKRClient,
    account_id: str,
    resolved_orders: List[ResolvedOrder],
    order_payloads: List[Dict[str, Any]],
    report: ExecutionReport,
) -> Dict[int, tuple]:
    """Fallback to sequential preview when batch preview fails."""
    results: Dict[int, tuple] = {}

    for i, resolved in enumerate(resolved_orders):
        order_payload = order_payloads[i]

        try:
            preview_response = ibkr.preview_order(account_id, order_payload)
        except IBKRError as exc:
            message = str(exc)
            report.warnings.append(f"{resolved.intent.ticker}: Preview failed ({message})")
            report.skipped.append(OrderSkip(ticker=resolved.intent.ticker, action=resolved.intent.action, reason="Preview failed"))
            continue

        report.previews.append({"intent": resolved.intent, "response": preview_response})

        error_message = _extract_error_message(preview_response)
        if error_message:
            report.warnings.append(f"{resolved.intent.ticker}: Preview error ({error_message})")
            report.skipped.append(
                OrderSkip(
                    ticker=resolved.intent.ticker,
                    action=resolved.intent.action,
                    reason=f"Preview error: {error_message}",
                )
            )
            continue

        results[i] = (preview_response, order_payload)

    return results


def _extract_batch_preview_items(batch_response: Any, expected_count: int) -> List[Any]:
    """Extract individual preview results from batch response."""
    if isinstance(batch_response, list):
        return batch_response

    # Handle nested response structures
    if isinstance(batch_response, dict):
        # Some IBKR responses nest results under 'orders' or 'order'
        if "orders" in batch_response:
            return batch_response["orders"] if isinstance(batch_response["orders"], list) else [batch_response["orders"]]
        if "order" in batch_response:
            return batch_response["order"] if isinstance(batch_response["order"], list) else [batch_response["order"]]
        # Single order response wrapped in dict
        return [batch_response]

    return []


def _resolve_contracts(
    client: IBKRClient,
    intents: Iterable[OrderIntent],
    overrides: Dict[str, ContractOverride],
) -> tuple[List[ResolvedOrder], List[OrderSkip]]:
    resolved: List[ResolvedOrder] = []
    skipped: List[OrderSkip] = []

    for intent in intents:
        candidates = _extract_contract_candidates(client.get_stock_contracts(intent.ibkr_symbol))
        if not candidates:
            candidates = _extract_contract_candidates(client.search_contracts(intent.ibkr_symbol, sec_type="STK"))

        override = overrides.get(intent.ticker.upper())
        if override:
            candidate = next((c for c in candidates if c.conid == override.conid), None)
            if candidate:
                resolved.append(
                    ResolvedOrder(
                        intent=intent,
                        conid=candidate.conid,
                        exchange=override.exchange or candidate.exchange,
                        currency=override.currency or candidate.currency or intent.currency,
                    )
                )
                continue
            skipped.append(
                OrderSkip(
                    ticker=intent.ticker,
                    action=intent.action,
                    reason="Contract override not found in IBKR search results",
                )
            )
            continue

        candidate, reason = _select_candidate(candidates, intent.currency, intent.ibkr_symbol)
        if not candidate:
            skipped.append(
                OrderSkip(
                    ticker=intent.ticker,
                    action=intent.action,
                    reason=reason or "No contract match",
                )
            )
            continue

        resolved.append(
            ResolvedOrder(
                intent=intent,
                conid=candidate.conid,
                exchange=candidate.exchange,
                currency=candidate.currency or intent.currency,
            )
        )

    return resolved, skipped


def _extract_contract_candidates(payload: Any) -> List[ContractCandidate]:
    candidates: List[ContractCandidate] = []
    if payload is None:
        return candidates

    def _append_candidate(data: Dict[str, Any]) -> None:
        conid = data.get("conid") or data.get("conidex")
        if conid is None:
            return
        if isinstance(conid, str) and "@" in conid:
            parts = conid.split("@")
            try:
                conid = int(parts[0])
            except ValueError:
                return
        try:
            conid_int = int(conid)
        except (TypeError, ValueError):
            return
        candidates.append(
            ContractCandidate(
                conid=conid_int,
                exchange=data.get("exchange"),
                currency=data.get("currency"),
                symbol=data.get("symbol"),
                local_symbol=data.get("localSymbol") or data.get("local_symbol"),
                description=data.get("description") or data.get("companyName"),
            )
        )

    items: List[Any] = []
    if isinstance(payload, dict):
        items = list(payload.values())
    elif isinstance(payload, list):
        items = payload
    else:
        return candidates

    for item in items:
        if isinstance(item, dict) and "contracts" in item:
            contracts = item.get("contracts") or []
            for contract in contracts:
                if isinstance(contract, dict):
                    _append_candidate(contract)
        elif isinstance(item, dict):
            _append_candidate(item)
        elif isinstance(item, list):
            for entry in item:
                if isinstance(entry, dict) and "contracts" in entry:
                    contracts = entry.get("contracts") or []
                    for contract in contracts:
                        if isinstance(contract, dict):
                            _append_candidate(contract)
                elif isinstance(entry, dict):
                    _append_candidate(entry)

    return candidates


def _select_candidate(
    candidates: List[ContractCandidate],
    currency: str,
    ibkr_symbol: str,
) -> tuple[Optional[ContractCandidate], Optional[str]]:
    if not candidates:
        return None, "No contract candidates"

    currency_upper = currency.upper() if currency else ""
    filtered = [c for c in candidates if not currency_upper or (c.currency or "").upper() == currency_upper]
    if filtered:
        candidates = filtered

    if len(candidates) == 1:
        return candidates[0], None

    symbol_upper = ibkr_symbol.upper() if ibkr_symbol else ""
    exact_symbol = [c for c in candidates if (c.local_symbol or c.symbol or "").upper() == symbol_upper]
    if len(exact_symbol) == 1:
        return exact_symbol[0], None

    smart = [c for c in candidates if (c.exchange or "").upper() == "SMART"]
    if len(smart) == 1:
        return smart[0], None

    return None, "Multiple contract matches (add override in data/ibkr_contract_mappings.json)"


def _apply_snapshot_prices(orders: List[ResolvedOrder], snapshot: Any, report: ExecutionReport) -> None:
    if not snapshot:
        return

    snapshot_rows: List[Dict[str, Any]] = []
    if isinstance(snapshot, list):
        snapshot_rows = [row for row in snapshot if isinstance(row, dict)]
    elif isinstance(snapshot, dict):
        snapshot_rows = [snapshot]

    for order in orders:
        row = next((r for r in snapshot_rows if str(r.get("conid")) == str(order.conid)), None)
        if not row:
            continue
        bid = _to_float(row.get("31"))
        ask = _to_float(row.get("84"))
        last = _to_float(row.get("86"))
        new_price = order.intent.limit_price
        if order.intent.side == "BUY" and ask > 0:
            new_price = ask
        elif order.intent.side == "SELL" and bid > 0:
            new_price = bid
        elif last > 0:
            new_price = last

        if new_price <= 0:
            report.skipped.append(OrderSkip(ticker=order.intent.ticker, action=order.intent.action, reason="No valid market data price"))
            continue

        order.intent.limit_price = new_price


def _build_order_payload(order: ResolvedOrder, account_id: str, tick_size: Optional[float] = None) -> Dict[str, Any]:
    return {
        "conid": order.conid,
        "secType": "STK",
        "orderType": "LMT",
        "side": order.intent.side,
        "price": _round_to_tick(order.intent.limit_price, tick_size),
        "quantity": int(order.intent.quantity),
        "tif": "DAY",
        "exchange": order.exchange or "SMART",
        "cOID": f"hedge-{uuid4().hex[:8]}",
        "currency": order.currency or order.intent.currency,
    }


def _format_confirm_message(intent: OrderIntent) -> str:
    return f"Submit {intent.side} {intent.quantity} {intent.ticker} @ {intent.limit_price:.2f} {intent.currency}?"


def _extract_reply(payload: Any) -> Optional[tuple[str, str]]:
    if isinstance(payload, dict):
        if payload.get("id") and payload.get("message") is not None:
            message = payload.get("message")
            if isinstance(message, list):
                message = " ".join(str(item) for item in message if item is not None)
            return str(payload.get("id")), str(message)
        if payload.get("replyId") and payload.get("message") is not None:
            message = payload.get("message")
            if isinstance(message, list):
                message = " ".join(str(item) for item in message if item is not None)
            return str(payload.get("replyId")), str(message)
    if isinstance(payload, list):
        for item in payload:
            reply = _extract_reply(item)
            if reply:
                return reply
    return None


def _extract_error_message(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        if payload.get("error"):
            return str(payload.get("error"))
        if payload.get("message"):
            return str(payload.get("message"))
        errors = payload.get("errors")
        if isinstance(errors, list):
            messages = []
            for item in errors:
                if isinstance(item, dict):
                    if item.get("message"):
                        messages.append(str(item.get("message")))
                    elif item.get("error"):
                        messages.append(str(item.get("error")))
            if messages:
                return "; ".join(messages)
        if isinstance(errors, dict):
            if errors.get("message"):
                return str(errors.get("message"))
            if errors.get("error"):
                return str(errors.get("error"))
    if isinstance(payload, list):
        for item in payload:
            message = _extract_error_message(item)
            if message:
                return message
    return None


def _is_permission_error(message: str) -> bool:
    return "trading permissions" in message.lower()


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _get_tick_size(rules_response: Any, price: Optional[float] = None) -> Optional[float]:
    """Extract tick size (increment) from contract rules response."""
    rules_payload = _extract_rules_payload(rules_response)
    if not isinstance(rules_payload, dict):
        return None

    increment_rules = rules_payload.get("incrementRules") or rules_payload.get("increment_rules")
    if isinstance(increment_rules, list):
        parsed: List[tuple[float, float]] = []
        for rule in increment_rules:
            if not isinstance(rule, dict):
                continue
            lower_edge = _to_float(rule.get("lowerEdge") or rule.get("lower_edge") or 0.0)
            increment = _to_float(rule.get("increment"))
            if increment > 0:
                parsed.append((lower_edge, increment))
        if parsed:
            parsed.sort(key=lambda item: item[0])
            if price is not None:
                matched = [inc for edge, inc in parsed if edge <= float(price)]
                if matched:
                    return matched[-1]
            return parsed[0][1]

    increment = rules_payload.get("increment")
    if increment and _to_float(increment) > 0:
        return _to_float(increment)

    min_tick = rules_payload.get("minTick") or rules_payload.get("min_tick")
    if min_tick and _to_float(min_tick) > 0:
        return _to_float(min_tick)

    return None


def _round_to_tick(price: float, tick_size: Optional[float]) -> float:
    """Round price to nearest valid tick."""
    if tick_size is None or tick_size <= 0:
        return round(price, 4)
    price_decimal = Decimal(str(price))
    tick_decimal = Decimal(str(tick_size))
    if tick_decimal == 0:
        return round(price, 4)
    ticks = (price_decimal / tick_decimal).to_integral_value(rounding=ROUND_HALF_UP)
    rounded = ticks * tick_decimal
    return float(rounded.quantize(tick_decimal))


def _extract_rules_payload(rules_response: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(rules_response, dict):
        return None
    rules = rules_response.get("rules")
    if isinstance(rules, dict):
        return rules
    return rules_response


def _can_trade_account(rules_payload: Dict[str, Any], account_id: str) -> bool:
    if not account_id:
        return True
    acct_ids = rules_payload.get("canTradeAcctIds") or rules_payload.get("can_trade_acct_ids")
    if isinstance(acct_ids, list) and acct_ids:
        return str(account_id) in {str(acct_id) for acct_id in acct_ids}
    return True


def _process_submission(
    *,
    ibkr: IBKRClient,
    account_id: str,
    order_payload: Dict[str, Any],
    intent: OrderIntent,
    confirm_callback: Callable[[str], bool],
    report: ExecutionReport,
) -> None:
    submit_response = ibkr.place_order(account_id, order_payload)
    report.submissions.append({"intent": intent, "response": submit_response})

    response = submit_response
    for _ in range(5):
        submit_warning = _extract_reply(response)
        if not submit_warning:
            error_message = _extract_error_message(response)
            if error_message:
                report.warnings.append(f"{intent.ticker}: Submission error ({error_message})")
                report.skipped.append(OrderSkip(ticker=intent.ticker, action=intent.action, reason=f"Submission error: {error_message}"))
            else:
                report.final_submissions.append({"intent": intent, "response": response})
                order_id = _extract_order_id(response)
                if order_id:
                    status_result = _poll_order_status(ibkr, order_id, intent.ticker, intent.quantity)
                    report.order_statuses.append(status_result)
                    if status_result.status == "PartialFill":
                        report.warnings.append(f"{intent.ticker}: Partial fill ({status_result.filled_qty}/{status_result.total_qty})")
                    elif status_result.status == "Timeout":
                        report.warnings.append(f"{intent.ticker}: Order status polling timed out (last checked: order {order_id})")
            return

        report.warnings.append(f"{intent.ticker}: {submit_warning[1]}")
        if not confirm_callback(f"IBKR confirmation required for {intent.ticker}: {submit_warning[1]} Approve?"):
            report.skipped.append(OrderSkip(ticker=intent.ticker, action=intent.action, reason="Submission warning declined"))
            return

        response = ibkr.reply(submit_warning[0], confirmed=True)
        report.submissions.append({"intent": intent, "response": response, "reply_to": submit_warning[0]})

    report.warnings.append(f"{intent.ticker}: Exceeded reply confirmations; aborting submission")
    report.skipped.append(OrderSkip(ticker=intent.ticker, action=intent.action, reason="Reply confirmation loop"))


def _extract_order_id(response: Any) -> Optional[str]:
    """Extract order_id from a submission response."""
    if isinstance(response, dict):
        oid = response.get("order_id") or response.get("orderId")
        if oid:
            return str(oid)
        # Check nested in orders list
        orders = response.get("orders") or response.get("order")
        if isinstance(orders, list):
            for item in orders:
                if isinstance(item, dict):
                    oid = item.get("order_id") or item.get("orderId")
                    if oid:
                        return str(oid)
    if isinstance(response, list):
        for item in response:
            oid = _extract_order_id(item)
            if oid:
                return oid
    return None


def _poll_order_status(
    ibkr: IBKRClient,
    order_id: str,
    ticker: str,
    total_qty: int,
    poll_interval: float = 2.0,
    poll_timeout: float = 30.0,
) -> OrderStatusResult:
    """Poll order status until terminal state or timeout."""
    terminal_states = {"Filled", "Cancelled", "Inactive"}
    start = time.monotonic()
    last_status = "Unknown"
    filled_qty = 0
    remaining_qty = total_qty
    avg_fill_price = 0.0

    while True:
        elapsed = time.monotonic() - start
        try:
            status_resp = ibkr.get_order_status(order_id)
        except IBKRError as exc:
            logger.warning("Failed to poll order %s: %s", order_id, exc)
            break

        if isinstance(status_resp, dict):
            last_status = status_resp.get("order_status") or status_resp.get("orderStatus") or status_resp.get("status") or last_status
            filled_qty = int(float(status_resp.get("filled_qty") or status_resp.get("filledQuantity") or status_resp.get("cum_fill") or filled_qty))
            remaining_qty = int(float(status_resp.get("remaining_qty") or status_resp.get("remainingQuantity") or status_resp.get("rem_fill") or remaining_qty))
            avg_fill_price = float(status_resp.get("avg_fill_price") or status_resp.get("avgPrice") or status_resp.get("average_price") or avg_fill_price)

        if last_status in terminal_states:
            break

        if elapsed >= poll_timeout:
            last_status = "Timeout"
            break

        time.sleep(poll_interval)

    elapsed = time.monotonic() - start
    # Detect partial fill: filled some but not all
    if last_status == "Filled" and 0 < filled_qty < total_qty:
        last_status = "PartialFill"

    return OrderStatusResult(
        order_id=order_id,
        ticker=ticker,
        status=last_status,
        filled_qty=filled_qty,
        remaining_qty=remaining_qty,
        avg_fill_price=avg_fill_price,
        total_qty=total_qty,
        elapsed_seconds=round(elapsed, 2),
    )


def _extract_submission_rows(payload: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("orders"), list):
            rows.extend(row for row in payload["orders"] if isinstance(row, dict))
            return rows
        if isinstance(payload.get("order"), list):
            rows.extend(row for row in payload["order"] if isinstance(row, dict))
            return rows
        rows.append(payload)
        return rows
    if isinstance(payload, list):
        rows.extend(row for row in payload if isinstance(row, dict))
    return rows


def summarize_submissions(entries: List[Dict[str, Any]]) -> List[str]:
    summaries: List[str] = []
    for entry in entries:
        intent = entry.get("intent")
        response = entry.get("response")
        rows = _extract_submission_rows(response)
        for row in rows:
            order_id = row.get("order_id") or row.get("orderId")
            local_id = row.get("local_order_id") or row.get("localOrderId") or row.get("localOrderID")
            status = row.get("order_status") or row.get("orderStatus") or row.get("status")
            if not (order_id or local_id or status):
                continue
            parts: List[str] = []
            if order_id:
                parts.append(f"id {order_id}")
            if local_id:
                parts.append(f"local {local_id}")
            if status:
                parts.append(f"status {status}")
            prefix = f"{intent.ticker}: " if intent else ""
            summaries.append(prefix + " ".join(parts))
    return summaries


__all__ = [
    "OrderIntent",
    "OrderSkip",
    "OrderStatusResult",
    "ResolvedOrder",
    "ExecutionReport",
    "build_order_intents",
    "execute_ibkr_rebalance_trades",
    "summarize_submissions",
]
