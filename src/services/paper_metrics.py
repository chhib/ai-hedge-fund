"""Paper trading performance metrics: Sharpe, drawdown, win rate, avg P&L."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.data.decision_store import get_decision_store

logger = logging.getLogger(__name__)


def compute_paper_performance(pod_id: str, store=None) -> Dict[str, Any]:
    """Compute full performance metrics for a paper pod.

    Returns dict with: total_value, cash, positions_value, cumulative_return_pct,
    sharpe_ratio, sortino_ratio, max_drawdown, win_rate, avg_trade_pnl, num_trades,
    num_snapshots.
    """
    store = store or get_decision_store()
    snapshot = store.get_latest_paper_snapshot(pod_id)
    positions = store.get_latest_paper_positions(pod_id)
    history = store.get_paper_snapshot_history(pod_id)

    result: Dict[str, Any] = {
        "total_value": None,
        "cash": None,
        "positions_value": None,
        "cumulative_return_pct": None,
        "num_positions": 0,
        "num_snapshots": len(history),
        "observation_days": 0,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "max_drawdown": None,
        "current_drawdown_pct": None,
        "high_water_mark": None,
        "win_rate": None,
        "avg_trade_pnl": None,
        "num_trades": 0,
    }

    if snapshot:
        result["total_value"] = snapshot["total_value"]
        result["cash"] = snapshot["cash"]
        result["positions_value"] = snapshot["positions_value"]
        result["cumulative_return_pct"] = snapshot["cumulative_return_pct"]

    result["num_positions"] = len(positions)
    if history:
        start_date = _coerce_snapshot_date(history[0].get("created_at"))
        end_date = _coerce_snapshot_date(history[-1].get("created_at"))
        if start_date and end_date:
            result["observation_days"] = max((end_date - start_date).days + 1, 1)

        values_only = [snap["total_value"] for snap in history if snap.get("total_value") is not None]
        if values_only:
            high_water = max(values_only)
            current_value = values_only[-1]
            result["high_water_mark"] = high_water
            if high_water > 0:
                result["current_drawdown_pct"] = max(((high_water - current_value) / high_water) * 100.0, 0.0)

    # Portfolio value time series -> Sharpe, Sortino, Max Drawdown
    if len(history) >= 2:
        try:
            from src.backtesting.metrics import PerformanceMetricsCalculator
            values = []
            for snap in history:
                ts = snap.get("created_at", "")
                try:
                    dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
                values.append({"Date": dt, "Portfolio Value": snap["total_value"]})

            if len(values) >= 2:
                calc = PerformanceMetricsCalculator()
                metrics = calc.compute_metrics(values)
                result["sharpe_ratio"] = metrics.get("sharpe_ratio")
                result["sortino_ratio"] = metrics.get("sortino_ratio")
                result["max_drawdown"] = metrics.get("max_drawdown")
        except Exception:
            logger.debug("Failed to compute portfolio metrics for pod %s", pod_id, exc_info=True)

    # Trade-level metrics from execution_outcomes
    outcomes = store.get_paper_execution_outcomes(pod_id)
    filled = [o for o in outcomes if o.get("status") == "filled"]

    if filled:
        # Group fills by ticker to find closed trades (buy then sell)
        buys: Dict[str, List[Dict]] = {}
        sells: Dict[str, List[Dict]] = {}
        for o in filled:
            side = o.get("side", "").upper()
            ticker = o.get("ticker", "")
            if side == "BUY":
                buys.setdefault(ticker, []).append(o)
            elif side == "SELL":
                sells.setdefault(ticker, []).append(o)

        # Compute realized P&L for closed trades
        wins = 0
        losses = 0
        total_pnl = 0.0
        total_closed = 0

        for ticker, sell_list in sells.items():
            buy_list = buys.get(ticker, [])
            if not buy_list:
                continue
            # Simple: match sells to earliest buys
            avg_buy_price = sum(b.get("fill_price", 0) for b in buy_list) / len(buy_list) if buy_list else 0
            for sell in sell_list:
                sell_price = sell.get("fill_price", 0)
                sell_qty = sell.get("fill_quantity", 0)
                if sell_price and sell_qty and avg_buy_price:
                    pnl = (sell_price - avg_buy_price) * sell_qty
                    total_pnl += pnl
                    total_closed += 1
                    if pnl > 0:
                        wins += 1
                    else:
                        losses += 1

        result["num_trades"] = len(filled)
        if total_closed > 0:
            result["win_rate"] = wins / total_closed
            result["avg_trade_pnl"] = total_pnl / total_closed

    return result


def _coerce_snapshot_date(raw: Any) -> Optional[datetime.date]:
    try:
        return datetime.fromisoformat(raw).date()
    except (TypeError, ValueError, AttributeError):
        return None
