"""Tests for the append-only Decision DB ledger."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pytest

from src.data.decision_store import DecisionStore, get_decision_store


@pytest.fixture
def store(tmp_path: Path) -> DecisionStore:
    return DecisionStore(db_path=tmp_path / "test_decisions.db")


@pytest.fixture
def run_id() -> str:
    return "test-run-001"


# ── Schema & WAL ──


def test_wal_mode_enabled(store: DecisionStore) -> None:
    with store._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_all_tables_created(store: DecisionStore) -> None:
    expected = {"runs", "signals", "aggregations", "governor_decisions", "trade_recommendations", "execution_outcomes"}
    with store._connect() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    tables = {r[0] for r in rows}
    assert expected <= tables


# ── Singleton ──


def test_singleton_returns_same_instance(monkeypatch) -> None:
    import src.data.decision_store as mod

    monkeypatch.setattr(mod, "_store_instance", None)
    a = get_decision_store()
    b = get_decision_store()
    assert a is b
    monkeypatch.setattr(mod, "_store_instance", None)


# ── Write / Read: runs ──


def test_record_and_get_run(store: DecisionStore, run_id: str) -> None:
    store.record_run(
        run_id=run_id,
        run_type="dry_run",
        analysis_date="2026-03-24",
        analysts=["warren_buffett", "cathie_wood"],
        universe=["AAPL", "TSLA"],
        portfolio_source="csv",
        config_json='{"max_holdings": 8}',
    )
    run = store.get_run(run_id)
    assert run is not None
    assert run["run_id"] == run_id
    assert run["run_type"] == "dry_run"
    assert json.loads(run["analysts_json"]) == ["warren_buffett", "cathie_wood"]
    assert json.loads(run["universe_json"]) == ["AAPL", "TSLA"]


def test_get_runs_filtered_by_date(store: DecisionStore) -> None:
    store.record_run("r1", "live", "2026-03-20", ["a"], ["T1"])
    store.record_run("r2", "live", "2026-03-24", ["a"], ["T1"])
    store.record_run("r3", "live", "2026-03-28", ["a"], ["T1"])

    runs = store.get_runs(date_from="2026-03-22", date_to="2026-03-26")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "r2"


# ── Write / Read: signals ──


def test_record_signal_and_query(store: DecisionStore, run_id: str) -> None:
    store.record_signal(
        run_id=run_id,
        ticker="AAPL",
        analyst_name="warren_buffett",
        signal="bullish",
        signal_numeric=1.0,
        confidence=0.85,
        reasoning="Strong moat",
        model_name="gpt-4o",
        model_provider="OpenAI",
        close_price=189.50,
        currency="USD",
        price_source="borsdata",
        analysis_date="2026-03-24",
    )
    signals = store.get_signals(run_id=run_id)
    assert len(signals) == 1
    s = signals[0]
    assert s["ticker"] == "AAPL"
    assert s["signal"] == "bullish"
    assert s["close_price"] == 189.50
    assert s["price_source"] == "borsdata"


def test_close_price_null_when_unavailable(store: DecisionStore, run_id: str) -> None:
    """Close price should be NULL when prefetched data is unavailable."""
    store.record_signal(
        run_id=run_id,
        ticker="MYSTERY",
        analyst_name="test_analyst",
        signal="neutral",
        signal_numeric=0.0,
        confidence=0.5,
        close_price=None,
        currency=None,
        price_source=None,
        analysis_date="2026-03-24",
    )
    signals = store.get_signals(run_id=run_id, ticker="MYSTERY")
    assert len(signals) == 1
    assert signals[0]["close_price"] is None
    assert signals[0]["currency"] is None
    assert signals[0]["price_source"] is None


def test_append_only_signals(store: DecisionStore, run_id: str) -> None:
    """Re-running the same analysis creates NEW rows, not UPSERTs."""
    for i in range(3):
        store.record_signal(
            run_id=run_id,
            ticker="AAPL",
            analyst_name="warren_buffett",
            signal="bullish",
            signal_numeric=1.0,
            confidence=0.8 + i * 0.05,
            analysis_date="2026-03-24",
        )
    signals = store.get_signals(run_id=run_id, ticker="AAPL", analyst="warren_buffett")
    assert len(signals) == 3


def test_signal_query_filters(store: DecisionStore) -> None:
    store.record_signal("r1", "AAPL", "buffett", "bullish", 1.0, 0.9, analysis_date="2026-03-20")
    store.record_signal("r1", "TSLA", "wood", "bullish", 1.0, 0.8, analysis_date="2026-03-20")
    store.record_signal("r2", "AAPL", "buffett", "bearish", -1.0, 0.7, analysis_date="2026-03-24")

    assert len(store.get_signals(ticker="AAPL")) == 2
    assert len(store.get_signals(analyst="wood")) == 1
    assert len(store.get_signals(date_from="2026-03-22")) == 1


# ── Write / Read: aggregations ──


def test_record_aggregations_with_analyst_metadata(store: DecisionStore, run_id: str) -> None:
    """Aggregation records should include contributing_analysts count and weights."""
    aggs = [
        {
            "ticker": "AAPL",
            "weighted_score": 0.72,
            "long_only_score": 0.86,
            "contributing_analysts": 5,
            "analyst_weights": {"buffett": 1.2, "wood": 0.8, "simons": 1.0, "lynch": 1.1, "dalio": 0.9},
        },
        {
            "ticker": "TSLA",
            "weighted_score": -0.15,
            "long_only_score": 0.0,
            "contributing_analysts": 3,
            "analyst_weights": {"wood": 0.8, "simons": 1.0, "dalio": 0.9},
        },
    ]
    store.record_aggregations(run_id, aggs)

    chain = store.get_decision_chain(run_id)
    assert len(chain["aggregations"]) == 2

    aapl_agg = chain["aggregations"][0]
    assert aapl_agg["ticker"] == "AAPL"
    assert aapl_agg["weighted_score"] == 0.72
    assert aapl_agg["contributing_analysts"] == 5
    weights = json.loads(aapl_agg["analyst_weights_json"])
    assert weights["buffett"] == 1.2
    assert len(weights) == 5


# ── Write / Read: governor decisions ──


@dataclass
class FakeAnalystScore:
    analyst_name: str = "buffett"
    display_name: str = "Warren Buffett"
    credibility: float = 0.85
    hit_rate: float = 0.72
    avg_alpha: float = 0.03
    conviction_rate: float = 0.65
    weight: float = 1.2
    regime: str = "trend_up"


@dataclass
class FakeGovernorDecision:
    profile: str = "preservation"
    benchmark_ticker: str = "SPY"
    regime: str = "trend_up"
    risk_state: str = "normal"
    trading_enabled: bool = True
    deployment_ratio: float = 0.8
    analyst_weights: dict = field(default_factory=lambda: {"buffett": 1.2, "wood": 0.8})
    ticker_penalties: dict = field(default_factory=dict)
    max_position_override: Optional[float] = 0.20
    min_cash_buffer: float = 0.05
    reasons: list = field(default_factory=lambda: ["Trend up", "Low vol"])
    average_credibility: float = 0.85
    average_conviction: float = 0.70
    bullish_breadth: float = 0.60
    benchmark_drawdown_pct: float = -2.5
    analyst_scores: List = field(default_factory=lambda: [FakeAnalystScore()])


def test_record_governor_decision(store: DecisionStore, run_id: str) -> None:
    decision = FakeGovernorDecision()
    store.record_governor_decision(run_id, decision)

    chain = store.get_decision_chain(run_id)
    gov = chain["governor_decision"]
    assert gov is not None
    assert gov["profile"] == "preservation"
    assert gov["trading_enabled"] == 1
    assert gov["deployment_ratio"] == 0.8
    assert json.loads(gov["analyst_weights_json"]) == {"buffett": 1.2, "wood": 0.8}
    scores = json.loads(gov["analyst_scores_json"])
    assert len(scores) == 1
    assert scores[0]["analyst_name"] == "buffett"


# ── Write / Read: trade recommendations + recommendation_id linking ──


def test_record_trade_recommendations_generates_ids(store: DecisionStore, run_id: str) -> None:
    recs = [
        {"ticker": "AAPL", "action": "ADD", "current_shares": 0, "target_shares": 50, "current_price": 190.0, "confidence": 0.8, "currency": "USD"},
        {"ticker": "TSLA", "action": "SELL", "current_shares": 30, "target_shares": 0, "current_price": 250.0, "confidence": 0.7, "currency": "USD"},
    ]
    result = store.record_trade_recommendations(run_id, recs)

    # recommendation_id injected into each dict
    assert "recommendation_id" in result[0]
    assert "recommendation_id" in result[1]
    assert result[0]["recommendation_id"] != result[1]["recommendation_id"]

    # Persisted in DB
    chain = store.get_decision_chain(run_id)
    assert len(chain["trade_recommendations"]) == 2
    db_ids = {r["recommendation_id"] for r in chain["trade_recommendations"]}
    assert result[0]["recommendation_id"] in db_ids
    assert result[1]["recommendation_id"] in db_ids


def test_recommendation_id_links_to_execution_outcomes(store: DecisionStore, run_id: str) -> None:
    """Execution outcomes should link back to recommendations via recommendation_id."""
    recs = [
        {"ticker": "AAPL", "action": "ADD", "current_shares": 0, "target_shares": 50, "current_price": 190.0},
    ]
    recs = store.record_trade_recommendations(run_id, recs)
    rec_id = recs[0]["recommendation_id"]

    store.record_execution_outcomes(run_id, [
        {
            "recommendation_id": rec_id,
            "execution_type": "live",
            "ticker": "AAPL",
            "side": "BUY",
            "fill_price": 189.80,
            "fill_quantity": 50,
            "fill_timestamp": "2026-03-24T10:30:00",
            "ibkr_order_id": "12345",
            "status": "filled",
        },
    ])

    chain = store.get_decision_chain(run_id)
    assert len(chain["execution_outcomes"]) == 1
    outcome = chain["execution_outcomes"][0]
    assert outcome["recommendation_id"] == rec_id
    assert outcome["status"] == "filled"
    assert outcome["fill_price"] == 189.80


def test_execution_outcomes_skipped_and_deferred(store: DecisionStore, run_id: str) -> None:
    store.record_execution_outcomes(run_id, [
        {"ticker": "TSLA", "execution_type": "skipped", "status": "skipped", "rejection_reason": "Hold action"},
        {"ticker": "HOVE", "execution_type": "live", "status": "deferred", "rejection_reason": "Market closed (CPH CLOSED)"},
    ])
    chain = store.get_decision_chain(run_id)
    assert len(chain["execution_outcomes"]) == 2
    statuses = {o["ticker"]: o["status"] for o in chain["execution_outcomes"]}
    assert statuses["TSLA"] == "skipped"
    assert statuses["HOVE"] == "deferred"


# ── Full decision chain ──


def test_full_decision_chain(store: DecisionStore) -> None:
    rid = "chain-test-001"
    store.record_run(rid, "dry_run", "2026-03-24", ["buffett"], ["AAPL"])
    store.record_signal(rid, "AAPL", "buffett", "bullish", 1.0, 0.9, analysis_date="2026-03-24", close_price=190.0, price_source="borsdata")
    store.record_aggregations(rid, [{"ticker": "AAPL", "weighted_score": 0.9, "contributing_analysts": 1, "analyst_weights": {"buffett": 1.0}}])
    store.record_governor_decision(rid, FakeGovernorDecision())
    recs = store.record_trade_recommendations(rid, [{"ticker": "AAPL", "action": "ADD", "target_shares": 50, "current_price": 190.0}])
    store.record_execution_outcomes(rid, [{"recommendation_id": recs[0]["recommendation_id"], "execution_type": "paper", "ticker": "AAPL", "side": "BUY", "fill_price": 189.5, "fill_quantity": 50, "status": "filled"}])

    chain = store.get_decision_chain(rid)
    assert chain["run"]["run_id"] == rid
    assert len(chain["signals"]) == 1
    assert len(chain["aggregations"]) == 1
    assert chain["governor_decision"] is not None
    assert len(chain["trade_recommendations"]) == 1
    assert len(chain["execution_outcomes"]) == 1
    # Full FK chain
    assert chain["execution_outcomes"][0]["recommendation_id"] == chain["trade_recommendations"][0]["recommendation_id"]


# ── Thread safety ──


def test_concurrent_signal_writes(store: DecisionStore, run_id: str) -> None:
    """Concurrent threads can write signals without corruption (WAL mode)."""
    errors = []

    def write_signal(i: int):
        try:
            store.record_signal(
                run_id=run_id,
                ticker=f"T{i}",
                analyst_name="test",
                signal="bullish",
                signal_numeric=1.0,
                confidence=0.5,
                analysis_date="2026-03-24",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_signal, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    signals = store.get_signals(run_id=run_id)
    assert len(signals) == 20
