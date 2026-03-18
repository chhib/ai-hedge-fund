"""Reusable orchestration for the weekly portfolio rebalance workflow."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import requests
import urllib3

# Suppress SSL warnings for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.agents.enhanced_portfolio_manager import EnhancedPortfolioManager
from src.data.borsdata_ticker_mapping import get_ticker_market
from src.utils.output_formatter import display_results, format_as_portfolio_csv
from src.utils.portfolio_loader import Portfolio, Position as PortfolioPosition, load_portfolio, load_universe

# Path to IBKR Client Portal Gateway (relative to repo root)
IBKR_GATEWAY_DIR = Path(__file__).parent.parent.parent / "clientportal.gw"


def _ibkr_gateway_start_command() -> str:
    """Build the shell command used to start the local IBKR gateway."""
    try:
        gateway_dir = IBKR_GATEWAY_DIR.relative_to(Path.cwd())
    except ValueError:
        gateway_dir = IBKR_GATEWAY_DIR
    return f"cd {gateway_dir} && bin/run.sh root/conf.yaml"


def _format_ibkr_gateway_start_instructions(base_url: str) -> str:
    """Return a concise operator hint for bringing the gateway online."""
    lines = ["Suggestion: start the IBKR Client Portal Gateway:"]
    if not IBKR_GATEWAY_DIR.exists():
        lines.append(f"  Install clientportal.gw under {IBKR_GATEWAY_DIR}")
        lines.append("  Download: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/")
    lines.append(f"  {_ibkr_gateway_start_command()}")
    lines.append(f"  Authenticate at {base_url}")
    lines.append("  Then re-run this command.")
    return "\n".join(lines)


def _extract_hostname(host: str) -> str:
    """Extract the hostname portion from a configured IBKR host."""
    parsed = urlparse(host if "://" in host else f"https://{host}")
    return parsed.hostname or "localhost"


def _is_localhost(host: str) -> bool:
    """Return True when the host points at the current machine."""
    return _extract_hostname(host) in {"localhost", "127.0.0.1", "::1"}


def _is_local_port_in_use(port: int, timeout: float = 1.0) -> bool:
    """Check whether a TCP port is already accepting local connections."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _describe_local_listener(port: int) -> str | None:
    """Return a short process description for a local listening TCP port."""
    lsof_path = shutil.which("lsof")
    if not lsof_path:
        return None

    try:
        result = subprocess.run(
            [lsof_path, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) <= 1:
        return None

    listeners: List[str] = []
    for line in lines[1:4]:
        parts = line.split()
        if len(parts) >= 2:
            listeners.append(f"{parts[0]} (PID {parts[1]})")
    return ", ".join(listeners) if listeners else None


def _check_ibkr_gateway(base_url: str, timeout: float = 2.0) -> tuple[bool, bool]:
    """Check if IBKR gateway is running and authenticated.

    Returns: (is_running, is_authenticated)
    """
    try:
        resp = requests.get(
            f"{base_url}/v1/api/iserver/auth/status",
            verify=False,
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            return True, data.get("authenticated", False)
        return resp.status_code in (401, 403), False
    except requests.RequestException:
        return False, False


def _find_running_gateway(timeout: float = 2.0) -> tuple[str | None, bool]:
    """Check ports 5000 and 5001 for a running gateway.

    Returns: (base_url if found, is_authenticated)
    """
    for port in (5001, 5000):
        base_url = f"https://localhost:{port}"
        running, authenticated = _check_ibkr_gateway(base_url, timeout)
        if running:
            return base_url, authenticated
    return None, False


def _start_ibkr_gateway(port: int = 5001) -> bool:
    """Start the IBKR Client Portal Gateway if installed."""
    if not IBKR_GATEWAY_DIR.exists():
        print(f"⚠️  IBKR Gateway not found at {IBKR_GATEWAY_DIR}")
        print("   Download from: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/")
        return False

    run_script = IBKR_GATEWAY_DIR / "bin" / "run.sh"
    config_file = IBKR_GATEWAY_DIR / "root" / "conf.yaml"

    if not run_script.exists():
        print(f"⚠️  Gateway run script not found: {run_script}")
        return False

    print("🚀 Starting IBKR Client Portal Gateway...")
    subprocess.Popen(
        [str(run_script), str(config_file)],
        cwd=str(IBKR_GATEWAY_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for gateway to become responsive
    for i in range(10):
        time.sleep(1)
        running, _ = _check_ibkr_gateway(f"https://localhost:{port}")
        if running:
            print(f"✓ Gateway running on https://localhost:{port}")
            return True
        print(f"  Waiting for gateway... ({i + 1}/10)")

    print(f"⚠️  Gateway started but not responding. Check https://localhost:{port}")
    return False


def _ensure_ibkr_gateway(config: "RebalanceConfig") -> str:
    """Ensure the IBKR gateway is running and authenticated.

    Returns the base_url to use.
    Raises RuntimeError if gateway cannot be reached or user needs to authenticate.
    """
    preferred_gateway_url = _build_ibkr_base_url(config.ibkr_host, config.ibkr_port)
    manual_start_instructions = _format_ibkr_gateway_start_instructions(preferred_gateway_url)

    # Honor an explicit --ibkr-port first before falling back to defaults.
    is_running, is_authenticated = _check_ibkr_gateway(preferred_gateway_url, timeout=config.ibkr_timeout)
    if is_running:
        if is_authenticated:
            return preferred_gateway_url
        for _ in range(5):
            time.sleep(2)
            _, is_authenticated = _check_ibkr_gateway(preferred_gateway_url, timeout=config.ibkr_timeout)
            if is_authenticated:
                return preferred_gateway_url
        raise RuntimeError(
            f"IBKR Gateway running but not authenticated.\n"
            f"Please log in at: {preferred_gateway_url}\n"
            f"Then re-run this command."
        )

    # First check if there's already a running gateway on either port
    found_url, is_authenticated = _find_running_gateway(timeout=config.ibkr_timeout)

    if found_url:
        if is_authenticated:
            return found_url  # Ready to use
        # Give the gateway a brief window to finish authentication
        for _ in range(5):
            time.sleep(2)
            _, is_authenticated = _check_ibkr_gateway(found_url, timeout=config.ibkr_timeout)
            if is_authenticated:
                return found_url
        # Running but not authenticated
        raise RuntimeError(
            f"IBKR Gateway running but not authenticated.\n"
            f"Please log in at: {found_url}\n"
            f"Then re-run this command."
        )

    if _is_localhost(config.ibkr_host) and _is_local_port_in_use(config.ibkr_port, timeout=min(config.ibkr_timeout, 1.0)):
        listener = _describe_local_listener(config.ibkr_port)
        listener_suffix = f" Listener: {listener}." if listener else ""
        raise RuntimeError(
            f"IBKR Gateway port {config.ibkr_port} is already in use by another local process.{listener_suffix}\n"
            f"Stop that process or choose another --ibkr-port, then start the gateway.\n"
            f"{manual_start_instructions}"
        )

    # No gateway running, try to start one
    print("⚠️  IBKR Gateway on localhost is not responding on ports 5000 or 5001.")
    print(manual_start_instructions)
    print("Attempting to start it automatically...")
    if not _start_ibkr_gateway(config.ibkr_port):
        raise RuntimeError(
            "Could not start IBKR Gateway automatically.\n"
            f"{manual_start_instructions}"
        )

    # Check if it's now running and needs auth
    gateway_url = preferred_gateway_url
    running, is_authenticated = _check_ibkr_gateway(gateway_url, timeout=config.ibkr_timeout)

    if not running:
        raise RuntimeError(
            "IBKR Gateway is still not responding after the auto-start attempt.\n"
            f"{manual_start_instructions}"
        )

    if running and not is_authenticated:
        raise RuntimeError(
            f"IBKR Gateway started but requires authentication.\n"
            f"Please log in at: {gateway_url}\n"
            f"Then re-run this command."
        )

    return gateway_url


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
    ibkr_port: int = 5001
    ibkr_verify_ssl: bool = False
    ibkr_timeout: float = 10.0
    use_governor: bool = False
    governor_profile: str = "preservation"


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
    if config.portfolio_source == "ibkr":
        account_label = portfolio.resolved_account_id or (config.ibkr_account or "unknown account")
        print(f"\n✓ Loaded portfolio from IBKR account {account_label} with {len(portfolio.positions)} positions")
        print(f"  Positions: {_format_position_summary(portfolio.positions)}")
    else:
        print(f"\n✓ Loaded portfolio with {len(portfolio.positions)} positions")

    universe_list = load_universe(
        str(config.universe_path) if config.universe_path else None,
        config.universe_tickers,
        verbose=True,  # Show skipped delisted tickers
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
        use_governor=config.use_governor,
        governor_profile=config.governor_profile,
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


def _format_position_summary(positions: List[PortfolioPosition]) -> str:
    """Render a compact, human-readable list of loaded positions."""
    if not positions:
        return "none"
    return ", ".join(f"{position.ticker} ({position.shares:g})" for position in positions)


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
    if normalized == "favorites":
        return ["fundamentals", "technical", "jim_simons", "news_sentiment_analyst", "stanley_druckenmiller"]
    return [part.strip() for part in selection.split(",") if part.strip()]


def _load_portfolio_from_source(config: RebalanceConfig) -> Portfolio:
    if config.portfolio_source == "csv":
        if not config.portfolio_path:
            raise ValueError("Portfolio path is required for CSV input")
        return load_portfolio(str(config.portfolio_path))

    if config.portfolio_source == "ibkr":
        from src.integrations.ibkr_client import IBKRClient

        base_url = _ensure_ibkr_gateway(config)

        client = IBKRClient(
            base_url=base_url,
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
