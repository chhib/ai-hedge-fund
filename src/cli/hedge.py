from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import os

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
@click.option("--ibkr-host", default=os.environ.get("IBKR_HOST", "https://localhost"), show_default=True, help="Client Portal host (scheme optional)")
@click.option("--ibkr-port", default=int(os.environ.get("IBKR_PORT", "5001")), show_default=True, type=int, help="Client Portal port")
@click.option("--ibkr-verify-ssl/--no-ibkr-verify-ssl", default=os.environ.get("IBKR_VERIFY_SSL", "false").lower() in ("true", "1", "yes"), show_default=True, help="Verify SSL certificates for IBKR calls")
@click.option("--ibkr-timeout", default=float(os.environ.get("IBKR_TIMEOUT", "30")), show_default=True, type=float, help="Timeout in seconds for IBKR API calls")
@click.option("--ibkr-whatif", is_flag=True, help="Preview IBKR orders using what-if (no trades)")
@click.option("--ibkr-execute", is_flag=True, help="Place IBKR orders (requires confirmation)")
@click.option("--ibkr-yes", is_flag=True, help="Skip IBKR trade confirmation prompts")
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
    ibkr_whatif: bool,
    ibkr_execute: bool,
    ibkr_yes: bool,
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

    if ibkr_whatif or ibkr_execute:
        if dry_run and ibkr_execute:
            click.secho("⚠️  Dry-run mode: IBKR execution disabled (preview only).", fg="yellow")
            ibkr_execute = False
        if ibkr_execute and not ibkr_yes and not sys.stdin.isatty():
            click.secho("Error: --ibkr-execute requires interactive confirmation or --ibkr-yes in non-interactive mode.", fg="red")
            raise click.Abort()

        from src.integrations.ibkr_execution import execute_ibkr_rebalance_trades
        from src.services.portfolio_runner import _ensure_ibkr_gateway

        base_url = _ensure_ibkr_gateway(config)
        confirm = None
        if ibkr_execute:
            if ibkr_yes:
                confirm = lambda _: True
            else:
                confirm = lambda msg: click.confirm(msg, default=False)

        report = execute_ibkr_rebalance_trades(
            outcome.results.get("recommendations", []),
            base_url=base_url,
            account_id=ibkr_account,
            verify_ssl=ibkr_verify_ssl,
            timeout=ibkr_timeout,
            preview_only=True,
            execute=ibkr_execute,
            confirm=confirm,
        )
        _render_ibkr_report(report)

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


def _render_ibkr_report(report) -> None:
    from src.integrations.ibkr_execution import summarize_submissions

    click.echo("\n" + "-" * 40)
    title = "IBKR ORDER EXECUTION" if report.executed else "IBKR ORDER PREVIEW"
    click.echo(title)
    click.echo("-" * 40)
    click.echo(f"Account: {report.account_id or 'n/a'}")
    click.echo(f"Intents: {len(report.intents)} | Resolved: {len(report.resolved)} | Skipped: {len(report.skipped)}")
    if getattr(report, "aborted", False):
        click.echo("Status: aborted due to trading permissions")
    if report.warnings:
        click.echo("Warnings:")
        for warning in report.warnings:
            click.echo(f"  • {warning}")
    if report.skipped:
        click.echo("Skipped:")
        for skip in report.skipped:
            click.echo(f"  • {skip.ticker} ({skip.action}): {skip.reason}")
    if report.executed:
        final_summaries = summarize_submissions(getattr(report, "final_submissions", []))
        click.echo(f"Submitted: {len(final_summaries)}")
        if final_summaries:
            click.echo("Execution results:")
            for summary in final_summaries:
                click.echo(f"  • {summary}")


@cli.group()
def ibkr() -> None:
    """Interactive Brokers gateway tools."""


