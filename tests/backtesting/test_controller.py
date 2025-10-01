from src.backtesting.controller import AgentController
from src.data.exchange_rate_service import ExchangeRateService


class MockBorsdataClient:
    def get_all_instruments(self):
        return []

    def get_stock_prices(self, instrument_id):
        return []


def dummy_agent(**kwargs):
    # Echo basic structure with only one decision
    tickers = kwargs["tickers"]
    return {
        "decisions": {tickers[0]: {"action": "buy", "quantity": "10"}},
        "analyst_signals": {"agentA": {tickers[0]: {"signal": "bullish"}}},
    }


def test_agent_controller_normalizes_and_snapshots(portfolio):
    ctrl = AgentController()
    mock_client = MockBorsdataClient()
    exchange_rate_service = ExchangeRateService(mock_client)
    out = ctrl.run_agent(
        dummy_agent,
        tickers=["TTWO", "LUG"],
        start_date="2024-01-01",
        end_date="2024-01-10",
        portfolio=portfolio,
        model_name="m",
        model_provider="p",
        selected_analysts=["x"],
        exchange_rate_service=exchange_rate_service,
        target_currency="SEK",
    )

    # Decisions normalized for all tickers
    assert out["decisions"]["TTWO"]["action"] == "buy"
    assert out["decisions"]["TTWO"]["quantity"] == 10.0
    # Missing ticker defaults to hold/0
    assert out["decisions"]["LUG"]["action"] == "hold"
    assert out["decisions"]["LUG"]["quantity"] == 0.0
    # Analyst signals are passed through
    assert "agentA" in out["analyst_signals"]


