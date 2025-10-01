#!/usr/bin/env python3
"""Map portfolio tickers to Börsdata instruments.

This script takes a CSV with Name, Ticker, Market columns and searches for
matching instruments in Börsdata (both Nordic and Global markets).
"""

import csv
import os
import sys
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.data.borsdata_client import BorsdataClient


# Portfolio data provided by user
PORTFOLIO_CSV = """Name,Ticker,Market
Ballard Power Systems,BLDP,Canada/USA
Bio-Works Technologies,BIOW,Sweden
Chordate Medical Holding,CMH,Sweden
Climeon B,CLIME B,Sweden
Doubleview Gold Corp,DBLV,Canada
Gravity ADR,GRVY,USA
HAV Group,HAV,Norway
Impact Coatings,IMPC,Sweden
Leading Edge Materials Corp.,LEM,Canada/Sweden
Neonode,NEON,USA
4C Group,4C,Sweden
Advenica,ADVE,Sweden
Alphabet Inc Class A,GOOGL,USA
Apple,AAPL,USA
AQ Group,AQ,Sweden
Arvinas,ARVN,USA
ASP Isotopes,ASPI,USA
Bahnhof B,BAHN B,Sweden
Baidu ADR,BIDU,USA
Bambuser,BUSER,Sweden
Beijer Ref B,BEIJ B,Sweden
Berkshire Hathaway Inc Class B,BRK.B,USA
Berner Industrier B,BRNER B,Sweden
Beyond Frames,BEYOND,Sweden
BoMill,BOMILL,Sweden
Braze A,BRZE,USA
BrightBid Group,BRBID,Sweden
Brookfield Corporation,BN,Canada
C3is,CISS,USA
Canagold Resources Ltd,CCM,Canada
Catena Media,CTM,Sweden
CCC Intelligent Solutions,CCCS,USA
Cereno Scientific B,CRNO B,Sweden
Cloudflare,NET,USA
Confluent A,CFLT,USA
Constellation Software Inc,CSU,Canada
DHT,DHT,USA
Doro,DORO,Sweden
eBay,EBAY,USA
Embellence Group,EMBEL,Sweden
engcon B,ENGCON B,Sweden
Falco Resources Ltd.,FPC,Canada
Fireweed Metals Corp,FWZ,Canada
First Solar,FSLR,USA
G5 Entertainment,G5EN,Sweden
Gofore,GOFORE,Finland
Golar LNG,GLNG,Norway/USA
Goliath Resources Ltd,GOT,Canada
GoPro A,GPRO,USA
H&M B,HM B,Sweden
Handelsbanken A,SHB A,Sweden
Handelsbanken B,SHB B,Sweden
Hasbro,HAS,USA
Heba B,HEBA B,Sweden
Hove,HOVE,Denmark
I-tech,ITECH,Sweden
Industrivärden A,INDU A,Sweden
Inission B,INISS B,Sweden
Joint Stock Company Kaspi.kz,KSPI,London
JOYY ADR,YY,USA
Kesko B,KESKOB,Finland
Lundberg B,LUND B,Sweden
Lundin Gold,LUG,Canada/Sweden
Mako Mining Corp,MKO,Canada
Maravai LifeSciences A,MRVI,USA
Mentice,MNTC,Sweden
Meta Platforms A,META,USA
Micron Technology,MU,USA
Microsoft,MSFT,USA
Moderna,MRNA,USA
Moneyhero,MNY,USA
Montage Gold Corp,MAU,Canada
MPC Container Ships,MPCC,Norway
MTG B,MTG B,Sweden
Navigator Holdings,NVGS,USA
Nepa,NEPA,Sweden
Netflix,NFLX,USA
Ngex Minerals,NGEX,Canada/Sweden
Nibe Industrier B,NIBE B,Sweden
Nordrest,NORDREST,Sweden
North American Construction,NOA,Canada
North Media,NORTHM,Denmark
Novus Group,NOVUS,Sweden
NVIDIA,NVDA,USA
OncoZenge,ONCOZ,Sweden
Ondas Holdings,ONDS,USA
Onfolio,ONFO,USA
Paradox Interactive,PDX,Sweden
Parans,PARANS,Sweden
Perimeter Solutions,PRM,USA
Platzer Fastigheter Holding B,PLTZ B,Sweden
Playtika Holding,PLTK,USA
Portillo's A,PTLO,USA
PubMatic A,PUBM,USA
Qiiwi Games,QIIWI,Sweden
Qualisys,QUALISYS,Sweden
Qualys,QLYS,USA
Recyctec B,RECY B,Sweden
Roper Technologies,ROP,USA
RugVista Group,RUG,Sweden
Scorpio Tankers,STNG,USA
Serstech,SERT,Sweden
Sleep Cycle,SLEEP,Sweden
Sozap,SOZAP,Sweden
Stockwik Förvaltning,STWK,Sweden
TCECUR Sweden A,TCECUR A,Sweden
Teads,TEADS,USA
TerraVest Industries Inc,TVK,Canada
Tesla,TSLA,USA
The Trade Desk A,TTD,USA
Tinka Resources,TK,Canada
Titania,TITANIA,Sweden
TopRight Nordic,TOPR,Sweden
TORM A,TRMD A,Denmark
Trupanion,TRUP,USA
Unibap Space Solutions,UNIBAP,Sweden
Vend Marketplaces A,VEND A,Sweden
Vertiv Holdings A,VRT,USA
Vestas Wind Systems,VWS,Denmark
Viafin Service,VIAFIN,Finland
Viking Supply Ships B,VSSAB B,Sweden
Weibo ADR,WB,USA
Workday A,WDAY,USA
XPEL,XPEL,USA
Zillow Group Inc Class A,ZG,USA
Zillow Group Inc Class C,Z,USA
Adverty,ADVT,Sweden
Datadog A,DDOG,USA
Domo B,DOMO,USA
Logitech International SA,LOGI,Switzerland
Match Group,MTCH,USA
MongoDB A,MDB,USA
Pinterest A,PINS,USA"""


