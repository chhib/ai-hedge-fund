import logging
import re

from fastapi import APIRouter, HTTPException, Path

from app.backend.models.schemas import (
    LifecycleConfigResponse,
    PodLifecycleEventResponse,
    PodProposalResponse,
    PodResponse,
)
from app.backend.services.pod_service import (
    change_pod_tier,
    get_latest_proposals,
    get_lifecycle_config_dict,
    get_pod_history,
    list_pods_with_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pods")

POD_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"


def _validate_pod_id(pod_id: str) -> str:
    if not re.match(POD_ID_PATTERN, pod_id):
        raise HTTPException(status_code=400, detail="Invalid pod ID format")
    return pod_id


@router.get("", response_model=list[PodResponse])
def list_pods():
    """List all pods with their current status and metrics."""
    try:
        return list_pods_with_status()
    except Exception:
        logger.exception("Failed to list pods")
        raise HTTPException(status_code=500, detail="Failed to load pods")


@router.get("/config", response_model=LifecycleConfigResponse)
def get_config():
    """Get the current lifecycle configuration."""
    try:
        return get_lifecycle_config_dict()
    except Exception:
        logger.exception("Failed to load lifecycle config")
        raise HTTPException(status_code=500, detail="Failed to load lifecycle config")


@router.get("/{pod_id}/history", response_model=list[PodLifecycleEventResponse])
def get_history(pod_id: str = Path(..., pattern=POD_ID_PATTERN)):
    """Get lifecycle history for a pod."""
    try:
        result = get_pod_history(pod_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Pod {pod_id} not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load history for pod %s", pod_id)
        raise HTTPException(status_code=500, detail="Failed to load pod history")


@router.post("/{pod_id}/promote")
def promote_pod(pod_id: str = Path(..., pattern=POD_ID_PATTERN)):
    """Manually promote a pod to the next tier in the ladder."""
    try:
        result = change_pod_tier(pod_id, "promote")
        if result is None:
            raise HTTPException(status_code=404, detail=f"Pod {pod_id} not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to promote pod %s", pod_id)
        raise HTTPException(status_code=500, detail="Failed to promote pod")


@router.post("/{pod_id}/demote")
def demote_pod(pod_id: str = Path(..., pattern=POD_ID_PATTERN)):
    """Manually demote a pod to the previous tier in the ladder."""
    try:
        result = change_pod_tier(pod_id, "demote")
        if result is None:
            raise HTTPException(status_code=404, detail=f"Pod {pod_id} not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to demote pod %s", pod_id)
        raise HTTPException(status_code=500, detail="Failed to demote pod")


@router.get("/{pod_id}/proposals", response_model=list[PodProposalResponse])
def get_proposals(pod_id: str = Path(..., pattern=POD_ID_PATTERN)):
    """Get the latest portfolio proposals for a pod."""
    try:
        result = get_latest_proposals(pod_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Pod {pod_id} not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load proposals for pod %s", pod_id)
        raise HTTPException(status_code=500, detail="Failed to load pod proposals")
