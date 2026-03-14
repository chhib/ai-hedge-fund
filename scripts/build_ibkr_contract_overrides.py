#!/usr/bin/env python3
"""Build/update IBKR contract overrides for a Borsdata universe.

Three-tier resolution:
  1. ISIN lookup (globally unique, highest confidence)
  2. Ticker lookup via /trsrv/stocks + /iserver/secdef/search (fallback)
  3. Name-based disambiguation using Borsdata company name word overlap
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv

load_dotenv()

from src.integrations.ibkr_client import IBKRClient, IBKRError
from src.integrations.ticker_mapper import map_borsdata_to_ibkr


NORDIC_EXCHANGES = {
    "SFB",  # Stockholm
    "CPH",  # Copenhagen
    "OSE",  # Oslo
    "HEL",  # Helsinki
    "HEX",  # Helsinki
    "ICE",  # Iceland
}

US_PRIMARY_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA"}

NAME_NOISE_SUFFIXES = {
    "AB", "ASA", "INC", "CORP", "LTD", "PLC", "SE", "AG", "OYJ",
    "A/S", "GROUP", "HOLDING", "HOLDINGS", "CO", "COMPANY",
    "CLASS", "SERIES", "PUBL",
}

IBKR_CALL_DELAY = 0.3  # seconds between IBKR API calls


@dataclass(slots=True)
class Candidate:
    conid: int
    exchange: Optional[str]
    currency: Optional[str]
    symbol: Optional[str]
    description: Optional[str]


def _parse_universe_lines(lines: Iterable[str]) -> List[str]:
    tickers: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("--"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        if "," in line:
            parts = [part.strip().strip('"').strip("'") for part in line.split(",")]
            tickers.extend([part for part in parts if part])
        else:
            tickers.append(line.strip().strip('"').strip("'"))

    seen = set()
    ordered: List[str] = []
    for ticker in tickers:
        if ticker and ticker not in seen:
            seen.add(ticker)
            ordered.append(ticker)
    return ordered


def _load_existing(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"contracts": {}}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"contracts": {}}


def _save_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _extract_secdef_candidates(payload: Any) -> List[Candidate]:
    """Extract candidates from /iserver/secdef/search response.

    Response format: list of dicts with 'conid' (str, may include @EXCHANGE),
    'companyName', 'symbol', 'description' (exchange name), 'sections'.
    We only want STK entries (skip BOND, etc.) and deduplicate by base conid
    (ignoring per-exchange variants like '459530964@NASDAQ').
    """
    candidates: List[Candidate] = []
    if not isinstance(payload, list):
        return candidates

    seen_conids: set[int] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        # Skip non-stock entries (bonds, etc.)
        sections = entry.get("sections") or []
        has_stk = any(s.get("secType") == "STK" for s in sections if isinstance(s, dict))
        if not has_stk:
            continue

        raw_conid = entry.get("conid") or ""
        conid_str = str(raw_conid).split("@")[0]
        try:
            conid = int(conid_str)
        except (TypeError, ValueError):
            continue

        # Skip per-exchange duplicates (e.g. 459530964@NASDAQ, 459530964@NYSE)
        if conid in seen_conids:
            continue
        seen_conids.add(conid)

        # 'description' in secdef search is the exchange name (e.g. "NASDAQ")
        exchange = entry.get("description")
        # 'companyName' is the actual name (e.g. "APPLE INC")
        company_name = entry.get("companyName") or ""
        # 'companyHeader' has format "SYMBOL STK@EXCHANGE" or "COMPANY NAME - EXCHANGE"
        company_header = entry.get("companyHeader") or ""
        symbol = entry.get("symbol")

        # symbol field in secdef search is sometimes "STK" (the secType), fix that
        if symbol and symbol.upper() == "STK":
            # Extract real symbol from companyName (e.g. "ABNB STK@SMART" -> "ABNB")
            cn = company_name.split()
            symbol = cn[0] if cn else None

        # When exchange is None (ISIN search results), parse from companyHeader
        if not exchange and "@" in company_header:
            # "ABNB STK@SMART" -> "SMART"
            exchange = company_header.rsplit("@", 1)[-1].strip()
        if not exchange and " - " in company_header:
            # "APPLE INC - NASDAQ" -> "NASDAQ"
            exchange = company_header.rsplit(" - ", 1)[-1].strip()

        # Clean up description: use companyHeader to get real name
        # "ABNB STK@SMART" is not a useful description; prefer "Airbnb Inc" style
        description = company_name
        if description and " STK@" in description:
            # This is a symbol-style name, not a real company name
            description = symbol or description

        candidates.append(Candidate(
            conid=conid,
            exchange=exchange,
            currency=None,
            symbol=symbol,
            description=description,
        ))

    return candidates


def _extract_trsrv_candidates(payload: Any) -> List[Candidate]:
    """Extract candidates from /trsrv/stocks response.

    Response format: dict mapping symbol -> list of stock groups, each with
    'name', 'contracts': [{'conid': int, 'exchange': str, 'isUS': bool}].
    Prefer isUS=True contracts when available.
    """
    candidates: List[Candidate] = []
    if not isinstance(payload, dict):
        return candidates

    for symbol_key, stock_groups in payload.items():
        if not isinstance(stock_groups, list):
            continue
        for group in stock_groups:
            if not isinstance(group, dict):
                continue
            name = group.get("name")
            for contract in (group.get("contracts") or []):
                if not isinstance(contract, dict):
                    continue
                conid = contract.get("conid")
                if conid is None:
                    continue
                try:
                    conid = int(conid)
                except (TypeError, ValueError):
                    continue
                candidates.append(Candidate(
                    conid=conid,
                    exchange=contract.get("exchange"),
                    currency=None,
                    symbol=symbol_key,
                    description=name,
                ))

    return candidates


def _pick_candidate(candidates: List[Candidate], ibkr_symbol: str, prefer_nordic: bool) -> Optional[Candidate]:
    if not candidates:
        return None

    symbol_upper = ibkr_symbol.upper()
    exact_symbol = [c for c in candidates if (c.symbol or "").upper() == symbol_upper]
    if len(exact_symbol) == 1:
        return exact_symbol[0]

    # Narrow to exact symbol matches for further heuristics
    pool = exact_symbol if exact_symbol else candidates

    if prefer_nordic:
        nordic = [c for c in pool if (c.exchange or "").upper() in NORDIC_EXCHANGES]
        if len(nordic) == 1:
            return nordic[0]

    # Prefer US primary exchange (NASDAQ/NYSE/AMEX/ARCA)
    us_primary = [c for c in pool if (c.exchange or "").upper() in US_PRIMARY_EXCHANGES]
    if len(us_primary) == 1:
        return us_primary[0]

    if len(pool) == 1:
        return pool[0]

    return None


def _candidate_payload(candidate: Candidate) -> Dict[str, Any]:
    return {
        "conid": candidate.conid,
        "exchange": candidate.exchange,
        "currency": candidate.currency,
        "description": candidate.description,
        "symbol": candidate.symbol,
    }


def _tokenize_name(name: str) -> set[str]:
    """Tokenize a company name, stripping common suffixes."""
    words = set()
    for word in name.upper().replace("-", " ").replace("(", " ").replace(")", " ").split():
        cleaned = word.strip(".,;:'\"")
        if cleaned and cleaned not in NAME_NOISE_SUFFIXES:
            words.add(cleaned)
    return words


def _pick_by_name(candidates: List[Candidate], borsdata_name: str) -> Optional[Candidate]:
    """Pick the best candidate by comparing Borsdata name to IBKR descriptions."""
    if not candidates or not borsdata_name:
        return None

    bd_tokens = _tokenize_name(borsdata_name)
    if not bd_tokens:
        return None

    best_candidate = None
    best_overlap = 0

    for c in candidates:
        desc = c.description or ""
        if not desc:
            continue
        desc_tokens = _tokenize_name(desc)
        overlap = len(bd_tokens & desc_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_candidate = c

    # Require at least half of the Borsdata name tokens to match
    if best_overlap >= max(1, len(bd_tokens) // 2):
        return best_candidate

    return None


def _build_borsdata_lookup() -> Dict[str, Dict[str, str]]:
    """Build ticker -> {isin, name} map from all Borsdata instruments.

    Returns empty dict if no BORSDATA_API_KEY is set.
    """
    api_key = os.environ.get("BORSDATA_API_KEY")
    if not api_key:
        print("  [borsdata] No BORSDATA_API_KEY set, ISIN lookup disabled")
        return {}

    try:
        from src.data.borsdata_client import BorsdataClient
        client = BorsdataClient(api_key=api_key)
        instruments = client.get_all_instruments(api_key=api_key)
    except Exception as exc:
        print(f"  [borsdata] Failed to load instruments: {exc}")
        return {}

    lookup: Dict[str, Dict[str, str]] = {}
    for inst in instruments:
        ticker = inst.get("ticker")
        if not ticker:
            continue
        isin = inst.get("isin") or ""
        name = inst.get("name") or ""
        lookup[ticker.upper()] = {"isin": isin, "name": name}

    print(f"  [borsdata] Loaded {len(lookup)} instruments for ISIN lookup")
    return lookup


def main() -> None:
    parser = argparse.ArgumentParser(description="Build IBKR contract overrides for a Borsdata universe.")
    parser.add_argument("--input", default="portfolios/borsdata_universe.txt", help="Borsdata universe file")
    parser.add_argument("--output", default="data/ibkr_contract_mappings.json", help="Overrides file to update")
    parser.add_argument("--report", default="data/ibkr_contract_candidates.json", help="Ambiguous candidates report")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of tickers processed")
    parser.add_argument("--ibkr-host", default="https://localhost", help="IBKR host (scheme optional)")
    parser.add_argument("--ibkr-port", type=int, default=5000, help="IBKR port")
    parser.add_argument("--ibkr-verify-ssl", action="store_true", help="Verify IBKR SSL certs")
    parser.add_argument("--skip-isin", action="store_true", help="Skip ISIN lookup, ticker-only mode")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input universe not found: {input_path}")

    output_path = Path(args.output)
    report_path = Path(args.report)

    tickers = _parse_universe_lines(input_path.read_text().splitlines())
    if args.limit:
        tickers = tickers[: args.limit]

    payload = _load_existing(output_path)
    contracts = payload.setdefault("contracts", {})
    ambiguous: Dict[str, Any] = {}

    # Build Borsdata ISIN/name lookup
    if args.skip_isin:
        print("ISIN lookup skipped (--skip-isin)")
        bd_lookup: Dict[str, Dict[str, str]] = {}
    else:
        bd_lookup = _build_borsdata_lookup()

    host = args.ibkr_host.rstrip("/")
    if "://" not in host:
        host = f"https://{host}"
    host_no_scheme = host.split("://", 1)[1]
    if ":" in host_no_scheme:
        base_url = host
    else:
        base_url = f"{host}:{args.ibkr_port}"
    client = IBKRClient(base_url=base_url, verify_ssl=args.ibkr_verify_ssl)

    # Counters for summary
    already_mapped = 0
    resolved_isin = 0
    resolved_ticker = 0
    resolved_name = 0

    for ticker in tickers:
        if ticker.upper() in contracts:
            already_mapped += 1
            continue

        ibkr_symbol = map_borsdata_to_ibkr(ticker)
        bd_info = bd_lookup.get(ticker.upper(), {})
        isin = bd_info.get("isin", "")
        borsdata_name = bd_info.get("name", "")
        selected = None
        resolution = None
        candidates: List[Candidate] = []

        # --- Tier 1: ISIN lookup via secdef search ---
        if isin and not args.skip_isin:
            try:
                time.sleep(IBKR_CALL_DELAY)
                response = client.search_contracts(isin, sec_type="STK")
                candidates = _extract_secdef_candidates(response)
                if len(candidates) == 1:
                    selected = candidates[0]
                    resolution = "isin"
                elif candidates:
                    prefer_nordic = " " in ticker or "." in ibkr_symbol
                    selected = _pick_candidate(candidates, ibkr_symbol, prefer_nordic)
                    if selected:
                        resolution = "isin"
            except IBKRError:
                pass  # Fall through to tier 2

        # --- Tier 2: Ticker lookup ---
        if not selected:
            # 2a: Try /trsrv/stocks first (returns conid + exchange + name)
            try:
                time.sleep(IBKR_CALL_DELAY)
                response = client.get_stock_contracts(ibkr_symbol)
                candidates = _extract_trsrv_candidates(response)
            except IBKRError as exc:
                ambiguous[ticker] = {
                    "error": str(exc),
                    "ibkr_symbol": ibkr_symbol,
                    "isin": isin,
                    "borsdata_name": borsdata_name,
                }
                continue

            # 2b: If trsrv returned nothing, try secdef search by ticker
            if not candidates:
                try:
                    time.sleep(IBKR_CALL_DELAY)
                    response = client.search_contracts(ibkr_symbol, sec_type="STK")
                    candidates = _extract_secdef_candidates(response)
                except IBKRError as exc:
                    ambiguous[ticker] = {
                        "error": str(exc),
                        "ibkr_symbol": ibkr_symbol,
                        "isin": isin,
                        "borsdata_name": borsdata_name,
                    }
                    continue

            prefer_nordic = " " in ticker or "." in ibkr_symbol
            selected = _pick_candidate(candidates, ibkr_symbol, prefer_nordic)
            if selected:
                resolution = "ticker"

        # --- Tier 3: Name disambiguation ---
        if not selected and borsdata_name and candidates:
            selected = _pick_by_name(candidates, borsdata_name)
            if selected:
                resolution = "name"

        if not selected:
            ambiguous[ticker] = {
                "ibkr_symbol": ibkr_symbol,
                "isin": isin,
                "borsdata_name": borsdata_name,
                "candidates": [_candidate_payload(c) for c in candidates],
            }
            continue

        contracts[ticker.upper()] = {
            "conid": selected.conid,
            "exchange": selected.exchange,
            "currency": selected.currency,
            "description": selected.description,
        }

        if resolution == "isin":
            resolved_isin += 1
        elif resolution == "ticker":
            resolved_ticker += 1
        elif resolution == "name":
            resolved_name += 1

    _save_payload(output_path, payload)
    if ambiguous:
        _save_payload(report_path, ambiguous)
        print(f"Wrote ambiguous report: {report_path} ({len(ambiguous)} tickers)")
    else:
        print("No ambiguous tickers detected")

    # Summary
    total_resolved = resolved_isin + resolved_ticker + resolved_name
    print(f"\n--- Summary ---")
    print(f"Already mapped:    {already_mapped}")
    print(f"Resolved (ISIN):   {resolved_isin}")
    print(f"Resolved (ticker): {resolved_ticker}")
    print(f"Resolved (name):   {resolved_name}")
    print(f"Total resolved:    {total_resolved}")
    print(f"Ambiguous:         {len(ambiguous)}")
    print(f"Updated overrides: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Error: {exc}", file=sys.stderr)
        raise
