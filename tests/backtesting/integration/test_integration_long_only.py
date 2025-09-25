from src.backtesting.engine import BacktestEngine
from tests.backtesting.integration.mocks import MockConfigurableAgent

def test_long_only_strategy_buys_and_sells():
    """Test a strategy that buys shares, holds, then sells some shares to test realized gains/losses."""
    
    # Test parameters
    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2025-09-15"  
    end_date = "2025-09-23"    
    initial_capital = 100000.0  # $100k starting capital
    margin_requirement = 0.5   
    
    # Define the exact trading sequence we want to test
    decision_sequence = [
        # Day 1: Initial purchases
        {
            "TTWO": {"action": "buy", "quantity": 100},  # Buy 100 TTWO shares
            "LUG": {"action": "buy", "quantity": 30},   # Buy 30 LUG shares
            # FDEV will default to hold
        },
        # Day 2: Hold all positions (empty dict = hold all)
        {},
        # Day 3: Partial sell of TTWO
        {
            "TTWO": {"action": "sell", "quantity": 30},  # Sell 30 of 100 TTWO shares
            # LUG and FDEV will default to hold
        },
        # Day 4+: Hold remaining positions (empty dict = hold all)
        {}
    ]
    
    # Create configurable agent with explicit trading plan
    agent = MockConfigurableAgent(decision_sequence, tickers)
    
    # Create and run backtest
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )
    
    # Run the backtest
    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()
    
    # Get final portfolio state
    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]
    
    # Extract key values from our configuration for high-level verification
    initial_aapl_purchase = decision_sequence[0]["TTWO"]["quantity"]  # 100 
    aapl_sell_quantity = decision_sequence[2]["TTWO"]["quantity"]     # 30
    expected_final_aapl = initial_aapl_purchase - aapl_sell_quantity  # 70
    
    # Verify the final positions match our trading plan
    assert positions["TTWO"]["long"] == expected_final_aapl, f"TTWO position mismatch: expected {expected_final_aapl} shares, got {positions['TTWO']['long']}"
    assert positions["LUG"]["long"] == 30, f"LUG position mismatch: expected 30 shares, got {positions['LUG']['long']}"
    assert positions["FDEV"]["long"] == 0, f"FDEV position mismatch: expected 0 shares, got {positions['FDEV']['long']}"
    
    # Verify the TTWO sale generated realized gains (proves sale happened)
    assert realized_gains["TTWO"]["long"] != 0.0, "TTWO should have realized gains from sale"
    assert realized_gains["LUG"]["long"] == 0.0, "LUG should have no realized gains (no sales)"
    
    # PORTFOLIO SUMMARY VERIFICATION: Focus on what matters most
    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]
    
    from src.backtesting.valuation import compute_portfolio_summary
    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics
    )
    
    # Core assertions: Portfolio summary calculations should be internally consistent
    actual_return_pct = portfolio_summary["return_pct"] 
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct, f"Return percentage should {expected_return_pct}"
    
    # Final portfolio value should be correct
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value, f"Final portfolio value should be {expected_total_value}"

    # Verify corporate events and insider trades context is surfaced
    context_history = engine.get_daily_context()
    assert context_history, "Expected daily context history to be populated"
    latest_context = context_history[-1]
    assert latest_context["date"] == end_date

    events_by_ticker = latest_context["company_events"]
    for ticker in tickers:
        assert ticker in events_by_ticker, f"Missing corporate events for {ticker}"
    assert any(event["category"] == "dividend" for event in events_by_ticker["LUG"])
    assert any(event["title"].startswith("Report release") for event in events_by_ticker["TTWO"])

    trades_by_ticker = latest_context["insider_trades"]
    for ticker in tickers:
        assert ticker in trades_by_ticker, f"Missing insider trades for {ticker}"
    assert any(trade["is_board_director"] for trade in trades_by_ticker["FDEV"])


