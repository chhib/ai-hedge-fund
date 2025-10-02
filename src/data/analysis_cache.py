"""Persistent cache for analyst signals keyed by ticker/date/model."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "prefetch_cache.db"


def _normalise(value: Optional[str], fallback: str) -> str:
    """Return a consistent key component for optional fields."""
    if value is None or value == "":
        return fallback
    return str(value)


@dataclass(frozen=True)
class CachedAnalystSignal:
    ticker: str
    analyst_name: str
    analysis_date: str
    model_name: str
    model_provider: str
    signal: str
    signal_numeric: float
    confidence: float
    reasoning: str


class AnalysisCache:
    """SQLite-backed cache for analyst outputs keyed by ticker/date/model."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _initialise(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    ticker TEXT NOT NULL,
                    analyst_name TEXT NOT NULL,
                    analysis_date TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, analyst_name, analysis_date, model_name, model_provider)
                )
                """
            )

    def get_cached_analysis(
        self,
        *,
        ticker: str,
        analyst_name: str,
        analysis_date: str,
        model_name: Optional[str],
        model_provider: Optional[str],
    ) -> Optional[CachedAnalystSignal]:
        """Retrieve cached analysis for the given key if present."""
        model_name_key = _normalise(model_name, "unknown")
        model_provider_key = _normalise(model_provider, "unknown")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT payload
                FROM analysis_cache
                WHERE ticker = ?
                  AND analyst_name = ?
                  AND analysis_date = ?
                  AND model_name = ?
                  AND model_provider = ?
                """,
                (ticker.upper(), analyst_name, analysis_date, model_name_key, model_provider_key),
            ).fetchone()

        if not row:
            return None

        payload = json.loads(row["payload"])
        return CachedAnalystSignal(
            ticker=ticker,
            analyst_name=analyst_name,
            analysis_date=analysis_date,
            model_name=model_name_key,
            model_provider=model_provider_key,
            signal=payload.get("signal", "neutral"),
            signal_numeric=float(payload.get("signal_numeric", 0.0)),
            confidence=float(payload.get("confidence", 0.0)),
            reasoning=payload.get("reasoning", ""),
        )

    def store_analysis(
        self,
        *,
        ticker: str,
        analyst_name: str,
        analysis_date: str,
        model_name: Optional[str],
        model_provider: Optional[str],
        signal: str,
        signal_numeric: float,
        confidence: float,
        reasoning: str,
    ) -> None:
        """Persist analysis result for future reuse."""
        model_name_key = _normalise(model_name, "unknown")
        model_provider_key = _normalise(model_provider, "unknown")
        payload = json.dumps(
            {
                "signal": signal,
                "signal_numeric": signal_numeric,
                "confidence": confidence,
                "reasoning": reasoning,
            }
        )
        cached_at = datetime.utcnow().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO analysis_cache (
                    ticker,
                    analyst_name,
                    analysis_date,
                    model_name,
                    model_provider,
                    payload,
                    cached_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, analyst_name, analysis_date, model_name, model_provider)
                DO UPDATE SET
                    payload = excluded.payload,
                    cached_at = excluded.cached_at
                """,
                (
                    ticker.upper(),
                    analyst_name,
                    analysis_date,
                    model_name_key,
                    model_provider_key,
                    payload,
                    cached_at,
                ),
            )


_cache_instance: Optional[AnalysisCache] = None


def get_analysis_cache() -> AnalysisCache:
    """Return singleton analysis cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = AnalysisCache()
    return _cache_instance


__all__ = ["AnalysisCache", "CachedAnalystSignal", "get_analysis_cache"]
