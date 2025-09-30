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

    def __init__(self, portfolio: Portfolio, universe: List[str], analysts: List[str], model_config: Dict[str, Any], ticker_markets: Dict[str, str] = None, verbose: bool = False):
        self.portfolio = portfolio
        self.universe = universe
        self.analyst_names = analysts
        self.model_config = model_config
        self.ticker_markets = ticker_markets or {}
        self.verbose = verbose
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
            print(f"Warning: No analysts initialized")
            return signals

        import os

        api_key = os.getenv("BORSDATA_API_KEY")
        if not api_key:
            print("Warning: BORSDATA_API_KEY not found - using neutral signals")
            return signals

        print(f"\n🔄 Collecting signals from {len(self.analysts)} analysts for {len(self.universe)} tickers...")

        # STEP 1: Pre-populate instrument caches (same as main.py lines 86-99)
        from src.tools.api import _borsdata_client, set_ticker_markets

        print("Pre-populating instrument caches...")
        try:
            _borsdata_client.get_instruments(force_refresh=False)
            print("✓ Nordic instruments cache populated")
            _borsdata_client.get_all_instruments(force_refresh=False)
            print("✓ Global instruments cache populated")
        except Exception as e:
            print(f"⚠️  Warning: Could not pre-populate instrument caches: {e}")

        # STEP 2: Set ticker market routing (Nordic vs Global API)
        set_ticker_markets(self.ticker_markets)

        # STEP 3: Parallel data prefetching - fetch ALL data needed by analysts
        from src.data.parallel_api_wrapper import run_parallel_fetch_ticker_data

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now().replace(year=datetime.now().year - 1)).strftime("%Y-%m-%d")

        print(f"Prefetching comprehensive data for all {len(self.universe)} tickers in parallel...")
        try:
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
            )
            print(f"✅ Parallel prefetching completed for {len(prefetched_data)} tickers\n")
        except Exception as e:
            print(f"❌ Error during parallel prefetching: {e}")
            return signals

        # STEP 4: Call function-based analysts with AgentState for each ticker
        from src.graph.state import AgentState

        for ticker in self.universe:
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
                    "show_reasoning": self.verbose,  # Required by agents
                }
            }

            # Call each analyst with this state
            for analyst_info in self.analysts:
                analyst_name = analyst_info["name"]
                analyst_func = analyst_info["func"]
                display_name = analyst_info["display_name"]

                try:
                    # Call the function-based analyst
                    result_state = analyst_func(state)

                    # Extract analysis from state - agents store in analyst_signals[agent_name_agent]
                    agent_id = f"{analyst_name}_agent"
                    analyst_signals = result_state.get("data", {}).get("analyst_signals", {})
                    analysis = analyst_signals.get(agent_id, {})

                    if not analysis or not isinstance(analysis, dict):
                        if self.verbose:
                            print(f"  Warning: No analysis returned by {display_name} for {ticker}")
                        continue

                    # Get the ticker's analysis
                    ticker_analysis = analysis.get(ticker, {})
                    if not ticker_analysis:
                        if self.verbose:
                            print(f"  Warning: No analysis for {ticker} from {display_name}")
                        continue

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

                    signals.append(AnalystSignal(
                        ticker=ticker,
                        analyst=analyst_name,
                        signal=numeric_signal,
                        confidence=confidence,
                        reasoning=reasoning
                    ))

                    if self.verbose:
                        print(f"  {ticker} - {display_name}: {signal_str} (confidence: {int(confidence * 100)}%)")

                except Exception as e:
                    if self.verbose:
                        print(f"  Warning: Analyst {display_name} failed for {ticker}: {e}")
                        import traceback
                        traceback.print_exc()
                    continue

        print(f"\n✓ Collected {len(signals)} signals from {len(self.analysts)} analysts")
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

    def _generate_recommendations(self, target_positions: Dict[str, float], min_trade_size: float) -> List[Dict[str, Any]]:
        """
        Generate trading recommendations based on target positions vs current portfolio
        """
        recommendations = []
        current_tickers = {p.ticker for p in self.portfolio.positions}
        all_tickers = set(list(target_positions.keys()) + list(current_tickers))

        # Calculate total portfolio value (simplified - using cost basis)
        total_value = sum(p.shares * p.cost_basis for p in self.portfolio.positions) + sum(self.portfolio.cash_holdings.values())

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

            # Calculate target shares (simplified - using cost basis as price)
            current_price = current_pos.cost_basis if current_pos else 100.0  # Default price
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
                    "currency": current_pos.currency if current_pos else "USD",
                }
            )

        return recommendations

    def _calculate_updated_portfolio(self, recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate the updated portfolio after applying recommendations
        Properly handles date_acquired for new and modified positions
        """
        updated_positions = []
        updated_cash = dict(self.portfolio.cash_holdings)  # Copy current cash

        for rec in recommendations:
            ticker = rec["ticker"]

            if rec["action"] == "SELL":
                # Position sold, not included in output
                continue

            elif rec["action"] == "ADD":
                # New position - use today's date
                updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": rec["current_price"], "currency": rec["currency"], "date_acquired": datetime.now().strftime("%Y-%m-%d")})

            elif rec["action"] in ["INCREASE", "DECREASE", "HOLD"]:
                # Find existing position
                existing = next((p for p in self.portfolio.positions if p.ticker == ticker), None)

                if existing and rec["target_shares"] > 0:
                    if rec["action"] == "INCREASE":
                        # Calculate weighted average cost basis
                        old_value = existing.shares * existing.cost_basis
                        new_shares = rec["target_shares"] - existing.shares
                        new_value = new_shares * rec["current_price"]
                        total_value = old_value + new_value
                        total_shares = rec["target_shares"]
                        new_cost_basis = total_value / total_shares if total_shares > 0 else 0
                    else:
                        # DECREASE or HOLD - keep existing cost basis
                        new_cost_basis = existing.cost_basis

                    updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": new_cost_basis, "currency": existing.currency, "date_acquired": existing.date_acquired.strftime("%Y-%m-%d") if existing.date_acquired else ""})

        return {"positions": updated_positions, "cash": updated_cash}

    def _portfolio_summary(self) -> Dict[str, Any]:
        """Generate summary of current portfolio"""
        total_value = sum(p.shares * p.cost_basis for p in self.portfolio.positions) + sum(self.portfolio.cash_holdings.values())

        return {"total_value": total_value, "num_positions": len(self.portfolio.positions), "cash_holdings": self.portfolio.cash_holdings}