def test_long_only_strategy_full_liquidation_cycle():
    """Test a strategy that buys multiple positions, holds, then sells everything back to cash."""
    
    # Test parameters
    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2025-09-15"  
    end_date = "2025-09-23"    
    initial_capital = 100000.0  # $100k starting capital
    margin_requirement = 0.5   
    
    # Define the exact trading sequence we want to test
    decision_sequence = [
        # Day 1: Initial purchases - diversify across all tickers
        {
            "TTWO": {"action": "buy", "quantity": 50},   # Buy 50 TTWO shares
            "LUG": {"action": "buy", "quantity": 25},   # Buy 25 LUG shares
            "FDEV": {"action": "buy", "quantity": 30},   # Buy 30 FDEV shares
        },
        # Day 2: Hold all positions (empty dict = hold all)
        {},
        # Day 3: Begin liquidation - sell TTWO completely
        {
            "TTWO": {"action": "sell", "quantity": 50},  # Sell all TTWO
        },
        # Day 4: Complete liquidation - sell LUG and FDEV completely
        {
            "LUG": {"action": "sell", "quantity": 25},  # Sell all LUG
            "FDEV": {"action": "sell", "quantity": 30},  # Sell all FDEV
        }
    ]
    
    # Create configurable agent with explicit trading plan
    agent = MockConfigurableAgent(decision_sequence, tickers)
    
    # Create and run backtest
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )
    
    # Run the backtest
    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()
    
    # Get final portfolio state
    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]
    
    # Verify complete liquidation - should have no positions left
    assert positions["TTWO"]["long"] == 0, f"TTWO should be fully sold, got {positions['TTWO']['long']}"
    assert positions["LUG"]["long"] == 0, f"LUG should be fully sold, got {positions['LUG']['long']}"
    assert positions["FDEV"]["long"] == 0, f"FDEV should be fully sold, got {positions['FDEV']['long']}"
    
    # Should have no short positions (long-only strategy)
    for ticker in tickers:
        assert positions[ticker]["short"] == 0, f"Expected no short position in {ticker}"
    
    # All tickers should have realized gains from complete liquidation
    assert realized_gains["TTWO"]["long"] != 0.0, "TTWO should have realized gains from sale"
    assert realized_gains["LUG"]["long"] != 0.0, "LUG should have realized gains from sale"
    assert realized_gains["FDEV"]["long"] != 0.0, "FDEV should have realized gains from sale"
    
    # Cost basis should be reset to zero after complete sales
    assert positions["TTWO"]["long_cost_basis"] == 0.0, "TTWO cost basis should be reset to 0"
    assert positions["LUG"]["long_cost_basis"] == 0.0, "LUG cost basis should be reset to 0"
    assert positions["FDEV"]["long_cost_basis"] == 0.0, "FDEV cost basis should be reset to 0"
    
    # PORTFOLIO SUMMARY VERIFICATION: Focus on what matters most
    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]
    
    from src.backtesting.valuation import compute_portfolio_summary
    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics
    )
    
    # Core assertions: Portfolio summary calculations should be internally consistent
    actual_return_pct = portfolio_summary["return_pct"] 
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct, f"Return percentage should be {expected_return_pct}"
    
    # After complete liquidation, portfolio should be mostly cash with no positions
    expected_total_position_value = 0.0  # No positions left
    assert portfolio_summary["total_position_value"] == expected_total_position_value, \
        f"Total position value should be 0 after liquidation, got {portfolio_summary['total_position_value']}"
    
    # Final portfolio value should equal cash balance (since no positions)
    assert abs(final_portfolio_value - final_cash) < 0.01, \
        f"Portfolio value should equal cash after liquidation: value={final_portfolio_value}, cash={final_cash}"


