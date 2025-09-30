"""
Parallel API wrapper for existing Börsdata functions.

This module provides JavaScript Promise-like parallel execution for the existing
get_prices, get_financial_metrics, etc. functions. It respects the 100 calls/10 seconds
rate limit and can burst up to 90+ calls efficiently.

Key Features:
- Works with existing tested API functions
- Proper Nordic/Global market handling
- Thread pool parallelization for blocking I/O
- Rate limiting awareness (though the underlying client handles this)
- Easy drop-in replacement for sequential calls

Usage Examples:

    # Basic parallel fetching
    data = await parallel_fetch_ticker_data(
        ["AAPL", "MSFT", "ERIC B"],
        end_date="2025-09-29"
    )

    # Synchronous wrapper
    data = run_parallel_fetch_ticker_data(
        ["AAPL", "MSFT", "ERIC B"],
        end_date="2025-09-29"
    )

    # Burst price fetching only
    prices = await parallel_fetch_prices(
        ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA"],
        start_date="2025-09-01",
        end_date="2025-09-29"
    )
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Dict, List, Optional, Any, Union
import time

# Import existing working API functions
from src.tools.api import (
    get_prices,
    get_financial_metrics,
    get_insider_trades,
    get_company_events,
    get_market_cap,
    set_ticker_markets,
    search_line_items,
)
from src.utils.logger import vprint
from src.utils.progress import progress


async def _run_in_thread_pool(func, *args, **kwargs):
    """Run a blocking function in a thread pool."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=20) as executor:
        partial_func = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, partial_func)


async def _timed_run_in_thread_pool(func, data_type, *args, **kwargs):
    """Run a blocking function in a thread pool and log its execution time."""
    ticker = args[0]
    start_time = time.time()
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=20) as executor:
        partial_func = partial(func, *args, **kwargs)
        result = await loop.run_in_executor(executor, partial_func)
    end_time = time.time()
    duration = end_time - start_time
    
    # The result can be an exception if gather(return_exceptions=True) is used
    if isinstance(result, Exception):
        vprint(f"  - [ ERROR ] Fetched {data_type:<15} for {ticker}: {type(result).__name__}")
    else:
        vprint(f"  - [{duration:5.2f}s] Fetched {data_type:<15} for {ticker}")
    return result



