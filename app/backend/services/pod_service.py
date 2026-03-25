"""Pod lifecycle service -- shared business logic for the Web UI pods router."""

import json
import logging
from typing import Any

from src.config.pod_config import load_lifecycle_config, load_pods
from src.data.decision_store import get_decision_store
from src.services.pod_lifecycle import (
    evaluate_pod_lifecycle,
    get_lifecycle_status,
    resolve_effective_tier,
)

logger = logging.getLogger(__name__)

TIER_LADDER = ["paper", "live"]


def _get_pod_or_none(pod_id: str):
    return next((p for p in load_pods() if p.name == pod_id), None)


def list_pods_with_status() -> list[dict[str, Any]]:
    """List all pods with lifecycle status and metrics.

    Per-pod errors are isolated -- a single pod's bad data will not
    prevent the remaining pods from being returned.
    """
    pods = load_pods()
    lifecycle_config = load_lifecycle_config()
    store = get_decision_store()

    results = []
    for pod in pods:
        try:
            status = get_lifecycle_status(pod.name, pod.tier, lifecycle_config, store=store)
            evaluation = evaluate_pod_lifecycle(pod.name, status.effective_tier, lifecycle_config, store=store)
            results.append({
                "name": pod.name,
                "analyst": pod.analyst,
                "enabled": pod.enabled,
                "max_picks": pod.max_picks,
                "tier": pod.tier,
                "starting_capital": pod.starting_capital,
                "schedule": pod.schedule,
                "effective_tier": status.effective_tier,
                "days_in_tier": status.days_in_tier,
                "next_evaluation_date": status.next_evaluation_date.isoformat(),
                "latest_event": status.latest_event,
                "metrics": evaluation.metrics,
                "error": None,
            })
        except Exception:
            logger.exception("Failed to load lifecycle data for pod %s", pod.name)
            results.append({
                "name": pod.name,
                "analyst": pod.analyst,
                "enabled": pod.enabled,
                "max_picks": pod.max_picks,
                "tier": pod.tier,
                "starting_capital": pod.starting_capital,
                "schedule": pod.schedule,
                "effective_tier": pod.tier,
                "days_in_tier": 0,
                "next_evaluation_date": "",
                "latest_event": None,
                "metrics": None,
                "error": "Failed to load lifecycle data",
            })
    return results


def get_lifecycle_config_dict() -> dict[str, Any]:
    config = load_lifecycle_config()
    return {
        "min_history_days": config.min_history_days,
        "promotion_sharpe": config.promotion_sharpe,
        "promotion_return_pct": config.promotion_return_pct,
        "promotion_drawdown_pct": config.promotion_drawdown_pct,
        "maintenance_sharpe": config.maintenance_sharpe,
        "hard_stop_drawdown_pct": config.hard_stop_drawdown_pct,
        "evaluation_schedule": config.evaluation_schedule,
        "next_evaluation_date": config.next_evaluation_date().isoformat(),
    }


def get_pod_history(pod_id: str) -> list[dict[str, Any]] | None:
    """Return lifecycle events for a pod, or None if the pod doesn't exist."""
    pod = _get_pod_or_none(pod_id)
    if pod is None:
        return None

    store = get_decision_store()
    events = store.get_pod_lifecycle_events(pod_id=pod_id)

    results = []
    for event in events:
        metrics_json = None
        if event.get("metrics_json"):
            try:
                metrics_json = json.loads(event["metrics_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Malformed metrics_json for lifecycle event %s", event.get("id"))
        results.append({
            **event,
            "metrics_json": metrics_json,
        })
    return results


def change_pod_tier(pod_id: str, direction: str) -> dict[str, Any] | None:
    """Promote or demote a pod. Returns result dict, or None if pod not found.

    Uses the tier ladder to compute the next tier rather than hardcoding,
    and records event_type as manual_promotion/manual_demotion to match the CLI.
    """
    pod = _get_pod_or_none(pod_id)
    if pod is None:
        return None

    store = get_decision_store()
    old_tier = resolve_effective_tier(pod.name, pod.tier, store=store)

    if direction == "promote":
        idx = TIER_LADDER.index(old_tier) if old_tier in TIER_LADDER else 0
        if idx >= len(TIER_LADDER) - 1:
            return {"message": f"Pod {pod_id} is already at the highest tier ({old_tier})", "changed": False}
        new_tier = TIER_LADDER[idx + 1]
        event_type = "manual_promotion"
    else:
        idx = TIER_LADDER.index(old_tier) if old_tier in TIER_LADDER else len(TIER_LADDER) - 1
        if idx <= 0:
            return {"message": f"Pod {pod_id} is already at the lowest tier ({old_tier})", "changed": False}
        new_tier = TIER_LADDER[idx - 1]
        event_type = "manual_demotion"

    store.record_pod_lifecycle_event(
        pod_id=pod.name,
        event_type=event_type,
        old_tier=old_tier,
        new_tier=new_tier,
        reason=f"Manual {direction} via Web UI",
        source="manual",
    )
    return {"message": f"Pod {pod_id} {direction}d: {old_tier} -> {new_tier}", "changed": True}


def get_latest_proposals(pod_id: str) -> list[dict[str, Any]] | None:
    """Return the latest run's proposals for a pod, or None if pod not found."""
    pod = _get_pod_or_none(pod_id)
    if pod is None:
        return None

    store = get_decision_store()
    proposals = store.get_pod_proposals(pod_id=pod_id)
    if not proposals:
        return []

    latest_run = proposals[-1]["run_id"]
    return [
        {
            "ticker": p["ticker"],
            "target_weight": p.get("target_weight"),
            "action": p.get("action"),
            "run_id": p["run_id"],
            "created_at": p.get("created_at", ""),
        }
        for p in proposals
        if p["run_id"] == latest_run
    ]
