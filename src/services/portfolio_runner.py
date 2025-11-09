"""Reusable orchestration for the weekly portfolio rebalance workflow."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from src.agents.enhanced_portfolio_manager import EnhancedPortfolioManager
from src.data.borsdata_ticker_mapping import get_ticker_market
from src.utils.output_formatter import display_results, format_as_portfolio_csv
from src.utils.portfolio_loader import Portfolio, load_portfolio, load_universe


AnalystGroup = Literal["all", "basic", "famous", "core"]
PortfolioSource = Literal["csv", "ibkr"]


@dataclass(slots=True)
class RebalanceConfig:
    """Configuration options consumed by the rebalance service."""

    portfolio_path: Optional[Path]
    universe_path: Optional[Path]
    universe_tickers: Optional[str]
    analysts: str = "all"
    model: str = "gpt-4o"
    model_provider: Optional[str] = None
    max_workers: int = 4
    max_holdings: int = 8
    max_position: float = 0.25
    min_position: float = 0.05
    min_trade: float = 500.0
    home_currency: str = "SEK"
    no_cache: bool = False
    no_cache_agents: bool = False
    verbose: bool = False
    dry_run: bool = False
    test_mode: bool = False
    output_dir: Optional[Path] = None
    portfolio_source: PortfolioSource = "csv"
    ibkr_account: Optional[str] = None
    ibkr_host: str = "https://localhost"
    ibkr_port: int = 5000
    ibkr_verify_ssl: bool = False
    ibkr_timeout: float = 30.0


@dataclass(slots=True)
class RebalanceOutcome:
    """Return payload for CLI layers."""

    session_id: str
    results: Dict[str, Any]
    output_path: Optional[Path]
    unknown_tickers: List[str]


def run_rebalance(config: RebalanceConfig) -> RebalanceOutcome:
    """Execute the long-only rebalance flow and persist results when requested."""

    if config.portfolio_source == "csv" and not config.portfolio_path:
        raise ValueError("Portfolio path must be provided when using CSV input")

    if not config.universe_path and not config.universe_tickers:
        raise ValueError("Provide --universe or --universe-tickers to define the investment universe")

    if config.no_cache:
        print("🔄 Bypassing all caches (fetching fresh KPI data and analyst analysis)")
    elif config.no_cache_agents:
        print("🔄 Reusing cached KPI data, generating fresh analyst recommendations")

    portfolio = _load_portfolio_from_source(config)
    print(f"\n✓ Loaded portfolio with {len(portfolio.positions)} positions")

    universe_list = load_universe(
        str(config.universe_path) if config.universe_path else None,
        config.universe_tickers,
    )
    if not universe_list:
        raise ValueError("Universe is empty. Provide valid tickers via file or --universe-tickers.")
    print(f"✓ Loaded universe with {len(universe_list)} tickers")

    ticker_markets, unknown = _build_ticker_market_map(universe_list)
    _warn_unknown_tickers(unknown)

    _ensure_current_holdings_in_universe(portfolio, universe_list)

    analyst_list = _resolve_analyst_list(config.analysts, config.test_mode)
    print(f"✓ Using {len(analyst_list)} analysts\n")

    session_id = str(uuid.uuid4())
    if config.verbose:
        print(f"Session ID: {session_id}\n")
    manager = EnhancedPortfolioManager(
        portfolio=portfolio,
        universe=universe_list,
        analysts=analyst_list,
        model_config={"name": config.model, "provider": config.model_provider},
        ticker_markets=ticker_markets,
        home_currency=config.home_currency,
        no_cache=config.no_cache,
        no_cache_agents=config.no_cache_agents,
        verbose=config.verbose,
        session_id=session_id,
        max_workers=config.max_workers,
    )

    results = manager.generate_rebalancing_recommendations(
        max_holdings=config.max_holdings,
        max_position=config.max_position,
        min_position=config.min_position,
        min_trade_size=config.min_trade,
    )

    display_results(results, config.verbose)

    output_path = None
    if not config.dry_run:
        output_dir = config.output_dir or Path.cwd()
        output_path = output_dir / f"portfolio_{datetime.now().strftime('%Y%m%d')}.csv"
        df = format_as_portfolio_csv(results)
        df.to_csv(output_path, index=False)
        print(f"\n✅ Rebalanced portfolio saved to: {output_path}")
        print(f"   Next run: python src/portfolio_manager.py --portfolio {output_path.name} --universe ...")
        if not df.empty:
            print("\n📄 Portfolio snapshot:")
            print(df.to_string(index=False))
        else:
            print("\n📄 Portfolio snapshot: (no positions)")
    else:
        print("\n⚠️  Dry-run mode - no files saved")

    return RebalanceOutcome(session_id=session_id, results=results, output_path=output_path, unknown_tickers=unknown)


def _build_ticker_market_map(universe: List[str]) -> tuple[Dict[str, str], List[str]]:
    ticker_markets: Dict[str, str] = {}
    unknown: List[str] = []
    for ticker in universe:
        market = get_ticker_market(ticker)
        if market:
            ticker_markets[ticker] = market
        else:
            ticker_markets[ticker] = "global"
            unknown.append(ticker)

    global_count = sum(1 for v in ticker_markets.values() if v.lower() == "global")
    nordic_count = sum(1 for v in ticker_markets.values() if v == "Nordic")
    print(f"✓ Market routing: {global_count} global, {nordic_count} Nordic\n")
    return ticker_markets, unknown


def _warn_unknown_tickers(unknown: List[str]) -> None:
    if not unknown:
        return
    print("\n⚠️  Warning: The following tickers are not in the Borsdata mapping:")
    for ticker in unknown:
        print(f"   • {ticker}")
    print("\n💡 Tip: Run this command to refresh the ticker mapping:")
    print("   poetry run python scripts/refresh_borsdata_mapping.py\n")


def _ensure_current_holdings_in_universe(portfolio: Portfolio, universe: List[str]) -> None:
    current_tickers = {pos.ticker for pos in portfolio.positions}
    missing = current_tickers - set(universe)
    if not missing:
        return
    print(f"⚠️  Warning: Adding current holdings to universe: {missing}\n")
    universe.extend(sorted(missing))


def _resolve_analyst_list(selection: str, test_mode: bool) -> List[str]:
    if test_mode:
        print("🧪 Test mode: Using fundamentals analyst for quick validation")
        return ["fundamentals"]

    normalized = selection.lower().strip()
    if normalized == "all":
        return [
            "warren_buffett",
            "charlie_munger",
            "stanley_druckenmiller",
            "peter_lynch",
            "ben_graham",
            "phil_fisher",
            "bill_ackman",
            "cathie_wood",
            "michael_burry",
            "mohnish_pabrai",
            "rakesh_jhunjhunwala",
            "aswath_damodaran",
            "jim_simons",
            "fundamentals",
            "technical",
            "sentiment",
            "valuation",
        ]
    if normalized == "basic":
        return ["fundamentals"]
    if normalized == "famous":
        return [
            "warren_buffett",
            "charlie_munger",
            "stanley_druckenmiller",
            "peter_lynch",
            "ben_graham",
            "phil_fisher",
            "bill_ackman",
            "cathie_wood",
            "michael_burry",
            "mohnish_pabrai",
            "rakesh_jhunjhunwala",
            "aswath_damodaran",
            "jim_simons",
        ]
    if normalized == "core":
        return ["fundamentals", "technical", "sentiment", "valuation"]
    return [part.strip() for part in selection.split(",") if part.strip()]


def _load_portfolio_from_source(config: RebalanceConfig) -> Portfolio:
    if config.portfolio_source == "csv":
        if not config.portfolio_path:
            raise ValueError("Portfolio path is required for CSV input")
        return load_portfolio(str(config.portfolio_path))

    if config.portfolio_source == "ibkr":
        from src.integrations.ibkr_client import IBKRClient

        client = IBKRClient(
            base_url=_build_ibkr_base_url(config.ibkr_host, config.ibkr_port),
            verify_ssl=config.ibkr_verify_ssl,
            timeout=config.ibkr_timeout,
        )
        return client.fetch_portfolio(account_id=config.ibkr_account)

    raise ValueError(f"Unsupported portfolio source: {config.portfolio_source}")


def _build_ibkr_base_url(host: str, port: int) -> str:
    parsed = urlparse(host)
    if parsed.scheme:
        netloc = parsed.netloc or parsed.path
        if ":" in netloc or parsed.port:
            return host.rstrip("/")
        return f"{parsed.scheme}://{netloc}:{port}".rstrip("/")
    cleaned = host.strip().strip("/") or "localhost"
    if cleaned.startswith("http"):
        return cleaned.rstrip("/")
    return f"https://{cleaned}:{port}".rstrip("/")


__all__ = ["RebalanceConfig", "RebalanceOutcome", "run_rebalance"]
