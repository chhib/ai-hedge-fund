from __future__ import annotations

from scripts.build_ibkr_contract_overrides import (
    _choose_borsdata_instrument,
    _dedupe_universe_entries,
    _parse_universe_lines,
    resolve_single_ticker,
)


def test_parse_universe_lines_preserves_market_and_company_name():
    entries = _parse_universe_lines(
        [
            "LUG             # Nordic  Lundin Gold",
            "META            # Global  Meta Platforms Inc",
            "META            # Nordic  Metacon",
        ]
    )

    assert [(entry.ticker, entry.market, entry.company_name) for entry in entries] == [
        ("LUG", "Nordic", "Lundin Gold"),
        ("META", "Global", "Meta Platforms Inc"),
        ("META", "Nordic", "Metacon"),
    ]


def test_dedupe_universe_entries_reports_duplicate_tickers():
    entries, duplicates = _dedupe_universe_entries(
        _parse_universe_lines(
            [
                "META            # Global  Meta Platforms Inc",
                "META            # Nordic  Metacon",
            ]
        )
    )

    assert [(entry.ticker, entry.market) for entry in entries] == [("META", "Global")]
    assert [(entry.ticker, entry.market) for entry in duplicates["META"]] == [
        ("META", "Global"),
        ("META", "Nordic"),
    ]


def test_choose_borsdata_instrument_prefers_matching_market():
    instruments = [
        {"ticker": "LUG", "market": "Nordic", "name": "Lundin Gold", "isin": "CA5503711080"},
        {"ticker": "LUG", "market": "Global", "name": "Lundin Gold Inc", "isin": "CA5503711080"},
        {"ticker": "LUG", "market": "Global", "name": "Triumph New Energy Co Ltd", "isin": "CNE1000003Q0"},
    ]

    nordic = _choose_borsdata_instrument(instruments, preferred_market="Nordic", preferred_name="Lundin Gold")
    global_ = _choose_borsdata_instrument(instruments, preferred_market="Global", preferred_name="Lundin Gold Inc")

    assert nordic["name"] == "Lundin Gold"
    assert global_["name"] == "Lundin Gold Inc"


class _FakeIBKRClient:
    def __init__(self, search_payload):
        self.search_payload = search_payload

    def search_contracts(self, symbol: str, sec_type: str = "STK"):
        return self.search_payload

    def get_stock_contracts(self, symbols):
        raise AssertionError("resolve_single_ticker should not hit ticker lookup when ISIN search resolves the match")


def test_resolve_single_ticker_prefers_nordic_exchange_for_plain_symbol():
    payload = [
        {
            "conid": "177292167",
            "companyName": "LUNDIN GOLD INC",
            "symbol": "LUG",
            "description": "TSE",
            "sections": [{"secType": "STK"}],
        },
        {
            "conid": "177584482",
            "companyName": "LUNDIN GOLD INC",
            "symbol": "LUG",
            "description": "SFB",
            "sections": [{"secType": "STK"}],
        },
        {
            "conid": "603525823",
            "companyName": "TRIUMPH NEW ENERGY CO LTD-H",
            "symbol": "LUG",
            "description": "FWB2",
            "sections": [{"secType": "STK"}],
        },
    ]

    resolved = resolve_single_ticker(
        _FakeIBKRClient(payload),
        "LUG",
        isin="CA5503711080",
        borsdata_name="Lundin Gold",
        preferred_market="Nordic",
        delay=0,
    )

    assert resolved == {
        "conid": 177584482,
        "exchange": "SFB",
        "currency": None,
        "description": "LUNDIN GOLD INC",
        "symbol": "LUG",
    }


def test_resolve_single_ticker_rejects_single_isin_hit_with_wrong_symbol_and_name():
    isin_payload = [
        {
            "conid": "574745848",
            "companyName": "23WA",
            "symbol": "23WA",
            "description": "FWB2",
            "sections": [{"secType": "STK"}],
        }
    ]

    class _FallbackClient:
        def search_contracts(self, symbol: str, sec_type: str = "STK"):
            if symbol == "SE0017937279":
                return isin_payload
            return []

        def get_stock_contracts(self, symbols):
            return {}

    resolved = resolve_single_ticker(
        _FallbackClient(),
        "BRIGHT",
        isin="SE0017937279",
        borsdata_name="BrightBid",
        preferred_market="Nordic",
        delay=0,
    )

    assert resolved is None
