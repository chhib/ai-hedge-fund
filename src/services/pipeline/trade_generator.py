"""Trade generation: diff current vs target portfolio, produce recommendations."""

import math
from datetime import datetime
from typing import Any, Callable, Dict, List

from src.agents.enhanced_portfolio_manager import PriceContext
from src.utils.currency import compute_cost_basis_after_rebalance
from src.utils.portfolio_loader import Portfolio, Position


def generate_recommendations(
    target_positions: Dict[str, float],
    min_trade_size: float,
    portfolio: Portfolio,
    exchange_rates: Dict[str, float],
    get_price_context: Callable[[str], PriceContext],
    get_ticker_currency: Callable[[str], str],
    home_currency: str,
    verbose: bool = False,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generate trading recommendations and updated portfolio.

    Returns (recommendations, position_value_map) where position_value_map
    maps ticker -> {price, currency, fx_rate, value_home}.
    """
    recommendations = []
    current_tickers = {p.ticker for p in portfolio.positions}
    all_tickers = set(list(target_positions.keys()) + list(current_tickers))

    position_value_map: Dict[str, Dict[str, float]] = {}
    total_value_home = 0.0

    for pos in portfolio.positions:
        value_info = _get_position_value_info(pos, get_price_context, exchange_rates, home_currency)
        position_value_map[pos.ticker] = value_info
        total_value_home += value_info["value_home"]

    for currency, cash in portfolio.cash_holdings.items():
        fx_rate = exchange_rates.get(currency, 1.0)
        total_value_home += cash * fx_rate

    total_value = total_value_home

    for ticker in all_tickers:
        current_pos = next((p for p in portfolio.positions if p.ticker == ticker), None)
        current_weight = 0.0
        current_shares = 0.0
        if current_pos:
            value_info = position_value_map.get(ticker)
            if value_info:
                current_value_home = value_info["value_home"]
                current_weight = current_value_home / total_value if total_value > 0 else 0
            else:
                fx_rate = exchange_rates.get(current_pos.currency, 1.0)
                current_value_home = current_pos.shares * current_pos.cost_basis * fx_rate
                current_weight = current_value_home / total_value if total_value > 0 else 0
            current_shares = current_pos.shares

        target_weight = target_positions.get(ticker, 0.0)
        weight_delta = target_weight - current_weight

        if abs(weight_delta * total_value) < min_trade_size:
            action = "HOLD"
        elif target_weight == 0 and current_weight > 0:
            action = "SELL"
        elif target_weight > 0 and current_weight == 0:
            action = "ADD"
        elif weight_delta > 0:
            action = "INCREASE"
        elif weight_delta < 0:
            action = "DECREASE"
        else:
            action = "HOLD"

        price_context = get_price_context(ticker)
        currency = price_context.currency or (current_pos.currency if current_pos else get_ticker_currency(ticker))

        if current_pos and currency and current_pos.currency and currency != current_pos.currency:
            if verbose:
                print(f"⚠️  Currency update for {ticker}: {current_pos.currency} → {currency}")

        fx_rate = exchange_rates.get(currency, 1.0)
        target_value_home = target_weight * total_value

        if action in {"ADD", "INCREASE"}:
            trade_price = price_context.buy_price or price_context.entry_price
        elif action in {"SELL", "DECREASE"}:
            trade_price = price_context.sell_price or price_context.entry_price
        else:
            trade_price = price_context.entry_price

        if current_pos and price_context.sample_size == 0:
            trade_price = current_pos.cost_basis or trade_price
            currency = current_pos.currency or currency
            fx_rate = exchange_rates.get(currency, 1.0)

        if trade_price <= 0:
            fallback_price = price_context.latest_close
            if (fallback_price is None or fallback_price <= 0) and current_pos:
                fallback_price = current_pos.cost_basis
            trade_price = fallback_price if fallback_price and fallback_price > 0 else 100.0

        trade_price_home = trade_price * fx_rate
        target_shares = target_value_home / trade_price_home if trade_price_home > 0 else 0
        value_delta = (target_shares - current_shares) * trade_price

        recommendations.append(
            {
                "ticker": ticker,
                "action": action,
                "current_shares": current_shares,
                "current_weight": current_weight,
                "target_shares": target_shares,
                "target_weight": target_weight,
                "value_delta": value_delta,
                "confidence": 0.75,
                "reasoning": f"Target allocation: {target_weight:.1%}",
                "current_price": trade_price,
                "currency": currency,
                "pricing_basis": price_context.entry_price,
                "pricing_band": {"low": price_context.band_low, "high": price_context.band_high},
                "latest_close": price_context.latest_close,
                "atr": price_context.atr,
                "pricing_sample": price_context.sample_size,
                "pricing_source": price_context.source,
                "desired_weight": target_weight,
            }
        )

    recommendations = _validate_cash_constraints(recommendations, portfolio, exchange_rates)
    recommendations = _round_and_top_up_shares(recommendations, target_positions, total_value, min_trade_size, exchange_rates)

    return recommendations, position_value_map


def _get_position_value_info(
    position: Position,
    get_price_context: Callable[[str], PriceContext],
    exchange_rates: Dict[str, float],
    home_currency: str,
) -> Dict[str, float]:
    """Calculate current market value for a position using price context."""
    price_context = None
    try:
        price_context = get_price_context(position.ticker)
    except Exception:
        price_context = None

    price_candidates = []
    if price_context:
        price_candidates.extend(
            [
                getattr(price_context, "entry_price", None),
                getattr(price_context, "latest_close", None),
            ]
        )
    price_candidates.append(position.cost_basis)
    price = next((float(p) for p in price_candidates if p is not None and p > 0), 0.0)

    currency = None
    if price_context and getattr(price_context, "currency", None):
        currency = price_context.currency
    elif position.currency:
        currency = position.currency
    else:
        currency = home_currency

    fx_rate = exchange_rates.get(currency, 1.0)
    value_home = position.shares * price * fx_rate

    return {
        "price": price,
        "currency": currency,
        "fx_rate": fx_rate,
        "value_home": value_home,
    }


def _validate_cash_constraints(
    recommendations: List[Dict[str, Any]],
    portfolio: Portfolio,
    exchange_rates: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Scale down purchases if they exceed projected available cash."""
    total_cash_available = 0.0
    for currency, cash in portfolio.cash_holdings.items():
        fx_rate = exchange_rates.get(currency, 1.0)
        total_cash_available += cash * fx_rate

    sale_proceeds_home = 0.0
    purchase_requirements_home = 0.0
    position_lookup = {p.ticker: p for p in portfolio.positions}

    for rec in recommendations:
        fx_rate = exchange_rates.get(rec["currency"], 1.0)
        if rec["action"] == "SELL":
            sale_proceeds_home += rec["current_shares"] * rec["current_price"] * fx_rate
        elif rec["action"] == "ADD":
            purchase_requirements_home += rec["target_shares"] * rec["current_price"] * fx_rate
        elif rec["action"] == "INCREASE":
            existing = position_lookup.get(rec["ticker"])
            if existing:
                delta_shares = rec["target_shares"] - existing.shares
                if delta_shares > 0:
                    purchase_requirements_home += delta_shares * rec["current_price"] * fx_rate
                elif delta_shares < 0:
                    sale_proceeds_home += abs(delta_shares) * rec["current_price"] * fx_rate
        elif rec["action"] == "DECREASE":
            existing = position_lookup.get(rec["ticker"])
            if existing:
                delta_shares = existing.shares - rec["target_shares"]
                sale_proceeds_home += delta_shares * rec["current_price"] * fx_rate

    projected_cash_available = total_cash_available + sale_proceeds_home

    if purchase_requirements_home > projected_cash_available:
        if projected_cash_available <= 0:
            scale_factor = 0.0
        else:
            scale_factor = (projected_cash_available * 0.99) / purchase_requirements_home
        scale_factor = max(min(scale_factor, 1.0), 0.0)

        for rec in recommendations:
            if rec["action"] in ["ADD", "INCREASE"]:
                if rec["action"] == "ADD":
                    rec["target_shares"] *= scale_factor
                    rec["target_weight"] *= scale_factor
                elif rec["action"] == "INCREASE":
                    existing = position_lookup.get(rec["ticker"])
                    if existing:
                        delta_shares = rec["target_shares"] - existing.shares
                        if delta_shares > 0:
                            scaled_delta = delta_shares * scale_factor
                            rec["target_shares"] = existing.shares + scaled_delta
                            rec["target_weight"] *= scale_factor

    return recommendations


def _round_and_top_up_shares(
    recommendations: List[Dict[str, Any]],
    target_positions: Dict[str, float],
    total_value: float,
    min_trade_size: float,
    exchange_rates: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Round share counts to integers and deploy residual cash."""
    if total_value <= 0:
        return recommendations

    for rec in recommendations:
        if "desired_weight" not in rec:
            rec["desired_weight"] = target_positions.get(rec["ticker"], 0.0)

    for rec in recommendations:
        if rec["ticker"].upper() == "CASH":
            continue

        current_shares = rec["current_shares"]
        raw_target_shares = rec["target_shares"]
        action = rec["action"]

        if action == "SELL":
            adjusted_shares = 0.0
        elif action == "ADD":
            adjusted_shares = math.floor(raw_target_shares)
        elif action == "INCREASE":
            delta = max(0.0, raw_target_shares - current_shares)
            adjusted_shares = current_shares + math.floor(delta)
        elif action == "DECREASE":
            delta = max(0.0, current_shares - raw_target_shares)
            adjusted_shares = current_shares - math.floor(delta)
        else:
            adjusted_shares = round(raw_target_shares)

        adjusted_shares = max(0.0, float(adjusted_shares))
        rec["target_shares"] = adjusted_shares

        delta_shares = adjusted_shares - current_shares
        if adjusted_shares == 0 and current_shares > 0:
            rec["action"] = "SELL"
        elif delta_shares > 0 and current_shares == 0:
            rec["action"] = "ADD"
        elif delta_shares > 0:
            rec["action"] = "INCREASE"
        elif delta_shares < 0 and adjusted_shares > 0:
            rec["action"] = "DECREASE"
        elif delta_shares < 0:
            rec["action"] = "SELL"
        else:
            rec["action"] = "HOLD"

        rec["value_delta"] = delta_shares * rec["current_price"]
        fx_rate = exchange_rates.get(rec["currency"], 1.0)
        position_value_home = adjusted_shares * rec["current_price"] * fx_rate
        rec["target_weight"] = position_value_home / total_value if total_value > 0 else 0.0

    _allocate_residual_cash(recommendations, total_value, min_trade_size, exchange_rates)
    return recommendations


def _allocate_residual_cash(
    recommendations: List[Dict[str, Any]],
    total_value: float,
    min_trade_size: float,
    exchange_rates: Dict[str, float],
    base_weight_tolerance: float = 0.02,
) -> None:
    """Greedily allocate remaining cash to most attractive tickers."""
    if total_value <= 0:
        return

    non_cash: List[Dict[str, Any]] = []
    residual_home = total_value

    for rec in recommendations:
        if rec["ticker"].upper() == "CASH":
            continue
        fx_rate = exchange_rates.get(rec["currency"], 1.0)
        allocation = rec["target_shares"] * rec["current_price"] * fx_rate
        residual_home -= allocation
        non_cash.append(rec)

    residual_home = max(residual_home, 0.0)

    if residual_home < min_trade_size:
        return

    tolerance_schedule = [0.0, base_weight_tolerance, 0.05, 0.1, 0.2, 0.5, 1.0]

    while residual_home >= min_trade_size - 1e-6:
        candidate = None
        candidate_units = 0
        candidate_cost = 0.0
        candidate_deficit = -1.0

        for tolerance in tolerance_schedule:
            for rec in non_cash:
                desired_weight = rec.get("desired_weight", 0.0)
                current_weight = rec.get("target_weight", 0.0)
                deficit = max(0.0, desired_weight - current_weight)

                fx_rate = exchange_rates.get(rec["currency"], 1.0)
                share_cost_home = rec["current_price"] * fx_rate
                if share_cost_home <= 0:
                    continue

                max_affordable_units = int(residual_home // share_cost_home)
                if max_affordable_units <= 0:
                    continue

                min_units = 1
                if min_trade_size > 0:
                    min_units = max(1, math.ceil(min_trade_size / share_cost_home))
                if max_affordable_units < min_units:
                    continue

                if tolerance < 1.0:
                    allowable_home = max(
                        0.0,
                        (desired_weight + tolerance) * total_value - current_weight * total_value,
                    )
                    max_units_tolerance = int(allowable_home // share_cost_home)
                    if max_units_tolerance <= 0:
                        continue
                    units = min(max_affordable_units, max(min_units, max_units_tolerance))
                else:
                    units = max_affordable_units

                if units < min_units:
                    continue

                if candidate is None or deficit > candidate_deficit or (
                    abs(deficit - candidate_deficit) < 1e-9 and share_cost_home * units < candidate_cost
                ):
                    candidate = rec
                    candidate_units = units
                    candidate_cost = share_cost_home * units
                    candidate_deficit = deficit

            if candidate:
                break

        if not candidate:
            break

        fx_rate = exchange_rates.get(candidate["currency"], 1.0)

        candidate["target_shares"] += float(candidate_units)
        delta_shares = candidate["target_shares"] - candidate["current_shares"]
        if candidate["current_shares"] == 0 and candidate["target_shares"] > 0:
            candidate["action"] = "ADD"
        elif candidate["target_shares"] > candidate["current_shares"]:
            candidate["action"] = "INCREASE"
        elif candidate["target_shares"] < candidate["current_shares"]:
            candidate["action"] = "DECREASE"
        elif candidate["target_shares"] == 0 and candidate["current_shares"] > 0:
            candidate["action"] = "SELL"
        else:
            candidate["action"] = "HOLD"

        candidate["value_delta"] = delta_shares * candidate["current_price"]
        position_value_home = candidate["target_shares"] * candidate["current_price"] * fx_rate
        candidate["target_weight"] = position_value_home / total_value if total_value > 0 else 0.0

        residual_home -= candidate_cost

        if residual_home < 0 and abs(residual_home) < 1e-6:
            residual_home = 0.0
            break


def calculate_updated_portfolio(
    recommendations: List[Dict[str, Any]],
    portfolio: Portfolio,
    exchange_rates: Dict[str, float],
    home_currency: str,
) -> Dict[str, Any]:
    """Calculate updated portfolio after applying recommendations."""
    updated_positions = []
    updated_cash = dict(portfolio.cash_holdings)

    if home_currency not in updated_cash:
        updated_cash[home_currency] = 0.0

    for rec in recommendations:
        ticker = rec["ticker"]
        currency = rec["currency"]

        if rec["action"] == "SELL":
            sale_value = rec["current_shares"] * rec["current_price"]
            fx_rate = exchange_rates.get(currency, 1.0)
            updated_cash[home_currency] += sale_value * fx_rate
            continue

        elif rec["action"] == "ADD":
            purchase_value = rec["target_shares"] * rec["current_price"]
            fx_rate = exchange_rates.get(currency, 1.0)
            updated_cash[home_currency] -= purchase_value * fx_rate
            updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": rec["current_price"], "currency": rec["currency"], "date_acquired": datetime.now().strftime("%Y-%m-%d")})

        elif rec["action"] in ["INCREASE", "DECREASE", "HOLD"]:
            existing = next((p for p in portfolio.positions if p.ticker == ticker), None)

            if existing and rec["target_shares"] > 0:
                if rec["action"] == "INCREASE":
                    delta_shares = rec["target_shares"] - existing.shares
                    purchase_value = delta_shares * rec["current_price"]
                    fx_rate = exchange_rates.get(currency, 1.0)
                    updated_cash[home_currency] -= purchase_value * fx_rate
                elif rec["action"] == "DECREASE":
                    delta_shares = existing.shares - rec["target_shares"]
                    sale_value = delta_shares * rec["current_price"]
                    fx_rate = exchange_rates.get(currency, 1.0)
                    updated_cash[home_currency] += sale_value * fx_rate

                new_cost_basis = compute_cost_basis_after_rebalance(
                    existing_shares=existing.shares,
                    existing_cost_basis=existing.cost_basis,
                    existing_currency=existing.currency,
                    current_price=rec["current_price"],
                    target_currency=rec["currency"],
                    target_shares=rec["target_shares"],
                    action=rec["action"],
                )

                updated_positions.append({"ticker": ticker, "shares": rec["target_shares"], "cost_basis": new_cost_basis, "currency": rec["currency"], "date_acquired": existing.date_acquired.strftime("%Y-%m-%d") if existing.date_acquired else ""})

    return {"positions": updated_positions, "cash": updated_cash}
