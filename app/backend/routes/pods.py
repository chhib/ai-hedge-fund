from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Dict, Any
from app.backend.models.schemas import PodResponse, PodLifecycleEventResponse, ErrorResponse
from src.config.pod_config import load_pods, load_lifecycle_config
from src.services.pod_lifecycle import get_lifecycle_status, evaluate_pod_lifecycle
from src.data.decision_store import get_decision_store
import json

router = APIRouter(prefix="/pods")

@router.get(
    path="",
    response_model=List[PodResponse],
    responses={500: {"model": ErrorResponse}}
)
async def list_pods():
    """List all pods with their current status and metrics."""
    try:
        pods = load_pods()
        lifecycle_config = load_lifecycle_config()
        store = get_decision_store()
        
        results = []
        for pod in pods:
            status = get_lifecycle_status(pod.name, pod.tier, lifecycle_config, store=store)
            evaluation = evaluate_pod_lifecycle(pod.name, status.effective_tier, lifecycle_config, store=store)
            
            results.append(PodResponse(
                name=pod.name,
                analyst=pod.analyst,
                enabled=pod.enabled,
                max_picks=pod.max_picks,
                tier=pod.tier,
                starting_capital=pod.starting_capital,
                schedule=pod.schedule,
                effective_tier=status.effective_tier,
                days_in_tier=status.days_in_tier,
                next_evaluation_date=status.next_evaluation_date.isoformat(),
                latest_event=status.latest_event,
                metrics=evaluation.metrics
            ))
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    path="/config",
    response_model=Dict[str, Any],
    responses={500: {"model": ErrorResponse}}
)
async def get_config():
    """Get the current lifecycle configuration."""
    try:
        config = load_lifecycle_config()
        return {
            "min_history_days": config.min_history_days,
            "promotion_sharpe": config.promotion_sharpe,
            "promotion_return_pct": config.promotion_return_pct,
            "promotion_drawdown_pct": config.promotion_drawdown_pct,
            "maintenance_sharpe": config.maintenance_sharpe,
            "hard_stop_drawdown_pct": config.hard_stop_drawdown_pct,
            "evaluation_schedule": config.evaluation_schedule,
            "next_evaluation_date": config.next_evaluation_date().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    path="/{pod_id}/history",
    response_model=List[PodLifecycleEventResponse],
    responses={500: {"model": ErrorResponse}}
)
async def get_pod_history(pod_id: str):
    """Get lifecycle history for a pod."""
    try:
        store = get_decision_store()
        events = store.get_pod_lifecycle_events(pod_id=pod_id)
        
        results = []
        for event in events:
            metrics_json = None
            if event.get("metrics_json"):
                metrics_json = json.loads(event["metrics_json"])
                
            results.append(PodLifecycleEventResponse(
                id=event["id"],
                pod_id=event["pod_id"],
                event_type=event["event_type"],
                old_tier=event["old_tier"],
                new_tier=event["new_tier"],
                reason=event["reason"],
                source=event["source"],
                metrics_json=metrics_json,
                created_at=event["created_at"]
            ))
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    path="/{pod_id}/promote",
    responses={200: {"description": "Pod promoted successfully"}, 500: {"model": ErrorResponse}}
)
async def promote_pod(pod_id: str):
    """Manually promote a pod."""
    try:
        pods = load_pods()
        pod = next((p for p in pods if p.name == pod_id), None)
        if not pod:
            raise HTTPException(status_code=404, detail=f"Pod {pod_id} not found")
            
        store = get_decision_store()
        lifecycle_config = load_lifecycle_config()
        status = get_lifecycle_status(pod.name, pod.tier, lifecycle_config, store=store)
        
        if status.effective_tier == "live":
            return {"message": f"Pod {pod_id} is already live"}
            
        evaluation = evaluate_pod_lifecycle(pod.name, status.effective_tier, lifecycle_config, store=store)
        
        store.record_pod_lifecycle_event(
            pod_id=pod.name,
            event_type="promotion",
            old_tier=status.effective_tier,
            new_tier="live",
            reason="Manual promotion via Web UI",
            source="manual",
            metrics=evaluation.metrics
        )
        return {"message": f"Pod {pod_id} promoted to live"}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    path="/{pod_id}/demote",
    responses={200: {"description": "Pod demoted successfully"}, 500: {"model": ErrorResponse}}
)
async def demote_pod(pod_id: str):
    """Manually demote a pod."""
    try:
        pods = load_pods()
        pod = next((p for p in pods if p.name == pod_id), None)
        if not pod:
            raise HTTPException(status_code=404, detail=f"Pod {pod_id} not found")
            
        store = get_decision_store()
        lifecycle_config = load_lifecycle_config()
        status = get_lifecycle_status(pod.name, pod.tier, lifecycle_config, store=store)
        
        if status.effective_tier == "paper":
            return {"message": f"Pod {pod_id} is already in paper tier"}
            
        evaluation = evaluate_pod_lifecycle(pod.name, status.effective_tier, lifecycle_config, store=store)
        
        store.record_pod_lifecycle_event(
            pod_id=pod.name,
            event_type="demotion",
            old_tier=status.effective_tier,
            new_tier="paper",
            reason="Manual demotion via Web UI",
            source="manual",
            metrics=evaluation.metrics
        )
        return {"message": f"Pod {pod_id} demoted to paper"}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
