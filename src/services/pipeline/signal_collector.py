"""Signal collection: parallel analyst execution with caching and Decision DB writes.

This module extracts the _collect_analyst_signals() logic from
EnhancedPortfolioManager into a reusable function. The heavy infrastructure
(ThreadPoolExecutor, caching, progress tracking, Decision DB eager writes)
is preserved exactly.
"""

import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agents.enhanced_portfolio_manager import AnalystSignal


@dataclass
class SignalCollectionConfig:
    """All parameters needed to collect analyst signals."""

    analysts: List[Dict[str, Any]]
    universe: List[str]
    model_config: Dict[str, Any]
    ticker_markets: Dict[str, str]
    home_currency: str
    no_cache: bool
    no_cache_agents: bool
    verbose: bool
    session_id: Optional[str]
    max_workers: int
    analysis_date: str
    portfolio_position_dates: Dict[str, Optional[str]] = field(default_factory=dict)


def collect_signals(
    config: SignalCollectionConfig,
    analysis_cache: Any,
    task_queue: Any,
    prefetch_fn: Callable[..., Dict[str, Dict[str, Any]]],
    fetch_exchange_rates_fn: Callable[[], None],
    extract_close_price_fn: Callable[[str], tuple],
) -> tuple[List[AnalystSignal], Dict[str, Dict[str, Any]]]:
    """Collect signals from all analysts for all tickers.

    Returns (signals, prefetched_data).

    This function preserves the exact behavior of
    EnhancedPortfolioManager._collect_analyst_signals(), including:
    - Pre-populating instrument caches
    - Parallel data prefetching
    - Batch cache resolution
    - ThreadPoolExecutor with 120s timeout (Session 55 fix)
    - Decision DB eager writes
    - Progress tracking
    """
    from src.data.decision_store import get_decision_store
    from src.graph.state import AgentState
    from src.utils.progress import progress

    signals: List[AnalystSignal] = []

    if not config.analysts:
        if config.verbose:
            print("Warning: No analysts initialized")
        return signals, {}

    api_key = os.getenv("BORSDATA_API_KEY")
    if not api_key:
        if config.verbose:
            print("Warning: BORSDATA_API_KEY not found - using neutral signals")
        return signals, {}

    # STEP 1: Pre-populate instrument caches
    from src.tools.api import _borsdata_client, set_ticker_markets

    force_refresh = config.no_cache
    if config.verbose:
        if force_refresh:
            print("Pre-populating instrument caches (bypassing cache)...")
        elif config.no_cache_agents:
            print("Pre-populating instrument caches (reusing cached data)...")
        else:
            print("Pre-populating instrument caches...")
    try:
        _borsdata_client.get_instruments(force_refresh=force_refresh)
        if config.verbose:
            print("✓ Nordic instruments cache populated")
        _borsdata_client.get_all_instruments(force_refresh=force_refresh)
        if config.verbose:
            print("✓ Global instruments cache populated")
    except Exception as e:
        if config.verbose:
            print(f"⚠️  Warning: Could not pre-populate instrument caches: {e}")

    # STEP 2: Set ticker market routing
    set_ticker_markets(config.ticker_markets)

    # STEP 3: Parallel data prefetching
    from datetime import datetime

    end_date = config.analysis_date
    start_date = (datetime.now().replace(year=datetime.now().year - 1)).strftime("%Y-%m-%d")

    progress.start()

    prefetched_data = prefetch_fn(
        tickers=config.universe,
        end_date=end_date,
        start_date=start_date,
    )

    progress.stop()

    # STEP 3.5: Fetch exchange rates
    fetch_exchange_rates_fn()

    # Initialize progress tracking
    agent_names = [f"{a['name']}_agent" for a in config.analysts]
    progress.initialize_agents(agent_names, len(config.universe))
    progress.start()

    allow_cache = not config.no_cache and not config.no_cache_agents
    configured_model_name = config.model_config.get("name")
    configured_model_provider = config.model_config.get("provider")

    # ── Fast path: resolve cache hits in bulk ──
    cache_batches: dict[tuple[str, str], dict[tuple[str, str], object]] = {}
    if allow_cache:
        seen_model_keys: set[tuple[str, str]] = set()
        for analyst_info in config.analysts:
            uses_llm = analyst_info.get("uses_llm", True)
            if uses_llm:
                mk = (configured_model_name or "unknown", configured_model_provider or "unknown")
            else:
                mk = ("deterministic", "deterministic")
            if mk not in seen_model_keys:
                seen_model_keys.add(mk)
                cache_batches[mk] = analysis_cache.load_batch(
                    analysis_date=end_date,
                    model_name=mk[0],
                    model_provider=mk[1],
                )

    uncached_combos = []
    from src.data.analyst_task_queue import TaskKey

    cached_queue_keys: list[TaskKey] = []
    cached_session_rows: list[dict] = []
    cached_count = 0

    for ticker_idx, ticker in enumerate(config.universe):
        for analyst_info in config.analysts:
            analyst_name = analyst_info["name"]
            uses_llm = analyst_info.get("uses_llm", True)
            if uses_llm:
                cache_model_name = configured_model_name or "unknown"
                cache_model_provider = configured_model_provider or "unknown"
                storage_model_name = configured_model_name
                storage_model_provider = configured_model_provider
            else:
                cache_model_name = "deterministic"
                cache_model_provider = "deterministic"
                storage_model_name = None
                storage_model_provider = None

            if not allow_cache:
                uncached_combos.append((analyst_info, ticker_idx, ticker))
                continue

            batch = cache_batches.get((cache_model_name, cache_model_provider), {})
            cached = batch.get((ticker.upper(), analyst_name))

            if not cached:
                uncached_combos.append((analyst_info, ticker_idx, ticker))
                continue

            # Cache hit
            signal_str = cached.signal
            numeric_signal = cached.signal_numeric
            confidence = cached.confidence
            reasoning = cached.reasoning or "Cached analysis"

            signals.append(AnalystSignal(
                ticker=ticker,
                analyst=analyst_name,
                signal=numeric_signal,
                confidence=confidence,
                reasoning=reasoning,
            ))

            cached_queue_keys.append(TaskKey(
                analysis_date=end_date,
                ticker=ticker.upper(),
                analyst_name=analyst_name,
                model_name=cache_model_name,
                model_provider=cache_model_provider,
            ))

            if config.session_id:
                cached_session_rows.append({
                    "session_id": config.session_id,
                    "ticker": ticker,
                    "analyst_name": analyst_name,
                    "signal": signal_str,
                    "signal_numeric": numeric_signal,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "model_name": storage_model_name if uses_llm else None,
                    "model_provider": storage_model_provider if uses_llm else None,
                })

            cached_count += 1
            if cached_count % 50 == 0 or cached_count == 1:
                agent_id = f"{analyst_name}_agent"
                next_ticker = config.universe[ticker_idx + 1] if ticker_idx + 1 < len(config.universe) else None
                progress.update_status(agent_id, ticker, f"Done (cached, {cached_count} resolved)", next_ticker=next_ticker)

    # Batch DB operations for cache hits
    if cached_queue_keys:
        task_queue.ensure_tasks_batch(cached_queue_keys)
        task_queue.mark_completed_batch(cached_queue_keys)

    if cached_session_rows:
        try:
            from src.data.analysis_storage import save_analyst_analyses_batch
            save_analyst_analyses_batch(cached_session_rows)
        except Exception as e:
            if config.verbose:
                print(f"  Warning: Failed to batch-save session analyses: {e}")

    # Decision DB: batch-record cached signals
    if cached_session_rows and config.session_id:
        try:
            decision_store = get_decision_store()
            for row in cached_session_rows:
                close_price, price_currency, price_source = extract_close_price_fn(row["ticker"])
                decision_store.record_signal(
                    run_id=config.session_id,
                    ticker=row["ticker"],
                    analyst_name=row["analyst_name"],
                    signal=row["signal"],
                    signal_numeric=row["signal_numeric"],
                    confidence=row["confidence"],
                    reasoning=row["reasoning"],
                    model_name=row.get("model_name"),
                    model_provider=row.get("model_provider"),
                    close_price=close_price,
                    currency=price_currency,
                    price_source=price_source,
                    analysis_date=end_date,
                )
        except Exception as e:
            if config.verbose:
                print(f"  Warning: Failed to record cached signals to Decision DB: {e}")

    # ── Slow path: ThreadPoolExecutor for cache misses ──
    def run_analyst(analyst_info, state, ticker, ticker_idx):
        analyst_name = analyst_info["name"]
        analyst_func = analyst_info["func"]
        display_name = analyst_info["display_name"]
        agent_id = f"{analyst_name}_agent"
        uses_llm = analyst_info.get("uses_llm", True)

        if uses_llm:
            cache_mn = configured_model_name or "unknown"
            cache_mp = configured_model_provider or "unknown"
            storage_mn = configured_model_name
            storage_mp = configured_model_provider
        else:
            cache_mn = "deterministic"
            cache_mp = "deterministic"
            storage_mn = None
            storage_mp = None

        next_ticker = config.universe[ticker_idx + 1] if ticker_idx + 1 < len(config.universe) else None
        progress.update_status(agent_id, ticker, f"Generating {display_name} analysis", next_ticker=next_ticker)

        queue_key = None
        if allow_cache:
            queue_key = TaskKey(
                analysis_date=end_date,
                ticker=ticker.upper(),
                analyst_name=analyst_name,
                model_name=cache_mn,
                model_provider=cache_mp,
            )
            task_queue.ensure_task(queue_key)

        try:
            if not config.verbose:
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()

            try:
                state_copy = dict(state)
                state_copy["data"] = dict(state["data"])
                state_copy["data"]["analyst_signals"] = {}
                result_state = analyst_func(state_copy, agent_id=agent_id)
            finally:
                if not config.verbose:
                    sys.stdout = old_stdout

            analyst_signals_result = result_state.get("data", {}).get("analyst_signals", {})
            analysis = analyst_signals_result.get(agent_id, {})

            if not analysis or not isinstance(analysis, dict):
                progress.update_status(agent_id, ticker, "Error")
                if config.verbose:
                    print(f"  Warning: No analysis returned by {display_name} for {ticker}")
                return None

            ticker_analysis = analysis.get(ticker, {})
            if not ticker_analysis:
                progress.update_status(agent_id, ticker, "Error")
                if config.verbose:
                    print(f"  Warning: No analysis for {ticker} from {display_name}")
                return None

            signal_str = ticker_analysis.get("signal", "neutral")
            confidence_val = ticker_analysis.get("confidence", 0)
            reasoning = ticker_analysis.get("reasoning", "No reasoning provided")

            signal_map = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
            numeric_signal = signal_map.get(signal_str.lower(), 0.0)

            if isinstance(confidence_val, (int, float)):
                confidence = confidence_val / 100.0 if confidence_val > 1 else confidence_val
            else:
                confidence = 0.5

            progress.update_status(agent_id, ticker, "Done", next_ticker=next_ticker)

            # Persist to session storage
            if config.session_id:
                try:
                    from src.data.analysis_storage import save_analyst_analysis
                    save_analyst_analysis(
                        session_id=config.session_id,
                        ticker=ticker,
                        analyst_name=analyst_name,
                        signal=signal_str,
                        signal_numeric=numeric_signal,
                        confidence=confidence,
                        reasoning=reasoning,
                        model_name=storage_mn if uses_llm else None,
                        model_provider=storage_mp if uses_llm else None,
                    )
                except Exception:
                    pass

                # Decision DB eager write
                try:
                    close_price, price_currency, price_source = extract_close_price_fn(ticker)
                    get_decision_store().record_signal(
                        run_id=config.session_id,
                        ticker=ticker,
                        analyst_name=analyst_name,
                        signal=signal_str,
                        signal_numeric=numeric_signal,
                        confidence=confidence,
                        reasoning=reasoning,
                        model_name=storage_mn if uses_llm else None,
                        model_provider=storage_mp if uses_llm else None,
                        close_price=close_price,
                        currency=price_currency,
                        price_source=price_source,
                        analysis_date=end_date,
                    )
                except Exception:
                    pass  # Decision DB is passive

            # Cache for next run
            if not config.no_cache:
                try:
                    analysis_cache.store_analysis(
                        ticker=ticker,
                        analyst_name=analyst_name,
                        analysis_date=end_date,
                        model_name=cache_mn,
                        model_provider=cache_mp,
                        signal=signal_str,
                        signal_numeric=numeric_signal,
                        confidence=confidence,
                        reasoning=reasoning,
                    )
                except Exception:
                    pass

            if queue_key:
                task_queue.mark_completed(queue_key)
            return AnalystSignal(ticker=ticker, analyst=analyst_name, signal=numeric_signal, confidence=confidence, reasoning=reasoning)

        except Exception as e:
            progress.update_status(agent_id, ticker, "Error", next_ticker=next_ticker)
            if config.verbose:
                print(f"\n  Warning: Analyst {display_name} failed for {ticker}: {e}")
                import traceback
                traceback.print_exc()
            if queue_key:
                task_queue.mark_failed(queue_key)
            return None

    if uncached_combos:
        max_workers = min(len(uncached_combos), config.max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_combo = {}
            for analyst_info, ticker_idx, ticker in uncached_combos:
                ticker_data = prefetched_data.get(ticker, {})
                position_date_acquired = config.portfolio_position_dates.get(ticker)

                state: AgentState = {
                    "messages": [],
                    "data": {
                        "tickers": [ticker],
                        "ticker": ticker,
                        "start_date": start_date,
                        "end_date": end_date,
                        "position_date_acquired": position_date_acquired,
                        "api_key": api_key,
                        "model_config": config.model_config,
                        "prefetched_financial_data": {ticker: ticker_data},
                        "analyst_signals": {},
                    },
                    "metadata": {
                        "portfolio_manager_mode": True,
                        "show_reasoning": False,
                    },
                }

                future = executor.submit(run_analyst, analyst_info, state, ticker, ticker_idx)
                future_to_combo[future] = (analyst_info, ticker)

            for future in as_completed(future_to_combo):
                try:
                    result = future.result(timeout=120)
                    if result:
                        signals.append(result)
                except TimeoutError:
                    analyst_info, ticker = future_to_combo[future]
                    if config.verbose:
                        print(f'\n  Warning: {analyst_info["display_name"]} for {ticker} timed out after 120 seconds')
                except Exception as exc:
                    analyst_info, ticker = future_to_combo[future]
                    if config.verbose:
                        print(f'\n  Warning: {analyst_info["display_name"]} for {ticker} generated an exception: {exc}')

    progress.stop()
    cache_msg = f" ({cached_count} cached)" if cached_count else ""
    print(f"\n✓ Collected {len(signals)} signals from {len(config.analysts)} analysts across {len(config.universe)} tickers{cache_msg}\n")
    return signals, prefetched_data
