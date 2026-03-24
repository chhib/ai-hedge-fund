from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.utils.portfolio_loader import Portfolio, Position
from src.utils.currency import (
    normalize_currency_code,
    normalize_price_and_currency,
)
from src.data.analysis_cache import get_analysis_cache
from src.data.analyst_task_queue import get_task_queue, TaskKey
from src.data.decision_store import get_decision_store
from src.services.portfolio_governor import GovernorDecision, PortfolioGovernor


@dataclass
class AnalystSignal:
    ticker: str
    analyst: str
    signal: float  # -1 to 1 (negative = bearish, positive = bullish)
    confidence: float  # 0 to 1
    reasoning: str


@dataclass
class PriceContext:
    ticker: str
    currency: str
    latest_close: float
    entry_price: float
    buy_price: float
    sell_price: float
    atr: float
    band_low: float
    band_high: float
    sample_size: int
    source: str


class EnhancedPortfolioManager:
    """
    Portfolio Manager that aggregates analyst signals for LONG-ONLY portfolios
    Handles conflicting signals by averaging and applying long-only constraint
    Maintains concentrated portfolio of 5-10 positions
    """

    def __init__(
        self,
        portfolio: Portfolio,
        universe: List[str],
        analysts: List[str],
        model_config: Dict[str, Any],
        ticker_markets: Dict[str, str] = None,
        home_currency: str = "SEK",
        no_cache: bool = False,
        no_cache_agents: bool = False,
        verbose: bool = False,
        session_id: str = None,
        max_workers: int = 50,
        use_governor: bool = False,
        governor_profile: str = "preservation",
    ):
        self.portfolio = portfolio
        self.universe = universe
        self.analyst_names = analysts
        self.model_config = model_config
        self.ticker_markets = ticker_markets or {}
        self.home_currency = home_currency.upper()
        self.no_cache = no_cache
        self.no_cache_agents = no_cache_agents
        self.verbose = verbose
        self.session_id = session_id
        self.max_workers = max_workers
        self.analysts = self._initialize_analysts(analysts, model_config)
        self.exchange_rates: Dict[str, float] = {}  # Currency -> rate (e.g., {"USD": 10.5, "GBP": 13.2})
        self.analysis_cache = get_analysis_cache()
        self.task_queue = get_task_queue()
        self.prefetched_data: Dict[str, Dict[str, Any]] = {}
        self.price_context_cache: Dict[str, PriceContext] = {}
        self._current_position_values: Dict[str, Dict[str, float]] = {}
        self._analysis_date: str | None = None
        self.use_governor = use_governor
        self.governor_profile = governor_profile
        self.governor = PortfolioGovernor(profile=governor_profile) if use_governor else None

    def _initialize_analysts(self, analyst_names: List[str], model_config: Dict[str, Any]) -> List[Any]:
        """
        Initialize all requested analysts from the analyst registry
        Uses function-based agents with AgentState for full LLM-based analysis
        """
        try:
            from src.utils.analysts import ANALYST_CONFIG

            # Map of friendly names to registry keys
            name_aliases = {
                # Famous investors
                "warren_buffett": "warren_buffett",
                "buffett": "warren_buffett",
                "charlie_munger": "charlie_munger",
                "munger": "charlie_munger",
                "stanley_druckenmiller": "stanley_druckenmiller",
                "druckenmiller": "stanley_druckenmiller",
                "peter_lynch": "peter_lynch",
                "lynch": "peter_lynch",
                "ben_graham": "ben_graham",
                "graham": "ben_graham",
                "phil_fisher": "phil_fisher",
                "fisher": "phil_fisher",
                "bill_ackman": "bill_ackman",
                "ackman": "bill_ackman",
                "cathie_wood": "cathie_wood",
                "wood": "cathie_wood",
                "michael_burry": "michael_burry",
                "burry": "michael_burry",
                "mohnish_pabrai": "mohnish_pabrai",
                "pabrai": "mohnish_pabrai",
                "rakesh_jhunjhunwala": "rakesh_jhunjhunwala",
                "jhunjhunwala": "rakesh_jhunjhunwala",
                "aswath_damodaran": "aswath_damodaran",
                "damodaran": "aswath_damodaran",
                "jim_simons": "jim_simons",
                "simons": "jim_simons",
                # Core analysts
                "fundamentals": "fundamentals_analyst",
                "fundamentals_analyst": "fundamentals_analyst",
                "technical": "technical_analyst",
                "technical_analyst": "technical_analyst",
                "sentiment": "sentiment_analyst",
                "sentiment_analyst": "sentiment_analyst",
                "valuation": "valuation_analyst",
                "valuation_analyst": "valuation_analyst",
                # News sentiment
                "news_sentiment": "news_sentiment_analyst",
                "news_sentiment_analyst": "news_sentiment_analyst",
            }

            analysts = []
            for name in analyst_names:
                name_lower = name.lower().strip()
                registry_key = name_aliases.get(name_lower, name_lower)

                if registry_key in ANALYST_CONFIG:
                    config = ANALYST_CONFIG[registry_key]
                    analysts.append({
                        "name": registry_key,
                        "display_name": config["display_name"],
                        "func": config["agent_func"],
                        "uses_llm": config.get("uses_llm", True),
                    })
                else:
                    print(f"Warning: Unknown analyst '{name}' - skipping")

            return analysts
        except ImportError as e:
            print(f"Warning: Could not import analyst registry: {e}")
            return []

    def generate_rebalancing_recommendations(self, max_holdings: int = 8, max_position: float = 0.25, min_position: float = 0.05, min_trade_size: float = 500) -> Dict[str, Any]:
        """
        Generate long-only rebalancing recommendations.
        Delegates to pipeline stage modules for each step.
        """
        from src.services.pipeline.signal_aggregator import (
            aggregate_signals,
            apply_long_only_constraint,
            apply_ticker_penalties,
        )
        from src.services.pipeline.position_sizer import (
            select_top_positions,
            calculate_target_positions,
        )
        from src.services.pipeline.trade_generator import (
            generate_recommendations,
            calculate_updated_portfolio,
        )

        # Track analysis date for queue/caching purposes
        analysis_timestamp = datetime.now()
        self._analysis_date = analysis_timestamp.strftime("%Y-%m-%d")

        # Step 1: Collect signals from all analysts
        all_signals = self._collect_analyst_signals()

        # Step 2: Compute baseline scores for governor diagnostics
        baseline_scores = aggregate_signals(all_signals, universe=self.universe)

        governor_decision = self._evaluate_governor(
            aggregated_scores=baseline_scores,
            max_position=max_position,
        )

        # Step 3: Aggregate signals with adaptive analyst weights
        aggregated_scores = aggregate_signals(
            all_signals,
            analyst_weights=governor_decision.analyst_weights if governor_decision else None,
            universe=self.universe,
        )

        # Decision DB: record governor decision + aggregations
        if self.session_id:
            try:
                decision_store = get_decision_store()
                if governor_decision:
                    decision_store.record_governor_decision(self.session_id, governor_decision)
                agg_weights = governor_decision.analyst_weights if governor_decision else {}
                agg_records = self._build_aggregation_records(all_signals, aggregated_scores, agg_weights)
                if agg_records:
                    decision_store.record_aggregations(self.session_id, agg_records)
            except Exception:
                pass  # Decision DB is passive

        # Step 4: Apply LONG-ONLY constraint
        long_only_scores = apply_long_only_constraint(aggregated_scores)
        if governor_decision:
            long_only_scores = apply_ticker_penalties(long_only_scores, governor_decision.ticker_penalties)

        # Step 5: Select top positions (concentration constraint)
        selected_tickers = select_top_positions(long_only_scores, max_holdings)

        # Step 6: Calculate target positions for selected tickers
        effective_max_position = governor_decision.max_position_override if governor_decision and governor_decision.max_position_override is not None else max_position
        target_positions = calculate_target_positions(selected_tickers, long_only_scores, effective_max_position, min_position)
        if governor_decision:
            target_positions = self.governor.apply_to_target_weights(target_positions, governor_decision)

        # Step 7: Generate recommendations
        recommendations, self._current_position_values = generate_recommendations(
            target_positions=target_positions,
            min_trade_size=min_trade_size,
            portfolio=self.portfolio,
            exchange_rates=self.exchange_rates,
            get_price_context=self._get_price_context,
            get_ticker_currency=self._get_ticker_currency,
            home_currency=self.home_currency,
            verbose=self.verbose,
        )
        if governor_decision:
            recommendations = self.governor.apply_to_recommendations(recommendations, governor_decision)

        # Decision DB: record trade recommendations (injects recommendation_id into each dict)
        if self.session_id:
            try:
                get_decision_store().record_trade_recommendations(self.session_id, recommendations)
            except Exception:
                pass  # Decision DB is passive

        # Step 8: Calculate updated portfolio
        updated_portfolio = calculate_updated_portfolio(
            recommendations=recommendations,
            portfolio=self.portfolio,
            exchange_rates=self.exchange_rates,
            home_currency=self.home_currency,
        )

        return {
            "analysis_date": analysis_timestamp.isoformat(),
            "current_portfolio": self._portfolio_summary(),
            "recommendations": recommendations,
            "updated_portfolio": updated_portfolio,
            "analyst_signals": all_signals if self.verbose else None,
            "governor": governor_decision,
        }

    def _collect_analyst_signals(self) -> List[AnalystSignal]:
        """
        Collect signals from all analysts for all tickers in universe
        Uses the same optimized infrastructure as main.py:
        1. Pre-populate instrument caches
        2. Parallel data prefetching
        3. Extract metrics and pass to analysts
        """
        signals = []

        if not self.analysts:
            if self.verbose:
                print(f"Warning: No analysts initialized")
            return signals

        import os
        from src.utils.progress import progress

        api_key = os.getenv("BORSDATA_API_KEY")
        if not api_key:
            if self.verbose:
                print("Warning: BORSDATA_API_KEY not found - using neutral signals")
            return signals

        # STEP 1: Pre-populate instrument caches (silent unless verbose)
        from src.tools.api import _borsdata_client, set_ticker_markets

        # Only force refresh instruments if full no_cache is set (not no_cache_agents)
        force_refresh = self.no_cache
        if self.verbose:
            if force_refresh:
                print("Pre-populating instrument caches (bypassing cache)...")
            elif self.no_cache_agents:
                print("Pre-populating instrument caches (reusing cached data)...")
            else:
                print("Pre-populating instrument caches...")
        try:
            _borsdata_client.get_instruments(force_refresh=force_refresh)
            if self.verbose:
                print("✓ Nordic instruments cache populated")
            _borsdata_client.get_all_instruments(force_refresh=force_refresh)
            if self.verbose:
                print("✓ Global instruments cache populated")
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Warning: Could not pre-populate instrument caches: {e}")

        # STEP 2: Set ticker market routing (Nordic vs Global API)
        set_ticker_markets(self.ticker_markets)

        # STEP 3: Parallel data prefetching - fetch ALL data needed by analysts
        from src.data.parallel_api_wrapper import run_parallel_fetch_ticker_data
        import io
        import sys

        end_date = self._analysis_date or datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now().replace(year=datetime.now().year - 1)).strftime("%Y-%m-%d")

        # Let parallel fetching output show through (it shows ticker-by-ticker progress)
        progress.start()

        # Only bypass KPI cache if --no-cache is set (not --no-cache-agents)
        # --no-cache-agents reuses cached KPI data but regenerates analyst analysis
        prefetched_data = run_parallel_fetch_ticker_data(
            tickers=self.universe,
            end_date=end_date,
            start_date=start_date,  # Pass start_date for events and insider trades
            include_prices=True,
            include_metrics=True,
            include_line_items=True,
            include_insider_trades=True,
            include_events=True,
            include_market_caps=True,
            ticker_markets=self.ticker_markets,
            progress_callback=progress.update_prefetch_status,
            no_cache=self.no_cache,  # Only bypass if --no-cache, not --no-cache-agents
        )

        progress.stop()

        # Make prefetched payloads available for downstream price heuristics
        self.prefetched_data = prefetched_data

        # STEP 3.5: Fetch exchange rates for all currencies in the universe
        self._fetch_exchange_rates(api_key)

        # Initialize progress tracking
        agent_names = [f"{a['name']}_agent" for a in self.analysts]
        progress.initialize_agents(agent_names, len(self.universe))

        # Start progress display for analyst execution
        progress.start()

        allow_cache = not self.no_cache and not self.no_cache_agents

        # STEP 4: Call function-based analysts with AgentState for each ticker
        from src.graph.state import AgentState
        from concurrent.futures import ThreadPoolExecutor, as_completed

        configured_model_name = self.model_config.get("name")
        configured_model_provider = self.model_config.get("provider")

        # Build a lookup of ticker -> acquisition date for existing positions
        position_dates = {
            p.ticker: p.date_acquired.strftime("%Y-%m-%d") if p.date_acquired else None
            for p in self.portfolio.positions
        }

        # ── Fast path: resolve cache hits in bulk before touching threads ──
        # Load all cached analyses for this date in ONE query per model variant
        cache_batches: dict[tuple[str, str], dict[tuple[str, str], object]] = {}
        if allow_cache:
            seen_model_keys: set[tuple[str, str]] = set()
            for analyst_info in self.analysts:
                uses_llm = analyst_info.get("uses_llm", True)
                if uses_llm:
                    mk = (configured_model_name or "unknown", configured_model_provider or "unknown")
                else:
                    mk = ("deterministic", "deterministic")
                if mk not in seen_model_keys:
                    seen_model_keys.add(mk)
                    cache_batches[mk] = self.analysis_cache.load_batch(
                        analysis_date=end_date,
                        model_name=mk[0],
                        model_provider=mk[1],
                    )

        # Separate cached hits from uncached misses
        uncached_combos = []  # (analyst_info, ticker_idx, ticker)
        cached_queue_keys: list[TaskKey] = []
        cached_session_rows: list[dict] = []
        cached_count = 0

        for ticker_idx, ticker in enumerate(self.universe):
            for analyst_info in self.analysts:
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

                # ── Cache hit: resolve instantly ──
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

                # Collect batch data for task queue
                cached_queue_keys.append(TaskKey(
                    analysis_date=end_date,
                    ticker=ticker.upper(),
                    analyst_name=analyst_name,
                    model_name=cache_model_name,
                    model_provider=cache_model_provider,
                ))

                # Collect batch data for session persistence
                if self.session_id:
                    cached_session_rows.append({
                        "session_id": self.session_id,
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
                # Throttle progress updates: every 50th cached item
                if cached_count % 50 == 0 or cached_count == 1:
                    agent_id = f"{analyst_name}_agent"
                    next_ticker = self.universe[ticker_idx + 1] if ticker_idx + 1 < len(self.universe) else None
                    progress.update_status(agent_id, ticker, f"Done (cached, {cached_count} resolved)", next_ticker=next_ticker)

        # ── Batch DB operations for all cache hits (3 calls instead of ~4,120) ──
        if cached_queue_keys:
            self.task_queue.ensure_tasks_batch(cached_queue_keys)
            self.task_queue.mark_completed_batch(cached_queue_keys)

        if cached_session_rows:
            try:
                from src.data.analysis_storage import save_analyst_analyses_batch
                save_analyst_analyses_batch(cached_session_rows)
            except Exception as e:
                if self.verbose:
                    print(f"  Warning: Failed to batch-save session analyses: {e}")

        # ── Decision DB: batch-record cached signals ──
        if cached_session_rows and self.session_id:
            try:
                decision_store = get_decision_store()
                for row in cached_session_rows:
                    close_price, price_currency, price_source = self._extract_close_price(row["ticker"])
                    decision_store.record_signal(
                        run_id=self.session_id,
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
                if self.verbose:
                    print(f"  Warning: Failed to record cached signals to Decision DB: {e}")

        # ── Slow path: only submit cache MISSES to ThreadPoolExecutor ──
        def run_analyst(analyst_info, state, ticker, ticker_idx):
            analyst_name = analyst_info["name"]
            analyst_func = analyst_info["func"]
            display_name = analyst_info["display_name"]
            agent_id = f"{analyst_name}_agent"
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

            # Calculate next ticker for this analyst
            next_ticker = self.universe[ticker_idx + 1] if ticker_idx + 1 < len(self.universe) else None

            # Update progress: analyzing
            progress.update_status(agent_id, ticker, f"Generating {display_name} analysis", next_ticker=next_ticker)

            queue_key = None
            if allow_cache:
                queue_key = TaskKey(
                    analysis_date=end_date,
                    ticker=ticker.upper(),
                    analyst_name=analyst_name,
                    model_name=cache_model_name,
                    model_provider=cache_model_provider,
                )
                self.task_queue.ensure_task(queue_key)

            try:
                # Suppress agent print statements (like show_agent_reasoning)
                if not self.verbose:
                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()

                try:
                    # Call the function-based analyst
                    # Shallow-copy only the mutable data dict to avoid concurrent modification
                    state_copy = dict(state)
                    state_copy["data"] = dict(state["data"])
                    state_copy["data"]["analyst_signals"] = {}
                    result_state = analyst_func(state_copy, agent_id=agent_id)
                finally:
                    if not self.verbose:
                        sys.stdout = old_stdout

                # Extract analysis from state - agents store in analyst_signals[agent_name_agent]
                analyst_signals_result = result_state.get("data", {}).get("analyst_signals", {})
                analysis = analyst_signals_result.get(agent_id, {})

                if not analysis or not isinstance(analysis, dict):
                    progress.update_status(agent_id, ticker, "Error")
                    if self.verbose:
                        print(f"  Warning: No analysis returned by {display_name} for {ticker}")
                        print(f"  DEBUG: result_state keys = {result_state.keys()}")
                        print(f"  DEBUG: result_state['data'] keys = {result_state.get('data', {}).keys()}")
                        print(f"  DEBUG: analyst_signals keys = {analyst_signals_result.keys()}")
                        print(f"  DEBUG: analysis type = {type(analysis)}, value = {analysis}")
                    return None

                # Get the ticker's analysis
                ticker_analysis = analysis.get(ticker, {})
                if not ticker_analysis:
                    progress.update_status(agent_id, ticker, "Error")
                    if self.verbose:
                        print(f"  Warning: No analysis for {ticker} from {display_name}")
                        print(f"  DEBUG: analysis keys = {analysis.keys()}")
                        print(f"  DEBUG: looking for ticker = {ticker}")
                    return None

                # Extract signal info (varies by analyst, but all have these fields)
                signal_str = ticker_analysis.get("signal", "neutral")
                confidence_val = ticker_analysis.get("confidence", 0)
                reasoning = ticker_analysis.get("reasoning", "No reasoning provided")

                # Convert signal to numeric score (-1 to 1)
                signal_map = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
                numeric_signal = signal_map.get(signal_str.lower(), 0.0)

                # Normalize confidence to 0-1 scale
                if isinstance(confidence_val, (int, float)):
                    confidence = confidence_val / 100.0 if confidence_val > 1 else confidence_val
                else:
                    confidence = 0.5

                # Update progress: done (next_ticker is already set from before)
                progress.update_status(agent_id, ticker, "Done", next_ticker=next_ticker)

                # Persist results for this session
                if self.session_id:
                    try:
                        from src.data.analysis_storage import save_analyst_analysis
                        save_analyst_analysis(
                            session_id=self.session_id,
                            ticker=ticker,
                            analyst_name=analyst_name,
                            signal=signal_str,
                            signal_numeric=numeric_signal,
                            confidence=confidence,
                            reasoning=reasoning,
                            model_name=storage_model_name if uses_llm else None,
                            model_provider=storage_model_provider if uses_llm else None,
                        )
                    except Exception as e:
                        if self.verbose:
                            print(f"  Warning: Failed to save analysis to database: {e}")

                    # Decision DB: record signal (eager write per analyst x ticker)
                    try:
                        close_price, price_currency, price_source = self._extract_close_price(ticker)
                        get_decision_store().record_signal(
                            run_id=self.session_id,
                            ticker=ticker,
                            analyst_name=analyst_name,
                            signal=signal_str,
                            signal_numeric=numeric_signal,
                            confidence=confidence,
                            reasoning=reasoning,
                            model_name=storage_model_name if uses_llm else None,
                            model_provider=storage_model_provider if uses_llm else None,
                            close_price=close_price,
                            currency=price_currency,
                            price_source=price_source,
                            analysis_date=end_date,
                        )
                    except Exception:
                        pass  # Decision DB is passive -- never break the pipeline

                # Cache results even when --no-cache-agents is used (for next run)
                # Only skip caching if --no-cache is set (which bypasses everything)
                if not self.no_cache:
                    try:
                        self.analysis_cache.store_analysis(
                            ticker=ticker,
                            analyst_name=analyst_name,
                            analysis_date=end_date,
                            model_name=cache_model_name,
                            model_provider=cache_model_provider,
                            signal=signal_str,
                            signal_numeric=numeric_signal,
                            confidence=confidence,
                            reasoning=reasoning,
                        )
                    except Exception as cache_error:
                        if self.verbose:
                            print(f"  Warning: Failed to cache analysis for {ticker}: {cache_error}")

                if queue_key:
                    self.task_queue.mark_completed(queue_key)
                return AnalystSignal(ticker=ticker, analyst=analyst_name, signal=numeric_signal, confidence=confidence, reasoning=reasoning)

            except Exception as e:
                progress.update_status(agent_id, ticker, "Error", next_ticker=next_ticker)
                if self.verbose:
                    print(f"\n  Warning: Analyst {display_name} failed for {ticker}: {e}")
                    import traceback
                    traceback.print_exc()
                if queue_key:
                    self.task_queue.mark_failed(queue_key)
                return None

        if uncached_combos:
            max_workers = min(len(uncached_combos), self.max_workers)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_combo = {}
                for analyst_info, ticker_idx, ticker in uncached_combos:
                    ticker_data = prefetched_data.get(ticker, {})

                    # Get position's acquisition date if this ticker is in the portfolio
                    position_date_acquired = position_dates.get(ticker)

                    # Create AgentState with prefetched data (same pattern as main.py)
                    state: AgentState = {
                        "messages": [],
                        "data": {
                            "tickers": [ticker],
                            "ticker": ticker,
                            "start_date": start_date,
                            "end_date": end_date,
                            "position_date_acquired": position_date_acquired,
                            "api_key": api_key,
                            "model_config": self.model_config,
                            "prefetched_financial_data": {
                                ticker: ticker_data
                            },
                            "analyst_signals": {},
                        },
                        "metadata": {
                            "portfolio_manager_mode": True,
                            "show_reasoning": False,
                        }
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
                        if self.verbose:
                            print(f'\n  Warning: {analyst_info["display_name"]} for {ticker} timed out after 120 seconds')
                    except Exception as exc:
                        analyst_info, ticker = future_to_combo[future]
                        if self.verbose:
                            print(f'\n  Warning: {analyst_info["display_name"]} for {ticker} generated an exception: {exc}')

        # Stop progress display and show summary
        progress.stop()
        cache_msg = f" ({cached_count} cached)" if cached_count else ""
        print(f"\n✓ Collected {len(signals)} signals from {len(self.analysts)} analysts across {len(self.universe)} tickers{cache_msg}\n")
        return signals

    def _fetch_exchange_rates(self, api_key: str) -> None:
        """
        Fetch exchange rates for all currencies in the universe relative to home currency.
        Uses Börsdata's instrument type 6 (currencies) to get FX rates.
        """
        from src.data.exchange_rate_service import ExchangeRateService
        from src.data.borsdata_client import BorsdataClient

        # Identify all currencies needed from the universe
        currencies_needed = set()
        for ticker in self.universe:
            currency = self._get_ticker_currency(ticker)
            if currency and currency != self.home_currency:
                currencies_needed.add(currency)

        # Always include home currency (rate = 1.0)
        self.exchange_rates[self.home_currency] = 1.0

        if not currencies_needed:
            if self.verbose:
                print(f"✓ All tickers in home currency ({self.home_currency}), no FX rates needed\n")
            return

        # Initialize exchange rate service
        client = BorsdataClient()
        fx_service = ExchangeRateService(client)

        # Fetch rates for each currency
        if self.verbose:
            print(f"Fetching exchange rates to {self.home_currency}...")

        def _get_rate_via_usd(target_currency: str) -> tuple[float | None, str]:
            """
            Attempt to derive the target/home rate via USD if direct pair is missing.
            Returns (rate, strategy) where strategy is "usd_cross" or "missing".
            """
            if target_currency.upper() == "USD" or self.home_currency.upper() == "USD":
                return None, "missing"

            usd_home = self.exchange_rates.get("USD")
            if usd_home is None:
                usd_home = fx_service.get_rate("USD", self.home_currency)
                if usd_home:
                    self.exchange_rates["USD"] = usd_home
                elif self.verbose:
                    print(f"  ⚠️  USD/{self.home_currency} rate not available for USD cross fallback")

            if not usd_home:
                return None, "missing"

            currency_usd = fx_service.get_rate(target_currency, "USD")
            if not currency_usd:
                inverse = fx_service.get_rate("USD", target_currency)
                if inverse and inverse != 0:
                    currency_usd = 1 / inverse

            if currency_usd:
                return currency_usd * usd_home, "usd_cross"

            return None, "missing"

        for currency in currencies_needed:
            try:
                rate = fx_service.get_rate(currency, self.home_currency)
                strategy = "direct"

                if not rate:
                    rate, strategy = _get_rate_via_usd(currency)

                if rate:
                    self.exchange_rates[currency] = rate
                    if self.verbose:
                        suffix = " (via USD)" if strategy == "usd_cross" else ""
                        print(f"  ✓ {currency}/{self.home_currency} = {rate:.4f}{suffix}")
                else:
                    # Fallback to 1.0 if rate not found (with warning)
                    self.exchange_rates[currency] = 1.0
                    if self.verbose:
                        print(f"  ⚠️  {currency}/{self.home_currency} rate not found, using 1.0")
            except Exception as e:
                # Fallback to 1.0 on error
                self.exchange_rates[currency] = 1.0
                if self.verbose:
                    print(f"  ⚠️  Error fetching {currency}/{self.home_currency}: {e}, using 1.0")

        if self.verbose:
            print()

    def _aggregate_signals(
        self,
        signals: List[AnalystSignal],
        analyst_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Delegate to pipeline.signal_aggregator."""
        from src.services.pipeline.signal_aggregator import aggregate_signals
        return aggregate_signals(signals, analyst_weights, universe=self.universe)

    def _apply_ticker_penalties(self, scores: Dict[str, float], decision: GovernorDecision) -> Dict[str, float]:
        from src.services.pipeline.signal_aggregator import apply_ticker_penalties
        return apply_ticker_penalties(scores, decision.ticker_penalties)

    def _evaluate_governor(
        self,
        *,
        aggregated_scores: Dict[str, float],
        max_position: float,
    ) -> Optional[GovernorDecision]:
        if not self.governor:
            return None
        return self.governor.evaluate(
            selected_analysts=self.analyst_names,
            aggregated_scores=aggregated_scores,
            ticker_markets=self.ticker_markets,
            max_position=max_position,
            persist=True,
        )

    def _apply_long_only_constraint(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Delegate to pipeline.signal_aggregator."""
        from src.services.pipeline.signal_aggregator import apply_long_only_constraint
        return apply_long_only_constraint(scores)

    def _select_top_positions(self, scores: Dict[str, float], max_holdings: int) -> List[str]:
        """Delegate to pipeline.position_sizer."""
        from src.services.pipeline.position_sizer import select_top_positions
        return select_top_positions(scores, max_holdings)

    def _calculate_target_positions(self, selected_tickers: List[str], scores: Dict[str, float], max_position: float, min_position: float) -> Dict[str, float]:
        """Delegate to pipeline.position_sizer."""
        from src.services.pipeline.position_sizer import calculate_target_positions
        return calculate_target_positions(selected_tickers, scores, max_position, min_position)

    def _get_ticker_currency(self, ticker: str) -> str:
        """
        Fetch actual currency from Borsdata instrument data
        Returns stockPriceCurrency from the API
        """
        import os
        from src.tools.api import _borsdata_client

        api_key = os.getenv("BORSDATA_API_KEY")
        if not api_key:
            # Fallback to market-based guess
            market = self.ticker_markets.get(ticker, "global")
            return "SEK" if market == "Nordic" else "USD"

        try:
            market = self.ticker_markets.get(ticker, "global")
            use_global = market.lower() == "global"
            instrument = _borsdata_client.get_instrument(ticker, api_key=api_key, use_global=use_global)
            currency = instrument.get("stockPriceCurrency")
            if currency:
                return normalize_currency_code(currency)
        except Exception as e:
            if self.verbose:
                print(f"Warning: Could not fetch currency for {ticker}: {e}")

        # Fallback
        market = self.ticker_markets.get(ticker, "global")
        return "SEK" if market == "Nordic" else "USD"

    def _fetch_latest_close(self, ticker: str) -> tuple[float, str]:
        """
        Fetch the latest available close from Börsdata as a simple fallback.
        Returns (price, currency).
        """
        import os
        from datetime import datetime, timedelta
        from src.tools.api import _borsdata_client

        api_key = os.getenv("BORSDATA_API_KEY")
        if not api_key:
            if self.verbose:
                print(f"Warning: No API key - using default price for {ticker}")
            return 100.0, self._get_ticker_currency(ticker)

        try:
            market = self.ticker_markets.get(ticker, "global")
            use_global = market.lower() == "global"

            instrument = _borsdata_client.get_instrument(ticker, api_key=api_key, use_global=use_global)
            raw_currency = instrument.get("stockPriceCurrency", "USD")
            instrument_id = instrument.get("insId")

            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

            prices = _borsdata_client.get_stock_prices(
                instrument_id,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
            )

            if prices:
                latest = prices[-1]
                close_price = latest.get("c")
                if close_price is not None:
                    normalized_price, normalized_currency = normalize_price_and_currency(float(close_price), raw_currency)
                    if self.verbose and normalized_price != float(close_price):
                        print(f"Normalized {raw_currency} quote {close_price} -> {normalized_price:.4f} {normalized_currency}")
                    return normalized_price, normalized_currency

            if self.verbose:
                print(f"Warning: No recent prices for {ticker}, using default")
            return 100.0, normalize_currency_code(raw_currency)

        except Exception as e:
            if self.verbose:
                print(f"Warning: Could not fetch price for {ticker}: {e}")
            return 100.0, self._get_ticker_currency(ticker)

    def _build_aggregation_records(
        self,
        all_signals: List[AnalystSignal],
        aggregated_scores: Dict[str, float],
        analyst_weights: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Build aggregation records with per-ticker analyst metadata."""
        ticker_analysts: Dict[str, List[str]] = {}
        for sig in all_signals:
            ticker_analysts.setdefault(sig.ticker, []).append(sig.analyst)

        records = []
        for ticker, score in aggregated_scores.items():
            analysts_for_ticker = ticker_analysts.get(ticker, [])
            weights_for_ticker = {a: analyst_weights.get(a, 1.0) for a in analysts_for_ticker}
            records.append({
                "ticker": ticker,
                "weighted_score": score,
                "contributing_analysts": len(analysts_for_ticker),
                "analyst_weights": weights_for_ticker,
            })
        return records

    def _extract_close_price(self, ticker: str) -> tuple:
        """Extract latest close price from prefetched data for Decision DB.

        Returns (close_price, currency, price_source) -- all nullable.
        """
        prices = self.prefetched_data.get(ticker, {}).get("prices", [])
        if prices:
            sorted_prices = sorted(prices, key=lambda p: p.time)
            latest = sorted_prices[-1]
            close = float(latest.close) if latest.close is not None else None
            currency = self._get_ticker_currency(ticker) if close else None
            return close, currency, "borsdata"
        return None, None, None

    def _get_price_context(self, ticker: str) -> PriceContext:
        """
        Build a three-day price context with rolling averages and ATR heuristics.
        """
        if ticker in self.price_context_cache:
            return self.price_context_cache[ticker]

        from datetime import datetime, timedelta
        from statistics import fmean
        from src.tools.api import get_prices

        cached_prices = self.prefetched_data.get(ticker, {}).get("prices", [])
        source = "prefetch" if cached_prices else "api"

        price_records = list(cached_prices)
        if not price_records:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
            price_records = get_prices(ticker, start_date, end_date)

        if not price_records:
            fallback_price, fallback_currency = self._fetch_latest_close(ticker)
            context = PriceContext(
                ticker=ticker,
                currency=fallback_currency,
                latest_close=fallback_price,
                entry_price=fallback_price,
                buy_price=fallback_price,
                sell_price=fallback_price,
                atr=0.0,
                band_low=fallback_price,
                band_high=fallback_price,
                sample_size=0,
                source="fallback",
            )
            self.price_context_cache[ticker] = context
            return context

        price_records.sort(key=lambda p: p.time)
        recent = price_records[-3:]
        sample_size = len(recent)

        closes = [float(p.close) for p in recent if p.close is not None]

        latest_close = closes[-1] if closes else float(price_records[-1].close)
        entry_price = fmean(closes) if closes else latest_close

        prev_close = None
        if len(price_records) > sample_size:
            prev_close = float(price_records[-sample_size - 1].close)

        true_ranges: List[float] = []
        prior_close = prev_close
        for price in recent:
            high = float(price.high)
            low = float(price.low)
            close = float(price.close)
            range_high_low = high - low
            if prior_close is None:
                tr = range_high_low
            else:
                tr = max(range_high_low, abs(high - prior_close), abs(low - prior_close))
            true_ranges.append(max(tr, 0.0))
            prior_close = close

        atr = fmean(true_ranges) if true_ranges else 0.0
        band_half = atr / 2 if atr else 0.0
        band_low = max(entry_price - band_half, 0.0)
        band_high = entry_price + band_half
        slippage = atr * 0.5 if atr else 0.0

        currency = self._get_ticker_currency(ticker)
        if not currency:
            _, currency = self._fetch_latest_close(ticker)

        context = PriceContext(
            ticker=ticker,
            currency=currency,
            latest_close=latest_close,
            entry_price=entry_price,
            buy_price=max(entry_price + slippage, 0.0),
            sell_price=max(entry_price - slippage, 0.0),
            atr=atr,
            band_low=band_low,
            band_high=band_high,
            sample_size=sample_size,
            source=source,
        )

        self.price_context_cache[ticker] = context
        return context

    def _get_position_value_info(self, position: Position) -> Dict[str, float]:
        """Delegate to pipeline.trade_generator."""
        from src.services.pipeline.trade_generator import _get_position_value_info
        return _get_position_value_info(position, self._get_price_context, self.exchange_rates, self.home_currency)

    def _generate_recommendations(self, target_positions: Dict[str, float], min_trade_size: float) -> List[Dict[str, Any]]:
        """Delegate to pipeline.trade_generator."""
        from src.services.pipeline.trade_generator import generate_recommendations
        recommendations, self._current_position_values = generate_recommendations(
            target_positions=target_positions,
            min_trade_size=min_trade_size,
            portfolio=self.portfolio,
            exchange_rates=self.exchange_rates,
            get_price_context=self._get_price_context,
            get_ticker_currency=self._get_ticker_currency,
            home_currency=self.home_currency,
            verbose=self.verbose,
        )
        return recommendations

    def _validate_cash_constraints(self, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Delegate to pipeline.trade_generator."""
        from src.services.pipeline.trade_generator import _validate_cash_constraints
        return _validate_cash_constraints(recommendations, self.portfolio, self.exchange_rates)

    def _round_and_top_up_shares(self, recommendations: List[Dict[str, Any]], target_positions: Dict[str, float], total_value: float, min_trade_size: float) -> List[Dict[str, Any]]:
        """Delegate to pipeline.trade_generator."""
        from src.services.pipeline.trade_generator import _round_and_top_up_shares
        return _round_and_top_up_shares(recommendations, target_positions, total_value, min_trade_size, self.exchange_rates)

    def _allocate_residual_cash(self, recommendations: List[Dict[str, Any]], total_value: float, min_trade_size: float, base_weight_tolerance: float = 0.02) -> None:
        """Delegate to pipeline.trade_generator."""
        from src.services.pipeline.trade_generator import _allocate_residual_cash
        _allocate_residual_cash(recommendations, total_value, min_trade_size, self.exchange_rates, base_weight_tolerance)

    def _calculate_updated_portfolio(self, recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delegate to pipeline.trade_generator."""
        from src.services.pipeline.trade_generator import calculate_updated_portfolio
        return calculate_updated_portfolio(recommendations, self.portfolio, self.exchange_rates, self.home_currency)

    def _portfolio_summary(self) -> Dict[str, Any]:
        """Generate summary of current portfolio in HOME CURRENCY"""
        # Convert position values to home currency
        total_value = 0.0
        position_value_map = getattr(self, "_current_position_values", {})
        for p in self.portfolio.positions:
            value_info = position_value_map.get(p.ticker)
            if not value_info:
                value_info = self._get_position_value_info(p)
            total_value += value_info["value_home"]

        # Convert cash holdings to home currency
        for currency, cash in self.portfolio.cash_holdings.items():
            fx_rate = self.exchange_rates.get(currency, 1.0)
            total_value += cash * fx_rate

        return {
            "total_value": total_value,
            "num_positions": len(self.portfolio.positions),
            "cash_holdings": self.portfolio.cash_holdings,
            "home_currency": self.home_currency,
            "exchange_rates": self.exchange_rates,
        }
