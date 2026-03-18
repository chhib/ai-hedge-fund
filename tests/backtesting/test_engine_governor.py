from src.analytics.scorecard import RegimeScorecardResult
from src.backtesting.engine import BacktestEngine
from src.services.portfolio_governor import GovernorDecision


def test_backtest_governor_blocks_buy_execution(monkeypatch, price_df_factory):
    monkeypatch.setenv("BORSDATA_API_KEY", "test-key")
    monkeypatch.setattr("src.backtesting.engine.get_ticker_market", lambda ticker: "global")
    monkeypatch.setattr(
        "src.backtesting.engine.build_regime_scorecard",
        lambda analyst_names, ticker_markets: RegimeScorecardResult(
            analyst_scores=[],
            regime_scores={},
            benchmark_ticker="SPY",
            regime_by_date={},
            date_range="n/a",
            evaluable_dates=0,
            horizon=7,
            total_outcomes=0,
        ),
    )

    def dummy_agent(**kwargs):
        return {
            "decisions": {"TTWO": {"action": "buy", "quantity": 10}},
            "analyst_signals": {},
        }

    halted = GovernorDecision(
        profile="preservation",
        benchmark_ticker="SPY",
        regime="high_vol",
        risk_state="halted",
        trading_enabled=False,
        deployment_ratio=0.0,
        analyst_weights={},
        ticker_penalties={},
        max_position_override=0.0,
        min_cash_buffer=1.0,
        reasons=["halt"],
        average_credibility=1.0,
        average_conviction=0.0,
        bullish_breadth=0.0,
        benchmark_drawdown_pct=-15.0,
        analyst_scores=[],
    )
    monkeypatch.setattr(
        "src.backtesting.engine.PortfolioGovernor.evaluate",
        lambda self, **kwargs: halted,
    )
    monkeypatch.setattr(BacktestEngine, "_prefetch_data", lambda self: None)
    monkeypatch.setattr(
        "src.backtesting.engine.get_price_data",
        lambda ticker, start, end: price_df_factory([100.0, 100.0]),
    )
    monkeypatch.setattr(
        "src.backtesting.engine.OutputBuilder.build_day_rows",
        lambda self, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.backtesting.engine.OutputBuilder.print_rows",
        lambda self, rows, context=None: None,
    )
    monkeypatch.setattr(
        "src.backtesting.engine.BenchmarkCalculator.get_return_pct",
        lambda self, ticker, start, end: 0.0,
    )

    engine = BacktestEngine(
        agent=dummy_agent,
        tickers=["TTWO"],
        start_date="2025-01-02",
        end_date="2025-01-03",
        initial_capital=100_000.0,
        initial_currency="USD",
        model_name="m",
        model_provider="p",
        selected_analysts=[],
        initial_margin_requirement=0.0,
        use_governor=True,
    )

    engine.run_backtest()

    assert engine._portfolio.get_positions()["TTWO"]["long"] == 0
