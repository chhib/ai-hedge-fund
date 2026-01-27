"""Automatic IBKR → Börsdata ticker mapping with learning capability."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# Persistent mapping file location
MAPPING_FILE = Path(__file__).parent.parent.parent / "data" / "ibkr_borsdata_mappings.json"


class TickerMapper:
    """Maps IBKR tickers to Börsdata format with automatic learning."""

    def __init__(self) -> None:
        self._mappings: dict[str, str] = {}
        self._unmapped: set[str] = set()
        self._borsdata_tickers: set[str] = set()
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Load persisted mappings from disk."""
        if MAPPING_FILE.exists():
            try:
                data = json.loads(MAPPING_FILE.read_text())
                self._mappings = data.get("mappings", {})
                self._unmapped = set(data.get("unmapped", []))
            except (json.JSONDecodeError, IOError):
                pass

    def _save_mappings(self) -> None:
        """Persist mappings to disk."""
        MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mappings": self._mappings,
            "unmapped": list(self._unmapped),
        }
        MAPPING_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))

    def load_borsdata_tickers(self, nordic: list[dict], global_: list[dict]) -> None:
        """Load known Börsdata tickers for fuzzy matching."""
        for inst in nordic + global_:
            ticker = inst.get("ticker")
            if ticker:
                self._borsdata_tickers.add(ticker.upper())

    def map_ticker(self, ibkr_ticker: str) -> str:
        """Map an IBKR ticker to Börsdata format.

        1. Check persistent mapping cache
        2. Apply rule-based transformations
        3. Try fuzzy matching against Börsdata instruments
        4. Learn and persist successful mappings
        """
        if not ibkr_ticker:
            return ibkr_ticker

        upper = ibkr_ticker.upper()

        # 1. Check existing mapping
        if upper in self._mappings:
            return self._mappings[upper]

        # 2. Apply rule-based transformations
        normalized = self._apply_rules(ibkr_ticker)

        # 3. Verify against Börsdata tickers if we have them
        if self._borsdata_tickers:
            if normalized.upper() in self._borsdata_tickers:
                # Rule worked, save mapping
                self._learn_mapping(upper, normalized)
                return normalized

            # Try fuzzy matching
            fuzzy_match = self._fuzzy_match(ibkr_ticker)
            if fuzzy_match:
                self._learn_mapping(upper, fuzzy_match)
                return fuzzy_match

            # Mark as unmapped for review
            if upper not in self._unmapped:
                self._unmapped.add(upper)
                self._save_mappings()
                print(f"⚠️  Unknown ticker mapping: {ibkr_ticker} → please add to {MAPPING_FILE}")

        # Return best guess (rule-based result)
        return normalized

    def _apply_rules(self, ticker: str) -> str:
        """Apply rule-based transformations."""
        if not ticker:
            return ticker

        result = ticker

        # Rule 1: Nordic share classes - dot to space (LUND.B → LUND B)
        match = re.match(r'^(.+)\.(A|B|C)$', ticker.upper())
        if match:
            result = f"{match.group(1)} {match.group(2)}"

        # Rule 2: Some exchanges use dash (LUND-B → LUND B)
        match = re.match(r'^(.+)-(A|B|C)$', result.upper())
        if match:
            result = f"{match.group(1)} {match.group(2)}"

        return result

    def _fuzzy_match(self, ibkr_ticker: str) -> Optional[str]:
        """Try to find a matching Börsdata ticker using fuzzy logic."""
        upper = ibkr_ticker.upper()
        base = upper.split(".")[0].split("-")[0]

        candidates = []
        for bd_ticker in self._borsdata_tickers:
            bd_upper = bd_ticker.upper()
            # Exact base match with different suffix format
            if bd_upper.startswith(base) and len(bd_upper) <= len(base) + 2:
                candidates.append(bd_ticker)
            # Check if it's the same without any suffix
            if bd_upper == base:
                candidates.append(bd_ticker)

        if len(candidates) == 1:
            return candidates[0]

        # If multiple candidates, prefer exact base match
        for c in candidates:
            if c.upper() == base:
                return c

        return None

    def _learn_mapping(self, ibkr: str, borsdata: str) -> None:
        """Learn and persist a new mapping."""
        if ibkr.upper() != borsdata.upper():  # Only save if different
            self._mappings[ibkr.upper()] = borsdata
            self._unmapped.discard(ibkr.upper())
            self._save_mappings()

    def add_manual_mapping(self, ibkr: str, borsdata: str) -> None:
        """Manually add a mapping."""
        self._mappings[ibkr.upper()] = borsdata
        self._unmapped.discard(ibkr.upper())
        self._save_mappings()

    def get_unmapped(self) -> list[str]:
        """Get list of tickers that couldn't be mapped."""
        return sorted(self._unmapped)


# Global singleton
_mapper: Optional[TickerMapper] = None


def get_ticker_mapper() -> TickerMapper:
    """Get the global ticker mapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = TickerMapper()
    return _mapper


def map_ibkr_to_borsdata(ibkr_ticker: str) -> str:
    """Convenience function to map a single ticker."""
    return get_ticker_mapper().map_ticker(ibkr_ticker)