def normalize_name(name: str) -> str:
    """Normalize company name for comparison."""
    name = name.upper()
    # Remove common suffixes
    for suffix in [
        " INC", " CORP", " LTD", " AB", " ASA", " PLC", " SPA", " CO", " GROUP",
        " CORPORATION", " HOLDING", " HOLDINGS", " ADR", " CLASS A", " CLASS B",
        " CLASS C", " A", " B", " C"
    ]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    # Remove special characters
    name = name.replace(".", "").replace(",", "").replace("&", "AND")
    return name.strip()


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker for comparison."""
    # Remove common suffixes and normalize
    ticker = ticker.upper().strip()
    # Handle Yahoo-style tickers (e.g., "BRK.B" -> "BRK-B")
    ticker = ticker.replace(".", "-")
    return ticker


def find_ticker_match(
    company_name: str,
    suggested_ticker: str,
    instruments: List[Dict],
    global_ids: set
) -> Optional[Tuple[str, str, str, str]]:
    """Find a matching ticker for the company.

    Returns: (borsdata_ticker, full_name, market, match_type) or None
    match_type: "exact_ticker", "exact_name", "partial_name", "none"
    """
    normalized_search = normalize_name(company_name)
    normalized_suggested = normalize_ticker(suggested_ticker)

    # First pass: exact ticker match (try both original and normalized)
    for inst in instruments:
        ticker = inst.get("ticker", "")
        ticker_norm = normalize_ticker(ticker)

        if ticker_norm == normalized_suggested or ticker.upper() == suggested_ticker.upper():
            market = "Global" if inst.get("insId") in global_ids else "Nordic"
            return (ticker, inst.get("name", ""), market, "exact_ticker")

    # Second pass: exact name match
    for inst in instruments:
        inst_name = inst.get("name", "")
        if normalize_name(inst_name) == normalized_search:
            market = "Global" if inst.get("insId") in global_ids else "Nordic"
            return (inst.get("ticker", ""), inst_name, market, "exact_name")

    # Third pass: partial match (name contains search term)
    for inst in instruments:
        inst_name = normalize_name(inst.get("name", ""))
        if normalized_search in inst_name or inst_name in normalized_search:
            market = "Global" if inst.get("insId") in global_ids else "Nordic"
            return (inst.get("ticker", ""), inst.get("name", ""), market, "partial_name")

    return None


def main():
    """Main execution function."""
    # Load environment variables
    load_dotenv()

    api_key = os.getenv("BORSDATA_API_KEY")
    if not api_key:
        print("❌ Error: BORSDATA_API_KEY not found in .env file")
        sys.exit(1)

    print("🔍 Mapping portfolio tickers to Börsdata instruments...")
    print()

    # Initialize client and fetch all instruments
    client = BorsdataClient(api_key=api_key)

    print("📥 Fetching all instruments (Nordic + Global)...")
    all_instruments = client.get_all_instruments()

    # Separate by checking which internal cache they came from
    nordic_instruments = client.get_instruments()
    nordic_ids = {inst.get("insId") for inst in nordic_instruments}
    global_instruments = [inst for inst in all_instruments if inst.get("insId") not in nordic_ids]

    print(f"   Found {len(nordic_instruments)} Nordic instruments")
    print(f"   Found {len(global_instruments)} Global instruments")
    print(f"✅ Total: {len(all_instruments)} instruments loaded")
    print()

    # Parse portfolio CSV
    csv_reader = csv.DictReader(StringIO(PORTFOLIO_CSV))
    portfolio_entries = list(csv_reader)

    print(f"📋 Processing {len(portfolio_entries)} portfolio entries...")
    print()

    # Search for matches
    matched: List[Tuple[str, str, str, str, str, str]] = []  # (orig_ticker, company_name, borsdata_ticker, full_name, market, match_type)
    unmatched: List[Tuple[str, str, str]] = []  # (company_name, suggested_ticker, market)
    global_ids_set = {inst.get("insId") for inst in global_instruments}

    print("🔎 Searching for matches...")
    print()

    for entry in portfolio_entries:
        company_name = entry["Name"]
        suggested_ticker = entry["Ticker"]
        orig_market = entry["Market"]

        result = find_ticker_match(company_name, suggested_ticker, all_instruments, global_ids_set)

        if result:
            borsdata_ticker, full_name, market, match_type = result
            matched.append((suggested_ticker, company_name, borsdata_ticker, full_name, market, match_type))

            # Format output based on match type
            if match_type == "exact_ticker":
                print(f"✓ {company_name:<45} {suggested_ticker:<15} → {borsdata_ticker:<12} ({market})")
            elif match_type == "exact_name":
                print(f"⊕ {company_name:<45} {suggested_ticker:<15} → {borsdata_ticker:<12} ({market}) [by name]")
            else:
                print(f"≈ {company_name:<45} {suggested_ticker:<15} → {borsdata_ticker:<12} ({market}) [{full_name}]")
        else:
            unmatched.append((company_name, suggested_ticker, orig_market))
            print(f"✗ {company_name:<45} {suggested_ticker:<15} → NOT FOUND")

    print()
    print("=" * 120)
    print(f"📊 Results: {len(matched)} matched, {len(unmatched)} unmatched")
    print("=" * 120)
    print()

    # Save matched tickers to universe files
    if matched:
        universe_dir = project_root / "portfolios"
        universe_dir.mkdir(exist_ok=True)

        # Helper function to load existing tickers from a file
        def load_existing_tickers(file_path: Path) -> set:
            """Load existing tickers from a universe file, ignoring comments."""
            if not file_path.exists():
                return set()
            existing = set()
            with open(file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # Extract ticker (first word before any comment or space)
                    ticker = line.split()[0] if line.split() else ""
                    if ticker:
                        existing.add(ticker)
            return existing

        # Separate by market
        new_nordic_tickers = {bt: (fn, mt) for _, _, bt, fn, m, mt in matched if m == "Nordic"}
        new_global_tickers = {bt: (fn, mt) for _, _, bt, fn, m, mt in matched if m == "Global"}

        # Load existing tickers
        nordic_file = universe_dir / "borsdata_universe_nordic.txt"
        global_file = universe_dir / "borsdata_universe_global.txt"
        universe_file = universe_dir / "borsdata_universe.txt"

        existing_nordic = load_existing_tickers(nordic_file)
        existing_global = load_existing_tickers(global_file)

        # Merge and deduplicate
        all_nordic_tickers = existing_nordic | set(new_nordic_tickers.keys())
        all_global_tickers = existing_global | set(new_global_tickers.keys())

        # Save combined universe with metadata
        all_tickers_with_market = [(t, "Nordic") for t in all_nordic_tickers] + [(t, "Global") for t in all_global_tickers]
        with open(universe_file, "w") as f:
            f.write(f"# Börsdata Universe - {len(all_tickers_with_market)} tickers\n")
            f.write(f"# {len(all_nordic_tickers)} Nordic, {len(all_global_tickers)} Global\n")
            f.write(f"# Updated from portfolio mapping\n\n")
            for ticker, market in sorted(all_tickers_with_market, key=lambda x: (x[1], x[0])):
                # Try to get full name from new matches if available
                if market == "Nordic" and ticker in new_nordic_tickers:
                    full_name = new_nordic_tickers[ticker][0]
                    f.write(f"{ticker:<15} # {market:<7} {full_name}\n")
                elif market == "Global" and ticker in new_global_tickers:
                    full_name = new_global_tickers[ticker][0]
                    f.write(f"{ticker:<15} # {market:<7} {full_name}\n")
                else:
                    f.write(f"{ticker:<15} # {market:<7}\n")

        print(f"💾 Updated {universe_file}")
        print(f"   Total: {len(all_tickers_with_market)} tickers ({len(existing_nordic) + len(existing_global)} existing + {len(matched)} new)")
        print()

        # Save separate market files
        if all_nordic_tickers:
            with open(nordic_file, "w") as f:
                f.write(f"# Börsdata Nordic Universe - {len(all_nordic_tickers)} tickers\n\n")
                for ticker in sorted(all_nordic_tickers):
                    f.write(f"{ticker}\n")
            print(f"💾 Updated {nordic_file}")
            print(f"   Total: {len(all_nordic_tickers)} tickers ({len(existing_nordic)} existing + {len(new_nordic_tickers)} new)")

        if all_global_tickers:
            with open(global_file, "w") as f:
                f.write(f"# Börsdata Global Universe - {len(all_global_tickers)} tickers\n\n")
                for ticker in sorted(all_global_tickers):
                    f.write(f"{ticker}\n")
            print(f"💾 Updated {global_file}")
            print(f"   Total: {len(all_global_tickers)} tickers ({len(existing_global)} existing + {len(new_global_tickers)} new)")

        print()

        # Save detailed mapping report
        mapping_file = universe_dir / "borsdata_mapping_report.txt"
        with open(mapping_file, "w") as f:
            f.write("# Börsdata Portfolio Mapping Report\n")
            f.write(f"# Generated: {portfolio_entries[0] if portfolio_entries else 'N/A'}\n\n")
            f.write("## Matched Tickers\n\n")
            f.write(f"{'Company Name':<50} {'Suggested':<15} {'Börsdata':<15} {'Market':<8} {'Match Type':<15} {'Full Name'}\n")
            f.write("=" * 140 + "\n")
            for orig, company, borsdata, full_name, market, match_type in sorted(matched):
                f.write(f"{company:<50} {orig:<15} {borsdata:<15} {market:<8} {match_type:<15} {full_name}\n")

            if unmatched:
                f.write("\n\n## Unmatched Tickers\n\n")
                f.write(f"{'Company Name':<50} {'Suggested Ticker':<20} {'Original Market'}\n")
                f.write("=" * 100 + "\n")
                for company, ticker, market in sorted(unmatched):
                    f.write(f"{company:<50} {ticker:<20} {market}\n")

        print(f"📝 Saved detailed mapping report to: {mapping_file}")
        print()

    # Report unmatched
    if unmatched:
        print("❌ Unmatched tickers:")
        print()
        for company_name, suggested_ticker, market in sorted(unmatched):
            print(f"   • {company_name} ({suggested_ticker}) - {market}")
        print()

        # Save unmatched to file for review
        unmatched_file = project_root / "portfolios" / "borsdata_unmatched.txt"
        with open(unmatched_file, "w") as f:
            f.write(f"# Unmatched tickers - {len(unmatched)} items\n")
            f.write("# These tickers were not found in Börsdata (Nordic or Global)\n\n")
            for company_name, suggested_ticker, market in sorted(unmatched):
                f.write(f"{suggested_ticker:<15} # {company_name} ({market})\n")

        print(f"💾 Saved unmatched list to: {unmatched_file}")
        print()

    # Summary statistics
    print("📈 Summary by Market:")
    nordic_count = sum(1 for _, _, _, _, market, _ in matched if market == "Nordic")
    global_count = sum(1 for _, _, _, _, market, _ in matched if market == "Global")
    print(f"   Nordic: {nordic_count} tickers")
    print(f"   Global: {global_count} tickers")
    print()

    print("📊 Summary by Match Type:")
    exact_ticker = sum(1 for _, _, _, _, _, mt in matched if mt == "exact_ticker")
    exact_name = sum(1 for _, _, _, _, _, mt in matched if mt == "exact_name")
    partial = sum(1 for _, _, _, _, _, mt in matched if mt == "partial_name")
    print(f"   Exact ticker match: {exact_ticker}")
    print(f"   Exact name match: {exact_name}")
    print(f"   Partial name match: {partial}")
    print()

    print("✅ Done!")


if __name__ == "__main__":
    main()
