from src.utils.currency import (
    normalize_currency_code,
    normalize_price_and_currency,
    compute_cost_basis_after_rebalance,
)


def test_normalize_currency_code_gbx_to_gbp():
    assert normalize_currency_code("GBX") == "GBP"


def test_normalize_price_from_gbx_minor_units():
    price, currency = normalize_price_and_currency(250.0, "GBX")
    assert price == 2.5
    assert currency == "GBP"


def test_normalize_preserves_major_currency():
    price, currency = normalize_price_and_currency(4.05, "GBP")
    assert price == 4.05
    assert currency == "GBP"


def test_normalize_unknown_currency_passthrough():
    price, currency = normalize_price_and_currency(100.0, "sek")
    assert price == 100.0
    assert currency == "SEK"


def test_cost_basis_rebases_when_currency_mismatch_on_increase():
    cost_basis = compute_cost_basis_after_rebalance(
        existing_shares=50,
        existing_cost_basis=500.0,
        existing_currency="SEK",
        current_price=133.1,
        target_currency="DKK",
        target_shares=83,
        action="INCREASE",
    )
    assert round(cost_basis, 2) == 133.1


def test_cost_basis_rebases_when_currency_mismatch_on_hold():
    cost_basis = compute_cost_basis_after_rebalance(
        existing_shares=50,
        existing_cost_basis=500.0,
        existing_currency="SEK",
        current_price=133.1,
        target_currency="DKK",
        target_shares=50,
        action="HOLD",
    )
    assert round(cost_basis, 2) == 133.1


def test_cost_basis_maintains_weighted_average_when_currency_matches():
    cost_basis = compute_cost_basis_after_rebalance(
        existing_shares=50,
        existing_cost_basis=500.0,
        existing_currency="DKK",
        current_price=140.0,
        target_currency="DKK",
        target_shares=60,
        action="INCREASE",
    )
    expected = ((50 * 500.0) + (10 * 140.0)) / 60
    assert round(cost_basis, 2) == round(expected, 2)
