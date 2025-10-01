"""Helpers for normalising Börsdata currency codes and price denominations."""

from __future__ import annotations

from typing import Dict, Tuple

_MINOR_CURRENCY_FACTORS: Dict[str, Tuple[str, float]] = {
    "GBX": ("GBP", 100.0),  # London listings often quoted in pence
    "GBp": ("GBP", 100.0),
    "GBP": ("GBP", 1.0),
}


def normalize_currency_code(currency: str | None) -> str:
    """Return the major ISO currency code for a Börsdata currency identifier."""

    if not currency:
        return ""

    raw_code = currency.strip()
    mapping = _MINOR_CURRENCY_FACTORS.get(raw_code)
    if mapping is None:
        mapping = _MINOR_CURRENCY_FACTORS.get(raw_code.upper())
    if mapping:
        return mapping[0]
    return raw_code.upper()


def normalize_price_and_currency(price: float, currency: str | None) -> tuple[float, str]:
    """
    Convert prices quoted in minor units (e.g. GBX) to their major currency.

    Returns a tuple of ``(adjusted_price, major_currency)``.
    """

    if currency is None:
        return price, ""

    raw_code = currency.strip()
    mapping = _MINOR_CURRENCY_FACTORS.get(raw_code)
    if mapping is None:
        mapping = _MINOR_CURRENCY_FACTORS.get(raw_code.upper())

    if not mapping:
        return price, raw_code.upper()

    major_currency, factor = mapping
    adjusted_price = price / factor if factor and factor != 0 else price
    return adjusted_price, major_currency


def compute_cost_basis_after_rebalance(
    *,
    existing_shares: float,
    existing_cost_basis: float,
    existing_currency: str | None,
    current_price: float,
    target_currency: str,
    target_shares: float,
    action: str,
) -> float:
    """Return the updated cost basis after applying a rebalance action."""

    action_upper = (action or "").upper()
    target_currency = (target_currency or "").upper()
    existing_currency = (existing_currency or "").upper()
    currency_mismatch = existing_currency != target_currency

    if action_upper == "INCREASE":
        if target_shares <= 0:
            return 0.0
        delta_shares = target_shares - existing_shares
        if currency_mismatch:
            old_value = existing_shares * current_price
        else:
            old_value = existing_shares * existing_cost_basis
        new_value = max(delta_shares, 0) * current_price
        total_value = old_value + new_value
        return total_value / target_shares if target_shares else 0.0

    if action_upper in {"DECREASE", "HOLD"}:
        return current_price if currency_mismatch else existing_cost_basis

    return existing_cost_basis