@ibkr.command()
@click.option("--ibkr-host", default=os.environ.get("IBKR_HOST", "https://localhost"), show_default=True, help="Client Portal host")
@click.option("--ibkr-port", default=int(os.environ.get("IBKR_PORT", "5001")), show_default=True, type=int, help="Client Portal port")
@click.option("--ibkr-verify-ssl/--no-ibkr-verify-ssl", default=os.environ.get("IBKR_VERIFY_SSL", "false").lower() in ("true", "1", "yes"), show_default=True, help="Verify SSL certificates")
@click.option("--ibkr-timeout", default=float(os.environ.get("IBKR_TIMEOUT", "30")), show_default=True, type=float, help="Timeout in seconds")
def check(ibkr_host: str, ibkr_port: int, ibkr_verify_ssl: bool, ibkr_timeout: float) -> None:
    """Validate each IBKR pipeline stage against the live gateway."""
    from src.services.portfolio_runner import _check_ibkr_gateway
    from src.integrations.ibkr_client import IBKRClient
    from src.integrations.ibkr_contract_mapper import load_contract_overrides

    base_url = f"{ibkr_host}:{ibkr_port}"
    failures = 0

    # Stage 1: Gateway connectivity
    click.echo("1/5  Gateway connectivity ... ", nl=False)
    is_running, is_authenticated = _check_ibkr_gateway(base_url, timeout=ibkr_timeout)
    if not is_running:
        click.secho("FAIL (not reachable)", fg="red")
        click.secho("     Start the gateway and authenticate before running this check.", fg="yellow")
        sys.exit(1)
    if not is_authenticated:
        click.secho("FAIL (not authenticated)", fg="red")
        click.secho(f"     Open {base_url} in a browser and log in.", fg="yellow")
        sys.exit(1)
    click.secho("PASS", fg="green")

    client = IBKRClient(base_url, verify_ssl=ibkr_verify_ssl, timeout=ibkr_timeout)

    # Stage 2: Account resolution
    click.echo("2/5  Account resolution ... ", nl=False)
    account_id = None
    try:
        account_id = client.resolve_account_id()
        if account_id:
            click.secho(f"PASS ({account_id})", fg="green")
        else:
            click.secho("FAIL (no account found)", fg="red")
            failures += 1
    except Exception as exc:
        click.secho(f"FAIL ({exc})", fg="red")
        failures += 1

    # Stage 3: Contract resolution
    click.echo("3/5  Contract resolution ... ", nl=False)
    overrides = load_contract_overrides()
    if not overrides:
        click.secho("SKIP (no contract mappings found)", fg="yellow")
    else:
        sample_tickers = list(overrides.keys())[:3]
        sample_conids = [overrides[t].conid for t in sample_tickers]
        resolved = 0
        for conid in sample_conids:
            try:
                info = client.get_contract_info(conid)
                if info:
                    resolved += 1
            except Exception:
                pass
        if resolved == len(sample_conids):
            click.secho(f"PASS ({resolved}/{len(sample_conids)} - {', '.join(sample_tickers)})", fg="green")
        else:
            click.secho(f"FAIL ({resolved}/{len(sample_conids)} resolved)", fg="red")
            failures += 1

    # Stage 4: Market data
    click.echo("4/5  Market data ... ", nl=False)
    if not overrides:
        click.secho("SKIP (no conids to query)", fg="yellow")
    else:
        sample_conids = [overrides[t].conid for t in list(overrides.keys())[:3]]
        try:
            snap = client.get_marketdata_snapshot(sample_conids)
            if snap and isinstance(snap, list) and len(snap) > 0:
                click.secho(f"PASS ({len(snap)} snapshot(s))", fg="green")
            else:
                click.secho("FAIL (empty response)", fg="red")
                failures += 1
        except Exception as exc:
            click.secho(f"FAIL ({exc})", fg="red")
            failures += 1

    # Stage 5: Order preview (what-if)
    click.echo("5/5  Order preview ... ", nl=False)
    if not account_id or not overrides:
        click.secho("SKIP (need account + conids)", fg="yellow")
    else:
        first_ticker = list(overrides.keys())[0]
        first_conid = overrides[first_ticker].conid
        order = {
            "conid": first_conid,
            "orderType": "MKT",
            "side": "BUY",
            "quantity": 1,
            "tif": "DAY",
        }
        try:
            result = client.preview_order(account_id, order)
            if result:
                click.secho(f"PASS (whatif for {first_ticker})", fg="green")
            else:
                click.secho("FAIL (empty response)", fg="red")
                failures += 1
        except Exception as exc:
            click.secho(f"FAIL ({exc})", fg="red")
            failures += 1

    # Summary
    click.echo()
    if failures:
        click.secho(f"{failures} stage(s) failed.", fg="red")
        sys.exit(1)
    else:
        click.secho("All stages passed.", fg="green")


