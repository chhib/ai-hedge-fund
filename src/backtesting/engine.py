from __future__ import annotations

from datetime import datetime, date
from typing import Sequence, Dict, Any

import pandas as pd
from dateutil.relativedelta import relativedelta

from .controller import AgentController
from .trader import TradeExecutor
from .metrics import PerformanceMetricsCalculator
from .portfolio import Portfolio
from .types import PerformanceMetrics, PortfolioValuePoint
from .valuation import calculate_portfolio_value, compute_exposures
from .output import OutputBuilder
from .benchmarks import BenchmarkCalculator

from src.tools.api import (
    get_company_events,
    get_price_data,
    get_prices,
    get_financial_metrics,
    get_insider_trades,
)
from src.data.models import CompanyEvent, InsiderTrade


class BacktestEngine:
    """Coordinates the backtest loop using the new components.

    This implementation mirrors the semantics of src/backtester.py while
    avoiding any changes to that file. It orchestrates agent decisions,
    trade execution, valuation, exposures and performance metrics.
    """

    def __init__(
        self,
        *,
        agent,
        tickers: list[str],
        start_date: str,
        end_date: str,
        initial_capital: float,
        model_name: str,
        model_provider: str,
        selected_analysts: list[str] | None,
        initial_margin_requirement: float,
    ) -> None:
        self._agent = agent
        self._tickers = tickers
        self._start_date = start_date
        self._end_date = end_date
        self._initial_capital = float(initial_capital)
        self._model_name = model_name
        self._model_provider = model_provider
        self._selected_analysts = selected_analysts
        self._start_date_obj = datetime.strptime(self._start_date, "%Y-%m-%d").date()
        self._benchmark_ticker = "OMXS30"  # Default benchmark

        self._portfolio = Portfolio(
            tickers=tickers,
            initial_cash=initial_capital,
            margin_requirement=initial_margin_requirement,
        )
        self._executor = TradeExecutor()
        self._agent_controller = AgentController()
        self._perf = PerformanceMetricsCalculator()
        self._results = OutputBuilder(initial_capital=self._initial_capital)

        # Benchmark calculator
        self._benchmark = BenchmarkCalculator()

        self._portfolio_values: list[PortfolioValuePoint] = []
        self._table_rows: list[list] = []
        self._performance_metrics: PerformanceMetrics = {
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown": None,
            "long_short_ratio": None,
            "gross_exposure": None,
            "net_exposure": None,
        }
        self._prefetched_company_events: dict[str, list[Any]] = {}
        self._prefetched_insider_trades: dict[str, list[Any]] = {}
        self._daily_context: list[dict[str, Any]] = []

    def _prefetch_data(self) -> None:
        end_date_dt = datetime.strptime(self._end_date, "%Y-%m-%d")
        start_date_dt = end_date_dt - relativedelta(years=1)
        start_date_str = start_date_dt.strftime("%Y-%m-%d")

        for ticker in self._tickers:
            get_prices(ticker, start_date_str, self._end_date)
            get_financial_metrics(ticker, self._end_date, limit=10)
            insider_trades = get_insider_trades(
                ticker,
                self._end_date,
                start_date=self._start_date,
                limit=1000,
            )
            company_events = get_company_events(
                ticker,
                self._end_date,
                start_date=self._start_date,
                limit=1000,
            )
            self._prefetched_insider_trades[ticker] = insider_trades
            self._prefetched_company_events[ticker] = company_events
        
        # Preload data for benchmark comparison
        get_prices(self._benchmark_ticker, self._start_date, self._end_date)

    def _build_context_for_date(self, *, current_date: date) -> dict[str, Any]:
        context_events: dict[str, list[dict[str, Any]]] = {}
        context_insider: dict[str, list[dict[str, Any]]] = {}
        for ticker in self._tickers:
            events = self._prefetched_company_events.get(ticker, [])
            filtered_events: list[dict[str, Any]] = []
            for event in events:
                if isinstance(event, CompanyEvent):
                    event_date_str = event.date
                    event_payload = event.model_dump()
                elif isinstance(event, dict):
                    event_date_str = event.get("date")
                    event_payload = dict(event)
                else:
                    continue
                try:
                    event_date = date.fromisoformat(event_date_str)
                except (TypeError, ValueError):
                    continue
                if self._start_date_obj <= event_date <= current_date:
                    filtered_events.append(event_payload)
            if filtered_events:
                context_events[ticker] = filtered_events

            trades = self._prefetched_insider_trades.get(ticker, [])
            filtered_trades: list[dict[str, Any]] = []
            for trade in trades:
                if isinstance(trade, InsiderTrade):
                    trade_date_str = trade.transaction_date or trade.filing_date
                    trade_payload = trade.model_dump()
                elif isinstance(trade, dict):
                    trade_date_str = trade.get("transaction_date") or trade.get("filing_date")
                    trade_payload = dict(trade)
                else:
                    continue
                if not trade_date_str:
                    continue
                try:
                    trade_date = date.fromisoformat(trade_date_str)
                except (TypeError, ValueError):
                    continue
                if self._start_date_obj <= trade_date <= current_date:
                    filtered_trades.append(trade_payload)
            if filtered_trades:
                context_insider[ticker] = filtered_trades

        return {
            "date": current_date.strftime("%Y-%m-%d"),
            "company_events": context_events,
            "insider_trades": context_insider,
        }


    def run_backtest(self) -> PerformanceMetrics:
        self._prefetch_data()

        dates = pd.date_range(self._start_date, self._end_date, freq="B")
        if len(dates) > 0:
            self._portfolio_values = [
                {"Date": dates[0], "Portfolio Value": self._initial_capital}
            ]
        else:
            self._portfolio_values = []

        for current_date in dates:
            lookback_start = (current_date - relativedelta(months=1)).strftime("%Y-%m-%d")
            current_date_str = current_date.strftime("%Y-%m-%d")
            previous_date_str = (current_date - relativedelta(days=1)).strftime("%Y-%m-%d")
            if lookback_start == current_date_str:
                continue

            try:
                current_prices: Dict[str, float] = {}
                missing_data = False
                for ticker in self._tickers:
                    try:
                        price_data = get_price_data(ticker, previous_date_str, current_date_str)
                        if price_data.empty:
                            missing_data = True
                            break
                        current_prices[ticker] = float(price_data.iloc[-1]["close"])
                    except Exception:
                        missing_data = True
                        break
                if missing_data:
                    continue
            except Exception:
                continue

            agent_output = self._agent_controller.run_agent(
                self._agent,
                tickers=self._tickers,
                start_date=lookback_start,
                end_date=current_date_str,
                portfolio=self._portfolio,
                model_name=self._model_name,
                model_provider=self._model_provider,
                selected_analysts=self._selected_analysts,
            )
            decisions = agent_output["decisions"]

            executed_trades: Dict[str, int] = {}
            for ticker in self._tickers:
                d = decisions.get(ticker, {"action": "hold", "quantity": 0})
                action = d.get("action", "hold")
                qty = d.get("quantity", 0)
                executed_qty = self._executor.execute_trade(ticker, action, qty, current_prices[ticker], self._portfolio)
                executed_trades[ticker] = executed_qty

            total_value = calculate_portfolio_value(self._portfolio, current_prices)
            exposures = compute_exposures(self._portfolio, current_prices)

            point: PortfolioValuePoint = {
                "Date": current_date,
                "Portfolio Value": total_value,
                "Long Exposure": exposures["Long Exposure"],
                "Short Exposure": exposures["Short Exposure"],
                "Gross Exposure": exposures["Gross Exposure"],
                "Net Exposure": exposures["Net Exposure"],
                "Long/Short Ratio": exposures["Long/Short Ratio"],
            }
            self._portfolio_values.append(point)
            
            # Build daily rows (stateless usage)
            rows = self._results.build_day_rows(
                date_str=current_date_str,
                tickers=self._tickers,
                agent_output=agent_output,
                executed_trades=executed_trades,
                current_prices=current_prices,
                portfolio=self._portfolio,
                performance_metrics=self._performance_metrics,
                total_value=total_value,
                benchmark_return_pct=self._benchmark.get_return_pct(self._benchmark_ticker, self._start_date, current_date_str),
            )
            # Prepend today's rows to historical rows so latest day is on top
            self._table_rows = rows + self._table_rows
            latest_context = self._build_context_for_date(current_date=current_date.date())
            self._daily_context.append(latest_context)
            # Print full history with latest day first (matches backtester.py behavior)
            self._results.print_rows(self._table_rows, context=latest_context)

            # Update performance metrics after printing (match original timing)
            if len(self._portfolio_values) > 3:
                computed = self._perf.compute_metrics(self._portfolio_values)
                if computed:
                    self._performance_metrics.update(computed)

        return self._performance_metrics

    def get_portfolio_values(self) -> Sequence[PortfolioValuePoint]:
        return list(self._portfolio_values)

    def get_daily_context(self) -> Sequence[dict[str, Any]]:
        return list(self._daily_context)
