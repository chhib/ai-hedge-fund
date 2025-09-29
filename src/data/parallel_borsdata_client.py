"""
Parallel Börsdata API client using asyncio for high-throughput data fetching.

This client enables burst requests up to the 100 calls/10 seconds limit with
JavaScript Promise-like parallel execution patterns. Particularly useful for
prefetching data across multiple tickers efficiently.

Usage Example:
    # Burst fetch data for multiple tickers
    async def fetch_all_data():
        client = ParallelBorsdataClient()
        tickers = ["AAPL", "MSFT", "NVDA"]

        # Create parallel tasks - like Promise.all() in JavaScript
        tasks = []
        for ticker in tickers:
            tasks.extend([
                client.get_stock_prices_by_ticker(ticker),
                client.get_financial_metrics(ticker),
                client.get_insider_trades(ticker)
            ])

        # Execute all tasks in parallel (up to rate limit)
        results = await asyncio.gather(*tasks)
        return results

    # Run the parallel fetch
    results = asyncio.run(fetch_all_data())
"""

import asyncio
import os
import time
from collections import deque
from typing import Any, Dict, List, Optional, Iterable, Union
from dataclasses import dataclass
import aiohttp
import json


class ParallelBorsdataAPIError(RuntimeError):
    """Raised when the Börsdata API returns an error response."""


@dataclass
class APICall:
    """Represents a single API call to be executed."""
    method: str
    path: str
    params: Optional[Dict[str, Any]] = None
    json_data: Optional[Dict[str, Any]] = None
    ticker: Optional[str] = None  # For tracking which ticker this call belongs to


