"""Durable queue tracking analyst×ticker tasks for a given analysis date."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "analyst_tasks.db"


def _normalize(value: Optional[str], fallback: str) -> str:
    if value is None or value == "":
        return fallback
    return str(value)


@dataclass(frozen=True)
class TaskKey:
    analysis_date: str
    ticker: str
    analyst_name: str
    model_name: str
    model_provider: str


class AnalystTaskQueue:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _initialise(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analyst_tasks (
                    analysis_date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    analyst_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (analysis_date, ticker, analyst_name, model_name, model_provider)
                )
                """
            )

    def ensure_task(self, key: TaskKey) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO analyst_tasks(
                    analysis_date, ticker, analyst_name, model_name, model_provider, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (key.analysis_date, key.ticker, key.analyst_name, key.model_name, key.model_provider, datetime.utcnow().isoformat()),
            )

    def mark_completed(self, key: TaskKey) -> None:
        self._update_status(key, "completed")

    def mark_failed(self, key: TaskKey) -> None:
        self._update_status(key, "failed")

    def _update_status(self, key: TaskKey, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE analyst_tasks
                   SET status = ?, updated_at = ?
                 WHERE analysis_date = ? AND ticker = ? AND analyst_name = ?
                   AND model_name = ? AND model_provider = ?
                """,
                (
                    status,
                    datetime.utcnow().isoformat(),
                    key.analysis_date,
                    key.ticker,
                    key.analyst_name,
                    key.model_name,
                    key.model_provider,
                ),
            )

    def get_status(self, key: TaskKey) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT status FROM analyst_tasks
                 WHERE analysis_date = ? AND ticker = ? AND analyst_name = ?
                   AND model_name = ? AND model_provider = ?
                """,
                (key.analysis_date, key.ticker, key.analyst_name, key.model_name, key.model_provider),
            ).fetchone()
        return row[0] if row else None


_QUEUE_INSTANCE: Optional[AnalystTaskQueue] = None


def get_task_queue() -> AnalystTaskQueue:
    global _QUEUE_INSTANCE
    if _QUEUE_INSTANCE is None:
        _QUEUE_INSTANCE = AnalystTaskQueue()
    return _QUEUE_INSTANCE


__all__ = ["AnalystTaskQueue", "TaskKey", "get_task_queue"]