def test_long_only_strategy_portfolio_rebalancing():
    """Test a strategy that rebalances between stocks over time, validating complex position transitions."""
    
    # Test parameters
    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2025-09-15"  
    end_date = "2025-09-23"    
    initial_capital = 100000.0  # $100k starting capital
    margin_requirement = 0.5   
    
    # Define the exact trading sequence we want to test
    decision_sequence = [
        # Day 1: Initial allocation - focus on TTWO and LUG
        {
            "TTWO": {"action": "buy", "quantity": 100},  # Buy 100 TTWO shares
            "LUG": {"action": "buy", "quantity": 25},   # Buy 25 LUG shares
            # FDEV remains empty (no position)
        },
        # Day 2: First rebalance - reduce TTWO, add FDEV
        {
            "TTWO": {"action": "sell", "quantity": 40},  # Sell 40 of 100 TTWO (60 remaining)
            "FDEV": {"action": "buy", "quantity": 30},   # Add 30 FDEV shares
            # LUG holds at 25 shares
        },
        # Day 3: Hold all current positions
        {},
        # Day 4: Final rebalance - exit TTWO completely, increase LUG
        {
            "TTWO": {"action": "sell", "quantity": 60},  # Sell remaining 60 TTWO
            "LUG": {"action": "buy", "quantity": 15},   # Add 15 more LUG (40 total)
            # FDEV holds at 30 shares
        }
    ]
    
    # Create configurable agent with explicit trading plan
    agent = MockConfigurableAgent(decision_sequence, tickers)
    
    # Create and run backtest
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )
    
    # Run the backtest
    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()
    
    # Get final portfolio state
    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]
    
    # Extract expected values from our rebalancing configuration
    final_aapl_expected = 0      # Sold all: 100 initial - 40 - 60 = 0
    final_lug_expected = 40     # Accumulated: 25 initial + 15 = 40
    final_fdev_expected = 30     # Added: 0 initial + 30 = 30
    
    # Verify the final positions match our rebalancing plan
    assert positions["TTWO"]["long"] == final_aapl_expected, f"TTWO position mismatch: expected {final_aapl_expected} shares, got {positions['TTWO']['long']}"
    assert positions["LUG"]["long"] == final_lug_expected, f"LUG position mismatch: expected {final_lug_expected} shares, got {positions['LUG']['long']}"
    assert positions["FDEV"]["long"] == final_fdev_expected, f"FDEV position mismatch: expected {final_fdev_expected} shares, got {positions['FDEV']['long']}"
    
    # Should have no short positions (long-only strategy)
    for ticker in tickers:
        assert positions[ticker]["short"] == 0, f"Expected no short position in {ticker}"
    
    # Verify realized gains from rebalancing activities
    assert realized_gains["TTWO"]["long"] != 0.0, "TTWO should have realized gains from partial and complete sales"
    assert realized_gains["LUG"]["long"] == 0.0, "LUG should have no realized gains (only bought, never sold)"
    assert realized_gains["FDEV"]["long"] == 0.0, "FDEV should have no realized gains (only bought, never sold)"
    
    # TTWO should have zero cost basis (completely sold)
    assert positions["TTWO"]["long_cost_basis"] == 0.0, "TTWO cost basis should be reset to 0 after complete sale"
    # LUG and FDEV should have positive cost bases (still holding)
    assert positions["LUG"]["long_cost_basis"] > 0.0, "LUG should have positive cost basis (still holding)"
    assert positions["FDEV"]["long_cost_basis"] > 0.0, "FDEV should have positive cost basis (still holding)"
    
    # PORTFOLIO SUMMARY VERIFICATION: Focus on what matters most
    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]
    
    from src.backtesting.valuation import compute_portfolio_summary
    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics
    )
    
    # Core assertions: Portfolio summary calculations should be internally consistent
    actual_return_pct = portfolio_summary["return_pct"] 
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct, f"Return percentage should be {expected_return_pct}"
    
    # Portfolio should have mixed cash and positions after rebalancing
    expected_total_value = final_cash + portfolio_summary["total_position_value"]
    assert final_portfolio_value == expected_total_value, f"Final portfolio value should be {expected_total_value}"
    
    # Should have meaningful position values (not all cash, not zero cash)
    assert portfolio_summary["total_position_value"] > 0.0, "Should have position value after rebalancing"
    assert final_cash > 0.0, "Should have some cash remaining after rebalancing"
    
    # Verify that we successfully shifted from TTWO-heavy to LUG+FDEV portfolio
    # Final positions should be worth a meaningful portion of the portfolio
    expected_min_position_value = initial_capital * 0.15  # At least 15% should be in positions after rebalancing
    assert portfolio_summary["total_position_value"] >= expected_min_position_value, \
        f"Total position value should be at least {expected_min_position_value}, got {portfolio_summary['total_position_value']}"


