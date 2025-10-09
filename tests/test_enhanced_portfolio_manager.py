from datetime import datetime
import sys
import types

import pytest

# Provide a lightweight pandas stub so tests can run without native pandas binaries.
if "pandas" not in sys.modules:
    pandas_stub = types.ModuleType("pandas")

    class _StubDataFrame:
        pass

    def _stub_read_csv(*args, **kwargs):
        raise NotImplementedError("pandas.read_csv is not available in this test stub")

    pandas_stub.DataFrame = _StubDataFrame
    pandas_stub.read_csv = _stub_read_csv
    sys.modules["pandas"] = pandas_stub

from src.agents.enhanced_portfolio_manager import EnhancedPortfolioManager, PriceContext
from src.utils.portfolio_loader import Portfolio, Position


def _build_manager_with_price(price_usd: float) -> EnhancedPortfolioManager:
    portfolio = Portfolio(
        positions=[
            Position(
                ticker="ABC",
                shares=10,
                cost_basis=100.0,
                currency="USD",
                date_acquired=datetime(2025, 10, 3),
            )
        ],
        cash_holdings={"SEK": 0.0},
        last_updated=datetime.utcnow(),
    )

    manager = EnhancedPortfolioManager(
        portfolio=portfolio,
        universe=["ABC"],
        analysts=[],
        model_config={},
        ticker_markets={"ABC": "global"},
        home_currency="SEK",
        no_cache=True,
        no_cache_agents=True,
        verbose=False,
        session_id=None,
    )

    manager.exchange_rates = {"SEK": 1.0, "USD": 10.0}
    manager.price_context_cache["ABC"] = PriceContext(
        ticker="ABC",
        currency="USD",
        latest_close=price_usd,
        entry_price=price_usd,
        buy_price=price_usd,
        sell_price=price_usd,
        atr=0.0,
        band_low=price_usd,
        band_high=price_usd,
        sample_size=3,
        source="unit_test",
    )

    return manager


def test_generate_recommendations_uses_market_pricing_over_cost_basis():
    manager = _build_manager_with_price(price_usd=50.0)

    recommendations = manager._generate_recommendations({"ABC": 1.0}, min_trade_size=0.0)

    assert recommendations[0]["action"] == "HOLD"
    assert recommendations[0]["target_shares"] == pytest.approx(10)

    value_info = manager._current_position_values["ABC"]
    assert value_info["price"] == pytest.approx(50.0)
    assert value_info["value_home"] == pytest.approx(5000.0)

    summary = manager._portfolio_summary()
    assert summary["total_value"] == pytest.approx(5000.0)


def test_rounding_respects_budget_after_cash_scaling():
    portfolio = Portfolio(
        positions=[],
        cash_holdings={"SEK": 9600.0},
        last_updated=datetime.utcnow(),
    )

    manager = EnhancedPortfolioManager(
        portfolio=portfolio,
        universe=["AAA", "BBB"],
        analysts=[],
        model_config={},
        ticker_markets={"AAA": "global", "BBB": "global"},
        home_currency="SEK",
        no_cache=True,
        no_cache_agents=True,
        verbose=False,
        session_id=None,
    )

    manager.exchange_rates = {"SEK": 1.0, "USD": 10.0}
    manager.price_context_cache["AAA"] = PriceContext(
        ticker="AAA",
        currency="USD",
        latest_close=250.0,
        entry_price=250.0,
        buy_price=250.0,
        sell_price=250.0,
        atr=0.0,
        band_low=250.0,
        band_high=250.0,
        sample_size=3,
        source="unit_test",
    )
    manager.price_context_cache["BBB"] = PriceContext(
        ticker="BBB",
        currency="USD",
        latest_close=240.0,
        entry_price=240.0,
        buy_price=240.0,
        sell_price=240.0,
        atr=0.0,
        band_low=240.0,
        band_high=240.0,
        sample_size=3,
        source="unit_test",
    )

    recommendations = manager._generate_recommendations({"AAA": 0.5, "BBB": 0.5}, min_trade_size=0.0)
    updated = manager._calculate_updated_portfolio(recommendations)

    assert updated["cash"]["SEK"] >= -1e-6

    invested_home = 0.0
    for position in updated["positions"]:
        fx = manager.exchange_rates.get(position["currency"], 1.0)
        invested_home += position["shares"] * position["cost_basis"] * fx

    assert invested_home + updated["cash"]["SEK"] <= 9600.0 + 1e-6


