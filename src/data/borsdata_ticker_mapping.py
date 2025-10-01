"""Persistent ticker-to-market mapping for Borsdata instruments.

This module provides automatic detection of whether a ticker belongs to the Nordic
or Global market, eliminating the need for users to manually specify --tickers-nordics.

The mapping is cached locally with a 24-hour TTL to minimize API calls.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Tuple

from src.data.borsdata_client import BorsdataClient, BorsdataAPIError


# Cache file location
def _get_cache_path() -> Path:
    """Return the path to the ticker mapping cache file."""
    cache_dir = Path.home() / ".cache" / "ai-hedge-fund"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "borsdata_tickers.json"


# Cache TTL (24 hours)
CACHE_TTL_SECONDS = 24 * 60 * 60


class TickerMapping:
    """Manages the mapping of ticker symbols to their markets (Nordic/Global)."""

    def __init__(self, client: Optional[BorsdataClient] = None):
        """Initialize the ticker mapping.

        Args:
            client: Optional BorsdataClient instance. If not provided, a new one is created.
        """
        self.client = client or BorsdataClient()
        self._mapping: Dict[str, str] = {}  # ticker -> "Nordic" or "global"
        self._loaded = False

    def _load_from_cache(self) -> bool:
        """Load mapping from cache file if it exists and is fresh.

        Returns:
            True if cache was loaded successfully, False otherwise.
        """
        cache_path = _get_cache_path()
        if not cache_path.exists():
            return False

        try:
            with open(cache_path, "r") as f:
                data = json.load(f)

            # Check TTL
            cached_at = data.get("cached_at", 0)
            age = time.time() - cached_at
            if age > CACHE_TTL_SECONDS:
                return False

            # Load the mapping
            self._mapping = data.get("mapping", {})
            self._loaded = True
            return True

        except (json.JSONDecodeError, OSError):
            return False

    def _save_to_cache(self) -> None:
        """Save the current mapping to the cache file."""
        cache_path = _get_cache_path()
        data = {
            "cached_at": time.time(),
            "mapping": self._mapping,
            "stats": {
                "total": len(self._mapping),
                "nordic": sum(1 for v in self._mapping.values() if v == "Nordic"),
                "global": sum(1 for v in self._mapping.values() if v == "global"),
            },
        }

        try:
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            print(f"Warning: Could not save ticker mapping cache: {e}")

    def refresh(self, *, api_key: Optional[str] = None) -> Tuple[int, int]:
        """Fetch all tickers from Borsdata and rebuild the mapping.

        Args:
            api_key: Optional API key to use for the request.

        Returns:
            Tuple of (nordic_count, global_count)

        Raises:
            BorsdataAPIError: If the API request fails.
        """
        # Fetch Nordic instruments
        nordic_instruments = self.client.get_instruments(api_key=api_key, force_refresh=True)

        # Fetch Global instruments (get_all_instruments returns both, so we need to separate)
        all_instruments = self.client.get_all_instruments(api_key=api_key, force_refresh=True)

        # Build sets of instrument IDs to differentiate
        nordic_ids = {inst.get("insId") for inst in nordic_instruments}

        # Clear and rebuild the mapping
        self._mapping = {}
        nordic_count = 0
        global_count = 0

        for inst in all_instruments:
            ticker = inst.get("ticker")
            if not ticker:
                continue

            # Normalize ticker to uppercase for consistent lookups
            ticker_upper = ticker.upper()

            # Determine market based on instrument ID
            if inst.get("insId") in nordic_ids:
                self._mapping[ticker_upper] = "Nordic"
                nordic_count += 1
            else:
                self._mapping[ticker_upper] = "global"
                global_count += 1

            # Also map the yahoo ticker if available
            yahoo = inst.get("yahoo")
            if yahoo and yahoo.upper() not in self._mapping:
                if inst.get("insId") in nordic_ids:
                    self._mapping[yahoo.upper()] = "Nordic"
                else:
                    self._mapping[yahoo.upper()] = "global"

        self._loaded = True
        self._save_to_cache()

        return (nordic_count, global_count)

    def ensure_loaded(self, *, api_key: Optional[str] = None) -> None:
        """Ensure the mapping is loaded, either from cache or API.

        Args:
            api_key: Optional API key to use if fetching from API.
        """
        if self._loaded:
            return

        # Try loading from cache first
        if self._load_from_cache():
            return

        # Cache miss or stale, fetch from API
        try:
            self.refresh(api_key=api_key)
        except BorsdataAPIError as e:
            raise RuntimeError(f"Failed to load ticker mapping: {e}") from e

    def get_market(self, ticker: str) -> Optional[str]:
        """Get the market for a ticker symbol.

        Args:
            ticker: The ticker symbol to look up.

        Returns:
            "Nordic" or "global" if the ticker is found, None otherwise.
        """
        if not self._loaded:
            self.ensure_loaded()

        return self._mapping.get(ticker.upper())

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about the current mapping.

        Returns:
            Dictionary with 'total', 'nordic', and 'global' counts.
        """
        if not self._loaded:
            self.ensure_loaded()

        return {
            "total": len(self._mapping),
            "nordic": sum(1 for v in self._mapping.values() if v == "Nordic"),
            "global": sum(1 for v in self._mapping.values() if v == "global"),
        }


# Singleton instance for convenience
_global_mapping: Optional[TickerMapping] = None


def get_ticker_mapping(client: Optional[BorsdataClient] = None) -> TickerMapping:
    """Get the global ticker mapping instance.

    Args:
        client: Optional BorsdataClient to use. Only used on first call.

    Returns:
        The global TickerMapping instance.
    """
    global _global_mapping
    if _global_mapping is None:
        _global_mapping = TickerMapping(client)
    return _global_mapping


def get_ticker_market(ticker: str, *, api_key: Optional[str] = None) -> Optional[str]:
    """Get the market for a ticker symbol (convenience function).

    Args:
        ticker: The ticker symbol to look up.
        api_key: Optional API key to use if fetching from API.

    Returns:
        "Nordic" or "global" if the ticker is found, None otherwise.
    """
    mapping = get_ticker_mapping()
    mapping.ensure_loaded(api_key=api_key)
    return mapping.get_market(ticker)


def refresh_ticker_mapping(*, api_key: Optional[str] = None) -> Tuple[int, int]:
    """Refresh the ticker mapping from the Borsdata API (convenience function).

    Args:
        api_key: Optional API key to use.

    Returns:
        Tuple of (nordic_count, global_count)
    """
    mapping = get_ticker_mapping()
    return mapping.refresh(api_key=api_key)


__all__ = [
    "TickerMapping",
    "get_ticker_mapping",
    "get_ticker_market",
    "refresh_ticker_mapping",
    "CACHE_TTL_SECONDS",
]