def test_long_only_strategy_multiple_entry_exit_cycles():
    """Test a strategy that performs multiple entry/exit cycles on the same ticker.

    Objective: validate realized gains aggregation across cycles, cost basis resets on full exits,
    and portfolio summary correctness at the end of the run.
    """
    
    # Test parameters
    tickers = ["TTWO", "LUG", "FDEV"]
    start_date = "2025-09-15"  
    end_date = "2025-09-23"    
    initial_capital = 100000.0  # $100k starting capital
    margin_requirement = 0.5   
    
    # Multiple cycles on TTWO and LUG within the available 4 business days (Mar 5-8)
    # Day 1: Buy TTWO 60, LUG 20
    # Day 2: Sell TTWO 60, LUG 20 (flat both)
    # Day 3: Buy TTWO 30, LUG 10 (re-entry both)
    # Day 4: Sell TTWO 30, LUG 10 (flat both again)
    decision_sequence = [
        {"TTWO": {"action": "buy", "quantity": 60}, "LUG": {"action": "buy", "quantity": 20}},
        {"TTWO": {"action": "sell", "quantity": 60}, "LUG": {"action": "sell", "quantity": 20}},
        {"TTWO": {"action": "buy", "quantity": 30}, "LUG": {"action": "buy", "quantity": 10}},
        {"TTWO": {"action": "sell", "quantity": 30}, "LUG": {"action": "sell", "quantity": 10}},
    ]
    
    # Create configurable agent with explicit trading plan
    agent = MockConfigurableAgent(decision_sequence, tickers)
    
    # Create and run backtest
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )
    
    # Run the backtest
    performance_metrics = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()
    
    # Get final portfolio state
    final_portfolio = engine._portfolio.get_snapshot()
    positions = final_portfolio["positions"]
    realized_gains = final_portfolio["realized_gains"]
    
    # Verify final positions are flat after multiple cycles
    assert positions["TTWO"]["long"] == 0, f"TTWO should be fully sold after cycles, got {positions['TTWO']['long']}"
    assert positions["LUG"]["long"] == 0, f"LUG should be fully sold after cycles, got {positions['LUG']['long']}"
    assert positions["FDEV"]["long"] == 0, f"FDEV should be 0 shares (never traded), got {positions['FDEV']['long']}"
    
    # Should have no short positions (long-only strategy)
    for ticker in tickers:
        assert positions[ticker]["short"] == 0, f"Expected no short position in {ticker}"
    
    # Realized gains should be non-zero for TTWO and LUG due to two completed round trips
    assert realized_gains["TTWO"]["long"] != 0.0, "TTWO should have realized gains/losses from multiple cycles"
    assert realized_gains["LUG"]["long"] != 0.0, "LUG should have realized gains/losses from multiple cycles"
    assert realized_gains["FDEV"]["long"] == 0.0, "FDEV should have no realized gains (not traded)"
    
    # Cost basis should be reset to zero for TTWO and LUG after final full exit
    assert positions["TTWO"]["long_cost_basis"] == 0.0, "TTWO cost basis should reset to 0 after full exit"
    assert positions["LUG"]["long_cost_basis"] == 0.0, "LUG cost basis should reset to 0 after full exit"
    
    # PORTFOLIO SUMMARY VERIFICATION
    final_portfolio_value = portfolio_values[-1]["Portfolio Value"]
    final_cash = final_portfolio["cash"]
    
    from src.backtesting.valuation import compute_portfolio_summary
    portfolio_summary = compute_portfolio_summary(
        portfolio=engine._portfolio,
        total_value=final_portfolio_value,
        initial_value=initial_capital,
        performance_metrics=performance_metrics
    )
    
    # Core assertions: Portfolio summary calculations should be internally consistent
    actual_return_pct = portfolio_summary["return_pct"] 
    expected_return_pct = (final_portfolio_value / initial_capital - 1.0) * 100.0
    assert actual_return_pct == expected_return_pct, f"Return percentage should be {expected_return_pct}"
    
    # After final liquidation, no positions should remain
    assert portfolio_summary["total_position_value"] == 0.0, \
        f"Total position value should be 0 after final liquidation, got {portfolio_summary['total_position_value']}"
    assert abs(final_portfolio_value - final_cash) < 0.01, \
        f"Portfolio value should equal cash after final liquidation: value={final_portfolio_value}, cash={final_cash}"


