"""
Portfolio Management CLI - Long-only portfolio rebalancing

Manages a concentrated portfolio of 5-10 high-conviction positions.
Analyzes current portfolio and investment universe using selected analysts,
then generates rebalancing recommendations.
"""

from datetime import datetime
from pathlib import Path

import click

from src.agents.enhanced_portfolio_manager import EnhancedPortfolioManager
from src.utils.output_formatter import display_results, format_as_portfolio_csv
from src.utils.portfolio_loader import load_portfolio, load_universe


@click.command()
# Portfolio input
@click.option("--portfolio", type=click.Path(exists=True), required=True, help="Path to portfolio CSV file")
# Universe input options
@click.option("--universe", type=click.Path(exists=True), help="Path to universe list file")
@click.option("--universe-tickers", type=str, help="Comma-separated list of global tickers")
@click.option("--universe-nordics", type=str, help="Comma-separated list of Nordic tickers")
@click.option("--universe-global", type=str, help="Comma-separated list of global tickers")
# Analysis configuration
@click.option("--analysts", type=str, default="all", help='Comma-separated list: warren_buffett, charlie_munger, fundamentals (or "all" for all 3)')
@click.option("--model", type=str, default="gpt-4o", help="LLM model to use")
@click.option("--model-provider", type=click.Choice(["openai", "anthropic", "groq", "ollama"]), help="Model provider (optional, auto-detected from model name)")
# Position sizing constraints
@click.option("--max-holdings", type=int, default=8, help="Maximum number of holdings in portfolio (default: 8)")
@click.option("--max-position", type=float, default=0.25, help="Maximum position size as decimal (0.25 = 25%)")
@click.option("--min-position", type=float, default=0.05, help="Minimum position size as decimal (0.05 = 5%)")
@click.option("--min-trade", type=float, default=500.0, help="Minimum trade size in USD equivalent")
# Output control
@click.option("--verbose", is_flag=True, help="Show detailed analysis from each analyst")
@click.option("--dry-run", is_flag=True, help="Show recommendations without saving")
@click.option("--test", is_flag=True, help="Run in test mode with limited analysts for quick validation")
def main(portfolio, universe, universe_tickers, universe_nordics, universe_global, analysts, model, model_provider, max_holdings, max_position, min_position, min_trade, verbose, dry_run, test):
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

        # Quick test with limited analysts
        python src/portfolio_manager.py --portfolio portfolio.csv --universe-tickers "AAPL,MSFT" --test
    """

    # Test mode overrides
    if test:
        analysts = "warren_buffett"
        if verbose:
            print("🧪 Test mode: Using 1 analyst for quick validation")

    # Validate inputs
    if not universe and not universe_tickers and not universe_nordics and not universe_global:
        click.echo("Error: Must provide at least one universe source (--universe, --universe-tickers, --universe-nordics, or --universe-global)", err=True)
        raise click.Abort()

    # Load portfolio
    try:
        portfolio_data = load_portfolio(portfolio)
        if verbose:
            print(f"\n✓ Loaded portfolio with {len(portfolio_data.positions)} positions")
    except Exception as e:
        click.echo(f"Error loading portfolio: {e}", err=True)
        raise click.Abort()

    # Load universe
    try:
        universe_list = load_universe(universe, universe_tickers, universe_nordics, universe_global)
        if not universe_list:
            click.echo("Error: Universe is empty. Please provide valid ticker symbols.", err=True)
            raise click.Abort()
        if verbose:
            print(f"✓ Loaded universe with {len(universe_list)} tickers")
    except Exception as e:
        click.echo(f"Error loading universe: {e}", err=True)
        raise click.Abort()

    # Validate universe includes all current holdings
    current_tickers = {pos.ticker for pos in portfolio_data.positions}
    universe_set = set(universe_list)
    missing = current_tickers - universe_set
    if missing:
        print(f"⚠️  Warning: Current holdings not in universe: {missing}")
        universe_list.extend(list(missing))

    # Parse analysts
    if analysts == "all":
        analyst_list = ["warren_buffett", "charlie_munger", "fundamentals"]
    elif analysts == "basic":
        analyst_list = ["fundamentals"]
    else:
        analyst_list = [a.strip() for a in analysts.split(",")]

    if verbose:
        print(f"✓ Using analysts: {', '.join(analyst_list)}")

    # Initialize portfolio manager
    manager = EnhancedPortfolioManager(portfolio=portfolio_data, universe=universe_list, analysts=analyst_list, model_config={"name": model, "provider": model_provider}, verbose=verbose)

    # Generate recommendations (LONG-ONLY constraint applied here)
    if verbose:
        print("\n🔄 Analyzing portfolio and generating recommendations...\n")

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
    else:
        print("\n⚠️  Dry-run mode - no files saved")


if __name__ == "__main__":
    main()