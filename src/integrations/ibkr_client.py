"""Thin wrapper around Interactive Brokers Client Portal positions endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import logging
import time

import requests
import re

logger = logging.getLogger(__name__)

from src.integrations.ticker_mapper import get_ticker_mapper, map_ibkr_to_borsdata
from src.utils.portfolio_loader import Portfolio, Position


class IBKRError(RuntimeError):
    """Raised when the Client Portal API responds with an error."""


@dataclass(slots=True)
class IBKRConnectionConfig:
    base_url: str = "https://localhost:5001"
    verify_ssl: bool = False
    timeout: float = 30.0


class IBKRClient:
    """Very small client focused on positions + cash extraction."""

    def __init__(self, base_url: str, verify_ssl: bool = False, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.timeout = timeout

    def fetch_portfolio(self, account_id: Optional[str] = None) -> Portfolio:
        target_account = self.resolve_account_id(account_id)
        if not target_account:
            raise IBKRError("No IBKR account could be resolved")

        # Load Börsdata tickers for smart mapping
        _load_borsdata_tickers_for_mapper()

        positions = self.get_positions(target_account)
        ledger = self.get_ledger(target_account)

        position_models = _transform_positions(positions)
        cash_balances = _transform_ledger_balances(ledger)

        return Portfolio(
            positions=position_models,
            cash_holdings=cash_balances,
            last_updated=datetime.utcnow(),
            resolved_account_id=target_account,
        )

    def list_accounts(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/v1/api/portfolio/accounts") or []

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/v1/api/portfolio/{account_id}/positions/0") or []

    def get_ledger(self, account_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/api/portfolio/{account_id}/ledger") or {}

    def get_trading_accounts(self) -> Any:
        """Return the list of trading accounts from the /iserver namespace."""
        return self._request("GET", "/iserver/accounts")

    def resolve_account_id(self, preferred: Optional[str] = None) -> Optional[str]:
        """Resolve an IBKR trading account id, optionally by alias."""
        accounts_payload: Any = None
        try:
            accounts_payload = self.get_trading_accounts()
        except IBKRError:
            accounts_payload = None

        account_index = _build_account_index(accounts_payload, [])

        if preferred:
            # Try to resolve by alias or metadata first
            portfolio_accounts = []
            try:
                portfolio_accounts = self.list_accounts()
            except IBKRError:
                portfolio_accounts = []
            account_index = _build_account_index(accounts_payload, portfolio_accounts)
            match = _match_account(preferred, account_index)
            if match:
                return match
            if _looks_like_account_id(preferred):
                return preferred
            available = _format_account_choices(account_index)
            raise IBKRError(f"IBKR account '{preferred}' not found. Available: {available}")

        if isinstance(accounts_payload, dict):
            selected = accounts_payload.get("selectedAccount")
            if selected and not _is_all_account_id(selected):
                return str(selected)
            account_list = accounts_payload.get("accounts") or accounts_payload.get("accountIds")
            if isinstance(account_list, list) and account_list:
                for account_id in account_list:
                    if account_id and not _is_all_account_id(account_id):
                        return str(account_id)
        elif isinstance(accounts_payload, list) and accounts_payload:
            first = accounts_payload[0]
            if isinstance(first, dict):
                account_id = first.get("accountId") or first.get("acctId")
                if account_id and not _is_all_account_id(account_id):
                    return str(account_id)
            if isinstance(first, str):
                if not _is_all_account_id(first):
                    return first

        # Fallback to portfolio account listing
        accounts = []
        try:
            accounts = self.list_accounts()
        except IBKRError:
            accounts = []
        if accounts:
            first = accounts[0]
            return first.get("accountId") or first.get("acctId")
        return None

    def get_stock_contracts(self, symbols: Iterable[str] | str) -> Any:
        """Lookup stock contracts for one or more symbols."""
        if isinstance(symbols, str):
            joined = symbols
        else:
            joined = ",".join(symbols)
        return self._request("GET", "/trsrv/stocks", params={"symbols": joined})

    def search_contracts(self, symbol: str, sec_type: str = "STK") -> Any:
        """Search for contracts using the security definition endpoint."""
        return self._request("GET", "/iserver/secdef/search", params={"symbol": symbol, "secType": sec_type})

    def get_contract_info(self, conid: int) -> Any:
        """Fetch contract details for a conid."""
        return self._request("GET", f"/iserver/contract/{conid}/info")

    def get_contract_rules(self, conid: int, is_buy: bool, exchange: Optional[str] = None) -> Any:
        """Fetch contract rules including tick size for a conid."""
        payload: Dict[str, Any] = {"conid": conid, "isBuy": bool(is_buy)}
        if exchange:
            payload["exchange"] = exchange
        try:
            return self._request("POST", "/iserver/contract/rules", json=payload)
        except IBKRError:
            # Fallback to info-and-rules for environments that do not support /contract/rules
            return self._request("GET", f"/iserver/contract/{conid}/info-and-rules", params={"isBuy": str(is_buy).lower()})

    def get_marketdata_snapshot(self, conids: Iterable[int], fields: str = "31,84,86") -> Any:
        """Fetch a market data snapshot for conids."""
        joined = ",".join(str(c) for c in conids)
        return self._request("GET", "/iserver/marketdata/snapshot", params={"conids": joined, "fields": fields})

    def preview_order(self, account_id: str, order: Dict[str, Any]) -> Any:
        """Submit an order to the what-if endpoint."""
        return self._request("POST", f"/iserver/account/{account_id}/orders/whatif", json={"orders": [order]})

    def preview_orders_batch(self, account_id: str, orders: List[Dict[str, Any]]) -> Any:
        """Submit multiple orders to the what-if endpoint in a single request.

        This avoids the cash depletion issue where IBKR's what-if endpoint treats
        sequential previews as pending orders, causing subsequent previews to fail
        with "Cash needed for this order and other pending orders" errors.
        """
        if not orders:
            return []
        return self._request("POST", f"/iserver/account/{account_id}/orders/whatif", json={"orders": orders})

    def place_order(self, account_id: str, order: Dict[str, Any]) -> Any:
        """Place an order."""
        return self._request("POST", f"/iserver/account/{account_id}/orders", json={"orders": [order]})

    def reply(self, reply_id: str, confirmed: bool = True) -> Any:
        """Reply to an order warning/confirmation prompt."""
        return self._request("POST", f"/iserver/reply/{reply_id}", json={"confirmed": confirmed})

    def get_orders(self) -> Any:
        """Fetch live orders from the gateway."""
        return self._request("GET", "/iserver/account/orders")

    def get_order_status(self, order_id: str) -> Any:
        """Fetch status for a specific order."""
        return self._request("GET", f"/iserver/account/order/status/{order_id}")

    def cancel_order(self, account_id: str, order_id: str) -> Any:
        """Cancel an open order."""
        return self._request("DELETE", f"/iserver/account/{account_id}/order/{order_id}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _default_account_id(self) -> Optional[str]:
        accounts = self.list_accounts()
        if not accounts:
            return None
        first = accounts[0]
        return first.get("accountId") or first.get("acctId")

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Any:
        normalized_path = path
        if not path.startswith("/v1/api") and (path.startswith("/iserver") or path.startswith("/trsrv")):
            normalized_path = f"/v1/api{path}"

        url = f"{self.base_url}{normalized_path}"
        max_attempts = 3
        last_exc: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                response = self.session.request(method=method.upper(), url=url, timeout=self.timeout, params=params, json=json)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    delay = min(2 ** attempt, 8)
                    logger.warning("IBKR request %s %s failed (attempt %d/%d), retrying in %ds: %s", method, path, attempt + 1, max_attempts, delay, exc)
                    time.sleep(delay)
                    continue
                raise IBKRError(f"IBKR request failed after {max_attempts} attempts: {exc}") from exc
            except requests.RequestException as exc:
                raise IBKRError(f"IBKR request failed: {exc}") from exc

            if response.status_code >= 400:
                raise IBKRError(f"IBKR API error {response.status_code}: {response.text}")
            try:
                return response.json()
            except ValueError as exc:  # pragma: no cover - malformed response
                raise IBKRError("Failed to decode IBKR response") from exc

        raise IBKRError(f"IBKR request failed after {max_attempts} attempts: {last_exc}") from last_exc  # pragma: no cover


def _load_borsdata_tickers_for_mapper() -> None:
    """Load Börsdata instruments into the ticker mapper for smart matching."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
        from src.data.borsdata_client import BorsdataClient

        mapper = get_ticker_mapper()
        if mapper._borsdata_tickers:  # Already loaded
            return

        client = BorsdataClient()
        nordic = client.get_instruments()
        global_ = client.get_all_instruments()
        mapper.load_borsdata_tickers(nordic, global_)
    except Exception:
        pass  # Continue without verification if Börsdata unavailable