def test_cli_output_ordering_and_benchmark_validation(monkeypatch, capsys):
    """Test that CLI output displays in correct order with proper benchmark calculations."""
    
    # Mock os.system to prevent clearing screen during tests  
    monkeypatch.setattr("src.utils.display.os.system", lambda *_: 0)
    
    # Test parameters
    tickers = ["TTWO", "LUG"]
    start_date = "2025-09-15"  
    end_date = "2025-09-23"    # Use existing fixture date range
    initial_capital = 100000.0
    margin_requirement = 0.5
    
    # Simple buy-and-hold strategy for predictable output
    decision_sequence = [
        {"TTWO": {"action": "buy", "quantity": 100}, "LUG": {"action": "buy", "quantity": 30}},
        {},  # Hold for remaining days
    ]
    
    agent = MockConfigurableAgent(decision_sequence, tickers)
    
    # Create and run backtest
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        model_name="test-model",
        model_provider="test-provider", 
        selected_analysts=None,
        initial_margin_requirement=margin_requirement,
    )
    
    # Run the backtest
    performance_metrics = engine.run_backtest()
    
    # Capture the printed output
    output = capsys.readouterr().out
    
    # Validate output structure and ordering
    assert "PORTFOLIO SUMMARY:" in output
    assert "MARKET CONTEXT" in output
    assert "Corporate Events:" in output
    
    # Check that market context appears after portfolio summary
    portfolio_summary_pos = output.find("PORTFOLIO SUMMARY:")
    market_context_pos = output.find("MARKET CONTEXT")
    assert portfolio_summary_pos < market_context_pos, "Portfolio summary should appear before market context"
    
    # Validate benchmark return appears in output (may not appear for very short backtests)
    if "Benchmark Return:" in output:
        # Extract and validate benchmark return format
        import re
        benchmark_pattern = r"Benchmark Return: [+-]?\d+\.\d+%"
        assert re.search(benchmark_pattern, output), "Benchmark return should be properly formatted"
    
    # Validate performance metrics are displayed (may not appear for short backtests) 
    performance_metrics_present = "Sharpe Ratio:" in output
    if performance_metrics_present:
        assert "Sortino Ratio:" in output, "Sortino ratio should be displayed if Sharpe is shown"
        assert "Max Drawdown:" in output, "Max drawdown should be displayed if Sharpe is shown"
    
    # Validate portfolio return is displayed
    assert "Portfolio Return:" in output, "Portfolio return should be displayed"
    
    # Validate market context contains relevant tickers
    for ticker in tickers:
        assert ticker in output, f"Ticker {ticker} should appear in market context"
    
    # Validate corporate events are properly formatted
    assert "Corporate Events:" in output
    assert "Insider Trades:" in output
    
    # Check that table headers are present
    assert "Date" in output, "Date column header should be present"
    assert "Ticker" in output, "Ticker column header should be present"
    assert "Action" in output, "Action column header should be present"
    assert "Position Value" in output, "Position Value column header should be present"
