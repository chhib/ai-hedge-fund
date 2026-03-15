"""Tests for IBKR portfolio reconciliation logic."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import pytest

from src.integrations.ibkr_reconcile import (
    PositionDrift,
    build_result,
    compute_drift_score,
    find_latest_target_csv,
    reconcile,
)
from src.utils.portfolio_loader import Portfolio, Position


def _portfolio(positions: list[Position], cash: dict[str, float] | None = None) -> Portfolio:
    return Portfolio(positions=positions, cash_holdings=cash or {}, last_updated=datetime.now())


def _pos(ticker: str, shares: float, cost_basis: float = 100.0, currency: str = "USD") -> Position:
    return Position(ticker=ticker, shares=shares, cost_basis=cost_basis, currency=currency)


# --- reconcile() tests ---


class TestReconcile:
    def test_identical_portfolios(self):
        positions = [_pos("AAPL", 10), _pos("GOOG", 5)]
        live = _portfolio(positions)
        target = _portfolio(positions)
        drifts = reconcile(live, target)
        assert all(d.status == "match" for d in drifts)
        assert all(d.shares_delta == 0 for d in drifts)

    def test_share_count_drift(self):
        live = _portfolio([_pos("AAPL", 10)])
        target = _portfolio([_pos("AAPL", 20)])
        drifts = reconcile(live, target)
        assert len(drifts) == 1
        assert drifts[0].status == "drift"
        assert drifts[0].shares_delta == -10

    def test_missing_live_position(self):
        live = _portfolio([_pos("AAPL", 10)])
        target = _portfolio([_pos("AAPL", 10), _pos("GOOG", 5)])
        drifts = reconcile(live, target)
        by_ticker = {d.ticker: d for d in drifts}
        assert by_ticker["AAPL"].status == "match"
        assert by_ticker["GOOG"].status == "missing_live"
        assert by_ticker["GOOG"].live_shares == 0

    def test_extra_live_position(self):
        live = _portfolio([_pos("AAPL", 10), _pos("TSLA", 3)])
        target = _portfolio([_pos("AAPL", 10)])
        drifts = reconcile(live, target)
        by_ticker = {d.ticker: d for d in drifts}
        assert by_ticker["TSLA"].status == "extra_live"
        assert by_ticker["TSLA"].target_shares == 0

    def test_within_tolerance(self):
        live = _portfolio([_pos("AAPL", 11)])
        target = _portfolio([_pos("AAPL", 10)])
        drifts = reconcile(live, target, tolerance=1)
        assert drifts[0].status == "match"
        assert drifts[0].shares_delta == 1

    def test_empty_target(self):
        live = _portfolio([_pos("AAPL", 10), _pos("GOOG", 5)])
        target = _portfolio([])
        drifts = reconcile(live, target)
        assert all(d.status == "extra_live" for d in drifts)

    def test_empty_live(self):
        live = _portfolio([])
        target = _portfolio([_pos("AAPL", 10), _pos("GOOG", 5)])
        drifts = reconcile(live, target)
        assert all(d.status == "missing_live" for d in drifts)

    def test_zero_cost_basis(self):
        live = _portfolio([_pos("AAPL", 10, cost_basis=0.0)])
        target = _portfolio([_pos("AAPL", 10, cost_basis=0.0)])
        drifts = reconcile(live, target)
        assert drifts[0].status == "match"
        assert drifts[0].live_weight == 0.0
        assert drifts[0].target_weight == 0.0


# --- compute_drift_score() tests ---


class TestDriftScore:
    def test_drift_score_zero(self):
        drifts = [
            PositionDrift("AAPL", "match", 10, 10, 0, 50.0, 50.0, 0.0, "USD"),
            PositionDrift("GOOG", "match", 5, 5, 0, 50.0, 50.0, 0.0, "USD"),
        ]
        assert compute_drift_score(drifts) == 0.0

    def test_drift_score_nonzero(self):
        drifts = [
            PositionDrift("AAPL", "drift", 10, 15, -5, 40.0, 60.0, -20.0, "USD"),
            PositionDrift("GOOG", "match", 5, 5, 0, 60.0, 40.0, 20.0, "USD"),
        ]
        expected = math.sqrt((400 + 400) / 2)
        assert abs(compute_drift_score(drifts) - expected) < 0.001

    def test_drift_score_empty(self):
        assert compute_drift_score([]) == 0.0


# --- find_latest_target_csv() tests ---


class TestFindLatestCsv:
    def test_find_latest_csv(self, tmp_path: Path):
        (tmp_path / "portfolio_20260101.csv").touch()
        (tmp_path / "portfolio_20260314.csv").touch()
        (tmp_path / "portfolio_20260201.csv").touch()
        result = find_latest_target_csv(tmp_path)
        assert result is not None
        assert result.name == "portfolio_20260314.csv"

    def test_find_latest_csv_excludes_actual(self, tmp_path: Path):
        (tmp_path / "portfolio_20260314.csv").touch()
        (tmp_path / "portfolio_20260315_actual.csv").touch()
        result = find_latest_target_csv(tmp_path)
        assert result is not None
        assert result.name == "portfolio_20260314.csv"

    def test_find_latest_csv_no_files(self, tmp_path: Path):
        assert find_latest_target_csv(tmp_path) is None


# --- build_result() tests ---


class TestBuildResult:
    def test_build_result_basic(self):
        live = _portfolio([_pos("AAPL", 10)])
        target = _portfolio([_pos("AAPL", 10)])
        csv_path = Path("portfolio_20260314.csv")
        result = build_result(live, target, csv_path, account_id="U12345")
        assert result.live_count == 1
        assert result.target_count == 1
        assert result.target_csv_date == "2026-03-14"
        assert result.account_id == "U12345"
        assert result.drift_score == 0.0
        assert len(result.drifts) == 1
        assert result.drifts[0].status == "match"
