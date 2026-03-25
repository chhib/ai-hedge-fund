"""Tests for the pods API routes and underlying service layer."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.backend.main import app
from src.config.pod_config import LifecycleConfig, Pod


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _make_pod(name="buffett", tier="paper", analyst="warren_buffett", enabled=True):
    return Pod(name=name, analyst=analyst, enabled=enabled, max_picks=3, tier=tier, starting_capital=100000.0, schedule="nordic-morning")


class FakeStore:
    """Minimal Decision DB stand-in for route/service tests."""

    def __init__(self, lifecycle_events=None, proposals=None, snapshot=None):
        self._lifecycle_events = lifecycle_events or []
        self._proposals = proposals or []
        self._snapshot = snapshot
        self.recorded_events = []

    def get_latest_pod_lifecycle_event(self, pod_id):
        for e in reversed(self._lifecycle_events):
            if e.get("pod_id") == pod_id:
                return e
        return None

    def get_pod_lifecycle_events(self, pod_id=None, limit=100):
        if pod_id:
            return [e for e in self._lifecycle_events if e.get("pod_id") == pod_id][:limit]
        return self._lifecycle_events[:limit]

    def record_pod_lifecycle_event(self, **kwargs):
        self.recorded_events.append(kwargs)

    def get_pod_proposals(self, pod_id=None, run_id=None, date_from=None, date_to=None):
        out = self._proposals
        if pod_id:
            out = [p for p in out if p.get("pod_id") == pod_id]
        return out

    def get_latest_paper_snapshot(self, pod_id):
        return self._snapshot

    def get_latest_paper_positions(self, pod_id):
        return []

    def get_paper_snapshot_history(self, pod_id):
        return []

    def get_paper_execution_outcomes(self, pod_id):
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def pods_setup(monkeypatch):
    """Patch pod_config and decision_store at the service-module level."""
    pods = [_make_pod("buffett", "paper"), _make_pod("simons", "live")]
    store = FakeStore()

    monkeypatch.setattr("app.backend.services.pod_service.load_pods", lambda: pods)
    monkeypatch.setattr("app.backend.services.pod_service.load_lifecycle_config", LifecycleConfig)
    monkeypatch.setattr("app.backend.services.pod_service.get_decision_store", lambda: store)

    return {"pods": pods, "store": store}


# ---------------------------------------------------------------------------
# GET /pods
# ---------------------------------------------------------------------------

class TestListPods:
    def test_returns_all_pods(self, client, pods_setup):
        resp = client.get("/pods")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {p["name"] for p in data}
        assert names == {"buffett", "simons"}

    def test_pod_fields_present(self, client, pods_setup):
        resp = client.get("/pods")
        pod = resp.json()[0]
        for field in ("name", "analyst", "enabled", "max_picks", "tier", "schedule",
                       "effective_tier", "days_in_tier", "next_evaluation_date"):
            assert field in pod, f"Missing field: {field}"

    def test_single_pod_failure_does_not_crash_list(self, client, monkeypatch):
        pods = [_make_pod("good"), _make_pod("bad")]
        call_count = {"n": 0}

        def patched_get_lifecycle_status(pod_id, tier, config, store=None):
            call_count["n"] += 1
            if pod_id == "bad":
                raise RuntimeError("corrupt data")
            from src.services.pod_lifecycle import get_lifecycle_status
            return get_lifecycle_status(pod_id, tier, config, store=store)

        store = FakeStore()
        monkeypatch.setattr("app.backend.services.pod_service.load_pods", lambda: pods)
        monkeypatch.setattr("app.backend.services.pod_service.load_lifecycle_config", LifecycleConfig)
        monkeypatch.setattr("app.backend.services.pod_service.get_decision_store", lambda: store)
        monkeypatch.setattr("app.backend.services.pod_service.get_lifecycle_status", patched_get_lifecycle_status)

        resp = client.get("/pods")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        good_pod = next(p for p in data if p["name"] == "good")
        bad_pod = next(p for p in data if p["name"] == "bad")
        assert good_pod["error"] is None
        assert bad_pod["error"] is not None


# ---------------------------------------------------------------------------
# GET /pods/config
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_returns_config(self, client, pods_setup):
        resp = client.get("/pods/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "min_history_days" in data
        assert "evaluation_schedule" in data
        assert "next_evaluation_date" in data
        assert data["evaluation_schedule"] == "weekly-monday"


# ---------------------------------------------------------------------------
# GET /pods/{pod_id}/history
# ---------------------------------------------------------------------------

class TestGetHistory:
    def test_returns_events(self, client, monkeypatch):
        events = [
            {"id": 1, "pod_id": "buffett", "event_type": "manual_promotion",
             "old_tier": "paper", "new_tier": "live", "reason": "test",
             "source": "manual", "metrics_json": None, "created_at": "2026-03-25T10:00:00"},
        ]
        store = FakeStore(lifecycle_events=events)
        monkeypatch.setattr("app.backend.services.pod_service.load_pods",
                            lambda: [_make_pod("buffett")])
        monkeypatch.setattr("app.backend.services.pod_service.get_decision_store", lambda: store)

        resp = client.get("/pods/buffett/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["event_type"] == "manual_promotion"

    def test_404_for_unknown_pod(self, client, pods_setup):
        resp = client.get("/pods/nonexistent/history")
        assert resp.status_code == 404

    def test_rejects_invalid_pod_id(self, client, pods_setup):
        resp = client.get("/pods/../../etc/passwd/history")
        assert resp.status_code in (404, 422)  # Router non-match or Path validation


# ---------------------------------------------------------------------------
# POST /pods/{pod_id}/promote
# ---------------------------------------------------------------------------

class TestPromotePod:
    def test_promotes_paper_to_live(self, client, pods_setup):
        resp = client.post("/pods/buffett/promote")
        assert resp.status_code == 200
        data = resp.json()
        assert "promote" in data["message"].lower() or "live" in data["message"].lower()

        store = pods_setup["store"]
        assert len(store.recorded_events) == 1
        event = store.recorded_events[0]
        assert event["event_type"] == "manual_promotion"
        assert event["old_tier"] == "paper"
        assert event["new_tier"] == "live"
        assert event["source"] == "manual"

    def test_already_at_highest_tier(self, client, pods_setup):
        resp = client.post("/pods/simons/promote")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("changed") is False
        assert pods_setup["store"].recorded_events == []

    def test_404_for_unknown_pod(self, client, pods_setup):
        resp = client.post("/pods/nonexistent/promote")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /pods/{pod_id}/demote
# ---------------------------------------------------------------------------

class TestDemotePod:
    def test_demotes_live_to_paper(self, client, monkeypatch):
        pods = [_make_pod("simons", "paper")]
        events = [{"pod_id": "simons", "event_type": "promotion",
                    "new_tier": "live", "created_at": "2026-03-25T10:00:00"}]
        store = FakeStore(lifecycle_events=events)

        monkeypatch.setattr("app.backend.services.pod_service.load_pods", lambda: pods)
        monkeypatch.setattr("app.backend.services.pod_service.load_lifecycle_config", LifecycleConfig)
        monkeypatch.setattr("app.backend.services.pod_service.get_decision_store", lambda: store)

        resp = client.post("/pods/simons/demote")
        assert resp.status_code == 200

        assert len(store.recorded_events) == 1
        event = store.recorded_events[0]
        assert event["event_type"] == "manual_demotion"
        assert event["old_tier"] == "live"
        assert event["new_tier"] == "paper"

    def test_already_at_lowest_tier(self, client, pods_setup):
        resp = client.post("/pods/buffett/demote")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("changed") is False

    def test_404_for_unknown_pod(self, client, pods_setup):
        resp = client.post("/pods/nonexistent/demote")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /pods/{pod_id}/proposals
# ---------------------------------------------------------------------------

class TestGetProposals:
    def test_returns_latest_proposals(self, client, monkeypatch):
        proposals = [
            {"pod_id": "buffett", "ticker": "AAPL", "target_weight": 0.5,
             "action": "buy", "run_id": "run-1", "created_at": "2026-03-25"},
            {"pod_id": "buffett", "ticker": "MSFT", "target_weight": 0.3,
             "action": "buy", "run_id": "run-1", "created_at": "2026-03-25"},
        ]
        store = FakeStore(proposals=proposals)
        monkeypatch.setattr("app.backend.services.pod_service.load_pods",
                            lambda: [_make_pod("buffett")])
        monkeypatch.setattr("app.backend.services.pod_service.get_decision_store", lambda: store)

        resp = client.get("/pods/buffett/proposals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        tickers = {p["ticker"] for p in data}
        assert tickers == {"AAPL", "MSFT"}

    def test_empty_proposals(self, client, monkeypatch):
        store = FakeStore(proposals=[])
        monkeypatch.setattr("app.backend.services.pod_service.load_pods",
                            lambda: [_make_pod("buffett")])
        monkeypatch.setattr("app.backend.services.pod_service.get_decision_store", lambda: store)

        resp = client.get("/pods/buffett/proposals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_404_for_unknown_pod(self, client, pods_setup):
        resp = client.get("/pods/nonexistent/proposals")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_rejects_path_traversal(self, client, pods_setup):
        resp = client.get("/pods/../../../etc/passwd/history")
        assert resp.status_code in (404, 422)

    def test_rejects_overlong_pod_id(self, client, pods_setup):
        resp = client.get(f"/pods/{'a' * 100}/history")
        assert resp.status_code == 422

    def test_accepts_valid_pod_id(self, client, pods_setup):
        resp = client.get("/pods/buffett-v2_test/history")
        # Should not fail validation (404 is fine since pod doesn't exist)
        assert resp.status_code in (200, 404)
