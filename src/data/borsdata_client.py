"""Lightweight Börsdata API client used by the ingestion pipeline.

The client centralises authentication, rate limiting, and instrument caching so
callers can focus on transforming payloads into internal models. Network access
is abstracted behind a small public surface to simplify migration away from the
legacy FinancialDatasets provider.
"""

from __future__ import annotations

import os
import time
from collections import deque
from threading import Lock
from typing import Any, Callable, Dict, Iterable, Optional

import requests


class BorsdataAPIError(RuntimeError):
    """Raised when the Börsdata API returns an error response."""


class RateLimiter:
    """Simple token bucket limiter enforcing a max request rate."""

    def __init__(
        self,
        max_calls: int = 100,
        period_seconds: float = 10.0,
        *,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._sleep = sleep_func
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        """Block until the caller is permitted to proceed."""
        while True:
            wait_time = 0.0
            with self._lock:
                now = time.monotonic()
                # Drop timestamps that are outside the window
                while self._timestamps and now - self._timestamps[0] >= self.period_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return

                oldest = self._timestamps[0]
                wait_time = max(0.0, self.period_seconds - (now - oldest))

            # Sleep outside the lock so other callers can queue behind us
            self._sleep(wait_time if wait_time > 0 else 0.01)


class BorsdataClient:
    """HTTP client wrapper for Börsdata endpoints."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = "https://apiservice.borsdata.se",
        session: Optional[requests.Session] = None,
        rate_limiter: Optional[RateLimiter] = None,
        instrument_cache_ttl: float = 6 * 60 * 60,
        sleep_func: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
    ) -> None:
        self._explicit_api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or RateLimiter(sleep_func=sleep_func)
        self._instrument_cache_ttl = instrument_cache_ttl
        self._instrument_cache_timestamp = 0.0
        self._instrument_by_id: Dict[int, Dict[str, Any]] = {}
        self._instrument_by_ticker: Dict[str, Dict[str, Any]] = {}
        self._sleep = sleep_func
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_api_key(self, override: Optional[str]) -> str:
        api_key = override or self._explicit_api_key or os.environ.get("BORSDATA_API_KEY")
        if not api_key:
            raise BorsdataAPIError(
                "Missing Börsdata API key. Set BORSDATA_API_KEY or pass api_key explicitly."
            )
        return api_key

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        query_params: Dict[str, Any] = dict(params or {})
        query_params["authKey"] = self._resolve_api_key(api_key)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            self.rate_limiter.acquire()
            try:
                response = self.session.request(method.upper(), url, params=query_params)
            except requests.RequestException as exc:  # pragma: no cover - network failure path
                last_error = exc
                break

            if response.status_code == 429 and attempt < self._max_retries:
                retry_after_header = response.headers.get("Retry-After", "")
                try:
                    retry_after = float(retry_after_header)
                except (TypeError, ValueError):
                    retry_after = self.rate_limiter.period_seconds
                self._sleep(max(retry_after, 0))
                continue

            if response.status_code >= 400:
                raise BorsdataAPIError(
                    f"Börsdata API error {response.status_code} for {path}: {response.text}"
                )

            try:
                return response.json()
            except ValueError as exc:  # pragma: no cover - malformed response
                raise BorsdataAPIError(f"Failed to decode JSON for {path}") from exc

        if last_error is not None:
            raise BorsdataAPIError("Börsdata request failed") from last_error
        raise BorsdataAPIError(f"Exceeded retry budget for {path}")

    def _refresh_instrument_cache(self, *, api_key: Optional[str]) -> None:
        payload = self._request("GET", "/v1/instruments", api_key=api_key)
        instruments: Iterable[Dict[str, Any]] = payload.get("instruments") or []

        self._instrument_by_id = {}
        self._instrument_by_ticker = {}
        for instrument in instruments:
            ins_id = instrument.get("insId")
            if ins_id is None:
                continue
            ins_id = int(ins_id)
            self._instrument_by_id[ins_id] = instrument

            for key in ("ticker", "yahoo"):
                ticker_value = instrument.get(key)
                if ticker_value:
                    self._instrument_by_ticker.setdefault(ticker_value.upper(), instrument)

        self._instrument_cache_timestamp = time.time()

    def _ensure_instrument_cache(self, *, api_key: Optional[str], force_refresh: bool) -> None:
        cache_stale = (time.time() - self._instrument_cache_timestamp) >= self._instrument_cache_ttl
        if force_refresh or not self._instrument_by_id or cache_stale:
            self._refresh_instrument_cache(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_instruments(self, *, api_key: Optional[str] = None, force_refresh: bool = False) -> list[Dict[str, Any]]:
        self._ensure_instrument_cache(api_key=api_key, force_refresh=force_refresh)
        return list(self._instrument_by_id.values())

    def get_instrument(self, ticker: str, *, api_key: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        if not ticker:
            raise BorsdataAPIError("Ticker symbol is required")

        normalised = ticker.strip().upper()
        if not normalised:
            raise BorsdataAPIError("Ticker symbol is required")

        self._ensure_instrument_cache(api_key=api_key, force_refresh=force_refresh)
        instrument = self._instrument_by_ticker.get(normalised)
        if instrument is None:
            # Some tickers may only be available after a fresh sync
            self._ensure_instrument_cache(api_key=api_key, force_refresh=True)
            instrument = self._instrument_by_ticker.get(normalised)

        if instrument is None:
            raise BorsdataAPIError(f"Ticker '{ticker}' not found in Börsdata instruments")
        return instrument

    def get_stock_prices(
        self,
        instrument_id: int,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_count: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date
        if max_count:
            params["maxCount"] = max_count

        payload = self._request(
            "GET",
            f"/v1/instruments/{int(instrument_id)}/stockprices",
            params=params,
            api_key=api_key,
        )
        return payload.get("stockPricesList") or []

    def get_stock_prices_by_ticker(
        self,
        ticker: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_count: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        instrument = self.get_instrument(ticker, api_key=api_key)
        return self.get_stock_prices(
            instrument_id=instrument["insId"],
            start_date=start_date,
            end_date=end_date,
            max_count=max_count,
            api_key=api_key,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Expose the explicitly configured API key (if any)."""
        return self._explicit_api_key


__all__ = ["BorsdataAPIError", "BorsdataClient", "RateLimiter"]
