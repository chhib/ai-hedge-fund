"""Pod lifecycle policy, metrics, and effective-tier resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from src.config.pod_config import LifecycleConfig
from src.data.decision_store import get_decision_store
from src.services.paper_metrics import compute_paper_performance


@dataclass(slots=True)
class LifecycleStatus:
    pod_id: str
    configured_tier: str
    effective_tier: str
    latest_event: Optional[Dict[str, Any]]
    days_in_tier: int
    next_evaluation_date: date


@dataclass(slots=True)
class LifecycleEvaluation:
    pod_id: str
    metrics: Dict[str, Any]
    eligible_for_promotion: bool
    passes_maintenance: bool
    should_drawdown_stop: bool
    promotion_reason: str
    maintenance_reason: str
    drawdown_reason: str


def resolve_effective_tier(pod_id: str, configured_tier: str, store=None) -> str:
    """Resolve the current effective tier for a pod."""
    latest_event = (store or get_decision_store()).get_latest_pod_lifecycle_event(pod_id)
    if not latest_event:
        return configured_tier
    return latest_event.get("new_tier") or configured_tier


def get_lifecycle_status(
    pod_id: str,
    configured_tier: str,
    lifecycle_config: LifecycleConfig,
    store=None,
    today: Optional[date] = None,
) -> LifecycleStatus:
    """Resolve lifecycle status for CLI and daemon use."""
    store = store or get_decision_store()
    latest_event = store.get_latest_pod_lifecycle_event(pod_id)
    effective_tier = latest_event.get("new_tier") if latest_event else configured_tier

    days_in_tier = 0
    if latest_event and latest_event.get("created_at"):
        changed_at = _parse_date(latest_event["created_at"])
        if changed_at:
            days_in_tier = max(((today or date.today()) - changed_at).days, 0)

    return LifecycleStatus(
        pod_id=pod_id,
        configured_tier=configured_tier,
        effective_tier=effective_tier,
        latest_event=latest_event,
        days_in_tier=days_in_tier,
        next_evaluation_date=lifecycle_config.next_evaluation_date(today=today),
    )


def evaluate_pod_lifecycle(
    pod_id: str,
    effective_tier: str,
    lifecycle_config: LifecycleConfig,
    store=None,
) -> LifecycleEvaluation:
    """Evaluate promotion, maintenance, and hard-stop conditions for a pod."""
    metrics = compute_paper_performance(pod_id, store=store)

    observation_days = metrics.get("observation_days") or 0
    sharpe_ratio = metrics.get("sharpe_ratio")
    cumulative_return_pct = metrics.get("cumulative_return_pct")
    max_drawdown = _coerce_positive_pct(metrics.get("max_drawdown"))
    current_drawdown_pct = _coerce_positive_pct(metrics.get("current_drawdown_pct"))

    promotion_checks = [
        observation_days >= lifecycle_config.min_history_days,
        sharpe_ratio is not None and sharpe_ratio > lifecycle_config.promotion_sharpe,
        cumulative_return_pct is not None and cumulative_return_pct > lifecycle_config.promotion_return_pct,
        max_drawdown is not None and max_drawdown < lifecycle_config.promotion_drawdown_pct,
    ]
    eligible_for_promotion = all(promotion_checks)

    maintenance_checks = [
        sharpe_ratio is not None and sharpe_ratio > lifecycle_config.maintenance_sharpe,
        current_drawdown_pct is not None and current_drawdown_pct < lifecycle_config.hard_stop_drawdown_pct,
    ]
    passes_maintenance = all(maintenance_checks)
    should_drawdown_stop = (
        effective_tier == "live"
        and current_drawdown_pct is not None
        and current_drawdown_pct >= lifecycle_config.hard_stop_drawdown_pct
    )

    return LifecycleEvaluation(
        pod_id=pod_id,
        metrics=metrics,
        eligible_for_promotion=eligible_for_promotion,
        passes_maintenance=passes_maintenance,
        should_drawdown_stop=should_drawdown_stop,
        promotion_reason=(
            f"history={observation_days}d sharpe={_fmt_num(sharpe_ratio)} return={_fmt_pct(cumulative_return_pct)} "
            f"max_dd={_fmt_pct(max_drawdown)}"
        ),
        maintenance_reason=(
            f"sharpe={_fmt_num(sharpe_ratio)} current_dd={_fmt_pct(current_drawdown_pct)}"
        ),
        drawdown_reason=(
            f"Current drawdown {_fmt_pct(current_drawdown_pct)} breached hard stop "
            f"{lifecycle_config.hard_stop_drawdown_pct:.1f}%"
        ),
    )


def _parse_date(raw: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(raw).date()
    except (TypeError, ValueError):
        return None


def _coerce_positive_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return abs(float(value))


def _fmt_num(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.1f}%"
