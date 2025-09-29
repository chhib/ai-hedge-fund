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
        metadata_cache_ttl: float = 6 * 60 * 60,
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
        self._global_instrument_cache_timestamp = 0.0
        self._global_instrument_by_id: Dict[int, Dict[str, Any]] = {}
        self._global_instrument_by_ticker: Dict[str, Dict[str, Any]] = {}
        self._metadata_cache_ttl = metadata_cache_ttl
        self._kpi_metadata_timestamp = 0.0
        self._kpi_metadata: list[Dict[str, Any]] = []
        self._sleep = sleep_func
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_api_key(self, override: Optional[str]) -> str:
        api_key = override or self._explicit_api_key or os.environ.get("BORSDATA_API_KEY")
        if not api_key:
            raise BorsdataAPIError("Missing Börsdata API key. Set BORSDATA_API_KEY or pass api_key explicitly.")
        return api_key

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        query_params: Dict[str, Any] = dict(params or {})
        query_params["authKey"] = self._resolve_api_key(api_key)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            self.rate_limiter.acquire()
            try:
                response = self.session.request(method.upper(), url, params=query_params, json=json)
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
                raise BorsdataAPIError(f"Börsdata API error {response.status_code} for {path}: {response.text}")

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

    def _refresh_global_instrument_cache(self, *, api_key: Optional[str]) -> None:
        payload = self._request("GET", "/v1/instruments/global", api_key=api_key)
        instruments: Iterable[Dict[str, Any]] = payload.get("instruments") or []

        self._global_instrument_by_id = {}
        self._global_instrument_by_ticker = {}
        for instrument in instruments:
            ins_id = instrument.get("insId")
            if ins_id is None:
                continue
            ins_id = int(ins_id)
            self._global_instrument_by_id[ins_id] = instrument

            for key in ("ticker", "yahoo"):
                ticker_value = instrument.get(key)
                if ticker_value:
                    self._global_instrument_by_ticker.setdefault(ticker_value.upper(), instrument)

        self._global_instrument_cache_timestamp = time.time()

    def _ensure_instrument_cache(self, *, api_key: Optional[str], force_refresh: bool) -> None:
        cache_stale = (time.time() - self._instrument_cache_timestamp) >= self._instrument_cache_ttl
        if force_refresh or not self._instrument_by_id or cache_stale:
            self._refresh_instrument_cache(api_key=api_key)

    def _ensure_global_instrument_cache(self, *, api_key: Optional[str], force_refresh: bool) -> None:
        cache_stale = (time.time() - self._global_instrument_cache_timestamp) >= self._instrument_cache_ttl
        if force_refresh or not self._global_instrument_by_id or cache_stale:
            self._refresh_global_instrument_cache(api_key=api_key)

    def _refresh_kpi_metadata(self, *, api_key: Optional[str]) -> None:
        payload = self._request("GET", "/v1/instruments/kpis/metadata", api_key=api_key)
        metadata: Iterable[Dict[str, Any]] = payload.get("kpiHistoryMetadatas") or []
        self._kpi_metadata = list(metadata)
        self._kpi_metadata_timestamp = time.time()

    def _ensure_kpi_metadata(self, *, api_key: Optional[str], force_refresh: bool) -> None:
        cache_stale = (time.time() - self._kpi_metadata_timestamp) >= self._metadata_cache_ttl
        if force_refresh or not self._kpi_metadata or cache_stale:
            self._refresh_kpi_metadata(api_key=api_key)

    def _iter_chunks(self, values: Iterable[int], chunk_size: int = 50) -> Iterable[list[int]]:
        chunk: list[int] = []
        for value in values:
            chunk.append(int(value))
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_instruments(self, *, api_key: Optional[str] = None, force_refresh: bool = False) -> list[Dict[str, Any]]:
        self._ensure_instrument_cache(api_key=api_key, force_refresh=force_refresh)
        return list(self._instrument_by_id.values())

    def get_all_instruments(self, *, api_key: Optional[str] = None, force_refresh: bool = False) -> list[Dict[str, Any]]:
        self._ensure_instrument_cache(api_key=api_key, force_refresh=force_refresh)
        self._ensure_global_instrument_cache(api_key=api_key, force_refresh=force_refresh)
        return list(self._instrument_by_id.values()) + list(self._global_instrument_by_id.values())

    def get_instrument(self, ticker: str, *, api_key: Optional[str] = None, force_refresh: bool = False, use_global: bool = False) -> Dict[str, Any]:
        if not ticker:
            raise BorsdataAPIError("Ticker symbol is required")

        normalised = ticker.strip().upper()
        if not normalised:
            raise BorsdataAPIError("Ticker symbol is required")

        if use_global:
            self._ensure_global_instrument_cache(api_key=api_key, force_refresh=force_refresh)
            instrument = self._global_instrument_by_ticker.get(normalised)
            if instrument is None:
                # Some tickers may only be available after a fresh sync
                self._ensure_global_instrument_cache(api_key=api_key, force_refresh=True)
                instrument = self._global_instrument_by_ticker.get(normalised)

            if instrument is None:
                raise BorsdataAPIError(f"Ticker '{ticker}' not found in Börsdata global instruments")
        else:
            self._ensure_instrument_cache(api_key=api_key, force_refresh=force_refresh)
            instrument = self._instrument_by_ticker.get(normalised)
            if instrument is None:
                # Some tickers may only be available after a fresh sync
                self._ensure_instrument_cache(api_key=api_key, force_refresh=True)
                instrument = self._instrument_by_ticker.get(normalised)

            if instrument is None:
                raise BorsdataAPIError(f"Ticker '{ticker}' not found in Börsdata instruments")

        return instrument

    def get_kpi_metadata(self, *, api_key: Optional[str] = None, force_refresh: bool = False) -> list[Dict[str, Any]]:
        """Return cached KPI metadata."""
        self._ensure_kpi_metadata(api_key=api_key, force_refresh=force_refresh)
        return list(self._kpi_metadata)

    def get_kpi_summary(
        self,
        instrument_id: int,
        report_type: str,
        *,
        max_count: Optional[int] = None,
        original_currency: Optional[bool] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if max_count is not None:
            params["maxCount"] = max_count
        if original_currency is not None:
            params["original"] = 1 if original_currency else 0
        return self._request(
            "GET",
            f"/v1/instruments/{int(instrument_id)}/kpis/{report_type}/summary",
            params=params,
            api_key=api_key,
        )

    def get_kpi_history(
        self,
        instrument_id: int,
        kpi_id: int,
        report_type: str,
        price_type: str = "mean",
        *,
        max_count: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if max_count is not None:
            params["maxCount"] = max_count
        return self._request(
            "GET",
            f"/v1/instruments/{int(instrument_id)}/kpis/{int(kpi_id)}/{report_type}/{price_type}/history",
            params=params,
            api_key=api_key,
        )

    def get_kpi_screener_value(
        self,
        instrument_id: int,
        kpi_id: int,
        calc_group: str,
        calc: str,
        *,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/instruments/{int(instrument_id)}/kpis/{int(kpi_id)}/{calc_group}/{calc}",
            api_key=api_key,
        )

    def get_reports(
        self,
        instrument_id: int,
        report_type: str,
        *,
        max_count: Optional[int] = None,
        original_currency: Optional[bool] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if max_count is not None:
            params["maxCount"] = max_count
        if original_currency is not None:
            params["original"] = 1 if original_currency else 0
        return self._request(
            "GET",
            f"/v1/instruments/{int(instrument_id)}/reports/{report_type}",
            params=params,
            api_key=api_key,
        )

    def get_stock_prices(
        self,
        instrument_id: int,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_count: Optional[int] = None,
        original_currency: Optional[bool] = None,
        api_key: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date
        if max_count:
            params["maxCount"] = max_count
        if original_currency is not None:
            params["original"] = 1 if original_currency else 0

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
        use_global: bool = False,
    ) -> list[Dict[str, Any]]:
        instrument = self.get_instrument(ticker, api_key=api_key, use_global=use_global)
        return self.get_stock_prices(
            instrument_id=instrument["insId"],
            start_date=start_date,
            end_date=end_date,
            max_count=max_count,
            api_key=api_key,
        )

    def get_report_calendar(
        self,
        instrument_ids: Iterable[int],
        *,
        api_key: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        results: list[Dict[str, Any]] = []
        for batch in self._iter_chunks(instrument_ids, 50):
            params = {"instList": ",".join(str(int(ins_id)) for ins_id in batch)}
            payload = self._request(
                "GET",
                "/v1/instruments/report/calendar",
                params=params,
                api_key=api_key,
            )
            for company in payload.get("list") or []:
                company_values = company.get("values") or []
                for value in company_values:
                    enriched = dict(value)
                    enriched.setdefault("insId", company.get("insId"))
                    results.append(enriched)
        return results

    def get_dividend_calendar(
        self,
        instrument_ids: Iterable[int],
        *,
        api_key: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        results: list[Dict[str, Any]] = []
        for batch in self._iter_chunks(instrument_ids, 50):
            params = {"instList": ",".join(str(int(ins_id)) for ins_id in batch)}
            payload = self._request(
                "GET",
                "/v1/instruments/dividend/calendar",
                params=params,
                api_key=api_key,
            )
            for company in payload.get("list") or []:
                company_values = company.get("values") or []
                for value in company_values:
                    enriched = dict(value)
                    enriched.setdefault("insId", company.get("insId"))
                    results.append(enriched)
        return results

    def get_insider_holdings(
        self,
        instrument_ids: Iterable[int],
        *,
        api_key: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        results: list[Dict[str, Any]] = []
        for batch in self._iter_chunks(instrument_ids, 50):
            params = {"instList": ",".join(str(int(ins_id)) for ins_id in batch)}
            payload = self._request(
                "GET",
                "/v1/holdings/insider",
                params=params,
                api_key=api_key,
            )
            for company in payload.get("list") or []:
                company_values = company.get("values") or []
                for value in company_values:
                    enriched = dict(value)
                    enriched.setdefault("insId", company.get("insId"))
                    results.append(enriched)
        return results

    def get_kpi_holdings(
        self,
        instrument_id: int,
        kpi_id: int,
        *,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return KPI holdings data for an instrument."""
        return self._request(
            "GET",
            f"/v1/instruments/{instrument_id}/kpis/{kpi_id}/holdings",
            api_key=api_key,
        )

    def get_kpi_screener_history(
        self,
        instrument_id: int,
        kpi_id: int,
        *,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return historical screener data for a KPI."""
        return self._request(
            "GET",
            f"/v1/instruments/{instrument_id}/kpis/{kpi_id}/screener/history",
            api_key=api_key,
        )

    def get_kpi_all_instruments(
        self,
        kpi_id: int,
        calc_group: str,
        calc: str,
        *,
        use_global: bool = False,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return KPI values for all instruments (much more efficient than individual requests)."""
        endpoint = "/v1/instruments/global/kpis" if use_global else "/v1/instruments/kpis"
        return self._request(
            "GET",
            f"{endpoint}/{kpi_id}/{calc_group}/{calc}",
            api_key=api_key,
        )

    @property
    def api_key(self) -> Optional[str]:
        """Expose the explicitly configured API key (if any)."""
        return self._explicit_api_key


__all__ = ["BorsdataAPIError", "BorsdataClient", "RateLimiter"]
