from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import click
from dotenv import load_dotenv

from src.services.portfolio_runner import RebalanceConfig, run_rebalance


load_dotenv()


@click.group(help="Unified CLI for the AI Hedge Fund workflows.")
def cli() -> None:
    """Top-level command group."""


@cli.command()
@click.option("--portfolio", type=click.Path(path_type=Path, exists=True), help="Path to the current portfolio CSV (required for CSV source)")
@click.option("--universe", type=click.Path(path_type=Path, exists=True), help="Path to a universe list")
@click.option("--universe-tickers", type=str, help="Comma-separated tickers if no file is provided")
@click.option("--analysts", default="all", show_default=True, help="Analyst preset or comma-separated list")
@click.option("--model", default="gpt-4o", show_default=True, help="LLM model name")
@click.option("--model-provider", help="Optional model provider override")
@click.option("--max-workers", default=4, show_default=True, type=int, help="Parallel worker cap for analyst tasks")
@click.option("--max-holdings", default=8, show_default=True, type=int, help="Maximum holdings in the target portfolio")
@click.option("--max-position", default=0.25, show_default=True, type=float, help="Maximum position size as decimal")
@click.option("--min-position", default=0.05, show_default=True, type=float, help="Minimum position size as decimal")
@click.option("--min-trade", default=500.0, show_default=True, type=float, help="Minimum trade size in USD equivalent")
@click.option("--home-currency", default="SEK", show_default=True, help="Home currency for portfolio calculations")
@click.option("--no-cache", is_flag=True, help="Bypass all cached Börsdata payloads")
@click.option("--no-cache-agents", is_flag=True, help="Reuse KPI cache but refresh analyst runs")
@click.option("--dry-run", is_flag=True, help="Show recommendations without saving a CSV")
@click.option("--verbose", is_flag=True, help="Show detailed analyst output")
@click.option("--test", is_flag=True, help="Quick validation using the fundamentals analyst")
@click.option("--export-transcript", is_flag=True, help="Export analyst transcript automatically")
@click.option("--output-dir", type=click.Path(path_type=Path), help="Directory for the generated CSV (defaults to CWD)")
@click.option("--portfolio-source", type=click.Choice(["csv", "ibkr"], case_sensitive=False), default="csv", show_default=True, help="Source of the current holdings")
@click.option("--ibkr-account", help="Optional IBKR account override (defaults to first account)")
@click.option("--ibkr-host", default="https://localhost", show_default=True, help="Client Portal host (scheme optional)")
@click.option("--ibkr-port", default=5000, show_default=True, type=int, help="Client Portal port")
@click.option("--ibkr-verify-ssl/--no-ibkr-verify-ssl", default=False, show_default=True, help="Verify SSL certificates for IBKR calls")
@click.option("--ibkr-timeout", default=30.0, show_default=True, type=float, help="Timeout in seconds for IBKR API calls")
def rebalance(
    portfolio: Optional[Path],
    universe: Optional[Path],
    universe_tickers: Optional[str],
    analysts: str,
    model: str,
    model_provider: Optional[str],
    max_workers: int,
    max_holdings: int,
    max_position: float,
    min_position: float,
    min_trade: float,
    home_currency: str,
    no_cache: bool,
    no_cache_agents: bool,
    dry_run: bool,
    verbose: bool,
    test: bool,
    export_transcript: bool,
    output_dir: Optional[Path],
    portfolio_source: str,
    ibkr_account: Optional[str],
    ibkr_host: str,
    ibkr_port: int,
    ibkr_verify_ssl: bool,
    ibkr_timeout: float,
) -> None:
    """Run the weekly long-only rebalance flow."""

    normalized_source = portfolio_source.lower()
    if normalized_source == "csv" and portfolio is None:
        click.secho("Error: --portfolio is required when --portfolio-source=csv", fg="red")
        raise click.Abort()

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
        click.secho(f"Error: {exc}", fg="red")
        raise click.Abort()

    if export_transcript:
        _export_transcript(outcome.session_id)


@cli.command()
@click.option("--tickers", required=True, help="Comma-separated tickers")
@click.option("--start-date", required=True, help="Backtest start date (YYYY-MM-DD)")
@click.option("--end-date", required=True, help="Backtest end date (YYYY-MM-DD)")
@click.option("--initial-capital", default=100_000.0, show_default=True, type=float, help="Starting capital")
@click.option("--initial-currency", default="USD", show_default=True, help="Currency for the starting capital")
@click.option("--margin-requirement", default=0.0, show_default=True, type=float, help="Margin requirement percentage")
@click.option("--analysts", help="Comma-separated analysts for the run")
@click.option("--model-name", default="gpt-4.1", show_default=True, help="LLM model name")
@click.option("--model-provider", default="OpenAI", show_default=True, help="LLM provider")
def backtest(
    tickers: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    initial_currency: str,
    margin_requirement: float,
    analysts: Optional[str],
    model_name: str,
    model_provider: str,
) -> None:
    """Backtest the hedge-fund agent pipeline without interactive prompts."""

    ticker_list = _parse_ticker_list(tickers)
    if not ticker_list:
        click.secho("Error: At least one ticker must be provided", fg="red")
        raise click.Abort()

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
        click.secho("Warning: tickers missing from Börsdata mapping: " + ", ".join(unknown), fg="yellow")
    set_ticker_markets(markets)
    return markets


def _export_transcript(session_id: str) -> None:
    from src.data.analysis_storage import export_to_markdown

    try:
        output = export_to_markdown(session_id)
    except Exception as exc:  # pragma: no cover - filesystem / DB errors
        click.secho(f"Transcript export failed: {exc}", fg="red")
        return
    click.secho(f"Transcript saved to {output}", fg="green")


if __name__ == "__main__":
    cli()
