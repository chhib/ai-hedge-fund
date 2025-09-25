from src.backtesting.trader import TradeExecutor


def test_trade_executor_routes_actions(portfolio):
    ex = TradeExecutor()

    # buy
    qty = ex.execute_trade("TTWO", "buy", 10, 100.0, portfolio)
    assert qty == 10
    # sell
    qty = ex.execute_trade("TTWO", "sell", 5, 100.0, portfolio)
    assert qty == 5
    # short
    qty = ex.execute_trade("LUG", "short", 4, 200.0, portfolio)
    assert qty == 4
    # cover
    qty = ex.execute_trade("LUG", "cover", 1, 200.0, portfolio)
    assert qty == 1


def test_trade_executor_guards_and_unknown_action(portfolio):
    ex = TradeExecutor()

    assert ex.execute_trade("TTWO", "buy", 0, 10.0, portfolio) == 0
    assert ex.execute_trade("TTWO", "buy", -5, 10.0, portfolio) == 0
    assert ex.execute_trade("TTWO", "unknown", 10, 10.0, portfolio) == 0

