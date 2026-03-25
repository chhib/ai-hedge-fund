"""Tests for the paper trading execution engine."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

import pytest

from src.data.decision_store import DecisionStore
from src.services.paper_engine import PaperExecutionEngine
from src.utils.portfolio_loader import Portfolio, Position


@pytest.fixture
def store(tmp_path: Path) -> DecisionStore:
    return DecisionStore(db_path=tmp_path / "test.db")


@pytest.fixture
def engine(store: DecisionStore) -> PaperExecutionEngine:
    eng = PaperExecutionEngine("test_pod", starting_capital=100_000.0)
    eng._store = store
    return eng


def _make_rec(ticker: str, action: str, target_shares: float, price: float, currency: str = "SEK", rec_id: str | None = None) -> dict:
    return {
        "ticker": ticker,
        "action": action,
        "target_shares": target_shares,
        "current_shares": 0,
        "current_price": price,
        "currency": currency,
        "recommendation_id": rec_id or f"rec-{ticker}",
    }


# ── load_virtual_portfolio ──


class TestLoadVirtualPortfolio:

    def test_cold_start_returns_empty_with_cash(self, engine: PaperExecutionEngine):
        portfolio = engine.load_virtual_portfolio()
        assert portfolio.positions == []
        assert portfolio.cash_holdings["SEK"] == 100_000.0

    def test_warm_state_loads_positions(self, engine: PaperExecutionEngine, store: DecisionStore):
        store.record_paper_positions("test_pod", "run-001", [
            {"ticker": "AAPL", "shares": 10, "cost_basis": 190.0, "current_price": 195.0, "currency": "USD"},
        ])
        store.record_paper_snapshot("test_pod", "run-001", {
            "total_value": 98_050.0, "cash": 96_100.0, "positions_value": 1_950.0,
            "cumulative_return_pct": -1.95, "starting_capital": 100_000.0,
        })

        portfolio = engine.load_virtual_portfolio()
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].ticker == "AAPL"
        assert portfolio.positions[0].shares == 10
        assert portfolio.cash_holdings["SEK"] == 96_100.0


# ── mark_to_market ──


class TestMarkToMarket:

    def test_price_increase(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        snapshot = engine.mark_to_market("run-mtm", portfolio, {"AAPL": 200.0})
        assert snapshot["positions_value"] == 2_000.0
        assert snapshot["cash"] == 50_000.0
        assert snapshot["total_value"] == 52_000.0
        assert snapshot["cumulative_return_pct"] == pytest.approx(-48.0, abs=0.1)

    def test_price_decrease(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        snapshot = engine.mark_to_market("run-mtm", portfolio, {"AAPL": 180.0})
        assert snapshot["positions_value"] == 1_800.0

    def test_missing_price_uses_cost_basis(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        snapshot = engine.mark_to_market("run-mtm", portfolio, {})
        assert snapshot["positions_value"] == 1_900.0  # cost_basis fallback

    def test_cold_start_no_positions(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(positions=[], cash_holdings={"SEK": 100_000.0}, last_updated=datetime.now())
        snapshot = engine.mark_to_market("run-mtm", portfolio, {})
        assert snapshot["cash"] == 100_000.0
        assert snapshot["positions_value"] == 0.0
        assert snapshot["cumulative_return_pct"] == 0.0

    def test_records_to_decision_db(self, engine: PaperExecutionEngine, store: DecisionStore):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        engine.mark_to_market("run-mtm", portfolio, {"AAPL": 200.0})

        positions = store.get_latest_paper_positions("test_pod")
        assert len(positions) == 1
        assert positions[0]["current_price"] == 200.0

        snapshot = store.get_latest_paper_snapshot("test_pod")
        assert snapshot is not None
        assert snapshot["total_value"] == 52_000.0


# ── execute_paper_trades ──


class TestExecutePaperTrades:

    def test_cold_start_buys(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(positions=[], cash_holdings={"SEK": 100_000.0}, last_updated=datetime.now())
        recs = [
            _make_rec("AAPL", "ADD", 10, 100.0),
            _make_rec("MSFT", "ADD", 5, 200.0),
        ]
        fills = engine.execute_paper_trades("run-001", recs, portfolio)

        buy_fills = [f for f in fills if f["status"] == "filled"]
        assert len(buy_fills) == 2
        assert buy_fills[0]["fill_quantity"] == 10
        assert buy_fills[0]["fill_price"] == 100.0
        assert buy_fills[1]["fill_quantity"] == 5

        # Cash accounting: 100k - (10*100) - (5*200) = 98k
        assert portfolio.cash_holdings["SEK"] == pytest.approx(98_000.0)
        assert len(portfolio.positions) == 2

    def test_sell_existing_position(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        recs = [_make_rec("AAPL", "SELL", 0, 200.0)]
        fills = engine.execute_paper_trades("run-002", recs, portfolio)

        sell_fills = [f for f in fills if f["side"] == "SELL" and f["status"] == "filled"]
        assert len(sell_fills) == 1
        assert sell_fills[0]["fill_quantity"] == 10
        # Cash: 50k + 10*200 = 52k
        assert portfolio.cash_holdings["SEK"] == pytest.approx(52_000.0)
        assert len(portfolio.positions) == 0

    def test_sell_not_held_skipped(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(positions=[], cash_holdings={"SEK": 100_000.0}, last_updated=datetime.now())
        recs = [_make_rec("AAPL", "SELL", 0, 200.0)]
        fills = engine.execute_paper_trades("run-003", recs, portfolio)

        assert len(fills) == 1
        assert fills[0]["status"] == "skipped"
        assert "long-only" in fills[0]["rejection_reason"].lower()

    def test_sell_clamps_to_holdings(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 5, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        recs = [{"ticker": "AAPL", "action": "DECREASE", "target_shares": 0, "current_shares": 5, "current_price": 200.0, "recommendation_id": "rec-1"}]
        fills = engine.execute_paper_trades("run-004", recs, portfolio)

        sell_fills = [f for f in fills if f["side"] == "SELL" and f["status"] == "filled"]
        assert sell_fills[0]["fill_quantity"] == 5  # clamped to actual 5

    def test_buy_insufficient_cash_skipped(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(positions=[], cash_holdings={"SEK": 100.0}, last_updated=datetime.now())
        recs = [_make_rec("AAPL", "ADD", 10, 1000.0)]
        fills = engine.execute_paper_trades("run-005", recs, portfolio)

        assert len(fills) == 1
        assert fills[0]["status"] == "skipped"
        assert "insufficient cash" in fills[0]["rejection_reason"].lower()

    def test_hold_actions_skipped(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 190.0, "USD")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        recs = [{"ticker": "AAPL", "action": "HOLD", "target_shares": 10, "current_price": 200.0, "recommendation_id": "rec-h"}]
        fills = engine.execute_paper_trades("run-006", recs, portfolio)
        assert len(fills) == 0  # HOLD is not BUY/SELL/ADD/INCREASE/DECREASE

    def test_sells_before_buys(self, engine: PaperExecutionEngine):
        """Sells execute first to free cash for buys."""
        portfolio = Portfolio(
            positions=[Position("OLD", 100, 100.0, "SEK")],
            cash_holdings={"SEK": 0.0},
            last_updated=datetime.now(),
        )
        recs = [
            _make_rec("OLD", "SELL", 0, 100.0),
            _make_rec("NEW", "ADD", 50, 100.0),
        ]
        fills = engine.execute_paper_trades("run-007", recs, portfolio)

        filled = [f for f in fills if f["status"] == "filled"]
        assert len(filled) == 2
        assert portfolio.cash_holdings["SEK"] == pytest.approx(5_000.0)  # 10k sell - 5k buy

    def test_increase_averages_cost_basis(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(
            positions=[Position("AAPL", 10, 100.0, "SEK")],
            cash_holdings={"SEK": 50_000.0},
            last_updated=datetime.now(),
        )
        recs = [_make_rec("AAPL", "INCREASE", 20, 200.0)]
        fills = engine.execute_paper_trades("run-008", recs, portfolio)

        assert len(fills) == 1
        assert fills[0]["fill_quantity"] == 10  # increase from 10 to 20
        pos = next(p for p in portfolio.positions if p.ticker == "AAPL")
        assert pos.shares == 20
        # Weighted avg: (10*100 + 10*200) / 20 = 150
        assert pos.cost_basis == pytest.approx(150.0)

    def test_fills_recorded_to_decision_db(self, engine: PaperExecutionEngine, store: DecisionStore):
        # Need a run in DB for the FK
        store.record_run("run-db", "paper", "2026-03-25", ["test"], ["AAPL"])
        portfolio = Portfolio(positions=[], cash_holdings={"SEK": 100_000.0}, last_updated=datetime.now())
        recs = [_make_rec("AAPL", "ADD", 10, 100.0)]
        engine.execute_paper_trades("run-db", recs, portfolio)

        snapshot = store.get_latest_paper_snapshot("test_pod")
        assert snapshot is not None
        positions = store.get_latest_paper_positions("test_pod")
        assert len(positions) == 1
        assert positions[0]["ticker"] == "AAPL"

    def test_cash_never_negative(self, engine: PaperExecutionEngine):
        portfolio = Portfolio(positions=[], cash_holdings={"SEK": 1_000.0}, last_updated=datetime.now())
        recs = [
            _make_rec("A", "ADD", 5, 100.0),  # 500
            _make_rec("B", "ADD", 5, 100.0),  # 500
            _make_rec("C", "ADD", 5, 100.0),  # 500 -- should be skipped
        ]
        fills = engine.execute_paper_trades("run-neg", recs, portfolio)

        filled = [f for f in fills if f["status"] == "filled"]
        skipped = [f for f in fills if f["status"] == "skipped"]
        assert len(filled) == 2
        assert len(skipped) == 1
        assert portfolio.cash_holdings["SEK"] >= 0
