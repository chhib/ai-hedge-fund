from src.backtesting.output import OutputBuilder
from src.utils.display import format_backtest_row, print_backtest_results


def _build_sample_rows():
    ticker_row = format_backtest_row(
        date="2025-09-23",
        ticker="TTWO",
        action="buy",
        quantity=10,
        price=140.25,
        long_shares=10,
        short_shares=0,
        position_value=1402.5,
    )
    summary_row = format_backtest_row(
        date="2025-09-23",
        ticker="",
        action="",
        quantity=0,
        price=0,
        long_shares=0,
        short_shares=0,
        position_value=0,
        is_summary=True,
        total_value=105_000.0,
        return_pct=5.0,
        cash_balance=45_000.0,
        total_position_value=60_000.0,
        sharpe_ratio=1.2,
        sortino_ratio=0.9,
        max_drawdown=3.5,
        benchmark_return_pct=3.0,
    )
    return [ticker_row, summary_row]


def test_results_builder_builds_rows_and_summary(monkeypatch, portfolio):
    rows_captured = []

    def fake_format_backtest_row(**kwargs):
        # Keep a compact tuple to validate ordering and key fields
        rows_captured.append((
            kwargs.get("date"),
            kwargs.get("ticker"),
            kwargs.get("action"),
            kwargs.get("quantity"),
            kwargs.get("price"),
            kwargs.get("is_summary", False),
            kwargs.get("total_value"),
        ))
        return [kwargs.get("date"), kwargs.get("ticker"), kwargs.get("action"), kwargs.get("quantity")]  # minimal row shape

    printed = {"called": False, "rows": None, "context": None}

    def fake_print_backtest_results(rows, context=None):
        printed["called"] = True
        printed["rows"] = rows
        printed["context"] = context

    # OutputBuilder imports these directly, so patch in its module
    monkeypatch.setattr("src.backtesting.output.format_backtest_row", fake_format_backtest_row)
    monkeypatch.setattr("src.backtesting.output.print_backtest_results", fake_print_backtest_results)

    rb = OutputBuilder(initial_capital=100_000.0)

    # Prepare state: own 10 TTWO @100, no shorts
    portfolio.apply_long_buy("TTWO", 10, 100.0)
    current_prices = {"TTWO": 100.0}

    agent_output = {
        "decisions": {"TTWO": {"action": "buy", "quantity": 10}},
        "analyst_signals": {"agentA": {"TTWO": {"signal": "bullish"}}},
    }

    rows = rb.build_day_rows(
        date_str="2024-01-02",
        tickers=["TTWO"],
        agent_output=agent_output,
        executed_trades={"TTWO": 10},
        current_prices=current_prices,
        portfolio=portfolio,
        performance_metrics={"sharpe_ratio": None, "sortino_ratio": None, "max_drawdown": None},
        total_value=100_000.0,
    )
    rb.print_rows(rows)

    # We should have 2 rows produced: 1 per-ticker + 1 summary
    assert len(printed["rows"]) == 2
    # The captured tuples include a summary row with total_value
    assert any(r[5] and r[6] == 100_000.0 for r in rows_captured)


def test_print_backtest_results_includes_market_context(monkeypatch, capsys):
    monkeypatch.setattr("src.utils.display.os.system", lambda *_: 0)

    rows = _build_sample_rows()
    context = {
        "date": "2025-09-23",
        "company_events": {
            "LUG": [
                {
                    "title": "Dividend 2.10 SEK",
                    "date": "2025-09-21",
                    "category": "dividend",
                }
            ],
            "TTWO": [
                {
                    "title": "Report release (Q2)",
                    "date": "2025-09-22",
                    "category": "report",
                },
            ],
        },
        "insider_trades": {
            "LUG": [
                {
                    "name": "Tomas Zed",
                    "transaction_shares": 1250,
                    "transaction_date": "2025-09-20",
                },
            ],
            "TTWO": [
                {
                    "name": "Karl Slatoff",
                    "transaction_shares": -7500,
                    "transaction_date": "2025-09-22",
                },
            ],
        },
    }

    print_backtest_results(rows, context=context)
    output = capsys.readouterr().out

    assert "MARKET CONTEXT 2025-09-23" in output
    assert "Corporate Events" in output
    assert "Dividend 2.10 SEK" in output
    assert "Report release (Q2)" in output
    assert "Insider Trades" in output
    assert "Karl Slatoff" in output
    assert "Sell 7,500 shares" in output
    assert "Tomas Zed" in output
    assert "Buy 1,250 shares" in output


def test_print_backtest_results_handles_empty_context(monkeypatch, capsys):
    monkeypatch.setattr("src.utils.display.os.system", lambda *_: 0)

    rows = _build_sample_rows()
    context = {"date": "2025-09-23", "company_events": {}, "insider_trades": {}}

    print_backtest_results(rows, context=context)
    output = capsys.readouterr().out

    assert "MARKET CONTEXT" not in output