def _transform_positions(rows: List[Dict[str, Any]]) -> List[Position]:
    positions: List[Position] = []
    for row in rows:
        shares_raw = row.get("position")
        if shares_raw in (None, 0, "0"):
            continue
        try:
            shares = float(shares_raw)
        except (TypeError, ValueError):
            continue

        symbol = row.get("contractDesc") or row.get("symbol") or row.get("localSymbol")
        if not symbol:
            conid = row.get("conid")
            symbol = str(conid) if conid is not None else None
        if not symbol:
            continue

        # Map to Börsdata format (learns and persists mappings)
        symbol = map_ibkr_to_borsdata(symbol)

        avg_cost_raw = row.get("avgCost") or row.get("averageCost")
        try:
            avg_cost = float(avg_cost_raw) if avg_cost_raw is not None else 0.0
        except (TypeError, ValueError):
            avg_cost = 0.0

        currency = row.get("currency") or row.get("fxCurrency") or "USD"

        positions.append(
            Position(
                ticker=symbol,
                shares=shares,
                cost_basis=avg_cost,
                currency=currency,
                date_acquired=None,
            )
        )
    return positions


def _transform_ledger_balances(ledger: Dict[str, Any]) -> Dict[str, float]:
    """Transform IBKR ledger response to cash balances dict.

    Ledger format: {"USD": {"cashbalance": 100.0, ...}, "SEK": {...}, "BASE": {...}}
    """
    balances: Dict[str, float] = {}
    for currency, data in ledger.items():
        if currency == "BASE":  # Skip the aggregate BASE entry
            continue
        if not isinstance(data, dict):
            continue
        balance_raw = data.get("cashbalance") or data.get("cashBalance")
        try:
            balance = float(balance_raw) if balance_raw is not None else 0.0
        except (TypeError, ValueError):
            continue
        if balance != 0.0:  # Only include non-zero balances
            balances[currency] = balance
    return balances


