"""
Portfolio Management CLI - Long-only portfolio rebalancing

Manages a concentrated portfolio of 5-10 high-conviction positions.
Analyzes current portfolio and investment universe using selected analysts,
then generates rebalancing recommendations.
"""

import warnings

# Suppress LangChain deprecation warnings about debug imports
warnings.filterwarnings("ignore", message=".*Importing debug from langchain root module.*", category=UserWarning)

import uuid
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv

from src.agents.enhanced_portfolio_manager import EnhancedPortfolioManager
from src.utils.output_formatter import display_results, format_as_portfolio_csv
from src.utils.portfolio_loader import load_portfolio, load_universe
from src.data.borsdata_ticker_mapping import get_ticker_market

# Load environment variables from .env file
load_dotenv()


@click.command()
# Portfolio input
@click.option("--portfolio", type=click.Path(exists=True), required=True, help="Path to portfolio CSV file")
# Universe input options
@click.option("--universe", type=click.Path(exists=True), help="Path to universe list file")
@click.option("--universe-tickers", type=str, help="Comma-separated list of tickers (auto-detects Nordic/Global, e.g., AAPL,TELIA,VOLV B)")
# Analysis configuration
@click.option("--analysts", type=str, default="all", help='Analyst selection: "all" (16 analysts), "famous" (13 investors), "core" (4 analysts), "basic" (fundamentals only), or comma-separated list')
@click.option("--model", type=str, default="gpt-4o", help="LLM model to use")
@click.option("--model-provider", type=click.Choice(["openai", "anthropic", "groq", "ollama"]), help="Model provider (optional, auto-detected from model name)")
# Position sizing constraints
@click.option("--max-holdings", type=int, default=8, help="Maximum number of holdings in portfolio (default: 8)")
@click.option("--max-position", type=float, default=0.25, help="Maximum position size as decimal (0.25 = 25%)")
@click.option("--min-position", type=float, default=0.05, help="Minimum position size as decimal (0.05 = 5%)")
@click.option("--min-trade", type=float, default=500.0, help="Minimum trade size in USD equivalent")
# Currency settings
@click.option("--home-currency", type=str, default="SEK", help="Home currency for portfolio calculations (default: SEK)")
# Cache control
@click.option("--no-cache", is_flag=True, help="Bypass all caches and fetch fresh data from Börsdata")
# Output control
@click.option("--verbose", is_flag=True, help="Show detailed analysis from each analyst")
@click.option("--dry-run", is_flag=True, help="Show recommendations without saving")
@click.option("--test", is_flag=True, help="Run in test mode with limited analysts for quick validation")
def main(portfolio, universe, universe_tickers, analysts, model, model_provider, max_holdings, max_position, min_position, min_trade, home_currency, no_cache, verbose, dry_run, test):
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

        # Quick test with limited analysts (auto-detects Nordic/Global)
        python src/portfolio_manager.py --portfolio portfolio.csv --universe-tickers "AAPL,TELIA,VOLV B" --test
    """

    # Test mode overrides - use basic analyst for quick validation
    if test:
        analysts = "basic"
        if verbose:
            print("🧪 Test mode: Using fundamentals analyst for quick validation")

    # Validate inputs
    if not universe and not universe_tickers:
        click.echo("Error: Must provide at least one universe source (--universe or --universe-tickers)", err=True)
        raise click.Abort()

    # Load portfolio
    try:
        portfolio_data = load_portfolio(portfolio)
        print(f"\n✓ Loaded portfolio with {len(portfolio_data.positions)} positions")
    except Exception as e:
        click.echo(f"Error loading portfolio: {e}", err=True)
        raise click.Abort()

    # Load universe and build ticker_markets dict with auto-detection
    try:
        universe_list = load_universe(universe, universe_tickers)
        if not universe_list:
            click.echo("Error: Universe is empty. Please provide valid ticker symbols.", err=True)
            raise click.Abort()
        print(f"✓ Loaded universe with {len(universe_list)} tickers")
    except Exception as e:
        click.echo(f"Error loading universe: {e}", err=True)
        raise click.Abort()

    # Build ticker_markets dict using auto-detection
    ticker_markets = {}
    unknown_tickers = []

    for ticker in universe_list:
        market = get_ticker_market(ticker)
        if market:
            ticker_markets[ticker] = market
        else:
            # Unknown ticker - default to global and warn
            ticker_markets[ticker] = "global"
            unknown_tickers.append(ticker)

    # Show warning for unknown tickers
    if unknown_tickers:
        click.echo(f"\n⚠️  Warning: The following tickers are not in the Borsdata mapping:", err=False)
        for ticker in unknown_tickers:
            click.echo(f"   • {ticker}")
        click.echo(f"\n💡 Tip: Run this command to refresh the ticker mapping:")
        click.echo(f"   poetry run python scripts/refresh_borsdata_mapping.py\n")

    # Show ticker routing info
    global_count = sum(1 for v in ticker_markets.values() if v.lower() == "global")
    nordic_count = sum(1 for v in ticker_markets.values() if v == "Nordic")
    print(f"✓ Market routing: {global_count} global, {nordic_count} Nordic\n")

    # Validate universe includes all current holdings
    current_tickers = {pos.ticker for pos in portfolio_data.positions}
    universe_set = set(universe_list)
    missing = current_tickers - universe_set
    if missing:
        print(f"⚠️  Warning: Adding current holdings to universe: {missing}\n")
        universe_list.extend(list(missing))

    # Parse analysts
    if analysts == "all":
        # Use all 16 available analysts from the registry
        analyst_list = [
            "warren_buffett", "charlie_munger", "stanley_druckenmiller",
            "peter_lynch", "ben_graham", "phil_fisher", "bill_ackman",
            "cathie_wood", "michael_burry", "mohnish_pabrai",
            "rakesh_jhunjhunwala", "aswath_damodaran", "jim_simons",
            "fundamentals", "technical", "sentiment", "valuation"
        ]
    elif analysts == "basic":
        analyst_list = ["fundamentals"]
    elif analysts == "famous":
        # Just the famous investor personas
        analyst_list = [
            "warren_buffett", "charlie_munger", "stanley_druckenmiller",
            "peter_lynch", "ben_graham", "phil_fisher", "bill_ackman",
            "cathie_wood", "michael_burry", "mohnish_pabrai",
            "rakesh_jhunjhunwala", "aswath_damodaran", "jim_simons"
        ]
    elif analysts == "core":
        # Just the core 4 analysts
        analyst_list = ["fundamentals", "technical", "sentiment", "valuation"]
    else:
        analyst_list = [a.strip() for a in analysts.split(",")]

    # Show selected analysts
    print(f"✓ Using {len(analyst_list)} analysts\n")

    # Generate session ID for tracking analyses
    session_id = str(uuid.uuid4())
    if verbose:
        print(f"Session ID: {session_id}\n")

    # Initialize portfolio manager
    manager = EnhancedPortfolioManager(portfolio=portfolio_data, universe=universe_list, analysts=analyst_list, model_config={"name": model, "provider": model_provider}, ticker_markets=ticker_markets, home_currency=home_currency, no_cache=no_cache, verbose=verbose, session_id=session_id)

    # Generate recommendations (LONG-ONLY constraint applied here)

    try:
        results = manager.generate_rebalancing_recommendations(max_holdings=max_holdings, max_position=max_position, min_position=min_position, min_trade_size=min_trade)
    except Exception as e:
        click.echo(f"Error generating recommendations: {e}", err=True)
        if verbose:
            import traceback

            traceback.print_exc()
        raise click.Abort()

    # Display results
    display_results(results, verbose)

    # Save to CSV (unless dry-run)
    if not dry_run:
        output_file = f"portfolio_{datetime.now().strftime('%Y%m%d')}.csv"
        df = format_as_portfolio_csv(results)
        df.to_csv(output_file, index=False)
        print(f"\n✅ Rebalanced portfolio saved to: {output_file}")
        print(f"   Next run: python src/portfolio_manager.py --portfolio {output_file} --universe ...")
        if not df.empty:
            print("\n📄 Portfolio snapshot:")
            print(df.to_string(index=False))
        else:
            print("\n📄 Portfolio snapshot: (no positions)")
    else:
        print("\n⚠️  Dry-run mode - no files saved")

    # Prompt to export analyst transcript
    print("\n" + "=" * 60)
    response = click.prompt("Export full analyst transcript to markdown? (y/N)", default="N", show_default=False)
    if response.lower() in ["y", "yes"]:
        try:
            from src.data.analysis_storage import export_to_markdown

            output_path = export_to_markdown(session_id)
            print(f"\n✅ Analyst transcript saved to: {output_path}")
        except Exception as e:
            click.echo(f"\n⚠️  Error exporting transcript: {e}", err=True)


if __name__ == "__main__":
    main()
