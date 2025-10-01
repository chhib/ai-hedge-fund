from src.backtesting.engine import BacktestEngine
from tests.backtesting.integration.mocks import MockConfigurableAgent


def test_long_short_strategy_partial_exits():
    """Simultaneous long and short with partial exits on both sides."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    # Day 1: Long TTWO 60, Short LUG 20
    # Day 2: Hold
    # Day 3: Sell 20 TTWO (partial), Cover 10 LUG (partial)
    # Day 4: Hold
    decision_sequence = [
        {"TTWO": {"action": "buy", "quantity": 60}, "LUG": {"action": "short", "quantity": 20}},
        {},
        {"TTWO": {"action": "sell", "quantity": 20}, "LUG": {"action": "cover", "quantity": 10}},
        {},
    ]

    agent = MockConfigurableAgent(decision_sequence, tickers)

    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_currency="SEK",
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )

    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()

    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]

    # Final positions: TTWO long 40, LUG short 10, FDEV flat
    assert positions["TTWO"]["long"] == 40
    assert positions["TTWO"]["short"] == 0
    assert positions["LUG"]["short"] == 10
    assert positions["LUG"]["long"] == 0
    assert positions["FDEV"]["long"] == 0
    assert positions["FDEV"]["short"] == 0

    # Realized PnL on both sides where we exited partially
    assert realized_gains["TTWO"]["long"] != 0.0
    assert realized_gains["LUG"]["short"] != 0.0
    assert realized_gains["FDEV"]["long"] == 0.0
    assert realized_gains["FDEV"]["short"] == 0.0

    # Cost bases: remaining open legs should have positive cost basis
    assert positions["TTWO"]["long_cost_basis"] > 0.0
    assert positions["LUG"]["short_cost_basis"] > 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    # Summary consistency
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert portfolio_summary["return_pct"] == expected_return_pct
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value


def test_long_short_strategy_full_liquidation_to_cash():
    """Start with mixed longs and shorts, then fully exit to all cash."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        # Day 1: Open mixed book
        {"TTWO": {"action": "buy", "quantity": 50}, "LUG": {"action": "short", "quantity": 25}, "FDEV": {"action": "buy", "quantity": 30}},
        # Day 2: Hold
        {},
        # Day 3: Exit longs
        {"TTWO": {"action": "sell", "quantity": 50}, "FDEV": {"action": "sell", "quantity": 30}},
        # Day 4: Cover remaining shorts
        {"LUG": {"action": "cover", "quantity": 25}},
    ]

    agent = MockConfigurableAgent(decision_sequence, tickers)

    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_currency="SEK",
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )

    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()

    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]

    # All flat after liquidation
    for t in tickers:
        assert positions[t]["long"] == 0
        assert positions[t]["short"] == 0

    # Realized PnL on all tickers as they were exited
    assert realized_gains["TTWO"]["long"] != 0.0
    assert realized_gains["FDEV"]["long"] != 0.0
    assert realized_gains["LUG"]["short"] != 0.0

    # Cost basis reset on both sides
    assert positions["TTWO"]["long_cost_basis"] == 0.0
    assert positions["FDEV"]["long_cost_basis"] == 0.0
    assert positions["LUG"]["short_cost_basis"] == 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert portfolio_summary["return_pct"] == expected_return_pct

    # With all positions closed, total position value should be zero and value ~ cash
    assert portfolio_summary["total_position_value"] == 0.0
    assert abs(final_portfolio_value - final_cash) < 0.01


def test_long_short_strategy_directional_flip_on_ticker():
    """Exit long fully, then open short on same ticker later (and vice versa on another)."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        # Day 1: Long TTWO 40, Short FDEV 20
        {"TTWO": {"action": "buy", "quantity": 40}, "FDEV": {"action": "short", "quantity": 20}},
        # Day 2: Exit TTWO long fully; exit FDEV short fully
        {"TTWO": {"action": "sell", "quantity": 40}, "FDEV": {"action": "cover", "quantity": 20}},
        # Day 3: Flip directions: Short TTWO 25, Long FDEV 15
        {"TTWO": {"action": "short", "quantity": 25}, "FDEV": {"action": "buy", "quantity": 15}},
        # Day 4: Hold
        {},
    ]

    agent = MockConfigurableAgent(decision_sequence, tickers)

    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_currency="SEK",
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )

    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()

    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]

    # Final: TTWO short 25, FDEV long 15, LUG flat
    assert positions["TTWO"]["short"] == 25
    assert positions["TTWO"]["long"] == 0
    assert positions["FDEV"]["long"] == 15
    assert positions["FDEV"]["short"] == 0
    assert positions["LUG"]["long"] == 0
    assert positions["LUG"]["short"] == 0

    # After flipping: earlier legs realized PnL and cost bases reset
    assert realized_gains["TTWO"]["long"] != 0.0  # from exit of long
    assert realized_gains["FDEV"]["short"] != 0.0  # from cover of short
    assert positions["TTWO"]["long_cost_basis"] == 0.0
    assert positions["FDEV"]["short_cost_basis"] == 0.0

    # New legs have cost bases initialized
    assert positions["TTWO"]["short_cost_basis"] > 0.0
    assert positions["FDEV"]["long_cost_basis"] > 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert portfolio_summary["return_pct"] == expected_return_pct
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value


def test_long_short_strategy_dca_both_sides():
    """Add to existing long and short (averaging), then partially exit both."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        # Day 1: seed positions
        {"TTWO": {"action": "buy", "quantity": 30}, "LUG": {"action": "short", "quantity": 15}},
        # Day 2: add to both sides (new prices -> test weighted cost bases)
        {"TTWO": {"action": "buy", "quantity": 20}, "LUG": {"action": "short", "quantity": 10}},
        # Day 3: hold
        {},
        # Day 4: partial exits: sell some TTWO, cover some LUG
        {"TTWO": {"action": "sell", "quantity": 25}, "LUG": {"action": "cover", "quantity": 12}},
    ]

    agent = MockConfigurableAgent(decision_sequence, tickers)

    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_currency="SEK",
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )

    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()

    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]

    # TTWO: 30+20=50 then sell 25 -> 25 remaining long
    assert positions["TTWO"]["long"] == 25
    # LUG: 15+10=25 then cover 12 -> 13 remaining short
    assert positions["LUG"]["short"] == 13
    # FDEV unused
    assert positions["FDEV"]["long"] == 0
    assert positions["FDEV"]["short"] == 0

    # Weighted cost bases should be positive for both remaining open legs
    assert positions["TTWO"]["long_cost_basis"] > 0.0
    assert positions["LUG"]["short_cost_basis"] > 0.0

    # Realized PnL should be non-zero on both partial exits
    assert realized_gains["TTWO"]["long"] != 0.0
    assert realized_gains["LUG"]["short"] != 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert portfolio_summary["return_pct"] == expected_return_pct
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value
    # Mixed book remains -> non-zero position value magnitude
    assert abs(portfolio_summary["total_position_value"]) > 0.0