_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Z]{1,4}\d+$")


def _looks_like_account_id(value: str) -> bool:
    return bool(_ACCOUNT_ID_PATTERN.match(value.strip().upper()))


def _build_account_index(trading_accounts: Any, portfolio_accounts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[str]]]:
    index: Dict[str, Dict[str, Optional[str]]] = {}
    alias_map: Dict[str, str] = {}
    account_ids: List[str] = []

    if isinstance(trading_accounts, dict):
        account_ids = [str(a) for a in trading_accounts.get("accounts") or trading_accounts.get("accountIds") or []]
        aliases_payload = trading_accounts.get("aliases")
        if isinstance(aliases_payload, dict):
            alias_map = {str(k): str(v) for k, v in aliases_payload.items() if v}
    elif isinstance(trading_accounts, list):
        for entry in trading_accounts:
            if isinstance(entry, dict):
                account_id = entry.get("accountId") or entry.get("acctId")
                if account_id and not _is_all_account_id(account_id):
                    account_ids.append(str(account_id))
            elif isinstance(entry, str):
                if not _is_all_account_id(entry):
                    account_ids.append(entry)

    for account_id in account_ids:
        if _is_all_account_id(account_id):
            continue
        index.setdefault(account_id, {})
        alias = alias_map.get(account_id)
        if alias:
            index[account_id]["alias"] = alias

    for entry in portfolio_accounts or []:
        if not isinstance(entry, dict):
            continue
        account_id = entry.get("accountId") or entry.get("acctId") or entry.get("id")
        if not account_id:
            continue
        account_id = str(account_id)
        info = index.setdefault(account_id, {})
        for key, field in (
            ("alias", "accountAlias"),
            ("display_name", "displayName"),
            ("title", "accountTitle"),
            ("desc", "desc"),
            ("type", "type"),
            ("trading_type", "tradingType"),
        ):
            value = entry.get(field)
            if value:
                info[key] = str(value)

    return index


def _match_account(preferred: str, account_index: Dict[str, Dict[str, Optional[str]]]) -> Optional[str]:
    preferred_norm = preferred.strip().upper()
    if not preferred_norm:
        return None

    for account_id in account_index:
        if account_id.upper() == preferred_norm:
            return account_id

    exact_matches: List[str] = []
    for account_id, info in account_index.items():
        for value in info.values():
            if value and value.upper() == preferred_norm:
                exact_matches.append(account_id)
                break
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise IBKRError(f"Ambiguous IBKR account selector '{preferred}'. Matches: {', '.join(sorted(exact_matches))}")

    partial_matches: List[str] = []
    for account_id, info in account_index.items():
        for value in info.values():
            if value and preferred_norm in value.upper():
                partial_matches.append(account_id)
                break
    if len(partial_matches) == 1:
        return partial_matches[0]
    if len(partial_matches) > 1:
        raise IBKRError(f"Ambiguous IBKR account selector '{preferred}'. Matches: {', '.join(sorted(partial_matches))}")

    return None


def _format_account_choices(account_index: Dict[str, Dict[str, Optional[str]]]) -> str:
    if not account_index:
        return "none"
    choices = []
    for account_id, info in account_index.items():
        label = info.get("alias") or info.get("display_name") or info.get("title") or info.get("desc")
        if label and label.upper() != account_id.upper():
            choices.append(f"{account_id} ({label})")
        else:
            choices.append(account_id)
    return ", ".join(sorted(choices))


def _is_all_account_id(value: Optional[str]) -> bool:
    if not value:
        return False
    normalized = str(value).strip().upper()
    return normalized in {"ALL", "ALL ACCOUNTS"}


__all__ = ["IBKRClient", "IBKRConnectionConfig", "IBKRError"]