async def parallel_fetch_prices(
    tickers: List[str],
    start_date: str,
    end_date: str,
    *,
    ticker_markets: Dict[str, str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, List]:
    """
    Fetch stock prices for multiple tickers in parallel.

    Args:
        tickers: List of ticker symbols
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        ticker_markets: Optional dictionary mapping tickers to markets
        api_key: Optional API key override

    Returns:
        Dict mapping ticker -> list of Price objects
    """
    set_ticker_markets(ticker_markets or {})

    tasks = []
    for ticker in tickers:
        tasks.append(
            _run_in_thread_pool(get_prices, ticker, start_date, end_date, api_key)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        ticker: result if not isinstance(result, Exception) else []
        for ticker, result in zip(tickers, results)
    }


async def parallel_fetch_financial_metrics(
    tickers: List[str],
    end_date: str,
    *,
    period: str = "ttm",
    limit: int = 1,
    ticker_markets: Dict[str, str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, List]:
    """
    Fetch financial metrics for multiple tickers in parallel.

    Args:
        tickers: List of ticker symbols
        end_date: End date (YYYY-MM-DD)
        period: Period ("ttm", "year", etc.)
        limit: Number of periods to fetch
        ticker_markets: Optional dictionary mapping tickers to markets
        api_key: Optional API key override

    Returns:
        Dict mapping ticker -> list of FinancialMetrics objects
    """
    set_ticker_markets(ticker_markets or {})

    tasks = []
    for ticker in tickers:
        tasks.append(
            _run_in_thread_pool(get_financial_metrics, ticker, end_date, period, limit, api_key)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        ticker: result if not isinstance(result, Exception) else []
        for ticker, result in zip(tickers, results)
    }


async def parallel_fetch_insider_trades(
    tickers: List[str],
    end_date: str,
    *,
    start_date: Optional[str] = None,
    limit: int = 1000,
    ticker_markets: Dict[str, str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, List]:
    """
    Fetch insider trades for multiple tickers in parallel.

    Args:
        tickers: List of ticker symbols
        end_date: End date (YYYY-MM-DD)
        start_date: Optional start date (YYYY-MM-DD)
        limit: Maximum number of trades per ticker
        ticker_markets: Optional dictionary mapping tickers to markets
        api_key: Optional API key override

    Returns:
        Dict mapping ticker -> list of InsiderTrade objects
    """
    set_ticker_markets(ticker_markets or {})

    tasks = []
    for ticker in tickers:
        tasks.append(
            _run_in_thread_pool(get_insider_trades, ticker, end_date, start_date, limit, api_key)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        ticker: result if not isinstance(result, Exception) else []
        for ticker, result in zip(tickers, results)
    }


async def parallel_fetch_company_events(
    tickers: List[str],
    end_date: str,
    *,
    start_date: Optional[str] = None,
    limit: int = 1000,
    ticker_markets: Dict[str, str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, List]:
    """
    Fetch company events for multiple tickers in parallel.

    Args:
        tickers: List of ticker symbols
        end_date: End date (YYYY-MM-DD)
        start_date: Optional start date (YYYY-MM-DD)
        limit: Maximum number of events per ticker
        ticker_markets: Optional dictionary mapping tickers to markets
        api_key: Optional API key override

    Returns:
        Dict mapping ticker -> list of CompanyEvent objects
    """
    set_ticker_markets(ticker_markets or {})

    tasks = []
    for ticker in tickers:
        tasks.append(
            _run_in_thread_pool(get_company_events, ticker, end_date, start_date, limit, api_key)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        ticker: result if not isinstance(result, Exception) else []
        for ticker, result in zip(tickers, results)
    }


async def parallel_fetch_market_caps(
    tickers: List[str],
    end_date: str,
    *,
    ticker_markets: Dict[str, str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """
    Fetch market caps for multiple tickers in parallel.

    Args:
        tickers: List of ticker symbols
        end_date: End date (YYYY-MM-DD)
        ticker_markets: Optional dictionary mapping tickers to markets
        api_key: Optional API key override

    Returns:
        Dict mapping ticker -> market cap (float or None)
    """
    set_ticker_markets(ticker_markets or {})

    tasks = []
    for ticker in tickers:
        tasks.append(
            _run_in_thread_pool(get_market_cap, ticker, end_date, api_key)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        ticker: result if not isinstance(result, Exception) else None
        for ticker, result in zip(tickers, results)
    }


async def parallel_fetch_ticker_data(
    tickers: List[str],
    end_date: str,
    *,
    start_date: Optional[str] = None,
    include_prices: bool = True,
    include_metrics: bool = True,
    include_line_items: bool = True,
    include_insider_trades: bool = True,
    include_events: bool = True,
    include_market_caps: bool = True,
    ticker_markets: Dict[str, str] = None,
    price_days: int = 30,
    api_key: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch comprehensive data for multiple tickers in parallel.

    This is the main function for comprehensive parallel data fetching.
    It creates multiple API calls per ticker and executes them all in parallel
    to maximize the 100 calls/10 seconds rate limit.

    Args:
        tickers: List of ticker symbols
        end_date: End date (YYYY-MM-DD)
        start_date: Start date for prices/events (defaults to price_days before end_date)
        include_prices: Whether to fetch stock prices
        include_metrics: Whether to fetch financial metrics
        include_insider_trades: Whether to fetch insider trades
        include_events: Whether to fetch company events
        include_market_caps: Whether to fetch market caps
        ticker_markets: Optional dictionary mapping tickers to markets
        price_days: Number of days back to fetch prices (if start_date not provided)
        api_key: Optional API key override

    Returns:
        Dict mapping ticker -> {prices, metrics, insider_trades, events, market_cap}
    """

    # Auto-calculate start_date if not provided
    if start_date is None and include_prices:
        import datetime
        end_dt = datetime.datetime.fromisoformat(end_date).date()
        start_dt = end_dt - datetime.timedelta(days=price_days)
        start_date = start_dt.isoformat()

    set_ticker_markets(ticker_markets or {})

    # Create all parallel tasks
    tasks = []
    task_mapping = []  # Track which task corresponds to which ticker and data type

    for ticker in tickers:
        if include_prices and start_date:
            tasks.append(_timed_run_in_thread_pool(get_prices, "prices", ticker, start_date, end_date, api_key))
            task_mapping.append((ticker, "prices"))

        if include_metrics:
            tasks.append(_timed_run_in_thread_pool(get_financial_metrics, "metrics", ticker, end_date, "ttm", 1, api_key))
            task_mapping.append((ticker, "metrics"))

        if include_line_items:
            tasks.append(_timed_run_in_thread_pool(search_line_items, "line_items", ticker, [
                "capital_expenditure", "depreciation_and_amortization", "net_income",
                "outstanding_shares", "total_assets", "total_liabilities",
                "shareholders_equity", "dividends_and_other_cash_distributions",
                "issuance_or_purchase_of_equity_shares", "gross_profit", "revenue",
                "free_cash_flow", "current_assets", "current_liabilities",
            ], end_date, "ttm", 10, api_key))
            task_mapping.append((ticker, "line_items"))

        if include_insider_trades:
            tasks.append(_timed_run_in_thread_pool(get_insider_trades, "insider_trades", ticker, end_date, start_date, 1000, api_key))
            task_mapping.append((ticker, "insider_trades"))

        if include_events:
            tasks.append(_timed_run_in_thread_pool(get_company_events, "events", ticker, end_date, start_date, 1000, api_key))
            task_mapping.append((ticker, "events"))

        # DO NOT include market_caps here, it will be derived from metrics

    # Execute all tasks in parallel
    vprint(f"⚡ Executing {len(tasks)} parallel API calls for {len(tickers)} tickers...")
    start_time = time.time()

    # Initialize progress for prefetching
    total_tasks = len(tasks)
    completed_tasks = 0

    # Update progress as tasks complete
    async def task_wrapper(ticker, data_type, coro):
        nonlocal completed_tasks
        try:
            result = await coro
            return (ticker, data_type, result)
        finally:
            completed_tasks += 1
            if progress_callback:
                progress_callback(completed_tasks, total_tasks, ticker)
            else:
                progress.update_prefetch_status(completed_tasks, total_tasks, ticker)

    # Wrap tasks for progress tracking
    progress_wrapped_tasks = []
    for i, task in enumerate(tasks):
        ticker, data_type = task_mapping[i]
        progress_wrapped_tasks.append(task_wrapper(ticker, data_type, task))

    results_with_info = await asyncio.gather(*progress_wrapped_tasks, return_exceptions=True)

    end_time = time.time()
    vprint(f"✅ Total parallel fetch completed in {end_time - start_time:.2f} seconds")

    # Organize results by ticker
    ticker_data = {ticker: {} for ticker in tickers}

    for item in results_with_info:
        if isinstance(item, Exception):
            # This case might be complex to handle if we don't know which task failed.
            # For now, we log a general error.
            vprint(f"⚠️  An error occurred during parallel fetching: {item}")
            continue
        
        ticker, data_type, result = item
        if isinstance(result, Exception):
            vprint(f"⚠️  Error fetching {data_type} for {ticker}: {result}")
            ticker_data[ticker][data_type] = []
        else:
            ticker_data[ticker][data_type] = result

    # Post-process to extract market_cap from metrics if requested
    if include_market_caps:
        for ticker in tickers:
            # Ensure metrics data exists and is not empty
            if ticker_data.get(ticker) and ticker_data[ticker].get("metrics"):
                first_metric = ticker_data[ticker]["metrics"][0]
                # It could be a Pydantic model or a dict, handle both
                if hasattr(first_metric, 'market_cap'):
                    ticker_data[ticker]["market_cap"] = first_metric.market_cap
                elif isinstance(first_metric, dict) and 'market_cap' in first_metric:
                    ticker_data[ticker]["market_cap"] = first_metric['market_cap']
                else:
                    ticker_data[ticker]["market_cap"] = None
            elif ticker_data.get(ticker):
                 ticker_data[ticker]["market_cap"] = None
            # If ticker is not in ticker_data, something went very wrong before, but we avoid a crash

    return ticker_data


# Synchronous wrappers for easy integration

def run_parallel_fetch_prices(tickers: List[str], start_date: str, end_date: str, **kwargs) -> Dict[str, List]:
    """Synchronous wrapper for parallel_fetch_prices."""
    return asyncio.run(parallel_fetch_prices(tickers, start_date, end_date, **kwargs))


def run_parallel_fetch_financial_metrics(tickers: List[str], end_date: str, **kwargs) -> Dict[str, List]:
    """Synchronous wrapper for parallel_fetch_financial_metrics."""
    return asyncio.run(parallel_fetch_financial_metrics(tickers, end_date, **kwargs))


def run_parallel_fetch_insider_trades(tickers: List[str], end_date: str, **kwargs) -> Dict[str, List]:
    """Synchronous wrapper for parallel_fetch_insider_trades."""
    return asyncio.run(parallel_fetch_insider_trades(tickers, end_date, **kwargs))


def run_parallel_fetch_company_events(tickers: List[str], end_date: str, **kwargs) -> Dict[str, List]:
    """Synchronous wrapper for parallel_fetch_company_events."""
    return asyncio.run(parallel_fetch_company_events(tickers, end_date, **kwargs))


def run_parallel_fetch_market_caps(tickers: List[str], end_date: str, **kwargs) -> Dict[str, Optional[float]]:
    """Synchronous wrapper for parallel_fetch_market_caps."""
    return asyncio.run(parallel_fetch_market_caps(tickers, end_date, **kwargs))


def run_parallel_fetch_ticker_data(tickers: List[str], end_date: str, progress_callback: Optional[callable] = None, **kwargs) -> Dict[str, Dict[str, Any]]:
    """
    Synchronous wrapper for parallel_fetch_ticker_data.

    This is the main function to use for comprehensive parallel data fetching.

    Example:
        data = run_parallel_fetch_ticker_data(
            ["AAPL", "MSFT", "ERIC B"],
            end_date="2025-09-29",
            price_days=30,
            include_line_items=True
        )

        # Access data like:
        # data["AAPL"]["prices"]  # List of Price objects
        # data["MSFT"]["metrics"]  # List of FinancialMetrics objects
        # data["ERIC B"]["insider_trades"]  # List of InsiderTrade objects
    """
    return asyncio.run(parallel_fetch_ticker_data(tickers, end_date, progress_callback=progress_callback, **kwargs))


__all__ = [
    "parallel_fetch_prices",
    "parallel_fetch_financial_metrics",
    "parallel_fetch_insider_trades",
    "parallel_fetch_company_events",
    "parallel_fetch_market_caps",
    "parallel_fetch_ticker_data",
    "run_parallel_fetch_prices",
    "run_parallel_fetch_financial_metrics",
    "run_parallel_fetch_insider_trades",
    "run_parallel_fetch_company_events",
    "run_parallel_fetch_market_caps",
    "run_parallel_fetch_ticker_data",
]