#!/usr/bin/env python3
"""Find Börsdata tickers for a list of company names.

This script searches for tickers in the Börsdata API (both Nordic and Global markets)
and saves matched tickers to a universe file.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from src.data.borsdata_client import BorsdataClient


# Company names to search for
COMPANY_NAMES = [
    "3D Systems", "Advanced Micro Devices", "Adverty", "Airbnb A", "AKELIUS PREF",
    "AKELIUS PREF BTA 140526", "Alibaba Group ADR", "Alpha Metallurgical Resources",
    "Alphabet Inc Class C", "Amhult 2 B", "AMHULT 2 BTA B 161109", "AMHULT 2 TR B 161109",
    "Apotea", "Apple", "AWARDIT", "AXIS", "AXIS - ACCEPT I ERBJUDANDE", "AZELIO AB",
    "Bahnhof B", "Bambuser", "BLANKA FING N", "Block A", "BoMill", "C3is",
    "Canagold Resources Ltd", "CAPCOM CO LTD", "Cereno Scientific B", "Cint Group",
    "Cloetta", "CoinShares International Limited", "CoinShares XBT Provider Bitcoin Tracker One",
    "CoinShares XBT Provider Ether Tracker One", "CONCENTRIC AB", "CONCENTRIC AB Acceptaktie",
    "CREASPAC AB", "CREATD INC", "CVRx", "DANSKE INVEST GLOBAL INDEX", "Digital Bros Spa",
    "DORO AB", "Egetis Therapeutics", "Electronic Arts", "Embracer Group B", "EMX Royalty",
    "Faraday Copper Corp", "FILO CORP", "FILO MINING CORP", "Fireweed Metals Corp",
    "FIRST SOLAR", "FRONTIER DEV", "Frontline", "G5 Entertainment", "Gaotu Techedu ADR",
    "Gogold Resources Inc", "Goliath Resources Ltd", "GoPro A", "GORES GUGGENHEIM INC",
    "Gravity ADR", "Guideline Geo", "H&M B", "Handelsbanken A", "HANDELSBANKEN A",
    "HANDELSBANKEN B", "HANDELSBANKEN MSCI EMERGING MKT INDEX A", "HEMFOSA FASTIGHETER BTA PR 141120",
    "HEMFOSA PREF", "HEMFOSA PREF", "Hexatronic Group", "Hive Digital Technologies", "Infrea",
    "International Petroleum Corp.", "Joint Stock Company Kaspi.kz", "JOYY ADR",
    "K2A KNAUST & ANDERSSON FASTIGHETER AB", "K2A KNAUST & ANDERSSON FASTIGHETER AB", "Kambi Group",
    "KING DIGITAL ENTERTAINMENT PLC", "KlaraBo", "LEOVEGAS AB", "Linc", "Line Corp",
    "Lucara Diamond Corp", "Lundin Gold", "Lundin Mining Corporation",
    "LÄNSFÖRSÄKRINGAR GLOBAL INDEXNÄRA", "LÄNSFÖRSÄKRINGAR TILLVÄXTMARKN INDEXNÄRA",
    "Mako Mining Corp", "Mentice", "Meren Energy", "Meta Platforms A", "Mineros S.A.",
    "MINI L FIVERR AVA 3", "MINISTELIAAVA31", "MODERN TIMES GROUP A", "Montage Gold Corp",
    "MTG B", "National Beverage", "NEXON CO LTD", "Ngex Minerals", "Nibe Industrier B",
    "Nutanix A", "Okeanis Eco Tankers Corp.", "Parans", "PARANS SOLAR BTU 170420",
    "PARANS SOLAR TO 1 180621", "PARANS SOLAR UR 170420", "Parks America Inc", "PARKS! AMERICA INC",
    "Penumbra", "POLYPLANK", "Pure Funds ISE Cyber Security ETF", "QLIK TECHNOLOGIES INC",
    "Rana Gruber", "Recyctec B", "RECYCTEC HOLDING TR B 170207", "Rovio Entertainment",
    "Sable Offshore", "ScandBook Holding", "Scorpio Tankers", "Sea1 Offshore",
    "SEGA SAMMY HOLDINGS INC", "Serstech", "Sleep Cycle", "Snap A",
    "SOCIAL CAPITAL HEDOSOPHIA HOLDINGS CORP", "Sohu.com ADR", "SPILTAN AB",
    "SPILTAN GLOBALFOND INVESTMENTBOLAG", "SPILTAN INLÖSENRÄTT SR1 170529", "Spiltan Invest",
    "Spiltan Räntefond Sverige", "Spotr Group", "Star Bulk Carriers", "Storskogen B",
    "Take-Two Interactive Software", "Telia Company", "Tesla", "The9 ADR", "Tiny Ltd.",
    "TINYBUILD INC", "TORM A", "Twitter Inc", "Ubisoft Entertainment SA", "Unibap Space Solutions",
    "Valour Polkadot (DOT) SEK", "Vizsla Silver", "VNV Global", "WECOMMERCE HOLDINGS LTD",
    "Yatra Online", "Yubico", "Zalaris ASA", "Zoom Communications A"
]


def normalize_name(name: str) -> str:
    """Normalize company name for comparison."""
    # Remove common suffixes and normalize
    name = name.upper()
    for suffix in [" INC", " CORP", " LTD", " AB", " ASA", " PLC", " SPA", " CO", " GROUP"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    # Remove special characters
    name = name.replace(".", "").replace(",", "").replace("&", "AND")
    return name.strip()


def find_ticker_match(
    company_name: str,
    instruments: List[Dict],
    global_ids: set
) -> Optional[Tuple[str, str, str]]:
    """Find a matching ticker for the company name.

    Returns: (ticker, full_name, market) or None
    """
    normalized_search = normalize_name(company_name)

    # First pass: exact ticker match
    for inst in instruments:
        ticker = inst.get("ticker", "")
        if ticker.upper() == company_name.upper():
            market = "Global" if inst.get("insId") in global_ids else "Nordic"
            return (ticker, inst.get("name", ""), market)

    # Second pass: exact name match
    for inst in instruments:
        inst_name = inst.get("name", "")
        if normalize_name(inst_name) == normalized_search:
            market = "Global" if inst.get("insId") in global_ids else "Nordic"
            return (inst.get("ticker", ""), inst_name, market)

    # Third pass: partial match (name contains search term)
    for inst in instruments:
        inst_name = normalize_name(inst.get("name", ""))
        if normalized_search in inst_name or inst_name in normalized_search:
            market = "Global" if inst.get("insId") in global_ids else "Nordic"
            return (inst.get("ticker", ""), inst.get("name", ""), market)

    return None


def main():
    """Main execution function."""
    # Load environment variables
    load_dotenv()

    api_key = os.getenv("BORSDATA_API_KEY")
    if not api_key:
        print("❌ Error: BORSDATA_API_KEY not found in .env file")
        sys.exit(1)

    print(f"🔍 Searching for {len(COMPANY_NAMES)} companies in Börsdata...")
    print()

    # Initialize client and fetch all instruments
    client = BorsdataClient(api_key=api_key)

    print("📥 Fetching all instruments (Nordic + Global)...")
    all_instruments = client.get_all_instruments()

    # Separate by checking which internal cache they came from
    nordic_instruments = client.get_instruments()
    # Global instruments are those in all_instruments but not in nordic_instruments
    nordic_ids = {inst.get("insId") for inst in nordic_instruments}
    global_instruments = [inst for inst in all_instruments if inst.get("insId") not in nordic_ids]

    print(f"   Found {len(nordic_instruments)} Nordic instruments")
    print(f"   Found {len(global_instruments)} Global instruments")
    print(f"✅ Total: {len(all_instruments)} instruments loaded")
    print()

    # Search for matches
    matched: List[Tuple[str, str, str, str]] = []  # (company_name, ticker, full_name, market)
    unmatched: List[str] = []
    global_ids = {inst.get("insId") for inst in global_instruments}

    print("🔎 Searching for matches...")
    print()

    for company_name in sorted(set(COMPANY_NAMES)):  # Remove duplicates
        result = find_ticker_match(company_name, all_instruments, global_ids)

        if result:
            ticker, full_name, market = result
            matched.append((company_name, ticker, full_name, market))
            print(f"✓ {company_name:<50} → {ticker:<10} ({market}) {full_name}")
        else:
            unmatched.append(company_name)
            print(f"✗ {company_name:<50} → NOT FOUND")

    print()
    print("=" * 100)
    print(f"📊 Results: {len(matched)} matched, {len(unmatched)} unmatched")
    print("=" * 100)
    print()

    # Save matched tickers to universe file
    if matched:
        # Separate by market
        nordic_tickers = [ticker for _, ticker, _, market in matched if market == "Nordic"]
        global_tickers = [ticker for _, ticker, _, market in matched if market == "Global"]

        universe_dir = project_root / "portfolios"
        universe_dir.mkdir(exist_ok=True)

        # Save combined universe
        universe_file = universe_dir / "borsdata_universe.txt"
        with open(universe_file, "w") as f:
            f.write(f"# Börsdata Universe - {len(matched)} tickers\n")
            f.write(f"# {len(nordic_tickers)} Nordic, {len(global_tickers)} Global\n")
            f.write(f"# Generated from company name search\n\n")
            for _, ticker, full_name, market in sorted(matched, key=lambda x: (x[3], x[1])):
                f.write(f"{ticker:<15} # {market:<7} {full_name}\n")

        print(f"💾 Saved {len(matched)} tickers to: {universe_file}")
        print()

        # Save separate market files
        if nordic_tickers:
            nordic_file = universe_dir / "borsdata_universe_nordic.txt"
            with open(nordic_file, "w") as f:
                f.write(f"# Börsdata Nordic Universe - {len(nordic_tickers)} tickers\n\n")
                for ticker in sorted(nordic_tickers):
                    f.write(f"{ticker}\n")
            print(f"💾 Saved {len(nordic_tickers)} Nordic tickers to: {nordic_file}")

        if global_tickers:
            global_file = universe_dir / "borsdata_universe_global.txt"
            with open(global_file, "w") as f:
                f.write(f"# Börsdata Global Universe - {len(global_tickers)} tickers\n\n")
                for ticker in sorted(global_tickers):
                    f.write(f"{ticker}\n")
            print(f"💾 Saved {len(global_tickers)} Global tickers to: {global_file}")

        print()

    # Report unmatched
    if unmatched:
        print("❌ Unmatched companies:")
        print()
        for company_name in sorted(unmatched):
            print(f"   • {company_name}")
        print()

        # Save unmatched to file for review
        unmatched_file = project_root / "portfolios" / "borsdata_unmatched.txt"
        with open(unmatched_file, "w") as f:
            f.write(f"# Unmatched companies - {len(unmatched)} items\n")
            f.write("# These companies were not found in Börsdata (Nordic or Global)\n\n")
            for company_name in sorted(unmatched):
                f.write(f"{company_name}\n")

        print(f"💾 Saved unmatched list to: {unmatched_file}")
        print()

    # Summary statistics
    print("📈 Summary by Market:")
    nordic_count = sum(1 for _, _, _, market in matched if market == "Nordic")
    global_count = sum(1 for _, _, _, market in matched if market == "Global")
    print(f"   Nordic: {nordic_count} tickers")
    print(f"   Global: {global_count} tickers")
    print()

    print("✅ Done!")


if __name__ == "__main__":
    main()
