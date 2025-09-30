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

    def __init__(self, portfolio: Portfolio, universe: List[str], analysts: List[str], model_config: Dict[str, Any], verbose: bool = False):
        self.portfolio = portfolio
        self.universe = universe
        self.analyst_names = analysts
        self.model_config = model_config
        self.verbose = verbose
        self.analysts = self._initialize_analysts(analysts, model_config)

    def _initialize_analysts(self, analyst_names: List[str], model_config: Dict[str, Any]) -> List[Any]:
        """
        Initialize only the requested analysts from existing codebase
        This wraps existing analyst classes without modifying them
        """
        # Import analysts dynamically to avoid circular dependencies
        # Note: Only importing analysts with class-based Agent interfaces
        # Other analysts (druckenmiller, lynch, etc.) are function-based and require LangGraph state
        try:
            from src.agents.fundamentals import FundamentalsAnalyst
            from src.agents.warren_buffett import WarrenBuffettAgent
            from src.agents.charlie_munger import CharlieMungerAgent

            analyst_map = {
                # Basic class-based analyst
                "fundamentals": FundamentalsAnalyst,
                # Famous investor personas with class-based interfaces
                "warren_buffett": WarrenBuffettAgent,
                "buffett": WarrenBuffettAgent,
                "charlie_munger": CharlieMungerAgent,
                "munger": CharlieMungerAgent,
            }

            analysts = []
            for name in analyst_names:
                name_lower = name.lower().strip()
                if name_lower in analyst_map:
                    # These are class-based analysts that can be instantiated
                    analysts.append({"name": name_lower, "class": analyst_map[name_lower]})
                else:
                    print(f"Warning: Unknown analyst '{name}' - skipping")

            return analysts
        except ImportError as e:
            print(f"Warning: Could not import all analysts: {e}")
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
        Calls each analyst's analyze() method with financial data
        """
        signals = []

        if not self.analysts:
            print(f"Warning: No analysts initialized")
            return signals

        print(f"Collecting signals from {len(self.analysts)} analysts for {len(self.universe)} tickers...")

        # Import financial data fetching
        from src.tools.api import get_financial_metrics
        import os

        api_key = os.getenv("BORSDATA_API_KEY")
        if not api_key:
            print("Warning: BORSDATA_API_KEY not found - using neutral signals")
            return signals

        # Use today's date as end_date
        end_date = datetime.now().strftime("%Y-%m-%d")

        # For each ticker, collect signals from all analysts
        for ticker in self.universe:
            try:
                # Fetch financial metrics for this ticker
                financial_data_list = get_financial_metrics(ticker=ticker, end_date=end_date, period="ttm", limit=10, api_key=api_key)

                if financial_data_list and len(financial_data_list) > 0:
                    # Use the most recent metrics
                    financial_data = financial_data_list[0]

                    # Call each analyst with this data
                    for analyst_info in self.analysts:
                        analyst_name = analyst_info["name"]
                        analyst_class = analyst_info["class"]

                        try:
                            # Instantiate analyst
                            analyst_instance = analyst_class()

                            # Call analyze with context
                            context = {"financial_data": financial_data}
                            result = analyst_instance.analyze(context)

                            # Convert signal to numeric score (-1 to 1)
                            signal_map = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
                            numeric_signal = signal_map.get(result.signal, 0.0)

                            # Convert confidence to 0-1 scale
                            confidence = result.confidence / 100.0

                            signals.append(AnalystSignal(ticker=ticker, analyst=analyst_name, signal=numeric_signal, confidence=confidence, reasoning=result.reasoning))

                            if self.verbose:
                                print(f"  {ticker} - {analyst_name}: {result.signal} (confidence: {result.confidence}%)")

                        except Exception as e:
                            if self.verbose:
                                print(f"  Warning: Analyst {analyst_name} failed for {ticker}: {e}")
                            continue
                else:
                    # No financial data available
                    if self.verbose:
                        print(f"  No financial data for {ticker}")

            except Exception as e:
                if self.verbose:
                    print(f"  Warning: Could not fetch data for {ticker}: {e}")
                continue

        print(f"✓ Collected {len(signals)} signals from {len(self.analysts)} analysts")
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