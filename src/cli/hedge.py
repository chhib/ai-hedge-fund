from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from dotenv import load_dotenv

from src.services.portfolio_runner import RebalanceConfig, run_rebalance


load_dotenv()

app = typer.Typer(help="Unified CLI for the AI Hedge Fund workflows.")


@app.command()
def rebalance(
    portfolio: Optional[Path] = typer.Option(None, metavar="CSV", help="Path to the current portfolio CSV"),
    universe: Optional[Path] = typer.Option(None, help="Path to a universe list"),
    universe_tickers: Optional[str] = typer.Option(None, help="Comma-separated tickers if no file is provided"),
    analysts: str = typer.Option("all", help="Analyst selection preset or comma-separated list"),
    model: str = typer.Option("gpt-4o", help="LLM model name"),
    model_provider: Optional[str] = typer.Option(None, help="Optional model provider override"),
    max_workers: int = typer.Option(4, min=1, help="Parallel worker cap for analyst tasks"),
    max_holdings: int = typer.Option(8, min=1, help="Maximum holdings in the target portfolio"),
    max_position: float = typer.Option(0.25, help="Maximum position size as decimal"),
    min_position: float = typer.Option(0.05, help="Minimum position size as decimal"),
    min_trade: float = typer.Option(500.0, help="Minimum trade size in USD equivalent"),
    home_currency: str = typer.Option("SEK", help="Home currency for portfolio calculations"),
    no_cache: bool = typer.Option(False, help="Bypass all cached Börsdata payloads"),
    no_cache_agents: bool = typer.Option(False, help="Reuse KPI cache but refresh analyst runs"),
    dry_run: bool = typer.Option(False, help="Show recommendations without saving a CSV"),
    verbose: bool = typer.Option(False, help="Show detailed analyst output"),
    test: bool = typer.Option(False, help="Quick validation using the fundamentals analyst"),
    export_transcript: bool = typer.Option(False, "--export-transcript", help="Export analyst transcript automatically"),
    output_dir: Optional[Path] = typer.Option(None, help="Directory for the generated CSV (defaults to CWD)"),
    portfolio_source: str = typer.Option("csv", help="Source for portfolio data (csv or ibkr)"),
    ibkr_account: Optional[str] = typer.Option(None, help="Optional IBKR account override (defaults to first account)"),
    ibkr_host: str = typer.Option("https://localhost", help="Client Portal host (scheme optional)"),
    ibkr_port: int = typer.Option(5000, help="Client Portal port"),
    ibkr_verify_ssl: bool = typer.Option(False, help="Verify SSL certificates for IBKR calls"),
    ibkr_timeout: float = typer.Option(30.0, help="Timeout in seconds for IBKR API calls"),
):
    """Run the weekly long-only rebalance flow."""

    normalized_source = portfolio_source.lower()
    if normalized_source == "csv" and portfolio is None:
        typer.secho("--portfolio is required when portfolio-source=csv", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    config = RebalanceConfig(
        portfolio_path=portfolio,
        universe_path=universe,
        universe_tickers=universe_tickers,
        analysts=analysts,
        model=model,
        model_provider=model_provider,
        max_workers=max_workers,
        max_holdings=max_holdings,
        max_position=max_position,
        min_position=min_position,
        min_trade=min_trade,
        home_currency=home_currency,
        no_cache=no_cache,
        no_cache_agents=no_cache_agents,
        verbose=verbose,
        dry_run=dry_run,
        test_mode=test,
        output_dir=output_dir,
        portfolio_source=normalized_source,
        ibkr_account=ibkr_account,
        ibkr_host=ibkr_host,
        ibkr_port=ibkr_port,
        ibkr_verify_ssl=ibkr_verify_ssl,
        ibkr_timeout=ibkr_timeout,
    )

    try:
        outcome = run_rebalance(config)
    except Exception as exc:  # pragma: no cover - CLI level guardrail
        typer.secho(f"Error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if export_transcript:
        _export_transcript(outcome.session_id)


@app.command()
def backtest(
    tickers: str = typer.Option(..., help="Comma-separated tickers"),
    start_date: str = typer.Option(..., help="Backtest start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(..., help="Backtest end date (YYYY-MM-DD)"),
    initial_capital: float = typer.Option(100_000.0, help="Starting capital"),
    initial_currency: str = typer.Option("USD", help="Currency for the starting capital"),
    margin_requirement: float = typer.Option(0.0, help="Margin requirement percentage"),
    analysts: Optional[str] = typer.Option(None, help="Comma-separated analysts for the run"),
    model_name: str = typer.Option("gpt-4.1", help="LLM model name"),
    model_provider: str = typer.Option("OpenAI", help="LLM provider"),
):
    """Backtest the hedge-fund agent pipeline without interactive prompts."""

    ticker_list = _parse_ticker_list(tickers)
    if not ticker_list:
        typer.secho("At least one ticker must be provided", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    selected_analysts = [item.strip() for item in analysts.split(",") if item.strip()] if analysts else []

    _build_ticker_markets(ticker_list)

    from src.main import run_hedge_fund
    from src.backtesting.engine import BacktestEngine
    from src.backtester import run_backtest as execute_backtest

    backtester = BacktestEngine(
        agent=run_hedge_fund,
        tickers=ticker_list,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        initial_currency=initial_currency,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=margin_requirement,
    )

    execute_backtest(backtester)


def _parse_ticker_list(raw: str) -> List[str]:
    return [ticker.strip() for ticker in raw.split(",") if ticker.strip()]


def _build_ticker_markets(tickers: List[str]) -> dict[str, str]:
    from src.data.borsdata_ticker_mapping import get_ticker_market
    from src.tools.api import set_ticker_markets

    markets: dict[str, str] = {}
    unknown: List[str] = []
    for ticker in tickers:
        market = get_ticker_market(ticker)
        if market:
            markets[ticker] = market.lower()
        else:
            markets[ticker] = "global"
            unknown.append(ticker)

    if unknown:
        typer.secho("Warning: tickers missing from Börsdata mapping: " + ", ".join(unknown), fg=typer.colors.YELLOW)
    set_ticker_markets(markets)
    return markets


def _export_transcript(session_id: str) -> None:
    from src.data.analysis_storage import export_to_markdown

    try:
        output = export_to_markdown(session_id)
    except Exception as exc:  # pragma: no cover - filesystem / DB errors
        typer.secho(f"Transcript export failed: {exc}", fg=typer.colors.RED)
        return
    typer.secho(f"Transcript saved to {output}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
