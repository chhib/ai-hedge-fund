"""Paper trading execution engine: virtual fills with forward P&L tracking.

Consumes the same recommendation list as IBKR execution but records virtual
fills using the recommendation's limit_price. Maintains per-pod virtual
portfolios (cash + positions) in Decision DB.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.data.decision_store import get_decision_store
from src.utils.portfolio_loader import Portfolio, Position

logger = logging.getLogger(__name__)

DEFAULT_STARTING_CAPITAL = 100_000.0
DEFAULT_HOME_CURRENCY = "SEK"


class PaperExecutionEngine:
    """Virtual execution engine for paper-tier pods."""

    def __init__(self, pod_id: str, starting_capital: float | None = None, home_currency: str = DEFAULT_HOME_CURRENCY) -> None:
        self.pod_id = pod_id
        self.starting_capital = starting_capital or DEFAULT_STARTING_CAPITAL
        self.home_currency = home_currency
        self._store = get_decision_store()

    def load_virtual_portfolio(self) -> Portfolio:
        """Synthesize a Portfolio from the latest paper_positions in Decision DB.

        On cold start (no positions), returns an empty portfolio with
        starting_capital as cash.
        """
        positions_data = self._store.get_latest_paper_positions(self.pod_id)
        snapshot = self._store.get_latest_paper_snapshot(self.pod_id)

        if not positions_data and not snapshot:
            # Cold start
            return Portfolio(
                positions=[],
                cash_holdings={self.home_currency: self.starting_capital},
                last_updated=datetime.now(),
            )

        positions = [
            Position(
                ticker=p["ticker"],
                shares=p["shares"],
                cost_basis=p["cost_basis"],
                currency=p.get("currency", self.home_currency),
            )
            for p in positions_data
        ]

        cash = snapshot["cash"] if snapshot else self.starting_capital
        return Portfolio(
            positions=positions,
            cash_holdings={self.home_currency: cash},
            last_updated=datetime.now(),
        )

    def mark_to_market(self, run_id: str, portfolio: Portfolio, current_prices: Dict[str, float]) -> Dict[str, Any]:
        """Update open positions with current market prices and record a snapshot.

        Returns the snapshot dict with total_value, cash, positions_value, cumulative_return_pct.
        """
        positions_value = 0.0
        updated_positions: List[Dict[str, Any]] = []

        for pos in portfolio.positions:
            price = current_prices.get(pos.ticker, pos.cost_basis)
            if pos.ticker not in current_prices:
                logger.warning("No current price for %s, using cost basis %.2f as fallback", pos.ticker, pos.cost_basis)
            value = pos.shares * price
            positions_value += value
            updated_positions.append({
                "ticker": pos.ticker,
                "shares": pos.shares,
                "cost_basis": pos.cost_basis,
                "current_price": price,
                "currency": pos.currency,
            })

        cash = sum(portfolio.cash_holdings.values())
        total_value = cash + positions_value
        cumulative_return_pct = ((total_value - self.starting_capital) / self.starting_capital) * 100.0 if self.starting_capital > 0 else 0.0

        snapshot = {
            "total_value": total_value,
            "cash": cash,
            "positions_value": positions_value,
            "cumulative_return_pct": cumulative_return_pct,
            "starting_capital": self.starting_capital,
        }

        # Record to Decision DB (passive observer)
        self._store.record_paper_positions(self.pod_id, run_id, updated_positions)
        self._store.record_paper_snapshot(self.pod_id, run_id, snapshot)

        return snapshot

    def execute_paper_trades(
        self,
        run_id: str,
        recommendations: List[Dict[str, Any]],
        portfolio: Portfolio,
    ) -> List[Dict[str, Any]]:
        """Execute virtual trades against the paper portfolio.

        Validates sells against virtual holdings (long-only guard).
        Fills at recommendation['current_price']. Returns paper fill dicts.
        """
        held = {pos.ticker: pos.shares for pos in portfolio.positions}
        cash = sum(portfolio.cash_holdings.values())

        fills: List[Dict[str, Any]] = []
        updated_positions: Dict[str, Dict[str, Any]] = {
            pos.ticker: {
                "ticker": pos.ticker,
                "shares": pos.shares,
                "cost_basis": pos.cost_basis,
                "currency": pos.currency,
            }
            for pos in portfolio.positions
        }

        # Process sells first (frees cash for buys)
        sell_recs = [r for r in recommendations if r.get("action") in ("SELL", "DECREASE")]
        buy_recs = [r for r in recommendations if r.get("action") in ("ADD", "INCREASE")]

        for rec in sell_recs:
            ticker = rec["ticker"]
            action = rec["action"]
            target_shares = rec.get("target_shares", 0)
            current_shares = held.get(ticker, 0)
            fill_price = rec.get("current_price", 0)

            if current_shares <= 0:
                logger.info("Paper: skipping %s %s -- not held (long-only)", action, ticker)
                fills.append(self._make_skip_fill(rec, f"Not held in paper portfolio (long-only)"))
                continue

            if action == "SELL":
                sell_qty = current_shares
            else:  # DECREASE
                sell_qty = current_shares - target_shares
                if sell_qty <= 0:
                    continue

            # Clamp to actual holdings
            sell_qty = min(sell_qty, current_shares)
            sell_value = sell_qty * fill_price
            cash += sell_value

            new_shares = current_shares - sell_qty
            if new_shares > 0:
                updated_positions[ticker]["shares"] = new_shares
            else:
                updated_positions.pop(ticker, None)
            held[ticker] = new_shares

            fills.append(self._make_fill(rec, "SELL", sell_qty, fill_price))

        for rec in buy_recs:
            ticker = rec["ticker"]
            action = rec["action"]
            target_shares = rec.get("target_shares", 0)
            current_shares = held.get(ticker, 0)
            fill_price = rec.get("current_price", 0)

            if action == "ADD":
                buy_qty = target_shares
            else:  # INCREASE
                buy_qty = target_shares - current_shares
                if buy_qty <= 0:
                    continue

            cost = buy_qty * fill_price
            if cost > cash:
                logger.warning("Paper: insufficient cash for %s %s (need %.2f, have %.2f) -- skipping", action, ticker, cost, cash)
                fills.append(self._make_skip_fill(rec, f"Insufficient cash (need {cost:.0f}, have {cash:.0f})"))
                continue

            cash -= cost

            if ticker in updated_positions:
                existing = updated_positions[ticker]
                old_shares = existing["shares"]
                old_basis = existing["cost_basis"]
                new_shares = old_shares + buy_qty
                # Weighted average cost basis
                new_basis = (old_shares * old_basis + buy_qty * fill_price) / new_shares if new_shares > 0 else fill_price
                existing["shares"] = new_shares
                existing["cost_basis"] = new_basis
            else:
                updated_positions[ticker] = {
                    "ticker": ticker,
                    "shares": buy_qty,
                    "cost_basis": fill_price,
                    "currency": rec.get("currency", self.home_currency),
                }
            held[ticker] = held.get(ticker, 0) + buy_qty

            fills.append(self._make_fill(rec, "BUY", buy_qty, fill_price))

        # Update portfolio in-place for downstream use
        portfolio.positions = [
            Position(
                ticker=p["ticker"],
                shares=p["shares"],
                cost_basis=p["cost_basis"],
                currency=p.get("currency", self.home_currency),
            )
            for p in updated_positions.values()
        ]
        portfolio.cash_holdings = {self.home_currency: cash}

        # Record to Decision DB
        self._record_results(run_id, fills, updated_positions, cash)

        return fills

    def _record_results(
        self,
        run_id: str,
        fills: List[Dict[str, Any]],
        positions: Dict[str, Dict[str, Any]],
        cash: float,
    ) -> None:
        """Write paper fills and updated state to Decision DB."""
        # Record execution outcomes (paper fills)
        execution_outcomes = []
        for fill in fills:
            execution_outcomes.append({
                "recommendation_id": fill.get("recommendation_id"),
                "execution_type": "paper",
                "ticker": fill["ticker"],
                "side": fill.get("side"),
                "fill_price": fill.get("fill_price"),
                "fill_quantity": fill.get("fill_quantity"),
                "fill_timestamp": datetime.now().isoformat(),
                "status": fill.get("status", "filled"),
                "rejection_reason": fill.get("rejection_reason"),
            })
        try:
            self._store.record_execution_outcomes(run_id, execution_outcomes)
        except Exception:
            logger.debug("Failed to record paper execution outcomes", exc_info=True)

        # Record positions
        position_list = [
            {**p, "current_price": p.get("cost_basis", 0)}
            for p in positions.values()
        ]
        self._store.record_paper_positions(self.pod_id, run_id, position_list)

        # Record snapshot
        positions_value = sum(p["shares"] * p.get("current_price", p.get("cost_basis", 0)) for p in position_list)
        total_value = cash + positions_value
        cumulative_return_pct = ((total_value - self.starting_capital) / self.starting_capital) * 100.0 if self.starting_capital > 0 else 0.0

        self._store.record_paper_snapshot(self.pod_id, run_id, {
            "total_value": total_value,
            "cash": cash,
            "positions_value": positions_value,
            "cumulative_return_pct": cumulative_return_pct,
            "starting_capital": self.starting_capital,
        })

    @staticmethod
    def _make_fill(rec: Dict[str, Any], side: str, quantity: float, price: float) -> Dict[str, Any]:
        return {
            "recommendation_id": rec.get("recommendation_id"),
            "ticker": rec["ticker"],
            "side": side,
            "fill_price": price,
            "fill_quantity": quantity,
            "status": "filled",
        }

    @staticmethod
    def _make_skip_fill(rec: Dict[str, Any], reason: str) -> Dict[str, Any]:
        return {
            "recommendation_id": rec.get("recommendation_id"),
            "ticker": rec["ticker"],
            "side": rec.get("action"),
            "fill_price": None,
            "fill_quantity": None,
            "status": "skipped",
            "rejection_reason": reason,
        }
