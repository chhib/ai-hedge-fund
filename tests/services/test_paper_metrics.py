"""Tests for paper trading performance metrics."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.data.decision_store import DecisionStore
from src.services.paper_metrics import compute_paper_performance


@pytest.fixture
def store(tmp_path: Path) -> DecisionStore:
    return DecisionStore(db_path=tmp_path / "test.db")


@pytest.fixture(autouse=True)
def patch_store(store, monkeypatch):
    monkeypatch.setattr("src.services.paper_metrics.get_decision_store", lambda: store)


def _record_snapshots(store, pod_id, values, start=None):
    """Helper to record a series of portfolio snapshots."""
    base = start or datetime(2026, 3, 1, 10, 0, 0)
    for i, val in enumerate(values):
        run_id = f"run-{pod_id}-{i:03d}"
        store.record_paper_snapshot(pod_id, run_id, {
            "total_value": val,
            "cash": val * 0.1,
            "positions_value": val * 0.9,
            "cumulative_return_pct": ((val - 100000) / 100000) * 100,
            "starting_capital": 100000.0,
        })


class TestComputePaperPerformance:

    def test_no_data_returns_empty(self, store):
        perf = compute_paper_performance("nonexistent")
        assert perf["total_value"] is None
        assert perf["sharpe_ratio"] is None
        assert perf["win_rate"] is None
        assert perf["num_snapshots"] == 0

    def test_single_snapshot_insufficient_for_metrics(self, store):
        _record_snapshots(store, "pod1", [100000])
        perf = compute_paper_performance("pod1")
        assert perf["total_value"] == 100000
        assert perf["sharpe_ratio"] is None
        assert perf["num_snapshots"] == 1

    def test_multiple_snapshots_computes_sharpe(self, store):
        _record_snapshots(store, "pod1", [100000, 101000, 102000, 103000, 102500])
        perf = compute_paper_performance("pod1")
        assert perf["num_snapshots"] == 5
        assert perf["sharpe_ratio"] is not None
        assert perf["max_drawdown"] is not None

    def test_win_rate_with_closed_trades(self, store):
        # Record a run so execution_outcomes can join
        store.record_run("run-1", "paper", "2026-03-25", ["buffett"], ["AAPL", "MSFT"], pod_id="pod1")
        store.record_run("run-2", "paper", "2026-03-26", ["buffett"], ["AAPL", "MSFT"], pod_id="pod1")

        # Buy AAPL at 100, sell at 120 (win)
        store.record_execution_outcomes("run-1", [
            {"execution_type": "paper", "ticker": "AAPL", "side": "BUY", "fill_price": 100.0, "fill_quantity": 10, "status": "filled"},
        ])
        store.record_execution_outcomes("run-2", [
            {"execution_type": "paper", "ticker": "AAPL", "side": "SELL", "fill_price": 120.0, "fill_quantity": 10, "status": "filled"},
        ])

        perf = compute_paper_performance("pod1")
        assert perf["win_rate"] == 1.0
        assert perf["avg_trade_pnl"] == pytest.approx(200.0)  # (120-100) * 10

    def test_win_rate_with_losing_trade(self, store):
        store.record_run("run-1", "paper", "2026-03-25", ["buffett"], ["AAPL"], pod_id="pod1")
        store.record_run("run-2", "paper", "2026-03-26", ["buffett"], ["AAPL"], pod_id="pod1")

        store.record_execution_outcomes("run-1", [
            {"execution_type": "paper", "ticker": "AAPL", "side": "BUY", "fill_price": 100.0, "fill_quantity": 10, "status": "filled"},
        ])
        store.record_execution_outcomes("run-2", [
            {"execution_type": "paper", "ticker": "AAPL", "side": "SELL", "fill_price": 80.0, "fill_quantity": 10, "status": "filled"},
        ])

        perf = compute_paper_performance("pod1")
        assert perf["win_rate"] == 0.0
        assert perf["avg_trade_pnl"] == pytest.approx(-200.0)

    def test_no_closed_trades_win_rate_none(self, store):
        store.record_run("run-1", "paper", "2026-03-25", ["buffett"], ["AAPL"], pod_id="pod1")
        store.record_execution_outcomes("run-1", [
            {"execution_type": "paper", "ticker": "AAPL", "side": "BUY", "fill_price": 100.0, "fill_quantity": 10, "status": "filled"},
        ])

        perf = compute_paper_performance("pod1")
        assert perf["win_rate"] is None
        assert perf["num_trades"] == 1

    def test_pod_isolation(self, store):
        store.record_run("run-a", "paper", "2026-03-25", ["buffett"], ["AAPL"], pod_id="pod_a")
        store.record_run("run-b", "paper", "2026-03-25", ["simons"], ["MSFT"], pod_id="pod_b")

        _record_snapshots(store, "pod_a", [100000, 110000])
        _record_snapshots(store, "pod_b", [100000, 90000])

        perf_a = compute_paper_performance("pod_a")
        perf_b = compute_paper_performance("pod_b")

        assert perf_a["cumulative_return_pct"] == pytest.approx(10.0)
        assert perf_b["cumulative_return_pct"] == pytest.approx(-10.0)
