from click.testing import CliRunner

from src.cli.hedge import cli


def test_pods_help_shows_subcommands():
    runner = CliRunner()
    result = runner.invoke(cli, ["pods", "--help"])
    assert result.exit_code == 0
    assert "promote" in result.output
    assert "demote" in result.output
    assert "status" in result.output


def test_pods_promote_records_manual_event(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.calls = []

        def get_latest_pod_lifecycle_event(self, pod_id):
            return None

        def record_pod_lifecycle_event(self, **kwargs):
            self.calls.append(kwargs)

    store = FakeStore()

    class Pod:
        def __init__(self, name, analyst, tier):
            self.name = name
            self.analyst = analyst
            self.tier = tier

    monkeypatch.setattr("src.config.pod_config.load_pods", lambda: [Pod("buffett", "warren_buffett", "paper")])
    monkeypatch.setattr("src.data.decision_store.get_decision_store", lambda: store)

    runner = CliRunner()
    result = runner.invoke(cli, ["pods", "promote", "buffett"])

    assert result.exit_code == 0
    assert "buffett: paper -> live" in result.output
    assert store.calls[0]["event_type"] == "manual_promotion"


def test_pods_status_shows_effective_tier(monkeypatch):
    class FakeStore:
        def get_pod_proposals(self, pod_id=None):
            return []

        def get_latest_pod_lifecycle_event(self, pod_id):
            return {"event_type": "promotion", "new_tier": "live", "created_at": "2026-03-25T10:00:00"}

        def get_latest_paper_snapshot(self, pod_id):
            return None

        def get_latest_paper_positions(self, pod_id):
            return []

        def get_paper_snapshot_history(self, pod_id):
            return []

        def get_paper_execution_outcomes(self, pod_id):
            return []

    class Pod:
        def __init__(self, name, analyst, tier, enabled=True):
            self.name = name
            self.analyst = analyst
            self.tier = tier
            self.enabled = enabled

    monkeypatch.setattr("src.config.pod_config.load_pods", lambda: [Pod("buffett", "warren_buffett", "paper")])
    monkeypatch.setattr("src.config.pod_config.load_lifecycle_config", lambda: __import__("src.config.pod_config", fromlist=["LifecycleConfig"]).LifecycleConfig())
    monkeypatch.setattr("src.data.decision_store.get_decision_store", lambda: FakeStore())

    runner = CliRunner()
    result = runner.invoke(cli, ["pods"])

    assert result.exit_code == 0
    assert "buffett" in result.output
    assert "live" in result.output
    assert "promotion 2026-03-25" in result.output
