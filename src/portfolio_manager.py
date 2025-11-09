"""
Portfolio Management CLI - Long-only portfolio rebalancing

Manages a concentrated portfolio of 5-10 high-conviction positions.
Analyzes current portfolio and investment universe using selected analysts,
then generates rebalancing recommendations.
"""

import warnings

# Suppress LangChain deprecation warnings about debug imports
warnings.filterwarnings("ignore", message=".*Importing debug from langchain root module.*", category=UserWarning)

from pathlib import Path

import click
from dotenv import load_dotenv

from src.services.portfolio_runner import RebalanceConfig, run_rebalance

# Load environment variables from .env file
load_dotenv()


@click.command()
# Portfolio input
@click.option("--portfolio", type=click.Path(exists=True), required=False, help="Path to portfolio CSV file (required for CSV source)")
# Universe input options
@click.option("--universe", type=click.Path(exists=True), help="Path to universe list file")
@click.option("--universe-tickers", type=str, help="Comma-separated list of tickers (auto-detects Nordic/Global, e.g., AAPL,TELIA,VOLV B)")
# Analysis configuration
@click.option("--analysts", type=str, default="all", help='Analyst selection: "all" (16 analysts), "famous" (13 investors), "core" (4 analysts), "basic" (fundamentals only), or comma-separated list')
@click.option("--model", type=str, default="gpt-4o", help="LLM model to use")
@click.option("--model-provider", type=click.Choice(["openai", "anthropic", "groq", "ollama"]), help="Model provider (optional, auto-detected from model name)")
@click.option("--max-workers", type=int, default=4, help="Maximum parallel workers for analyst tasks (default: 4, lower = slower but avoids rate limits)")
# Position sizing constraints
@click.option("--max-holdings", type=int, default=8, help="Maximum number of holdings in portfolio (default: 8)")
@click.option("--max-position", type=float, default=0.25, help="Maximum position size as decimal (0.25 = 25%)")
@click.option("--min-position", type=float, default=0.05, help="Minimum position size as decimal (0.05 = 5%)")
@click.option("--min-trade", type=float, default=500.0, help="Minimum trade size in USD equivalent")
# Currency settings
@click.option("--home-currency", type=str, default="SEK", help="Home currency for portfolio calculations (default: SEK)")
# Cache control
@click.option("--no-cache", is_flag=True, help="Bypass all caches and fetch fresh data from Börsdata")
@click.option("--no-cache-agents", is_flag=True, help="Reuse cached KPI data but force fresh analyst recommendations")
# Output control
@click.option("--verbose", is_flag=True, help="Show detailed analysis from each analyst")
@click.option("--dry-run", is_flag=True, help="Show recommendations without saving")
@click.option("--test", is_flag=True, help="Run in test mode with limited analysts for quick validation")
@click.option("--portfolio-source", type=click.Choice(["csv", "ibkr"]), default="csv", show_default=True, help="Where to load the current holdings from")
@click.option("--ibkr-account", type=str, help="Optional IBKR account identifier")
@click.option("--ibkr-host", type=str, default="https://localhost", show_default=True, help="Client Portal host (scheme optional)")
@click.option("--ibkr-port", type=int, default=5000, show_default=True, help="Client Portal port")
@click.option("--ibkr-verify-ssl/--no-ibkr-verify-ssl", default=False, show_default=True, help="Verify SSL certificates when calling IBKR")
@click.option("--ibkr-timeout", type=float, default=30.0, show_default=True, help="Timeout in seconds for IBKR requests")
def main(portfolio, universe, universe_tickers, analysts, model, model_provider, max_workers, max_holdings, max_position, min_position, min_trade, home_currency, no_cache, no_cache_agents, verbose, dry_run, test, portfolio_source, ibkr_account, ibkr_host, ibkr_port, ibkr_verify_ssl, ibkr_timeout):
    """
    AI Hedge Fund Portfolio Manager - Long-only portfolio rebalancing

    Manages a concentrated portfolio of 5-10 high-conviction positions.
    Analyzes current portfolio and investment universe using selected analysts,
    then generates rebalancing recommendations. Automatically saves updated
    portfolio to portfolio_YYYYMMDD.csv.

    Examples:

        # Starting from zero (empty portfolio)
        python src/portfolio_manager.py --portfolio empty.csv --universe stocks.txt

        # Regular rebalancing
        python src/portfolio_manager.py --portfolio portfolio.csv --universe stocks.txt

        # Refresh analyst recommendations (reuse cached KPI data)
        python src/portfolio_manager.py --portfolio portfolio.csv --universe stocks.txt --no-cache-agents

        # Quick test with limited analysts (auto-detects Nordic/Global)
        python src/portfolio_manager.py --portfolio portfolio.csv --universe-tickers "AAPL,TELIA,VOLV B" --test
    """

    if portfolio_source == "csv" and not portfolio:
        click.echo("Error: --portfolio is required when --portfolio-source=csv", err=True)
        raise click.Abort()

    config = RebalanceConfig(
        portfolio_path=Path(portfolio) if portfolio else None,
        universe_path=Path(universe) if universe else None,
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
        portfolio_source=portfolio_source,
        ibkr_account=ibkr_account,
        ibkr_host=ibkr_host,
        ibkr_port=ibkr_port,
        ibkr_verify_ssl=ibkr_verify_ssl,
        ibkr_timeout=ibkr_timeout,
    )

    try:
        outcome = run_rebalance(config)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.Abort()

    print("\n" + "=" * 60)
    response = click.prompt("Export full analyst transcript to markdown? (y/N)", default="N", show_default=False)
    if response.lower() in ["y", "yes"]:
        try:
            from src.data.analysis_storage import export_to_markdown

            output_path = export_to_markdown(outcome.session_id)
            print(f"\n✅ Analyst transcript saved to: {output_path}")
        except Exception as e:
            click.echo(f"\n⚠️  Error exporting transcript: {e}", err=True)


if __name__ == "__main__":
    main()
