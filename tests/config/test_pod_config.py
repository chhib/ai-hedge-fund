"""Tests for pod configuration: tier and starting_capital fields."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from src.config.pod_config import Pod, load_pods, resolve_pods, VALID_TIERS


MOCK_ANALYST_CONFIG = {
    "warren_buffett": {"display_name": "Warren Buffett"},
    "fundamentals_analyst": {"display_name": "Fundamentals"},
    "technical_analyst": {"display_name": "Technical"},
}


@pytest.fixture
def tmp_pods_yaml(tmp_path):
    """Write a YAML file and return its path."""
    def _write(content: dict) -> Path:
        p = tmp_path / "pods.yaml"
        p.write_text(yaml.dump(content))
        return p
    return _write


@patch("src.utils.analysts.ANALYST_CONFIG", MOCK_ANALYST_CONFIG)
class TestPodTierConfig:

    def test_default_tier_is_paper(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "pods": [{"name": "buffett", "analyst": "warren_buffett"}],
        })
        pods = load_pods(path)
        assert pods[0].tier == "paper"

    def test_explicit_tier_live(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "pods": [{"name": "buffett", "analyst": "warren_buffett", "tier": "live"}],
        })
        pods = load_pods(path)
        assert pods[0].tier == "live"

    def test_defaults_section_tier(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "defaults": {"tier": "live"},
            "pods": [{"name": "buffett", "analyst": "warren_buffett"}],
        })
        pods = load_pods(path)
        assert pods[0].tier == "live"

    def test_pod_overrides_default_tier(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "defaults": {"tier": "live"},
            "pods": [{"name": "buffett", "analyst": "warren_buffett", "tier": "paper"}],
        })
        pods = load_pods(path)
        assert pods[0].tier == "paper"

    def test_invalid_tier_raises(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "pods": [{"name": "buffett", "analyst": "warren_buffett", "tier": "invalid"}],
        })
        with pytest.raises(ValueError, match="invalid tier"):
            load_pods(path)

    def test_default_starting_capital_none(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "pods": [{"name": "buffett", "analyst": "warren_buffett"}],
        })
        pods = load_pods(path)
        assert pods[0].starting_capital is None

    def test_defaults_section_starting_capital(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "defaults": {"starting_capital": 200000},
            "pods": [{"name": "buffett", "analyst": "warren_buffett"}],
        })
        pods = load_pods(path)
        assert pods[0].starting_capital == 200000

    def test_pod_overrides_default_starting_capital(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "defaults": {"starting_capital": 100000},
            "pods": [{"name": "buffett", "analyst": "warren_buffett", "starting_capital": 500000}],
        })
        pods = load_pods(path)
        assert pods[0].starting_capital == 500000

    def test_resolve_pods_carries_tier(self, tmp_pods_yaml):
        path = tmp_pods_yaml({
            "defaults": {"tier": "paper"},
            "pods": [
                {"name": "buffett", "analyst": "warren_buffett", "tier": "live"},
                {"name": "fundamentals", "analyst": "fundamentals_analyst"},
            ],
        })
        pods = resolve_pods("all", config_path=path)
        tiers = {p.name: p.tier for p in pods}
        assert tiers["buffett"] == "live"
        assert tiers["fundamentals"] == "paper"


def test_real_pods_yaml_loads():
    """Verify the actual config/pods.yaml loads without error (uses real ANALYST_CONFIG)."""
    pods = load_pods()
    assert len(pods) > 0
    for pod in pods:
        assert pod.tier in VALID_TIERS
