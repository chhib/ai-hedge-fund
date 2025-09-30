"""
Service for fetching and caching exchange rates.
"""
from typing import Dict, Optional

from .borsdata_client import BorsdataClient
from src.utils.logger import vprint


class ExchangeRateService:
    """
    Service for fetching and caching exchange rates from Börsdata.
    """

    def __init__(self, client: BorsdataClient):
        self.client = client
        self._currency_map: Optional[Dict[str, int]] = None
        self._rate_cache: Dict[str, float] = {}

    def _initialize_currency_map(self):
        """
        Fetches all instruments and creates a map of currency pairs to instrument IDs.
        """
        if self._currency_map is not None:
            return

        vprint("Initializing currency map...")
        instruments = self.client.get_all_instruments()
        vprint(f"Found {len(instruments)} total instruments.")

        self._currency_map = {}
        for instrument in instruments:
            if instrument.get('instrument') == 6:
                ticker = instrument.get('ticker')
                if ticker:
                    self._currency_map[ticker] = instrument.get('insId')
        vprint(f"Found {len(self._currency_map)} potential currency instruments.")

    def get_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Gets the exchange rate between two currencies.
        """
        if from_currency == to_currency:
            return 1.0

        cache_key = f"{from_currency}_{to_currency}"
        if cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        self._initialize_currency_map()

        # Try direct pair, e.g., USDSEK
        pair_ticker = f"{from_currency}{to_currency}".upper()
        if pair_ticker in self._currency_map:
            ins_id = self._currency_map[pair_ticker]
            prices = self.client.get_stock_prices(instrument_id=ins_id)
            if prices:
                rate = prices[-1]['c']
                self._rate_cache[cache_key] = rate
                return rate

        # Try inverse pair, e.g., SEKUSD
        inverse_pair_ticker = f"{to_currency}{from_currency}".upper()
        if inverse_pair_ticker in self._currency_map:
            ins_id = self._currency_map[inverse_pair_ticker]
            prices = self.client.get_stock_prices(instrument_id=ins_id)
            if prices:
                rate = prices[-1]['c']
                if rate != 0:
                    inverse_rate = 1 / rate
                    self._rate_cache[cache_key] = inverse_rate
                    return inverse_rate

        return None
