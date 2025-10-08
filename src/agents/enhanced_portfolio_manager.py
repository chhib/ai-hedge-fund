from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from src.utils.portfolio_loader import Portfolio
from src.utils.currency import (
    normalize_currency_code,
    normalize_price_and_currency,
    compute_cost_basis_after_rebalance,
)
from src.data.analysis_cache import get_analysis_cache


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

    def __init__(self, portfolio: Portfolio, universe: List[str], analysts: List[str], model_config: Dict[str, Any], ticker_markets: Dict[str, str] = None, home_currency: str = "SEK", no_cache: bool = False, no_cache_agents: bool = False, verbose: bool = False, session_id: str = None):
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
        self.analysts = self._initialize_analysts(analysts, model_config)
        self.exchange_rates: Dict[str, float] = {}  # Currency -> rate (e.g., {"USD": 10.5, "GBP": 13.2})
        self.analysis_cache = get_analysis_cache()
        self.prefetched_data: Dict[str, Dict[str, Any]] = {}
        self.price_context_cache: Dict[str, PriceContext] = {}

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
        Generate long-only rebalancing recommendations
        Maintains concentrated portfolio of max_holdings positions
        """

        # Step 1: Collect signals from all analysts
        all_signals = self._collect_analyst_signals()

        # Step 2: Aggregate signals per ticker (handle conflicts)
        aggregated_scores = self._aggregate_signals(all_signals)

        # Step 3: Apply LONG-ONLY constraint
        long_only_scores = self._apply_long_only_constraint(aggregated_scores)

        # Step 4: Select top positions (concentration constraint)
        selected_tickers = self._select_top_positions(long_only_scores, max_holdings)

        # Step 5: Calculate target positions for selected tickers
        target_positions = self._calculate_target_positions(selected_tickers, long_only_scores, max_position, min_position)

        # Step 6: Generate recommendations
        recommendations = self._generate_recommendations(target_positions, min_trade_size)

        # Step 7: Calculate updated portfolio
        updated_portfolio = self._calculate_updated_portfolio(recommendations)

        return {"analysis_date": datetime.now().isoformat(), "current_portfolio": self._portfolio_summary(), "recommendations": recommendations, "updated_portfolio": updated_portfolio, "analyst_signals": all_signals if self.verbose else None}

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

        end_date = datetime.now().strftime("%Y-%m-%d")
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

        # STEP 4: Call function-based analysts with AgentState for each ticker
        from src.graph.state import AgentState
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def run_analyst(analyst_info, state, ticker, ticker_idx):
            analyst_name = analyst_info["name"]
            analyst_func = analyst_info["func"]
            display_name = analyst_info["display_name"]
            agent_id = f"{analyst_name}_agent"
            uses_llm = analyst_info.get("uses_llm", True)

            configured_model_name = self.model_config.get("name")
            configured_model_provider = self.model_config.get("provider")

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

            def persist_session_analysis(signal_str: str, numeric_signal: float, confidence_val: float, reasoning_text: str) -> None:
                if not self.session_id:
                    return
                try:
                    from src.data.analysis_storage import save_analyst_analysis

                    save_analyst_analysis(
                        session_id=self.session_id,
                        ticker=ticker,
                        analyst_name=analyst_name,
                        signal=signal_str,
                        signal_numeric=numeric_signal,
                        confidence=confidence_val,
                        reasoning=reasoning_text,
                        model_name=storage_model_name if uses_llm else None,
                        model_provider=storage_model_provider if uses_llm else None,
                    )
                except Exception as e:
                    if self.verbose:
                        print(f"  Warning: Failed to save analysis to database: {e}")

            # Attempt to reuse cached analysis when allowed
            # Skip cache if either no_cache or no_cache_agents is set
            if not self.no_cache and not self.no_cache_agents:
                cached = self.analysis_cache.get_cached_analysis(
                    ticker=ticker,
                    analyst_name=analyst_name,
                    analysis_date=end_date,
                    model_name=cache_model_name,
                    model_provider=cache_model_provider,
                )
                if cached:
                    signal_str = cached.signal
                    numeric_signal = cached.signal_numeric
                    confidence = cached.confidence
                    reasoning = cached.reasoning or "Cached analysis"
                    progress.update_status(agent_id, ticker, "Using cached analysis", next_ticker=next_ticker)
                    persist_session_analysis(signal_str, numeric_signal, confidence, reasoning)
                    progress.update_status(agent_id, ticker, "Done (cached)", next_ticker=next_ticker)
                    return AnalystSignal(
                        ticker=ticker,
                        analyst=analyst_name,
                        signal=numeric_signal,
                        confidence=confidence,
                        reasoning=reasoning,
                    )

            try:
                # Suppress agent print statements (like show_agent_reasoning)
                if not self.verbose:
                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()

                try:
                    # Call the function-based analyst
                    # Use deep copy to avoid concurrent modification of nested dicts
                    import copy
                    result_state = analyst_func(copy.deepcopy(state), agent_id=agent_id)
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

                # Persist results for this session and cache for future runs
                persist_session_analysis(signal_str, numeric_signal, confidence, reasoning)

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

                return AnalystSignal(ticker=ticker, analyst=analyst_name, signal=numeric_signal, confidence=confidence, reasoning=reasoning)

            except Exception as e:
                progress.update_status(agent_id, ticker, "Error", next_ticker=next_ticker)
                if self.verbose:
                    print(f"\n  Warning: Analyst {display_name} failed for {ticker}: {e}")
                    import traceback
                    traceback.print_exc()
                return None

        # Create all analyst×ticker combinations for maximum parallelization (same as main.py)
        analyst_ticker_combinations = [
            (analyst_info, ticker_idx, ticker)
            for ticker_idx, ticker in enumerate(self.universe)
            for analyst_info in self.analysts
        ]

        # Process all combinations in parallel with 16 workers to avoid rate limits
        max_workers = min(len(analyst_ticker_combinations), 16)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_combo = {}
            for analyst_info, ticker_idx, ticker in analyst_ticker_combinations:
                ticker_data = prefetched_data.get(ticker, {})

                # Create AgentState with prefetched data (same pattern as main.py)
                state: AgentState = {
                    "messages": [],
                    "data": {
                        "tickers": [ticker],
                        "ticker": ticker,
                        "start_date": start_date,
                        "end_date": end_date,
                        "api_key": api_key,
                        "model_config": self.model_config,
                        "prefetched_financial_data": {
                            ticker: ticker_data
                        },
                        "analyst_signals": {},  # Required by some analysts
                    },
                    "metadata": {
                        "portfolio_manager_mode": True,
                        "show_reasoning": False,  # Never show verbose reasoning in portfolio mode
                    }
                }

                future = executor.submit(run_analyst, analyst_info, state, ticker, ticker_idx)
                future_to_combo[future] = (analyst_info, ticker)

            for future in as_completed(future_to_combo):
                try:
                    result = future.result()
                    if result:
                        signals.append(result)
                except Exception as exc:
                    analyst_info, ticker = future_to_combo[future]
                    if self.verbose:
                        print(f'\n  Warning: {analyst_info["display_name"]} for {ticker} generated an exception: {exc}')

        # Stop progress display and show summary
        progress.stop()
        print(f"\n✓ Collected {len(signals)} signals from {len(self.analysts)} analysts across {len(self.universe)} tickers\n")
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

        for currency in currencies_needed:
            try:
                rate = fx_service.get_rate(currency, self.home_currency)
                if rate:
                    self.exchange_rates[currency] = rate
                    if self.verbose:
                        print(f"  ✓ {currency}/{self.home_currency} = {rate:.4f}")
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

    def _aggregate_signals(self, signals: List[AnalystSignal]) -> Dict[str, float]:
        """
        Aggregate multiple analyst signals per ticker
        Handles SHORT signals by reducing the score, not going negative
        """
        ticker_signals = {}

        for signal in signals:
            if signal.ticker not in ticker_signals:
                ticker_signals[signal.ticker] = []
            ticker_signals[signal.ticker].append(signal)

        aggregated = {}
        for ticker, ticker_sigs in ticker_signals.items():
            # Weighted average by confidence
            total_weight = sum(s.confidence for s in ticker_sigs)
            if total_weight > 0:
                weighted_sum = sum(s.signal * s.confidence for s in ticker_sigs)
                aggregated[ticker] = weighted_sum / total_weight
            else:
                aggregated[ticker] = 0

        # If no signals, assign neutral score to all universe tickers
        if not aggregated:
            for ticker in self.universe:
                aggregated[ticker] = 0.5  # Neutral score

        return aggregated

    def _apply_long_only_constraint(self, scores: Dict[str, float]) -> Dict[str, float]:
        """
        Convert -1 to 1 signals into 0 to 1 long-only scores
        -1 (strong sell) → 0 (sell all)
        0 (neutral) → 0.5 (hold)
        1 (strong buy) → 1 (max position)
        """
        long_only = {}
        for ticker, score in scores.items():
            # Transform: (score + 1) / 2 maps [-1,1] to [0,1]
            long_only[ticker] = (score + 1) / 2
        return long_only

    def _select_top_positions(self, scores: Dict[str, float], max_holdings: int) -> List[str]:
        """
        Select top N positions for concentrated portfolio
        Path-independent: selects best positions regardless of current holdings
        """
        MIN_SCORE_THRESHOLD = 0.5  # Minimum score to be considered (0.5 = neutral)

        # Filter tickers that meet minimum threshold
        qualified_tickers = {t: s for t, s in scores.items() if s >= MIN_SCORE_THRESHOLD}

        # Sort by score and select top N
        sorted_tickers = sorted(qualified_tickers.items(), key=lambda x: x[1], reverse=True)
        selected = [t for t, score in sorted_tickers[:max_holdings]]

        return selected

    def _calculate_target_positions(self, selected_tickers: List[str], scores: Dict[str, float], max_position: float, min_position: float) -> Dict[str, float]:
        """
        Calculate target portfolio weights for selected tickers
        Ensures concentrated portfolio with meaningful position sizes
        """
        if not selected_tickers:
            return {}

        # Get scores for selected tickers
        selected_scores = {t: scores[t] for t in selected_tickers}

        # Normalize scores to sum to 1
        total_score = sum(selected_scores.values())
        if total_score == 0:
            return {}

        target_weights = {}
        for ticker in selected_tickers:
            # Base weight proportional to score
            base_weight = selected_scores[ticker] / total_score

            # Apply position limits
            if base_weight > max_position:
                target_weights[ticker] = max_position
            elif base_weight < min_position:
                # For concentrated portfolio, either meaningful position or nothing
                target_weights[ticker] = min_position
            else:
                target_weights[ticker] = base_weight

        # Re-normalize after applying constraints
        total_weight = sum(target_weights.values())
        if total_weight > 1.0:
            for ticker in target_weights:
                target_weights[ticker] /= total_weight

        return target_weights

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

    def _generate_recommendations(self, target_positions: Dict[str, float], min_trade_size: float) -> List[Dict[str, Any]]:
        """
        Generate trading recommendations based on target positions vs current portfolio
        Multi-currency aware: calculates per-currency totals and validates cash constraints
        """
        recommendations = []
        current_tickers = {p.ticker for p in self.portfolio.positions}
        all_tickers = set(list(target_positions.keys()) + list(current_tickers))

        # Calculate total portfolio value in HOME CURRENCY
        total_value_home = 0.0

        # Convert position values to home currency
        for pos in self.portfolio.positions:
            fx_rate = self.exchange_rates.get(pos.currency, 1.0)
            position_value_home = pos.shares * pos.cost_basis * fx_rate
            total_value_home += position_value_home

        # Convert cash holdings to home currency
        for currency, cash in self.portfolio.cash_holdings.items():
            fx_rate = self.exchange_rates.get(currency, 1.0)
            total_value_home += cash * fx_rate

        total_value = total_value_home

        for ticker in all_tickers:
            # Current position
            current_pos = next((p for p in self.portfolio.positions if p.ticker == ticker), None)
            current_weight = 0.0
            current_shares = 0.0
            if current_pos:
                # Convert to home currency for weight calculation
                fx_rate = self.exchange_rates.get(current_pos.currency, 1.0)
                current_value_home = current_pos.shares * current_pos.cost_basis * fx_rate
                current_weight = current_value_home / total_value if total_value > 0 else 0
                current_shares = current_pos.shares

            # Target position
            target_weight = target_positions.get(ticker, 0.0)

            # Determine action
            weight_delta = target_weight - current_weight

            if abs(weight_delta * total_value) < min_trade_size:
                action = "HOLD"
            elif target_weight == 0 and current_weight > 0:
                action = "SELL"
            elif target_weight > 0 and current_weight == 0:
                action = "ADD"
            elif weight_delta > 0:
                action = "INCREASE"
            elif weight_delta < 0:
                action = "DECREASE"
            else:
                action = "HOLD"

            price_context = self._get_price_context(ticker)
            currency = price_context.currency or (current_pos.currency if current_pos else self._get_ticker_currency(ticker))

            # Align with existing position currency when possible
            if current_pos and currency and current_pos.currency and currency != current_pos.currency:
                if self.verbose:
                    print(f"⚠️  Currency update for {ticker}: {current_pos.currency} → {currency}")

            fx_rate = self.exchange_rates.get(currency, 1.0)
            target_value_home = target_weight * total_value

            # Select trade price based on intended action
            if action in {"ADD", "INCREASE"}:
                trade_price = price_context.buy_price or price_context.entry_price
            elif action in {"SELL", "DECREASE"}:
                trade_price = price_context.sell_price or price_context.entry_price
            else:
                trade_price = price_context.entry_price

            # Fallback handling for missing price context
            if current_pos and price_context.sample_size == 0:
                trade_price = current_pos.cost_basis or trade_price
                currency = current_pos.currency or currency
                fx_rate = self.exchange_rates.get(currency, 1.0)

            if trade_price <= 0:
                fallback_price = price_context.latest_close
                if (fallback_price is None or fallback_price <= 0) and current_pos:
                    fallback_price = current_pos.cost_basis
                trade_price = fallback_price if fallback_price and fallback_price > 0 else 100.0

            trade_price_home = trade_price * fx_rate
            target_shares = target_value_home / trade_price_home if trade_price_home > 0 else 0
            value_delta = (target_shares - current_shares) * trade_price

            recommendations.append(
                {
                    "ticker": ticker,
                    "action": action,
                    "current_shares": current_shares,
                    "current_weight": current_weight,
                    "target_shares": target_shares,
                    "target_weight": target_weight,
                    "value_delta": value_delta,
                    "confidence": 0.75,  # Simplified
                    "reasoning": f"Target allocation: {target_weight:.1%}",
                    "current_price": trade_price,
                    "currency": currency,
                    "pricing_basis": price_context.entry_price,
                    "pricing_band": {"low": price_context.band_low, "high": price_context.band_high},
                    "latest_close": price_context.latest_close,
                    "atr": price_context.atr,
                    "pricing_sample": price_context.sample_size,
                    "pricing_source": price_context.source,
                }
            )

        # Validate and adjust for cash constraints per currency
        recommendations = self._validate_cash_constraints(recommendations)

        for rec in recommendations:
            if rec["ticker"].upper() != "CASH":
                rec["target_shares"] = max(0, round(rec["target_shares"]))
            delta_shares = rec["target_shares"] - rec["current_shares"]
            rec["value_delta"] = delta_shares * rec["current_price"]

            # Recalculate target_weight after rounding shares (must convert to home currency)
            fx_rate = self.exchange_rates.get(rec["currency"], 1.0)
            position_value_home = rec["target_shares"] * rec["current_price"] * fx_rate
            rec["target_weight"] = position_value_home / total_value if total_value > 0 else 0.0

        return recommendations

    def _validate_cash_constraints(self, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate that recommendations don't exceed available cash.
        All calculations in HOME CURRENCY to handle multi-currency portfolios.
        Scale down ALL purchases proportionally if total cash insufficient.
        """
        # Calculate total cash available in HOME CURRENCY
        total_cash_available = 0.0
        for currency, cash in self.portfolio.cash_holdings.items():
            fx_rate = self.exchange_rates.get(currency, 1.0)
            total_cash_available += cash * fx_rate

        # Calculate net cash needed (in home currency) from purchases and sales
        net_cash_needed = 0.0

        for rec in recommendations:
            fx_rate = self.exchange_rates.get(rec["currency"], 1.0)

            if rec["action"] == "SELL":
                # Selling adds cash (convert to home currency)
                net_cash_needed -= rec["current_shares"] * rec["current_price"] * fx_rate

            elif rec["action"] == "ADD":
                # Buying deducts cash (convert to home currency)
                net_cash_needed += rec["target_shares"] * rec["current_price"] * fx_rate

            elif rec["action"] == "INCREASE":
                # Get existing position to calculate delta (convert to home currency)
                existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                if existing:
                    delta_shares = rec["target_shares"] - existing.shares
                    net_cash_needed += delta_shares * rec["current_price"] * fx_rate

            elif rec["action"] == "DECREASE":
                # Decreasing adds cash back (convert to home currency)
                existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                if existing:
                    delta_shares = existing.shares - rec["target_shares"]
                    net_cash_needed -= delta_shares * rec["current_price"] * fx_rate

        # Check if we need to scale down purchases
        if net_cash_needed > total_cash_available:
            # Calculate total value of all purchases (in home currency)
            total_purchases = 0.0
            for rec in recommendations:
                fx_rate = self.exchange_rates.get(rec["currency"], 1.0)

                if rec["action"] == "ADD":
                    total_purchases += rec["target_shares"] * rec["current_price"] * fx_rate
                elif rec["action"] == "INCREASE":
                    existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                    if existing:
                        delta_shares = rec["target_shares"] - existing.shares
                        total_purchases += delta_shares * rec["current_price"] * fx_rate

            if total_purchases > 0:
                # Scale factor to fit within available cash (99% to leave buffer)
                scale_factor = (total_cash_available * 0.99) / total_purchases

                # Apply scaling to ALL purchases proportionally
                for rec in recommendations:
                    if rec["action"] in ["ADD", "INCREASE"]:
                        if rec["action"] == "ADD":
                            rec["target_shares"] *= scale_factor
                            rec["target_weight"] *= scale_factor
                        elif rec["action"] == "INCREASE":
                            existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                            if existing:
                                delta_shares = rec["target_shares"] - existing.shares
                                scaled_delta = delta_shares * scale_factor
                                rec["target_shares"] = existing.shares + scaled_delta
                                rec["target_weight"] *= scale_factor

        return recommendations

    def _calculate_updated_portfolio(self, recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate the updated portfolio after applying recommendations
        Properly handles date_acquired for new and modified positions
        Deducts cash for purchases and adds cash for sales
        """
        updated_positions = []
        updated_cash = dict(self.portfolio.cash_holdings)  # Copy current cash

        if self.home_currency not in updated_cash:
            updated_cash[self.home_currency] = 0.0

        for rec in recommendations:
            ticker = rec["ticker"]
            currency = rec["currency"]

            if rec["action"] == "SELL":
                # Add cash back from sale (in home currency)
                sale_value = rec["current_shares"] * rec["current_price"]
                fx_rate = self.exchange_rates.get(currency, 1.0)
                updated_cash[self.home_currency] += sale_value * fx_rate
                # Position sold, not included in output
                continue

            elif rec["action"] == "ADD":
                # Deduct cash for purchase (in home currency)
                purchase_value = rec["target_shares"] * rec["current_price"]
                fx_rate = self.exchange_rates.get(currency, 1.0)
                updated_cash[self.home_currency] -= purchase_value * fx_rate

                # New position - use today's date
                updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": rec["current_price"], "currency": rec["currency"], "date_acquired": datetime.now().strftime("%Y-%m-%d")})

            elif rec["action"] in ["INCREASE", "DECREASE", "HOLD"]:
                # Find existing position
                existing = next((p for p in self.portfolio.positions if p.ticker == ticker), None)

                if existing and rec["target_shares"] > 0:
                    if rec["action"] == "INCREASE":
                        # Deduct cash for additional shares (in home currency)
                        delta_shares = rec["target_shares"] - existing.shares
                        purchase_value = delta_shares * rec["current_price"]
                        fx_rate = self.exchange_rates.get(currency, 1.0)
                        updated_cash[self.home_currency] -= purchase_value * fx_rate

                        # Calculate updated cost basis
                        new_cost_basis = compute_cost_basis_after_rebalance(
                            existing_shares=existing.shares,
                            existing_cost_basis=existing.cost_basis,
                            existing_currency=existing.currency,
                            current_price=rec["current_price"],
                            target_currency=rec["currency"],
                            target_shares=rec["target_shares"],
                            action=rec["action"],
                        )
                    elif rec["action"] == "DECREASE":
                        # Add cash back from partial sale (in home currency)
                        delta_shares = existing.shares - rec["target_shares"]
                        sale_value = delta_shares * rec["current_price"]
                        fx_rate = self.exchange_rates.get(currency, 1.0)
                        updated_cash[self.home_currency] += sale_value * fx_rate

                        new_cost_basis = compute_cost_basis_after_rebalance(
                            existing_shares=existing.shares,
                            existing_cost_basis=existing.cost_basis,
                            existing_currency=existing.currency,
                            current_price=rec["current_price"],
                            target_currency=rec["currency"],
                            target_shares=rec["target_shares"],
                            action=rec["action"],
                        )
                    else:
                        new_cost_basis = compute_cost_basis_after_rebalance(
                            existing_shares=existing.shares,
                            existing_cost_basis=existing.cost_basis,
                            existing_currency=existing.currency,
                            current_price=rec["current_price"],
                            target_currency=rec["currency"],
                            target_shares=rec["target_shares"],
                            action=rec["action"],
                        )

                    updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": new_cost_basis, "currency": rec["currency"], "date_acquired": existing.date_acquired.strftime("%Y-%m-%d") if existing.date_acquired else ""})

        return {"positions": updated_positions, "cash": updated_cash}

    def _portfolio_summary(self) -> Dict[str, Any]:
        """Generate summary of current portfolio in HOME CURRENCY"""
        # Convert position values to home currency
        total_value = 0.0
        for p in self.portfolio.positions:
            fx_rate = self.exchange_rates.get(p.currency, 1.0)
            total_value += p.shares * p.cost_basis * fx_rate

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
