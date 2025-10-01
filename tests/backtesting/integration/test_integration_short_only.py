from src.backtesting.engine import BacktestEngine
from tests.backtesting.integration.mocks import MockConfigurableAgent


def test_short_only_strategy_shorts_and_covers():
    """Short, hold, then partial cover. Validate positions, realized gains, and summary consistency."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    # Day1: open shorts; Day2: hold; Day3: partial cover TTWO; Day4: hold
    decision_sequence = [
        {
            "TTWO": {"action": "short", "quantity": 100},
            "LUG": {"action": "short", "quantity": 30},
        },
        {},
        {
            "TTWO": {"action": "cover", "quantity": 30},
        },
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

    # Expected: TTWO 70 short remaining, LUG 30 short, FDEV 0
    assert positions["TTWO"]["short"] == 70
    assert positions["LUG"]["short"] == 30
    assert positions["FDEV"]["short"] == 0
    # No long positions in a short-only plan
    for t in tickers:
        assert positions[t]["long"] == 0

    # TTWO partial cover should realize non-zero gains/losses; LUG none; FDEV none
    assert realized_gains["TTWO"]["short"] != 0.0
    assert realized_gains["LUG"]["short"] == 0.0
    assert realized_gains["FDEV"]["short"] == 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    actual_return_pct = portfolio_summary["return_pct"]
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct

    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value


def test_short_only_strategy_full_cover_cycle():
    """Open shorts, then fully cover all to return to flat and mostly cash."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        {
            "TTWO": {"action": "short", "quantity": 50},
            "LUG": {"action": "short", "quantity": 25},
            "FDEV": {"action": "short", "quantity": 30},
        },
        {},
        {
            "TTWO": {"action": "cover", "quantity": 50},
        },
        {
            "LUG": {"action": "cover", "quantity": 25},
            "FDEV": {"action": "cover", "quantity": 30},
        },
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

    # After full cover, all shorts 0
    assert positions["TTWO"]["short"] == 0
    assert positions["LUG"]["short"] == 0
    assert positions["FDEV"]["short"] == 0
    # No longs
    for t in tickers:
        assert positions[t]["long"] == 0

    # All tickers should have realized short-side PnL
    assert realized_gains["TTWO"]["short"] != 0.0
    assert realized_gains["LUG"]["short"] != 0.0
    assert realized_gains["FDEV"]["short"] != 0.0

    # Cost basis reset after flat
    assert positions["TTWO"]["short_cost_basis"] == 0.0
    assert positions["LUG"]["short_cost_basis"] == 0.0
    assert positions["FDEV"]["short_cost_basis"] == 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    actual_return_pct = portfolio_summary["return_pct"]
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct

    # No positions -> position value 0; portfolio value ~ cash
    assert portfolio_summary["total_position_value"] == 0.0
    assert abs(final_portfolio_value - final_cash) < 0.01


def test_short_only_strategy_multiple_short_cover_cycles():
    """Perform two complete short-cover cycles to test realized gains aggregation and resets."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        {"TTWO": {"action": "short", "quantity": 60}, "LUG": {"action": "short", "quantity": 20}},
        {"TTWO": {"action": "cover", "quantity": 60}, "LUG": {"action": "cover", "quantity": 20}},
        {"TTWO": {"action": "short", "quantity": 30}, "LUG": {"action": "short", "quantity": 10}},
        {"TTWO": {"action": "cover", "quantity": 30}, "LUG": {"action": "cover", "quantity": 10}},
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

    # Flat after cycles
    assert positions["TTWO"]["short"] == 0
    assert positions["LUG"]["short"] == 0
    assert positions["FDEV"]["short"] == 0
    for t in tickers:
        assert positions[t]["long"] == 0

    # Realized gains should be non-zero for cycled names
    assert realized_gains["TTWO"]["short"] != 0.0
    assert realized_gains["LUG"]["short"] != 0.0
    assert realized_gains["FDEV"]["short"] == 0.0

    # Cost basis resets after final flat
    assert positions["TTWO"]["short_cost_basis"] == 0.0
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

    actual_return_pct = portfolio_summary["return_pct"]
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct

    assert portfolio_summary["total_position_value"] == 0.0
    assert abs(final_portfolio_value - final_cash) < 0.01



def test_short_only_strategy_portfolio_rebalancing():
    """Rebalance across shorts: reduce TTWO short, add FDEV, then close TTWO and add to LUG."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        # Day 1: Initial shorts - focus on TTWO and LUG
        {
            "TTWO": {"action": "short", "quantity": 100},
            "LUG": {"action": "short", "quantity": 25},
        },
        # Day 2: First rebalance - reduce TTWO, add FDEV
        {
            "TTWO": {"action": "cover", "quantity": 40},  # 60 short remaining
            "FDEV": {"action": "short", "quantity": 30},   # add new short
        },
        # Day 3: Hold
        {},
        # Day 4: Final rebalance - close TTWO short, increase LUG short
        {
            "TTWO": {"action": "cover", "quantity": 60},   # close TTWO
            "LUG": {"action": "short", "quantity": 15},   # LUG 40 total
        },
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

    # Final expected shorts
    assert positions["TTWO"]["short"] == 0
    assert positions["LUG"]["short"] == 40
    assert positions["FDEV"]["short"] == 30
    # No longs
    for t in tickers:
        assert positions[t]["long"] == 0

    # Realized gains only for TTWO (covered), none for LUG/FDEV (still open)
    assert realized_gains["TTWO"]["short"] != 0.0
    assert realized_gains["LUG"]["short"] == 0.0
    assert realized_gains["FDEV"]["short"] == 0.0

    # Cost basis reset for TTWO, positive for open shorts
    assert positions["TTWO"]["short_cost_basis"] == 0.0
    assert positions["LUG"]["short_cost_basis"] > 0.0
    assert positions["FDEV"]["short_cost_basis"] > 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    # Summary math consistency
    actual_return_pct = portfolio_summary["return_pct"]
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value
    # Still have open shorts, so position value magnitude should be > 0
    assert abs(portfolio_summary["total_position_value"]) > 0.0


def test_short_only_strategy_dollar_cost_averaging_on_short():
    """Add to an existing short (averaging entry), then partially cover and validate cost basis and PnL."""

    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2023-09-01"
    end_date = "2023-09-30"
    initial_capital = 100000.0
    margin_requirement = 0.5

    decision_sequence = [
        # Day 1: initial short
        {"TTWO": {"action": "short", "quantity": 50}},
        # Day 2: add to short at a new price (tests weighted avg cost)
        {"TTWO": {"action": "short", "quantity": 30}},
        # Day 3: hold
        {},
        # Day 4: partial cover
        {"TTWO": {"action": "cover", "quantity": 40}},
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

    # 80 short opened, 40 covered -> 40 remaining
    assert positions["TTWO"]["short"] == 40
    assert positions["LUG"]["short"] == 0
    assert positions["FDEV"]["short"] == 0
    for t in tickers:
        assert positions[t]["long"] == 0

    # Weighted short_cost_basis should be positive (non-zero) while position remains
    assert positions["TTWO"]["short_cost_basis"] > 0.0

    # Partial cover should realize PnL
    assert realized_gains["TTWO"]["short"] != 0.0

    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]

    from src.backtesting.valuation import compute_portfolio_summary

    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics,
    )

    actual_return_pct = portfolio_summary["return_pct"]
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value
    # Open short remains -> non-zero position value magnitude
    assert abs(portfolio_summary["total_position_value"]) > 0.0

