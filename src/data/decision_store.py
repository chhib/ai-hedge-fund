"""Append-only decision ledger for the full pipeline chain.

Captures: analyst signals -> aggregation -> governor decisions ->
trade recommendations -> execution outcomes.

Uses raw sqlite3 (consistent with all CLI-side data modules).
WAL mode for concurrent eager writes from ThreadPoolExecutor threads.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "decisions.db"


class DecisionStore:
    """SQLite-backed append-only decision ledger."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    pod_id TEXT,
                    run_type TEXT NOT NULL,
                    analysis_date TEXT NOT NULL,
                    analysts_json TEXT NOT NULL,
                    universe_json TEXT NOT NULL,
                    portfolio_source TEXT,
                    portfolio_path TEXT,
                    config_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    analyst_name TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    signal_numeric REAL NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT,
                    model_name TEXT,
                    model_provider TEXT,
                    close_price REAL,
                    currency TEXT,
                    price_source TEXT,
                    analysis_date TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS aggregations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    weighted_score REAL NOT NULL,
                    long_only_score REAL,
                    contributing_analysts INTEGER NOT NULL,
                    analyst_weights_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS governor_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    profile TEXT,
                    benchmark_ticker TEXT,
                    regime TEXT,
                    risk_state TEXT,
                    trading_enabled INTEGER,
                    deployment_ratio REAL,
                    min_cash_buffer REAL,
                    max_position_override REAL,
                    average_credibility REAL,
                    average_conviction REAL,
                    bullish_breadth REAL,
                    benchmark_drawdown_pct REAL,
                    analyst_weights_json TEXT,
                    ticker_penalties_json TEXT,
                    reasons_json TEXT,
                    analyst_scores_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_recommendations (
                    recommendation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    current_shares REAL,
                    current_weight REAL,
                    target_shares REAL,
                    target_weight REAL,
                    limit_price REAL,
                    confidence REAL,
                    reasoning TEXT,
                    currency TEXT,
                    pricing_basis REAL,
                    latest_close REAL,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recommendation_id TEXT,
                    run_id TEXT NOT NULL,
                    execution_type TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    side TEXT,
                    fill_price REAL,
                    fill_quantity REAL,
                    fill_timestamp TEXT,
                    ibkr_order_id TEXT,
                    status TEXT NOT NULL,
                    rejection_reason TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pod_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    pod_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    target_weight REAL NOT NULL,
                    signal_score REAL,
                    reasoning TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pod_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    shares REAL NOT NULL,
                    cost_basis REAL NOT NULL,
                    current_price REAL NOT NULL,
                    currency TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pod_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    total_value REAL NOT NULL,
                    cash REAL NOT NULL,
                    positions_value REAL NOT NULL,
                    cumulative_return_pct REAL NOT NULL,
                    starting_capital REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pod_lifecycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pod_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    old_tier TEXT,
                    new_tier TEXT NOT NULL,
                    reason TEXT,
                    source TEXT NOT NULL,
                    metrics_json TEXT,
                    run_id TEXT,
                    daemon_run_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_run_id ON signals (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_ticker_date ON signals (ticker, analysis_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_analyst_ticker_date ON signals (analyst_name, ticker, analysis_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_aggregations_run_id ON aggregations (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_governor_decisions_run_id ON governor_decisions (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_recommendations_run_id ON trade_recommendations (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_outcomes_run_id ON execution_outcomes (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_outcomes_rec_id ON execution_outcomes (recommendation_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pod_proposals_pod_created ON pod_proposals (pod_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pod_proposals_run_id ON pod_proposals (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_pod_created ON paper_positions (pod_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_run_id ON paper_positions (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_snapshots_pod_created ON paper_snapshots (pod_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_snapshots_run_id ON paper_snapshots (run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_pod_id ON runs (pod_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pod_lifecycle_events_pod_created ON pod_lifecycle_events (pod_id, created_at)")

            # Daemon scheduling metadata (operational, not audit trail -- allows UPDATE)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daemon_runs (
                    id TEXT PRIMARY KEY,
                    pod_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    skip_reason TEXT,
                    phase1_run_id TEXT,
                    error_message TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daemon_runs_pod_phase ON daemon_runs (pod_id, phase)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daemon_runs_status ON daemon_runs (status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daemon_runs_created ON daemon_runs (created_at)")

    # ── Write methods (all INSERT-only, never UPSERT) ──

    def record_run(
        self,
        run_id: str,
        run_type: str,
        analysis_date: str,
        analysts: List[str],
        universe: List[str],
        portfolio_source: Optional[str] = None,
        portfolio_path: Optional[str] = None,
        config_json: Optional[str] = None,
        pod_id: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, pod_id, run_type, analysis_date,
                    analysts_json, universe_json, portfolio_source, portfolio_path,
                    config_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    pod_id,
                    run_type,
                    analysis_date,
                    json.dumps(analysts, sort_keys=True),
                    json.dumps(universe, sort_keys=True),
                    portfolio_source,
                    portfolio_path,
                    config_json,
                    datetime.now().isoformat(),
                ),
            )

    def record_signal(
        self,
        run_id: str,
        ticker: str,
        analyst_name: str,
        signal: str,
        signal_numeric: float,
        confidence: float,
        reasoning: Optional[str] = None,
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
        close_price: Optional[float] = None,
        currency: Optional[str] = None,
        price_source: Optional[str] = None,
        analysis_date: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signals (run_id, ticker, analyst_name, signal,
                    signal_numeric, confidence, reasoning, model_name,
                    model_provider, close_price, currency, price_source,
                    analysis_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    ticker,
                    analyst_name,
                    signal,
                    signal_numeric,
                    confidence,
                    reasoning,
                    model_name,
                    model_provider,
                    close_price,
                    currency,
                    price_source,
                    analysis_date,
                    datetime.now().isoformat(),
                ),
            )

    def record_aggregations(self, run_id: str, aggregations: List[Dict[str, Any]]) -> None:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO aggregations (run_id, ticker, weighted_score,
                    long_only_score, contributing_analysts, analyst_weights_json,
                    created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        agg["ticker"],
                        agg["weighted_score"],
                        agg.get("long_only_score"),
                        agg["contributing_analysts"],
                        json.dumps(agg.get("analyst_weights", {}), sort_keys=True),
                        now,
                    )
                    for agg in aggregations
                ],
            )

    def record_governor_decision(self, run_id: str, decision: Any) -> None:
        """Record a GovernorDecision dataclass instance."""
        with self._connect() as conn:
            analyst_scores = []
            for score in getattr(decision, "analyst_scores", []):
                analyst_scores.append({
                    "analyst_name": score.analyst_name,
                    "display_name": score.display_name,
                    "credibility": score.credibility,
                    "hit_rate": score.hit_rate,
                    "avg_alpha": score.avg_alpha,
                    "conviction_rate": score.conviction_rate,
                    "weight": score.weight,
                    "regime": str(score.regime),
                })

            conn.execute(
                """
                INSERT INTO governor_decisions (run_id, profile, benchmark_ticker,
                    regime, risk_state, trading_enabled, deployment_ratio,
                    min_cash_buffer, max_position_override, average_credibility,
                    average_conviction, bullish_breadth, benchmark_drawdown_pct,
                    analyst_weights_json, ticker_penalties_json, reasons_json,
                    analyst_scores_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    decision.profile,
                    decision.benchmark_ticker,
                    str(decision.regime),
                    decision.risk_state,
                    1 if decision.trading_enabled else 0,
                    decision.deployment_ratio,
                    decision.min_cash_buffer,
                    decision.max_position_override,
                    decision.average_credibility,
                    decision.average_conviction,
                    decision.bullish_breadth,
                    decision.benchmark_drawdown_pct,
                    json.dumps(dict(decision.analyst_weights), sort_keys=True),
                    json.dumps(dict(decision.ticker_penalties), sort_keys=True),
                    json.dumps(list(decision.reasons)),
                    json.dumps(analyst_scores, sort_keys=True),
                    datetime.now().isoformat(),
                ),
            )

    def record_trade_recommendations(self, run_id: str, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Record trade recommendations and inject recommendation_id into each dict.

        Returns the recommendations list with recommendation_id added to each entry.
        """
        now = datetime.now().isoformat()
        with self._connect() as conn:
            for rec in recommendations:
                rec_id = str(uuid.uuid4())
                rec["recommendation_id"] = rec_id
                conn.execute(
                    """
                    INSERT INTO trade_recommendations (recommendation_id, run_id,
                        ticker, action, current_shares, current_weight,
                        target_shares, target_weight, limit_price, confidence,
                        reasoning, currency, pricing_basis, latest_close,
                        created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec_id,
                        run_id,
                        rec.get("ticker", ""),
                        rec.get("action", "HOLD"),
                        rec.get("current_shares"),
                        rec.get("current_weight"),
                        rec.get("target_shares"),
                        rec.get("target_weight"),
                        rec.get("current_price"),
                        rec.get("confidence"),
                        rec.get("reasoning"),
                        rec.get("currency"),
                        rec.get("pricing_basis"),
                        rec.get("latest_close"),
                        now,
                    ),
                )
        return recommendations

    def record_execution_outcomes(self, run_id: str, outcomes: List[Dict[str, Any]]) -> None:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO execution_outcomes (recommendation_id, run_id,
                    execution_type, ticker, side, fill_price, fill_quantity,
                    fill_timestamp, ibkr_order_id, status, rejection_reason,
                    created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        o.get("recommendation_id"),
                        run_id,
                        o.get("execution_type", "live"),
                        o.get("ticker", ""),
                        o.get("side"),
                        o.get("fill_price"),
                        o.get("fill_quantity"),
                        o.get("fill_timestamp"),
                        o.get("ibkr_order_id"),
                        o.get("status", "unknown"),
                        o.get("rejection_reason"),
                        now,
                    )
                    for o in outcomes
                ],
            )

    def record_pod_proposal(
        self,
        run_id: str,
        pod_id: str,
        picks: List[Dict[str, Any]],
        reasoning: Optional[str] = None,
    ) -> None:
        """Record a pod's portfolio proposal. One row per pick."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            for pick in picks:
                conn.execute(
                    """
                    INSERT INTO pod_proposals (run_id, pod_id, rank, ticker,
                        target_weight, signal_score, reasoning, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        pod_id,
                        pick.get("rank", 0),
                        pick.get("ticker", ""),
                        pick.get("target_weight", 0.0),
                        pick.get("signal_score"),
                        reasoning if pick.get("rank", 0) == 1 else None,
                        now,
                    ),
                )

    def record_paper_positions(self, pod_id: str, run_id: str, positions: List[Dict[str, Any]]) -> None:
        """Record virtual portfolio positions for a paper pod (one row per position)."""
        now = datetime.now().isoformat()
        try:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO paper_positions (pod_id, run_id, ticker, shares,
                        cost_basis, current_price, currency, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            pod_id,
                            run_id,
                            pos["ticker"],
                            pos["shares"],
                            pos["cost_basis"],
                            pos["current_price"],
                            pos.get("currency", "SEK"),
                            now,
                        )
                        for pos in positions
                    ],
                )
        except Exception:
            logger.debug("Failed to record paper positions for pod %s", pod_id, exc_info=True)

    def record_paper_snapshot(self, pod_id: str, run_id: str, snapshot: Dict[str, Any]) -> None:
        """Record a portfolio value snapshot for a paper pod."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO paper_snapshots (pod_id, run_id, total_value, cash,
                        positions_value, cumulative_return_pct, starting_capital,
                        created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pod_id,
                        run_id,
                        snapshot["total_value"],
                        snapshot["cash"],
                        snapshot["positions_value"],
                        snapshot["cumulative_return_pct"],
                        snapshot["starting_capital"],
                        datetime.now().isoformat(),
                    ),
                )
        except Exception:
            logger.debug("Failed to record paper snapshot for pod %s", pod_id, exc_info=True)

    def record_pod_lifecycle_event(
        self,
        pod_id: str,
        event_type: str,
        old_tier: Optional[str],
        new_tier: str,
        reason: Optional[str],
        source: str,
        metrics: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        daemon_run_id: Optional[str] = None,
    ) -> None:
        """Record an append-only pod lifecycle event."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO pod_lifecycle_events (
                        pod_id, event_type, old_tier, new_tier, reason, source,
                        metrics_json, run_id, daemon_run_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pod_id,
                        event_type,
                        old_tier,
                        new_tier,
                        reason,
                        source,
                        json.dumps(metrics, sort_keys=True) if metrics else None,
                        run_id,
                        daemon_run_id,
                        datetime.now().isoformat(),
                    ),
                )
        except Exception:
            logger.debug("Failed to record pod lifecycle event for pod %s", pod_id, exc_info=True)

    # ── Daemon run methods (operational metadata, allows UPDATE) ──

    def record_daemon_run(
        self,
        daemon_run_id: str,
        pod_id: str,
        phase: str,
        status: str = "scheduled",
        phase1_run_id: Optional[str] = None,
    ) -> None:
        """Record a new daemon run entry."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO daemon_runs (id, pod_id, phase, status, retry_count,
                        phase1_run_id, created_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (daemon_run_id, pod_id, phase, status, phase1_run_id, datetime.now().isoformat()),
                )
        except Exception:
            logger.debug("Failed to record daemon run %s", daemon_run_id, exc_info=True)

    def update_daemon_run_status(
        self,
        daemon_run_id: str,
        status: str,
        error_message: Optional[str] = None,
        retry_count: Optional[int] = None,
        skip_reason: Optional[str] = None,
    ) -> None:
        """Update a daemon run's status and optional fields."""
        try:
            with self._connect() as conn:
                sets = ["status = ?"]
                params: list = [status]

                if status == "running":
                    sets.append("started_at = ?")
                    params.append(datetime.now().isoformat())
                elif status in ("completed", "failed", "skipped"):
                    sets.append("completed_at = ?")
                    params.append(datetime.now().isoformat())

                if error_message is not None:
                    sets.append("error_message = ?")
                    params.append(error_message)
                if retry_count is not None:
                    sets.append("retry_count = ?")
                    params.append(retry_count)
                if skip_reason is not None:
                    sets.append("skip_reason = ?")
                    params.append(skip_reason)

                params.append(daemon_run_id)
                conn.execute(f"UPDATE daemon_runs SET {', '.join(sets)} WHERE id = ?", params)
        except Exception:
            logger.debug("Failed to update daemon run %s", daemon_run_id, exc_info=True)

    def get_latest_daemon_run(self, pod_id: str, phase: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the most recent daemon run for a pod, optionally filtered by phase."""
        clauses = ["pod_id = ?"]
        params: list = [pod_id]
        if phase:
            clauses.append("phase = ?")
            params.append(phase)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM daemon_runs WHERE {where} ORDER BY created_at DESC LIMIT 1",
                params,
            ).fetchone()
        return dict(row) if row else None

    def get_daemon_run(self, daemon_run_id: str) -> Optional[Dict[str, Any]]:
        """Return a single daemon run by ID."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM daemon_runs WHERE id = ?", (daemon_run_id,)).fetchone()
        return dict(row) if row else None

    def get_daemon_runs(
        self,
        pod_id: Optional[str] = None,
        status: Optional[str] = None,
        phase: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query daemon runs with optional filters."""
        clauses, params = [], []
        if pod_id:
            clauses.append("pod_id = ?")
            params.append(pod_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if phase:
            clauses.append("phase = ?")
            params.append(phase)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM daemon_runs{where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Read methods ──

    def get_latest_paper_positions(self, pod_id: str) -> List[Dict[str, Any]]:
        """Return the most recent set of virtual positions for a pod.

        Positions from the same run_id form a snapshot. Returns all positions
        from the latest run_id that wrote paper_positions for this pod.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM paper_positions
                WHERE pod_id = ? AND run_id = (
                    SELECT run_id FROM paper_positions
                    WHERE pod_id = ? ORDER BY created_at DESC LIMIT 1
                )
                ORDER BY ticker
                """,
                (pod_id, pod_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_paper_snapshot(self, pod_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent portfolio snapshot for a pod, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_snapshots WHERE pod_id = ? ORDER BY created_at DESC LIMIT 1",
                (pod_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_paper_snapshot_history(
        self,
        pod_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return portfolio snapshots for a pod over time, ordered chronologically."""
        clauses = ["pod_id = ?"]
        params: List[Any] = [pod_id]
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to)

        where = " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM paper_snapshots{where} ORDER BY created_at ASC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_paper_execution_outcomes(self, pod_id: str) -> List[Dict[str, Any]]:
        """Return paper execution outcomes for a pod by joining through runs."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT eo.* FROM execution_outcomes eo
                JOIN runs r ON eo.run_id = r.run_id
                WHERE r.pod_id = ? AND eo.execution_type = 'paper'
                ORDER BY eo.created_at ASC
                """,
                (pod_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_pod_proposals(
        self,
        pod_id: Optional[str] = None,
        run_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query pod proposals with optional filters."""
        clauses, params = [], []
        if pod_id:
            clauses.append("pod_id = ?")
            params.append(pod_id)
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM pod_proposals{where} ORDER BY pod_id, created_at, rank",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_pod_lifecycle_event(self, pod_id: str) -> Optional[Dict[str, Any]]:
        """Return the newest lifecycle event for a pod, or None."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM pod_lifecycle_events
                WHERE pod_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (pod_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_pod_lifecycle_events(self, pod_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Query lifecycle events ordered chronologically."""
        clauses = []
        params: List[Any] = []
        if pod_id:
            clauses.append("pod_id = ?")
            params.append(pod_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM pod_lifecycle_events{where} ORDER BY created_at ASC, id ASC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_runs(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        pod_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if date_from:
            clauses.append("analysis_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("analysis_date <= ?")
            params.append(date_to)
        if pod_id:
            clauses.append("pod_id = ?")
            params.append(pod_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM runs{where} ORDER BY created_at DESC", params).fetchall()
        return [dict(r) for r in rows]

    def get_signals(
        self,
        run_id: Optional[str] = None,
        ticker: Optional[str] = None,
        analyst: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if analyst:
            clauses.append("analyst_name = ?")
            params.append(analyst)
        if date_from:
            clauses.append("analysis_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("analysis_date <= ?")
            params.append(date_to)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM signals{where} ORDER BY id", params).fetchall()
        return [dict(r) for r in rows]

    def get_decision_chain(self, run_id: str) -> Dict[str, Any]:
        """Return the full pipeline for a run: run + signals + aggregations + governor + trades + executions."""
        with self._connect() as conn:
            run_row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            signals = conn.execute("SELECT * FROM signals WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
            aggs = conn.execute("SELECT * FROM aggregations WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
            gov = conn.execute("SELECT * FROM governor_decisions WHERE run_id = ? ORDER BY id", (run_id,)).fetchone()
            trades = conn.execute("SELECT * FROM trade_recommendations WHERE run_id = ? ORDER BY ticker", (run_id,)).fetchall()
            execs = conn.execute("SELECT * FROM execution_outcomes WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()

        return {
            "run": dict(run_row) if run_row else None,
            "signals": [dict(r) for r in signals],
            "aggregations": [dict(r) for r in aggs],
            "governor_decision": dict(gov) if gov else None,
            "trade_recommendations": [dict(r) for r in trades],
            "execution_outcomes": [dict(r) for r in execs],
        }


# ── Singleton accessor ──

_store_instance: Optional[DecisionStore] = None


def get_decision_store() -> DecisionStore:
    """Return singleton DecisionStore instance."""
    global _store_instance
    if _store_instance is None:
        _store_instance = DecisionStore()
    return _store_instance


__all__ = ["DecisionStore", "get_decision_store"]
