from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

from src.utils.portfolio_loader import Portfolio


@dataclass
class AnalystSignal:
    ticker: str
    analyst: str
    signal: float  # -1 to 1 (negative = bearish, positive = bullish)
    confidence: float  # 0 to 1
    reasoning: str


class EnhancedPortfolioManager:
    """
    Portfolio Manager that aggregates analyst signals for LONG-ONLY portfolios
    Handles conflicting signals by averaging and applying long-only constraint
    Maintains concentrated portfolio of 5-10 positions
    """

    def __init__(self, portfolio: Portfolio, universe: List[str], analysts: List[str], model_config: Dict[str, Any], ticker_markets: Dict[str, str] = None, verbose: bool = False, session_id: str = None):
        self.portfolio = portfolio
        self.universe = universe
        self.analyst_names = analysts
        self.model_config = model_config
        self.ticker_markets = ticker_markets or {}
        self.verbose = verbose
        self.session_id = session_id
        self.analysts = self._initialize_analysts(analysts, model_config)

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
                        "func": config["agent_func"]
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

        if self.verbose:
            print("Pre-populating instrument caches...")
        try:
            _borsdata_client.get_instruments(force_refresh=False)
            if self.verbose:
                print("✓ Nordic instruments cache populated")
            _borsdata_client.get_all_instruments(force_refresh=False)
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

        prefetched_data = run_parallel_fetch_ticker_data(
            tickers=self.universe,
            end_date=end_date,
            include_prices=True,
            include_metrics=True,
            include_line_items=True,
            include_insider_trades=True,
            include_events=True,
            include_market_caps=True,
            ticker_markets=self.ticker_markets,
            progress_callback=progress.update_prefetch_status,
        )

        progress.stop()

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

            # Calculate next ticker for this analyst
            next_ticker = self.universe[ticker_idx + 1] if ticker_idx + 1 < len(self.universe) else None

            # Update progress: analyzing
            progress.update_status(agent_id, ticker, f"Generating {display_name} analysis", next_ticker=next_ticker)

            try:
                # Suppress agent print statements (like show_agent_reasoning)
                if not self.verbose:
                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()

                try:
                    # Call the function-based analyst
                    result_state = analyst_func(state.copy()) # Use a copy of the state for each thread
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
                    return None

                # Get the ticker's analysis
                ticker_analysis = analysis.get(ticker, {})
                if not ticker_analysis:
                    progress.update_status(agent_id, ticker, "Error")
                    if self.verbose:
                        print(f"  Warning: No analysis for {ticker} from {display_name}")
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

                # Save to database if session_id is provided
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
                            model_name=self.model_config.get("name"),
                            model_provider=self.model_config.get("provider"),
                        )
                    except Exception as e:
                        if self.verbose:
                            print(f"  Warning: Failed to save analysis to database: {e}")

                return AnalystSignal(ticker=ticker, analyst=analyst_name, signal=numeric_signal, confidence=confidence, reasoning=reasoning)

            except Exception as e:
                progress.update_status(agent_id, ticker, "Error", next_ticker=next_ticker)
                if self.verbose:
                    print(f"\n  Warning: Analyst {display_name} failed for {ticker}: {e}")
                    import traceback
                    traceback.print_exc()
                return None

        for ticker_idx, ticker in enumerate(self.universe):
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

            with ThreadPoolExecutor(max_workers=len(self.analysts)) as executor:
                future_to_analyst = {executor.submit(run_analyst, analyst_info, state, ticker, ticker_idx): analyst_info for analyst_info in self.analysts}
                for future in as_completed(future_to_analyst):
                    result = future.result()
                    if result:
                        signals.append(result)

        # Stop progress display and show summary
        progress.stop()
        print(f"\n✓ Collected {len(signals)} signals from {len(self.analysts)} analysts across {len(self.universe)} tickers\n")
        return signals

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
        Prioritizes: current holdings (unless score very low) + highest scoring new positions
        """
        current_tickers = {p.ticker for p in self.portfolio.positions}

        # Separate current holdings and new opportunities
        current_scores = {t: s for t, s in scores.items() if t in current_tickers}
        new_scores = {t: s for t, s in scores.items() if t not in current_tickers}

        # Keep current holdings unless score is very low
        SELL_THRESHOLD = 0.3  # Below this, consider selling even current holdings
        holdings_to_keep = [t for t, score in current_scores.items() if score >= SELL_THRESHOLD]

        # How many new positions can we add?
        slots_available = max_holdings - len(holdings_to_keep)

        # Get best new opportunities
        sorted_new = sorted(new_scores.items(), key=lambda x: x[1], reverse=True)
        MIN_SCORE_FOR_NEW = 0.6  # Higher bar for new positions
        new_additions = [t for t, score in sorted_new[:slots_available] if score >= MIN_SCORE_FOR_NEW]

        return holdings_to_keep + new_additions

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
                return currency
        except Exception as e:
            if self.verbose:
                print(f"Warning: Could not fetch currency for {ticker}: {e}")

        # Fallback
        market = self.ticker_markets.get(ticker, "global")
        return "SEK" if market == "Nordic" else "USD"

    def _get_current_price(self, ticker: str) -> tuple[float, str]:
        """
        Fetch current price and currency from Borsdata
        Returns (price, currency) tuple
        """
        import os
        from src.tools.api import _borsdata_client
        from datetime import datetime, timedelta

        api_key = os.getenv("BORSDATA_API_KEY")
        if not api_key:
            if self.verbose:
                print(f"Warning: No API key - using default price for {ticker}")
            return 100.0, self._get_ticker_currency(ticker)

        try:
            market = self.ticker_markets.get(ticker, "global")
            use_global = market.lower() == "global"

            # Get instrument for currency info
            instrument = _borsdata_client.get_instrument(ticker, api_key=api_key, use_global=use_global)
            currency = instrument.get("stockPriceCurrency", "USD")
            instrument_id = instrument.get("insId")

            # Fetch recent prices (last 5 days to handle weekends)
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

            prices = _borsdata_client.get_stock_prices(
                instrument_id,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
            )

            if prices:
                # Get most recent price
                latest = prices[-1]
                close_price = latest.get("c")  # close price
                if close_price:
                    return float(close_price), currency

            if self.verbose:
                print(f"Warning: No recent prices for {ticker}, using default")
            return 100.0, currency

        except Exception as e:
            if self.verbose:
                print(f"Warning: Could not fetch price for {ticker}: {e}")
            return 100.0, self._get_ticker_currency(ticker)

    def _generate_recommendations(self, target_positions: Dict[str, float], min_trade_size: float) -> List[Dict[str, Any]]:
        """
        Generate trading recommendations based on target positions vs current portfolio
        Multi-currency aware: calculates per-currency totals and validates cash constraints
        """
        recommendations = []
        current_tickers = {p.ticker for p in self.portfolio.positions}
        all_tickers = set(list(target_positions.keys()) + list(current_tickers))

        # Calculate total portfolio value PER CURRENCY to avoid mixing SEK+USD
        currency_totals = {}
        for pos in self.portfolio.positions:
            if pos.currency not in currency_totals:
                currency_totals[pos.currency] = 0.0
            currency_totals[pos.currency] += pos.shares * pos.cost_basis

        # Add cash holdings to currency totals
        for currency, cash in self.portfolio.cash_holdings.items():
            if currency not in currency_totals:
                currency_totals[currency] = 0.0
            currency_totals[currency] += cash

        # For weight calculations, use the dominant currency total or sum (legacy behavior)
        # This maintains backward compatibility while we fix the core issue
        total_value = sum(currency_totals.values())

        for ticker in all_tickers:
            # Current position
            current_pos = next((p for p in self.portfolio.positions if p.ticker == ticker), None)
            current_weight = 0.0
            current_shares = 0.0
            if current_pos:
                current_value = current_pos.shares * current_pos.cost_basis
                current_weight = current_value / total_value if total_value > 0 else 0
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

            # Fetch current price and currency from Borsdata
            current_price, currency = self._get_current_price(ticker)

            # For existing positions, validate currency and fall back to cost basis if fetch failed
            if current_pos:
                if current_price == 100.0:  # Default price indicates fetch failure
                    current_price = current_pos.cost_basis
                    currency = current_pos.currency
                elif currency != current_pos.currency and self.verbose:
                    print(f"⚠️  Currency update for {ticker}: {current_pos.currency} → {currency}")

            # Calculate target shares
            target_value = target_weight * total_value
            target_shares = target_value / current_price if current_price > 0 else 0

            recommendations.append(
                {
                    "ticker": ticker,
                    "action": action,
                    "current_shares": current_shares,
                    "current_weight": current_weight,
                    "target_shares": target_shares,
                    "target_weight": target_weight,
                    "value_delta": weight_delta * total_value,
                    "confidence": 0.75,  # Simplified
                    "reasoning": f"Target allocation: {target_weight:.1%}",
                    "current_price": current_price,
                    "currency": currency,
                }
            )

        # Validate and adjust for cash constraints per currency
        recommendations = self._validate_cash_constraints(recommendations)

        return recommendations

    def _validate_cash_constraints(self, recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate that recommendations don't exceed available cash per currency.
        Scale down purchases if needed to respect cash limits.
        """
        # Calculate net cash flow per currency
        cash_flows = {}
        for currency in self.portfolio.cash_holdings.keys():
            cash_flows[currency] = self.portfolio.cash_holdings[currency]

        # Calculate net cash needed per currency
        for rec in recommendations:
            currency = rec["currency"]
            if currency not in cash_flows:
                cash_flows[currency] = 0.0

            if rec["action"] == "SELL":
                # Selling adds cash
                cash_flows[currency] += rec["current_shares"] * rec["current_price"]

            elif rec["action"] == "ADD":
                # Buying deducts cash
                cash_flows[currency] -= rec["target_shares"] * rec["current_price"]

            elif rec["action"] == "INCREASE":
                # Get existing position to calculate delta
                existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                if existing:
                    delta_shares = rec["target_shares"] - existing.shares
                    cash_flows[currency] -= delta_shares * rec["current_price"]

            elif rec["action"] == "DECREASE":
                # Decreasing adds cash back
                existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                if existing:
                    delta_shares = existing.shares - rec["target_shares"]
                    cash_flows[currency] += delta_shares * rec["current_price"]

        # Check for violations and scale down if needed
        for currency, final_cash in cash_flows.items():
            if final_cash < 0:
                # We're over-allocated in this currency - need to scale down purchases
                deficit = abs(final_cash)
                available = self.portfolio.cash_holdings.get(currency, 0)

                # Calculate total purchases in this currency
                purchase_value = 0.0
                for rec in recommendations:
                    if rec["currency"] == currency:
                        if rec["action"] == "ADD":
                            purchase_value += rec["target_shares"] * rec["current_price"]
                        elif rec["action"] == "INCREASE":
                            existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                            if existing:
                                delta_shares = rec["target_shares"] - existing.shares
                                purchase_value += delta_shares * rec["current_price"]

                # Also factor in cash from sales
                sales_value = 0.0
                for rec in recommendations:
                    if rec["currency"] == currency:
                        if rec["action"] == "SELL":
                            sales_value += rec["current_shares"] * rec["current_price"]
                        elif rec["action"] == "DECREASE":
                            existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                            if existing:
                                delta_shares = existing.shares - rec["target_shares"]
                                sales_value += delta_shares * rec["current_price"]

                # Calculate scaling factor - add 1% buffer to avoid rounding errors
                total_available = available + sales_value
                if purchase_value > 0:
                    scale_factor = (total_available * 0.99) / purchase_value  # 99% to leave cash buffer

                    # Scale down all purchases in this currency
                    for rec in recommendations:
                        if rec["currency"] == currency and rec["action"] in ["ADD", "INCREASE"]:
                            if rec["action"] == "ADD":
                                rec["target_shares"] *= scale_factor
                                rec["target_weight"] *= scale_factor
                            elif rec["action"] == "INCREASE":
                                existing = next((p for p in self.portfolio.positions if p.ticker == rec["ticker"]), None)
                                if existing:
                                    delta_shares = rec["target_shares"] - existing.shares
                                    scaled_delta = delta_shares * scale_factor
                                    rec["target_shares"] = existing.shares + scaled_delta
                                    # Recalculate weight (approximation)
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

        for rec in recommendations:
            ticker = rec["ticker"]
            currency = rec["currency"]

            # Ensure currency exists in cash holdings
            if currency not in updated_cash:
                updated_cash[currency] = 0.0

            if rec["action"] == "SELL":
                # Add cash back from sale
                sale_value = rec["current_shares"] * rec["current_price"]
                updated_cash[currency] += sale_value
                # Position sold, not included in output
                continue

            elif rec["action"] == "ADD":
                # Deduct cash for purchase
                purchase_value = rec["target_shares"] * rec["current_price"]
                updated_cash[currency] -= purchase_value

                # New position - use today's date
                updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": rec["current_price"], "currency": rec["currency"], "date_acquired": datetime.now().strftime("%Y-%m-%d")})

            elif rec["action"] in ["INCREASE", "DECREASE", "HOLD"]:
                # Find existing position
                existing = next((p for p in self.portfolio.positions if p.ticker == ticker), None)

                if existing and rec["target_shares"] > 0:
                    if rec["action"] == "INCREASE":
                        # Deduct cash for additional shares
                        delta_shares = rec["target_shares"] - existing.shares
                        purchase_value = delta_shares * rec["current_price"]
                        updated_cash[currency] -= purchase_value

                        # Calculate weighted average cost basis
                        old_value = existing.shares * existing.cost_basis
                        new_value = delta_shares * rec["current_price"]
                        total_value = old_value + new_value
                        total_shares = rec["target_shares"]
                        new_cost_basis = total_value / total_shares if total_shares > 0 else 0
                    elif rec["action"] == "DECREASE":
                        # Add cash back from partial sale
                        delta_shares = existing.shares - rec["target_shares"]
                        sale_value = delta_shares * rec["current_price"]
                        updated_cash[currency] += sale_value

                        # Keep existing cost basis
                        new_cost_basis = existing.cost_basis
                    else:
                        # HOLD - keep existing cost basis, no cash change
                        new_cost_basis = existing.cost_basis

                    updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": new_cost_basis, "currency": rec["currency"], "date_acquired": existing.date_acquired.strftime("%Y-%m-%d") if existing.date_acquired else ""})

        return {"positions": updated_positions, "cash": updated_cash}

    def _portfolio_summary(self) -> Dict[str, Any]:
        """Generate summary of current portfolio"""
        total_value = sum(p.shares * p.cost_basis for p in self.portfolio.positions) + sum(self.portfolio.cash_holdings.values())

        return {"total_value": total_value, "num_positions": len(self.portfolio.positions), "cash_holdings": self.portfolio.cash_holdings}