def test_rebalance_slippage_within_three_percent():
    initial_cash = 283.0

    initial_positions = [
        Position("HOVE", 189, 4.84, "DKK", datetime(2025, 10, 3)),
        Position("TRMD A", 6, 136.01, "DKK", datetime(2025, 10, 9)),
        Position("DHT", 11, 11.92, "USD", datetime(2025, 10, 3)),
        Position("HAS", 2, 75.81, "USD", datetime(2025, 10, 9)),
        Position("SBLK", 8, 18.59, "USD", datetime(2025, 10, 9)),
        Position("STNG", 3, 57.50, "USD", datetime(2025, 10, 3)),
        Position("WB", 10, 12.72, "USD", datetime(2025, 10, 3)),
    ]

    portfolio = Portfolio(
        positions=initial_positions,
        cash_holdings={"SEK": initial_cash},
        last_updated=datetime.utcnow(),
    )

    universe = ["HOVE", "TRMD A", "DHT", "HAS", "SBLK", "STNG", "WB", "NVEC", "MTCH", "LUG"]

    manager = EnhancedPortfolioManager(
        portfolio=portfolio,
        universe=universe,
        analysts=[],
        model_config={},
        ticker_markets={
            "HOVE": "Nordic",
            "TRMD A": "Nordic",
            "DHT": "global",
            "HAS": "global",
            "SBLK": "global",
            "STNG": "global",
            "WB": "global",
            "NVEC": "global",
            "MTCH": "global",
            "LUG": "global",
        },
        home_currency="SEK",
        no_cache=True,
        no_cache_agents=True,
        verbose=False,
        session_id=None,
    )

    manager.exchange_rates = {"SEK": 1.0, "DKK": 1.4694, "USD": 9.4340, "CAD": 6.7614}

    price_map = {
        "HOVE": (4.84, "DKK"),
        "TRMD A": (136.01, "DKK"),
        "DHT": (11.92, "USD"),
        "HAS": (75.81, "USD"),
        "SBLK": (18.59, "USD"),
        "STNG": (57.50, "USD"),
        "WB": (12.72, "USD"),
        "NVEC": (68.86, "USD"),
        "MTCH": (33.82, "USD"),
        "LUG": (97.15, "CAD"),
    }

    for ticker, (price, currency) in price_map.items():
        manager.price_context_cache[ticker] = PriceContext(
            ticker=ticker,
            currency=currency,
            latest_close=price,
            entry_price=price,
            buy_price=price,
            sell_price=price,
            atr=0.0,
            band_low=price,
            band_high=price,
            sample_size=3,
            source="unit_test",
        )

    initial_total = initial_cash
    for position in initial_positions:
        px, currency = price_map[position.ticker]
        fx = manager.exchange_rates[currency]
        initial_total += position.shares * px * fx

    target_weights = {
        "HOVE": 0.0,
        "TRMD A": 0.0,
        "DHT": 0.16,
        "HAS": 0.14,
        "SBLK": 0.13,
        "STNG": 0.12,
        "WB": 0.10,
        "NVEC": 0.15,
        "MTCH": 0.10,
        "LUG": 0.10,
    }

    recommendations = manager._generate_recommendations(target_weights, min_trade_size=500.0)
    updated = manager._calculate_updated_portfolio(recommendations)

    final_total = updated["cash"].get("SEK", 0.0)
    for position in updated["positions"]:
        price, currency = price_map[position["ticker"]]
        fx = manager.exchange_rates[currency]
        final_total += position["shares"] * price * fx

    assert final_total == pytest.approx(initial_total, rel=0, abs=1e-6)
    assert updated["cash"]["SEK"] <= initial_total * 0.03 + 1e-6
