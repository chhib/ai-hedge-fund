"""
Persistent cache for LLM responses with 7-day freshness check.

Stores LLM request/response pairs in SQLite to avoid redundant API calls.
Old entries are never deleted, but only responses < 7 days old are returned.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session, sessionmaker


# Database setup - reuse the existing backend database
BACKEND_DIR = Path(__file__).parent.parent.parent / "app" / "backend"
DATABASE_PATH = BACKEND_DIR / "hedge_fund.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Create engine and session
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class LLMResponseCache:
    """Persistent cache for LLM responses with 7-day freshness policy."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """
        Initialize LLM response cache.

        Args:
            db_path: Optional custom database path. If None, uses default backend DB.
        """
        if db_path:
            custom_url = f"sqlite:///{db_path}"
            self.engine = create_engine(custom_url, connect_args={"check_same_thread": False})
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        else:
            self.engine = engine
            self.SessionLocal = SessionLocal

    def _get_prompt_hash(self, prompt: str) -> str:
        """Generate SHA256 hash of prompt for efficient lookup."""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get_cached_response(
        self,
        ticker: str,
        analyst_name: str,
        prompt: str,
        max_age_days: int = 7,
    ) -> Optional[dict[str, Any]]:
        """
        Retrieve cached LLM response if it exists and is fresh.

        Args:
            ticker: Stock ticker symbol
            analyst_name: Name of the analyst agent
            prompt: Full prompt text
            max_age_days: Maximum age in days to consider response fresh (default: 7)

        Returns:
            Cached response as dict if found and fresh, None otherwise
        """
        from app.backend.database.models import LLMResponseCache as CacheModel

        prompt_hash = self._get_prompt_hash(prompt)
        cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)

        db = self.SessionLocal()
        try:
            # Query for most recent matching entry
            cached_entry = (
                db.query(CacheModel)
                .filter(
                    CacheModel.ticker == ticker.upper(),
                    CacheModel.analyst_name == analyst_name,
                    CacheModel.prompt_hash == prompt_hash,
                    CacheModel.created_at >= cutoff_date,  # Only fresh entries
                )
                .order_by(desc(CacheModel.created_at))
                .first()
            )

            if cached_entry:
                # Deserialize and return cached response
                return json.loads(cached_entry.response_json)

            return None

        finally:
            db.close()

    def store_response(
        self,
        ticker: str,
        analyst_name: str,
        prompt: str,
        response: BaseModel,
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
    ) -> None:
        """
        Store LLM response in cache.

        Args:
            ticker: Stock ticker symbol
            analyst_name: Name of the analyst agent
            prompt: Full prompt text
            response: Pydantic model instance to cache
            model_name: Optional LLM model name
            model_provider: Optional LLM provider name
        """
        from app.backend.database.models import LLMResponseCache as CacheModel

        prompt_hash = self._get_prompt_hash(prompt)

        # Serialize pydantic response to JSON
        response_json = json.dumps(response.model_dump())

        db = self.SessionLocal()
        try:
            cache_entry = CacheModel(
                ticker=ticker.upper(),
                analyst_name=analyst_name,
                prompt_hash=prompt_hash,
                prompt_text=prompt,
                response_json=response_json,
                model_name=model_name,
                model_provider=model_provider,
            )
            db.add(cache_entry)
            db.commit()
        finally:
            db.close()

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with total entries, fresh entries, and unique tickers
        """
        from app.backend.database.models import LLMResponseCache as CacheModel

        cutoff_date = datetime.utcnow() - timedelta(days=7)

        db = self.SessionLocal()
        try:
            total_entries = db.query(CacheModel).count()
            fresh_entries = db.query(CacheModel).filter(CacheModel.created_at >= cutoff_date).count()
            unique_tickers = db.query(CacheModel.ticker).distinct().count()

            return {
                "total_entries": total_entries,
                "fresh_entries": fresh_entries,
                "stale_entries": total_entries - fresh_entries,
                "unique_tickers": unique_tickers,
            }
        finally:
            db.close()


# Singleton instance for global use
_cache_instance: Optional[LLMResponseCache] = None


def get_llm_cache() -> LLMResponseCache:
    """Get or create singleton LLM cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LLMResponseCache()
    return _cache_instance
