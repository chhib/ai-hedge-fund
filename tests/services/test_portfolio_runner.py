from click.testing import CliRunner

import pytest

import src.cli.hedge as hedge_cli
import src.services.portfolio_runner as portfolio_runner
from src.services.portfolio_runner import RebalanceConfig, RebalanceOutcome
from src.utils.portfolio_loader import Position


def test_ensure_ibkr_gateway_prints_manual_start_instructions_when_localhost_offline(monkeypatch, capsys) -> None:
    config = RebalanceConfig(
        portfolio_path=None,
        universe_path=None,
        universe_tickers=None,
        portfolio_source="ibkr",
        ibkr_port=5001,
        ibkr_timeout=1.0,
    )

    monkeypatch.setattr(portfolio_runner, "_check_ibkr_gateway", lambda base_url, timeout: (False, False))
    monkeypatch.setattr(portfolio_runner, "_find_running_gateway", lambda timeout: (None, False))
    monkeypatch.setattr(portfolio_runner, "_is_local_port_in_use", lambda port, timeout=1.0: False)
    monkeypatch.setattr(portfolio_runner, "_start_ibkr_gateway", lambda port: False)

    with pytest.raises(RuntimeError) as excinfo:
        portfolio_runner._ensure_ibkr_gateway(config)

    output = capsys.readouterr().out
    assert "IBKR Gateway on localhost is not responding on ports 5000 or 5001." in output
    assert "Suggestion: start the IBKR Client Portal Gateway:" in output
    assert "bin/run.sh root/conf.yaml" in output
    assert "Attempting to start it automatically..." in output

    message = str(excinfo.value)
    assert "Could not start IBKR Gateway automatically." in message
    assert "bin/run.sh root/conf.yaml" in message
    assert "Authenticate at https://localhost:5001" in message


def test_ensure_ibkr_gateway_reports_local_port_conflict(monkeypatch) -> None:
    config = RebalanceConfig(
        portfolio_path=None,
        universe_path=None,
        universe_tickers=None,
        portfolio_source="ibkr",
        ibkr_port=5001,
        ibkr_timeout=1.0,
    )

    monkeypatch.setattr(portfolio_runner, "_check_ibkr_gateway", lambda base_url, timeout: (False, False))
    monkeypatch.setattr(portfolio_runner, "_find_running_gateway", lambda timeout: (None, False))
    monkeypatch.setattr(portfolio_runner, "_is_local_port_in_use", lambda port, timeout=1.0: True)
    monkeypatch.setattr(portfolio_runner, "_describe_local_listener", lambda port: "Python (PID 10837)")

    with pytest.raises(RuntimeError) as excinfo:
        portfolio_runner._ensure_ibkr_gateway(config)

    message = str(excinfo.value)
    assert "IBKR Gateway port 5001 is already in use by another local process." in message
    assert "Listener: Python (PID 10837)." in message
    assert "choose another --ibkr-port" in message
    assert "bin/run.sh root/conf.yaml" in message


def test_rebalance_cli_surfaces_gateway_start_instructions(monkeypatch) -> None:
    outcome = RebalanceOutcome(
        session_id="session-94",
        results={"recommendations": []},
        output_path=None,
        unknown_tickers=[],
    )

    def _fail_gateway(config: RebalanceConfig) -> str:
        raise RuntimeError(
            "Could not start IBKR Gateway automatically.\n"
            "Suggestion: start the IBKR Client Portal Gateway:\n"
            "  cd clientportal.gw && bin/run.sh root/conf.yaml\n"
            "  Authenticate at https://localhost:5001\n"
            "  Then re-run this command."
        )

    monkeypatch.setattr(hedge_cli, "run_rebalance", lambda config: outcome)
    monkeypatch.setattr(portfolio_runner, "_ensure_ibkr_gateway", _fail_gateway)

    runner = CliRunner()
    result = runner.invoke(
        hedge_cli.cli,
        [
            "rebalance",
            "--portfolio-source",
            "ibkr",
            "--universe-tickers",
            "TTWO",
            "--ibkr-execute",
            "--ibkr-yes",
        ],
    )

    assert result.exit_code == 1
    assert "Error: Could not start IBKR Gateway automatically." in result.output
    assert "bin/run.sh root/conf.yaml" in result.output
    assert "Authenticate at https://localhost:5001" in result.output


def test_format_position_summary_lists_tickers_and_shares() -> None:
    positions = [
        Position(ticker="STNG", shares=2.0, cost_basis=57.5, currency="USD"),
        Position(ticker="DHT", shares=11.0, cost_basis=11.9, currency="USD"),
        Position(ticker="HOVE", shares=137.0, cost_basis=4.8, currency="DKK"),
    ]

    summary = portfolio_runner._format_position_summary(positions)

    assert summary == "STNG (2), DHT (11), HOVE (137)"
