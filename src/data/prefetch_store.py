"""SQLite-backed storage for prefetched ticker data."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import BaseModel

from src.data.models import CompanyEvent, FinancialMetrics, InsiderTrade, LineItem, Price

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "prefetch_cache.db"


@dataclass(frozen=True)
class PrefetchParameters:
    """Unique parameters that define a prefetched dataset."""

    end_date: str
    start_date: str
    required_fields: frozenset[str]

    @classmethod
    def build(
        cls,
        *,
        end_date: str,
        start_date: str | None,
        required_fields: Iterable[str],
    ) -> "PrefetchParameters":
        normalized_start = start_date or ""
        normalized_fields = frozenset(required_fields)
        return cls(end_date=end_date, start_date=normalized_start, required_fields=normalized_fields)


class PrefetchStore:
    """Persist prefetched ticker payloads to a local SQLite database."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def __enter__(self) -> "PrefetchStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prefetch_cache (
                    ticker TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    fields TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, end_date, start_date)
                )
                """
            )

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_batch(
        self,
        tickers: Iterable[str],
        params: PrefetchParameters,
    ) -> dict[str, dict[str, Any]]:
        """Load cached payloads for the provided tickers matching params."""
        cached: dict[str, dict[str, Any]] = {}
        for raw_ticker in tickers:
            ticker = raw_ticker.upper()
            row = self._conn.execute(
                """
                SELECT fields, payload
                FROM prefetch_cache
                WHERE ticker = ? AND end_date = ? AND start_date = ?
                """,
                (ticker, params.end_date, params.start_date),
            ).fetchone()

            if not row:
                continue

            stored_fields = set(json.loads(row["fields"]))
            if not params.required_fields.issubset(stored_fields):
                # Cached payload is missing required data; skip it
                continue

            payload = json.loads(row["payload"])
            cached[raw_ticker] = _deserialize_payload(payload)

        return cached

    def store_batch(
        self,
        payloads: Mapping[str, Mapping[str, Any]],
        params: PrefetchParameters,
    ) -> None:
        """Persist the provided payloads to the cache."""
        timestamp = datetime.utcnow().isoformat()
        with self._conn:
            for raw_ticker, payload in payloads.items():
                ticker = raw_ticker.upper()
                serialized_payload = _serialize_payload(payload)
                fields_json = json.dumps(sorted(serialized_payload.keys()))
                payload_json = json.dumps(serialized_payload)
                self._conn.execute(
                    """
                    INSERT INTO prefetch_cache (ticker, end_date, start_date, fields, payload, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, end_date, start_date)
                    DO UPDATE SET
                        fields = excluded.fields,
                        payload = excluded.payload,
                        fetched_at = excluded.fetched_at
                    """,
                    (ticker, params.end_date, params.start_date, fields_json, payload_json, timestamp),
                )


# ----------------------------------------------------------------------
# Serialization helpers
# ----------------------------------------------------------------------

def _serialize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a prefetched payload into JSON-serialisable primitives."""
    serialised: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            serialised[key] = [_serialise_item(item) for item in value]
        elif isinstance(value, BaseModel):
            serialised[key] = value.model_dump()
        else:
            serialised[key] = value
    return serialised


def _serialise_item(item: Any) -> Any:
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def _deserialize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Rehydrate JSON primitives into the expected prefetched object graph."""
    reconstructed: dict[str, Any] = {}

    for key, value in payload.items():
        if key == "prices":
            reconstructed[key] = [_construct_model(Price, item) for item in value]
        elif key == "metrics":
            reconstructed[key] = [_construct_model(FinancialMetrics, item) for item in value]
        elif key == "line_items":
            reconstructed[key] = [_construct_model(LineItem, item) for item in value]
        elif key == "insider_trades":
            reconstructed[key] = [_construct_model(InsiderTrade, item) for item in value]
        elif key in {"events", "company_events"}:
            reconstructed[key] = [_construct_model(CompanyEvent, item) for item in value]
        else:
            reconstructed[key] = value

    return reconstructed


def _construct_model(model_cls: type[BaseModel], data: Any) -> BaseModel:
    if isinstance(data, model_cls):
        return data
    if isinstance(data, BaseModel):
        return model_cls(**data.model_dump())
    if isinstance(data, dict):
        return model_cls(**data)
    raise TypeError(f"Cannot reconstruct {model_cls.__name__} from {type(data)!r}")


__all__ = ["PrefetchStore", "PrefetchParameters"]
