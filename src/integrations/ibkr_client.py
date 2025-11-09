"""Thin wrapper around Interactive Brokers Client Portal positions endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from src.utils.portfolio_loader import Portfolio, Position


class IBKRError(RuntimeError):
    """Raised when the Client Portal API responds with an error."""


@dataclass(slots=True)
class IBKRConnectionConfig:
    base_url: str = "https://localhost:5000"
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
        target_account = account_id or self._default_account_id()
        if not target_account:
            raise IBKRError("No IBKR account could be resolved")

        positions = self.get_positions(target_account)
        ledger = self.get_ledger(target_account)

        position_models = _transform_positions(positions)
        cash_balances = _transform_ledger_balances(ledger)

        return Portfolio(positions=position_models, cash_holdings=cash_balances, last_updated=datetime.utcnow())

    def list_accounts(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/v1/api/portfolio/accounts") or []

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/v1/api/portfolio/{account_id}/positions/0") or []

    def get_ledger(self, account_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/v1/api/portfolio/{account_id}/ledger") or []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _default_account_id(self) -> Optional[str]:
        accounts = self.list_accounts()
        if not accounts:
            return None
        first = accounts[0]
        return first.get("accountId") or first.get("acctId")

    def _request(self, method: str, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method=method.upper(), url=url, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover - network failure path
            raise IBKRError(f"IBKR request failed: {exc}") from exc

        if response.status_code >= 400:
            raise IBKRError(f"IBKR API error {response.status_code}: {response.text}")
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - malformed response
            raise IBKRError("Failed to decode IBKR response") from exc


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

        symbol = row.get("symbol") or row.get("localSymbol")
        if not symbol:
            conid = row.get("conid")
            symbol = str(conid) if conid is not None else None
        if not symbol:
            continue

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


def _transform_ledger_balances(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    balances: Dict[str, float] = {}
    for row in rows:
        currency = row.get("currency") or row.get("fxCurrency")
        if not currency:
            continue
        balance_raw = row.get("cashbalance") or row.get("cashBalance")
        try:
            balance = float(balance_raw)
        except (TypeError, ValueError):
            continue
        balances[currency] = balance
    return balances


__all__ = ["IBKRClient", "IBKRConnectionConfig", "IBKRError"]