class AsyncRateLimiter:
    """
    Async rate limiter that enforces Börsdata's 100 calls/10 seconds limit.
    Uses a token bucket approach with asyncio locks for thread safety.
    """

    def __init__(self, max_calls: int = 95, period_seconds: float = 10.0):
        # Use 95 instead of 100 to leave some buffer
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until the caller is permitted to proceed."""
        while True:
            async with self._lock:
                now = time.monotonic()

                # Remove timestamps outside the window
                while self._timestamps and now - self._timestamps[0] >= self.period_seconds:
                    self._timestamps.popleft()

                # If we have capacity, allow the request
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return

                # Calculate wait time
                oldest = self._timestamps[0]
                wait_time = max(0.0, self.period_seconds - (now - oldest))

            # Sleep outside the lock
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(0.01)  # Small yield


class ParallelBorsdataClient:
    """
    Async Börsdata client for parallel API calls with rate limiting.

    This client provides JavaScript Promise-like functionality for Python,
    allowing efficient burst fetching up to the API rate limits.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = "https://apiservice.borsdata.se",
        max_concurrent: int = 20,  # Concurrent connection limit
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self._explicit_api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_concurrent = max_concurrent
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.rate_limiter = AsyncRateLimiter()

        # Cache for instruments
        self._instrument_cache: Dict[str, Dict[str, Any]] = {}
        self._global_instrument_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp = 0
        self._cache_ttl = 6 * 60 * 60  # 6 hours

        # Session management
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

    def _resolve_api_key(self, override: Optional[str] = None) -> str:
        """Resolve API key from parameter, instance, or environment."""
        api_key = override or self._explicit_api_key or os.environ.get("BORSDATA_API_KEY")
        if not api_key:
            raise ParallelBorsdataAPIError(
                "Missing Börsdata API key. Set BORSDATA_API_KEY or pass api_key explicitly."
            )
        return api_key

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(limit=self.max_concurrent)
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=self.timeout
            )

    async def close(self):
        """Close the aiohttp session and connector."""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._connector:
            await self._connector.close()

    async def _make_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make a single API request with retries and rate limiting."""
        await self._ensure_session()

        url = f"{self.base_url}{path}"
        query_params = dict(params or {})
        query_params["authKey"] = self._resolve_api_key(api_key)

        for attempt in range(self.max_retries + 1):
            # Wait for rate limiter
            await self.rate_limiter.acquire()

            try:
                kwargs = {"params": query_params}
                if json_data:
                    kwargs["json"] = json_data

                async with self._session.request(
                    method.upper(),
                    url,
                    **kwargs
                ) as response:

                    # Handle rate limiting
                    if response.status == 429 and attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After", "10")
                        try:
                            wait_time = float(retry_after)
                        except ValueError:
                            wait_time = 10.0
                        await asyncio.sleep(max(wait_time, 0))
                        continue

                    # Handle other errors
                    if response.status >= 400:
                        error_text = await response.text()
                        raise ParallelBorsdataAPIError(
                            f"Börsdata API error {response.status} for {path}: {error_text}"
                        )

                    # Parse JSON response
                    try:
                        return await response.json()
                    except Exception as exc:
                        raise ParallelBorsdataAPIError(
                            f"Failed to decode JSON for {path}"
                        ) from exc

            except aiohttp.ClientError as exc:
                if attempt == self.max_retries:
                    raise ParallelBorsdataAPIError(f"Request failed for {path}") from exc
                await asyncio.sleep(1.0 * (attempt + 1))  # Exponential backoff

        raise ParallelBorsdataAPIError(f"Exceeded retry budget for {path}")

    async def _ensure_instrument_cache(self, use_global: bool = False):
        """Ensure instrument cache is populated and fresh."""
        now = time.time()
        cache_key = "global" if use_global else "nordic"

        if (
            now - self._cache_timestamp > self._cache_ttl
            or not getattr(self, f"_{cache_key}_instrument_cache", {})
        ):
            endpoint = "/v1/instruments/global" if use_global else "/v1/instruments"
            payload = await self._make_request("GET", endpoint)
            instruments = payload.get("instruments", [])

            cache = {}
            for instrument in instruments:
                ticker = instrument.get("ticker", "").upper()
                yahoo = instrument.get("yahoo", "").upper()
                if ticker:
                    cache[ticker] = instrument
                if yahoo and yahoo != ticker:
                    cache[yahoo] = instrument

            if use_global:
                self._global_instrument_cache = cache
            else:
                self._instrument_cache = cache

            self._cache_timestamp = now

    async def get_instrument(self, ticker: str, use_global: bool = False) -> Dict[str, Any]:
        """Get instrument data for a ticker."""
        await self._ensure_instrument_cache(use_global)

        ticker_upper = ticker.upper()
        cache = self._global_instrument_cache if use_global else self._instrument_cache

        instrument = cache.get(ticker_upper)
        if not instrument:
            raise ParallelBorsdataAPIError(f"Ticker '{ticker}' not found in {'global' if use_global else 'nordic'} instruments")

        return instrument

    # High-level methods that use the same interface as the sync client

    async def get_stock_prices_by_ticker(
        self,
        ticker: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_count: Optional[int] = None,
        use_global: bool = False,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get stock prices for a ticker."""
        instrument = await self.get_instrument(ticker, use_global=use_global)
        instrument_id = instrument["insId"]

        params = {}
        if start_date:
            params["from"] = start_date
        if end_date:
            params["to"] = end_date
        if max_count:
            params["maxCount"] = max_count

        payload = await self._make_request(
            "GET",
            f"/v1/instruments/{instrument_id}/stockprices",
            params=params,
            api_key=api_key,
        )
        return payload.get("stockPricesList", [])

    async def get_insider_trades(
        self,
        tickers: Union[str, List[str]],
        *,
        use_global: bool = False,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get insider trading data for one or multiple tickers."""
        if isinstance(tickers, str):
            tickers = [tickers]

        # Get instrument IDs for all tickers
        instrument_tasks = [
            self.get_instrument(ticker, use_global=use_global)
            for ticker in tickers
        ]
        instruments = await asyncio.gather(*instrument_tasks)
        instrument_ids = [inst["insId"] for inst in instruments]

        # Batch API call for insider holdings
        params = {"instList": ",".join(str(id_) for id_ in instrument_ids)}
        payload = await self._make_request(
            "GET",
            "/v1/holdings/insider",
            params=params,
            api_key=api_key,
        )

        results = []
        for company in payload.get("list", []):
            for value in company.get("values", []):
                enriched = dict(value)
                enriched.setdefault("insId", company.get("insId"))
                results.append(enriched)

        return results

    async def get_company_events(
        self,
        tickers: Union[str, List[str]],
        *,
        use_global: bool = False,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get company events (reports + dividends) for tickers."""
        if isinstance(tickers, str):
            tickers = [tickers]

        # Get instrument IDs
        instrument_tasks = [
            self.get_instrument(ticker, use_global=use_global)
            for ticker in tickers
        ]
        instruments = await asyncio.gather(*instrument_tasks)
        instrument_ids = [inst["insId"] for inst in instruments]

        # Fetch both report and dividend calendars in parallel
        reports_task = self._get_calendar_data("/v1/instruments/report/calendar", instrument_ids, api_key)
        dividends_task = self._get_calendar_data("/v1/instruments/dividend/calendar", instrument_ids, api_key)

        reports, dividends = await asyncio.gather(reports_task, dividends_task)

        # Combine and return
        return reports + dividends

    async def _get_calendar_data(
        self,
        endpoint: str,
        instrument_ids: List[int],
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Helper to fetch calendar data with batching."""
        results = []

        # Batch instrument IDs (50 per request)
        batch_size = 50
        tasks = []

        for i in range(0, len(instrument_ids), batch_size):
            batch = instrument_ids[i:i + batch_size]
            params = {"instList": ",".join(str(id_) for id_ in batch)}
            tasks.append(self._make_request("GET", endpoint, params=params, api_key=api_key))

        # Execute all batches in parallel
        batch_results = await asyncio.gather(*tasks)

        # Process results
        for payload in batch_results:
            for company in payload.get("list", []):
                for value in company.get("values", []):
                    enriched = dict(value)
                    enriched.setdefault("insId", company.get("insId"))
                    results.append(enriched)

        return results

    # Convenience methods for burst fetching multiple tickers

    async def bulk_fetch_ticker_data(
        self,
        tickers: List[str],
        *,
        include_prices: bool = True,
        include_metrics: bool = True,
        include_insider_trades: bool = True,
        include_events: bool = True,
        price_params: Optional[Dict[str, Any]] = None,
        use_global: bool = False,
        api_key: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch all data for multiple tickers in parallel.

        This is the main method for burst fetching - creates up to 90+ parallel
        requests to maximize the 100 calls/10 seconds rate limit.

        Returns:
            Dict mapping ticker -> {prices, metrics, insider_trades, events}
        """
        tasks = []
        task_mapping = []  # Track which task corresponds to which ticker/data type

        # Create individual tasks for each ticker and data type
        for ticker in tickers:
            if include_prices:
                params = price_params or {}
                tasks.append(
                    self.get_stock_prices_by_ticker(
                        ticker, use_global=use_global, api_key=api_key, **params
                    )
                )
                task_mapping.append((ticker, "prices"))

            if include_metrics:
                tasks.append(
                    self.get_financial_metrics(ticker, use_global=use_global, api_key=api_key)
                )
                task_mapping.append((ticker, "metrics"))

        # Batch the multi-ticker calls (more efficient)
        if include_insider_trades:
            tasks.append(
                self.get_insider_trades(tickers, use_global=use_global, api_key=api_key)
            )
            task_mapping.append(("ALL", "insider_trades"))

        if include_events:
            tasks.append(
                self.get_company_events(tickers, use_global=use_global, api_key=api_key)
            )
            task_mapping.append(("ALL", "events"))

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Organize results by ticker
        ticker_data = {ticker: {} for ticker in tickers}

        for (ticker, data_type), result in zip(task_mapping, results):
            if isinstance(result, Exception):
                print(f"Error fetching {data_type} for {ticker}: {result}")
                continue

            if ticker == "ALL":
                # Distribute multi-ticker results
                if data_type == "insider_trades":
                    # Group by insId/ticker
                    for ticker_name in tickers:
                        ticker_data[ticker_name][data_type] = []

                    # Distribute results based on instrument ID
                    instrument_cache = self._global_instrument_cache if use_global else self._instrument_cache
                    for item in result:
                        ins_id = item.get("insId")
                        # Find which ticker this belongs to
                        for ticker_name in tickers:
                            if ticker_name.upper() in instrument_cache:
                                if instrument_cache[ticker_name.upper()].get("insId") == ins_id:
                                    ticker_data[ticker_name][data_type].append(item)
                                    break

                elif data_type == "events":
                    # Similar distribution for events
                    for ticker_name in tickers:
                        ticker_data[ticker_name][data_type] = []

                    instrument_cache = self._global_instrument_cache if use_global else self._instrument_cache
                    for item in result:
                        ins_id = item.get("insId")
                        for ticker_name in tickers:
                            if ticker_name.upper() in instrument_cache:
                                if instrument_cache[ticker_name.upper()].get("insId") == ins_id:
                                    ticker_data[ticker_name][data_type].append(item)
                                    break
            else:
                ticker_data[ticker][data_type] = result

        return ticker_data


# Convenience functions for easy usage

async def parallel_fetch_multiple_tickers(
    tickers: List[str],
    *,
    include_prices: bool = True,
    include_metrics: bool = True,
    include_insider_trades: bool = True,
    include_events: bool = True,
    use_global: bool = False,
    api_key: Optional[str] = None,
    price_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Convenience function for parallel fetching.

    Example usage:
        data = await parallel_fetch_multiple_tickers(
            ["AAPL", "MSFT", "NVDA"],
            use_global=True,
            price_params={"max_count": 30}
        )

        # Access data like:
        # data["AAPL"]["prices"]
        # data["MSFT"]["metrics"]
        # etc.
    """
    async with ParallelBorsdataClient(api_key=api_key) as client:
        return await client.bulk_fetch_ticker_data(
            tickers,
            include_prices=include_prices,
            include_metrics=include_metrics,
            include_insider_trades=include_insider_trades,
            include_events=include_events,
            use_global=use_global,
            api_key=api_key,
            price_params=price_params,
        )


def run_parallel_fetch(
    tickers: List[str],
    **kwargs
) -> Dict[str, Dict[str, Any]]:
    """
    Synchronous wrapper for the async parallel fetch.

    Example:
        data = run_parallel_fetch(["AAPL", "MSFT", "NVDA"], use_global=True)
    """
    return asyncio.run(parallel_fetch_multiple_tickers(tickers, **kwargs))


__all__ = [
    "ParallelBorsdataClient",
    "ParallelBorsdataAPIError",
    "parallel_fetch_multiple_tickers",
    "run_parallel_fetch",
]