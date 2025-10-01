from __future__ import annotations

import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta
import argparse

from colorama import Fore, Style, init
import questionary

from .engine import BacktestEngine
from src.llm.models import LLM_ORDER, OLLAMA_LLM_ORDER, get_model_info, ModelProvider
from src.utils.analysts import ANALYST_ORDER
from src.main import run_hedge_fund
from src.utils.ollama import ensure_ollama_and_model
from src.data.borsdata_ticker_mapping import get_ticker_market


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backtesting engine (modular)")
    parser.add_argument("--tickers", type=str, required=False, help="Comma-separated tickers (auto-detects Nordic/Global, e.g., AAPL,TELIA)")
    parser.add_argument("--tickers-nordics", type=str, required=False, help="Comma-separated Nordic tickers (for backward compatibility)")
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d"),
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--initial-currency", type=str, default="USD", help="The currency for the initial capital and backtest.")
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument("--analysts", type=str, required=False)
    parser.add_argument("--analysts-all", action="store_true")
    parser.add_argument("--ollama", action="store_true")
    parser.add_argument("--model-name", type=str, required=False, help="The name of the model to use.")
    parser.add_argument("--model-provider", type=str, required=False, help="The provider of the model.")

    args = parser.parse_args()
    init(autoreset=True)

    from src.tools.api import set_ticker_markets

    # Parse ticker arguments
    explicit_nordic_tickers = [t.strip() for t in args.tickers_nordics.split(",")] if args.tickers_nordics else []
    raw_tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else []

    # Build ticker to market mapping
    ticker_markets = {}
    unknown_tickers = []

    # First, handle explicitly specified Nordic tickers (backward compatibility)
    for ticker in explicit_nordic_tickers:
        ticker_markets[ticker] = "nordic"

    # For --tickers, automatically detect market using the mapping
    for ticker in raw_tickers:
        # Skip if already classified as Nordic
        if ticker in ticker_markets:
            continue

        # Look up the ticker in the global mapping
        market = get_ticker_market(ticker)
        if market:
            # Convert "Nordic" to "nordic" for consistency with existing code
            ticker_markets[ticker] = market.lower()
        else:
            # Unknown ticker - we'll add it to global as fallback and warn
            ticker_markets[ticker] = "global"
            unknown_tickers.append(ticker)

    # Show warning for unknown tickers
    if unknown_tickers:
        print(f"\n{Fore.YELLOW}⚠️  Warning: The following tickers are not in the Borsdata mapping:{Style.RESET_ALL}")
        for ticker in unknown_tickers:
            print(f"   • {ticker}")
        print(f"\n{Fore.CYAN}💡 Tip: Run this command to refresh the ticker mapping:{Style.RESET_ALL}")
        print(f"   poetry run python scripts/refresh_borsdata_mapping.py\n")

    # Combine all tickers
    tickers = list(ticker_markets.keys())

    if not tickers:
        print(f"{Fore.RED}Error: At least one ticker must be provided via --tickers or --tickers-nordics.{Style.RESET_ALL}")
        return 1

    set_ticker_markets(ticker_markets)

    # Analysts selection is simplified; no interactive prompts here
    if args.analysts_all:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
    elif args.analysts:
        selected_analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
    else:
        # Interactive analyst selection (same as legacy backtester)
        choices = questionary.checkbox(
            "Use the Space bar to select/unselect analysts.",
            choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
            instruction="\n\nPress 'a' to toggle all.\n\nPress Enter when done to run the hedge fund.",
            validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
            style=questionary.Style(
                [
                    ("checkbox-selected", "fg:green"),
                    ("selected", "fg:green noinherit"),
                    ("highlighted", "noinherit"),
                    ("pointer", "noinherit"),
                ]
            ),
        ).ask()
        if not choices:
            print("\n\nInterrupt received. Exiting...")
            return 1
        selected_analysts = choices
        print(
            f"\nSelected analysts: "
            f"{', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n"
        )

    # Model selection
    if args.model_name:
        model_name = args.model_name
        if args.model_provider:
            model_provider = args.model_provider
            if model_provider.upper() == 'OPENAI':
                model_provider = 'OpenAI'
        else:
            # Default to OpenAI if no provider is specified
            model_provider = 'OpenAI'
        print(
            f"\nUsing model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL} from provider: {Fore.CYAN}{model_provider}{Style.RESET_ALL}\n"
        )
    elif args.ollama:
        print(f"{Fore.CYAN}Using Ollama for local LLM inference.{Style.RESET_ALL}")
        model_name = questionary.select(
            "Select your Ollama model:",
            choices=[questionary.Choice(display, value=value) for display, value, _ in OLLAMA_LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()
        if not model_name:
            print("\n\nInterrupt received. Exiting...")
            return 1
        if model_name == "-":
            model_name = questionary.text("Enter the custom model name:").ask()
            if not model_name:
                print("\n\nInterrupt received. Exiting...")
                return 1
        if not ensure_ollama_and_model(model_name):
            print(f"{Fore.RED}Cannot proceed without Ollama and the selected model.{Style.RESET_ALL}")
            return 1
        model_provider = ModelProvider.OLLAMA.value
        print(
            f"\nSelected {Fore.CYAN}Ollama{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n"
        )
    else:
        model_choice = questionary.select(
            "Select your LLM model:",
            choices=[questionary.Choice(display, value=(name, provider)) for display, name, provider in LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()
        if not model_choice:
            print("\n\nInterrupt received. Exiting...")
            return 1
        model_name, model_provider = model_choice
        model_info = get_model_info(model_name, model_provider)
        if model_info and model_info.is_custom():
            model_name = questionary.text("Enter the custom model name:").ask()
            if not model_name:
                print("\n\nInterrupt received. Exiting...")
                return 1
        print(
            f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n"
        )

    engine = BacktestEngine(
        agent=run_hedge_fund,
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        initial_currency=args.initial_currency,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=args.margin_requirement,
    )

    metrics = engine.run_backtest()
    values = engine.get_portfolio_values()

    # Minimal terminal output (no plots)
    if values:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}ENGINE RUN COMPLETE{Style.RESET_ALL}")
        last_value = values[-1]["Portfolio Value"]
        start_value = values[0]["Portfolio Value"]
        total_return = (last_value / start_value - 1.0) * 100.0 if start_value else 0.0
        print(f"Total Return: {Fore.GREEN if total_return >= 0 else Fore.RED}{total_return:.2f}%{Style.RESET_ALL}")
    if metrics.get("sharpe_ratio") is not None:
        print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    if metrics.get("sortino_ratio") is not None:
        print(f"Sortino: {metrics['sortino_ratio']:.2f}")
    if metrics.get("max_drawdown") is not None:
        md = abs(metrics["max_drawdown"]) if metrics["max_drawdown"] is not None else 0.0
        if metrics.get("max_drawdown_date"):
            print(f"Max DD: {md:.2f}% on {metrics['max_drawdown_date']}")
        else:
            print(f"Max DD: {md:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())