@ibkr.command()
@click.option("--ibkr-host", default=os.environ.get("IBKR_HOST", "https://localhost"), show_default=True, help="Client Portal host")
@click.option("--ibkr-port", default=int(os.environ.get("IBKR_PORT", "5001")), show_default=True, type=int, help="Client Portal port")
@click.option("--ibkr-verify-ssl/--no-ibkr-verify-ssl", default=os.environ.get("IBKR_VERIFY_SSL", "false").lower() in ("true", "1", "yes"), show_default=True, help="Verify SSL certificates")
@click.option("--ibkr-timeout", default=float(os.environ.get("IBKR_TIMEOUT", "30")), show_default=True, type=float, help="Timeout in seconds")
@click.option("--fix", is_flag=True, help="Auto-refresh invalid contracts via 3-tier resolution")
@click.option("--delay", default=0.15, show_default=True, type=float, help="Delay between IBKR API calls (seconds)")
def validate(ibkr_host: str, ibkr_port: int, ibkr_verify_ssl: bool, ibkr_timeout: float, fix: bool, delay: float) -> None:
    """Validate contract overrides against the live IBKR gateway."""
    from src.services.portfolio_runner import _check_ibkr_gateway
    from src.integrations.ibkr_client import IBKRClient
    from src.integrations.ibkr_contract_mapper import (
        load_contract_overrides,
        save_contract_overrides,
        validate_all_contracts,
    )

    base_url = f"{ibkr_host}:{ibkr_port}"

    # Check gateway
    click.echo("Checking IBKR gateway ... ", nl=False)
    is_running, is_authenticated = _check_ibkr_gateway(base_url, timeout=ibkr_timeout)
    if not is_running:
        click.secho("FAIL (not reachable)", fg="red")
        sys.exit(1)
    if not is_authenticated:
        click.secho("FAIL (not authenticated)", fg="red")
        sys.exit(1)
    click.secho("OK", fg="green")

    overrides = load_contract_overrides()
    if not overrides:
        click.secho("No contract mappings found.", fg="yellow")
        return

    client = IBKRClient(base_url, verify_ssl=ibkr_verify_ssl, timeout=ibkr_timeout)
    total = len(overrides)
    click.echo(f"Validating {total} contracts (delay={delay}s) ...")

    def _progress(ticker: str, result) -> None:
        status_colors = {"valid": "green", "invalid": "red", "exchange_changed": "yellow", "error": "red"}
        color = status_colors.get(result.status, "white")
        label = result.status.upper()
        extra = ""
        if result.status == "exchange_changed":
            extra = f" ({result.stored_exchange} -> {result.live_exchange})"
        elif result.status == "invalid":
            extra = f" ({result.error})"
        elif result.status == "error":
            extra = f" ({result.error})"
        click.echo(f"  {ticker:<12} {result.conid:>12}  ", nl=False)
        click.secho(f"{label}{extra}", fg=color)

    results = validate_all_contracts(client, overrides, delay=delay, progress_cb=_progress)

    # Summary
    valid = sum(1 for r in results if r.status == "valid")
    invalid = sum(1 for r in results if r.status == "invalid")
    exchange_changed = sum(1 for r in results if r.status == "exchange_changed")
    errors = sum(1 for r in results if r.status == "error")

    click.echo()
    click.echo(f"Valid:            {valid}")
    click.echo(f"Invalid:          {invalid}")
    click.echo(f"Exchange changed: {exchange_changed}")
    click.echo(f"Errors:           {errors}")

    if fix and invalid:
        click.echo()
        click.echo(f"Attempting to fix {invalid} invalid contract(s) ...")
        from scripts.build_ibkr_contract_overrides import resolve_single_ticker

        fixed = 0
        for r in results:
            if r.status != "invalid":
                continue
            resolved = resolve_single_ticker(client, r.ticker, delay=delay)
            if resolved:
                from src.integrations.ibkr_contract_mapper import ContractOverride

                overrides[r.ticker] = ContractOverride(
                    conid=int(resolved["conid"]),
                    exchange=resolved.get("exchange"),
                    currency=resolved.get("currency"),
                    description=resolved.get("description"),
                )
                fixed += 1
                click.secho(f"  Fixed {r.ticker} -> conid {resolved['conid']}", fg="green")
            else:
                click.secho(f"  Could not resolve {r.ticker}", fg="red")

        if fixed:
            save_contract_overrides(overrides)
            click.secho(f"Saved {fixed} updated mapping(s).", fg="green")

    if invalid or errors:
        sys.exit(1)


@cli.group()
def cache() -> None:
    """Manage the Börsdata prefetch cache."""


@cache.command("clear")
@click.option("--tickers", help="Comma-separated tickers to clear (clears all if omitted)")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def cache_clear(tickers: Optional[str], yes: bool) -> None:
    """Clear cache entries for specific tickers or all cache."""
    from src.data.prefetch_store import PrefetchStore

    with PrefetchStore() as store:
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
            if not yes:
                click.confirm(f"Clear cache for {len(ticker_list)} ticker(s)?", abort=True)
            deleted = store.delete_tickers(ticker_list)
            click.secho(f"✓ Cleared {deleted} cache entries for: {', '.join(ticker_list)}", fg="green")
        else:
            cached = store.get_cached_tickers()
            if not cached:
                click.secho("Cache is empty", fg="yellow")
                return
            if not yes:
                click.confirm(f"Clear ALL {len(cached)} cached tickers?", abort=True)
            deleted = store.delete_tickers(cached)
            click.secho(f"✓ Cleared {deleted} cache entries", fg="green")


@cache.command("list")
def cache_list() -> None:
    """List all tickers currently in the cache."""
    from src.data.prefetch_store import PrefetchStore

    with PrefetchStore() as store:
        cached = store.get_cached_tickers()
        if not cached:
            click.secho("Cache is empty", fg="yellow")
            return
        click.echo(f"Cached tickers ({len(cached)}):")
        for ticker in sorted(cached):
            click.echo(f"  • {ticker}")


if __name__ == "__main__":
    cli()
