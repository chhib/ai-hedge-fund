from datetime import date
from pathlib import Path

from src.config.pod_config import LifecycleConfig
from src.data.decision_store import DecisionStore
from src.services.pod_lifecycle import evaluate_pod_lifecycle, get_lifecycle_status, resolve_effective_tier


def test_resolve_effective_tier_defaults_to_configured(tmp_path: Path):
    store = DecisionStore(db_path=tmp_path / "test.db")
    assert resolve_effective_tier("buffett", "paper", store=store) == "paper"


def test_resolve_effective_tier_uses_latest_event(tmp_path: Path):
    store = DecisionStore(db_path=tmp_path / "test.db")
    store.record_pod_lifecycle_event(
        pod_id="buffett",
        event_type="promotion",
        old_tier="paper",
        new_tier="live",
        reason="Weekly promotion gate passed",
        source="weekly_evaluation",
    )
    assert resolve_effective_tier("buffett", "paper", store=store) == "live"


def test_get_lifecycle_status_reports_days_and_next_eval(tmp_path: Path):
    store = DecisionStore(db_path=tmp_path / "test.db")
    store.record_pod_lifecycle_event(
        pod_id="buffett",
        event_type="manual_demotion",
        old_tier="live",
        new_tier="paper",
        reason="Operator override",
        source="manual",
    )
    status = get_lifecycle_status(
        "buffett",
        "live",
        LifecycleConfig(),
        store=store,
        today=date(2026, 3, 25),
    )
    assert status.effective_tier == "paper"
    assert status.days_in_tier >= 0
    assert status.next_evaluation_date == date(2026, 3, 30)


def test_evaluate_pod_lifecycle_promotion_and_drawdown(tmp_path: Path):
    store = DecisionStore(db_path=tmp_path / "test.db")
    for idx, value in enumerate([100000, 101000, 102000, 103000, 104000]):
        store.record_paper_snapshot(
            "buffett",
            f"run-{idx}",
            {
                "total_value": value,
                "cash": value * 0.1,
                "positions_value": value * 0.9,
                "cumulative_return_pct": ((value - 100000) / 100000) * 100,
                "starting_capital": 100000.0,
            },
        )

    config = LifecycleConfig(min_history_days=1)
    evaluation = evaluate_pod_lifecycle("buffett", "paper", config, store=store)
    assert evaluation.eligible_for_promotion is True
    assert evaluation.should_drawdown_stop is False


def test_evaluate_pod_lifecycle_hard_stop_for_live_pod(tmp_path: Path):
    store = DecisionStore(db_path=tmp_path / "test.db")
    for idx, value in enumerate([100000, 110000, 90000]):
        store.record_paper_snapshot(
            "buffett",
            f"run-{idx}",
            {
                "total_value": value,
                "cash": value * 0.1,
                "positions_value": value * 0.9,
                "cumulative_return_pct": ((value - 100000) / 100000) * 100,
                "starting_capital": 100000.0,
            },
        )

    config = LifecycleConfig(min_history_days=1, hard_stop_drawdown_pct=10.0)
    evaluation = evaluate_pod_lifecycle("buffett", "live", config, store=store)
    assert evaluation.should_drawdown_stop is True
