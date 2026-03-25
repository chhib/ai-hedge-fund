"""Pod configuration: dataclass + YAML loader."""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "pods.yaml"


VALID_TIERS = {"paper", "live"}
VALID_EVALUATION_SCHEDULES = {"weekly-monday"}


@dataclass(slots=True)
class LifecycleConfig:
    min_history_days: int = 30
    promotion_sharpe: float = 0.5
    promotion_return_pct: float = 0.0
    promotion_drawdown_pct: float = 10.0
    maintenance_sharpe: float = 0.0
    hard_stop_drawdown_pct: float = 10.0
    evaluation_schedule: str = "weekly-monday"

    def next_evaluation_date(self, today: Optional[date] = None) -> date:
        """Return the next scheduled evaluation date."""
        today = today or date.today()
        if self.evaluation_schedule != "weekly-monday":
            raise ValueError(f"Unsupported evaluation schedule: {self.evaluation_schedule}")

        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return today + timedelta(days=days_until_monday)


@dataclass(slots=True)
class Pod:
    name: str
    analyst: str
    enabled: bool = True
    max_picks: int = 3
    tier: str = "paper"
    starting_capital: float | None = None
    schedule: str = "nordic-morning"


def load_lifecycle_config(config_path: Optional[Path] = None) -> LifecycleConfig:
    """Load lifecycle policy from pods.yaml.

    The lifecycle section is optional; missing values fall back to defaults.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    lifecycle = raw.get("lifecycle", {})

    config = LifecycleConfig(
        min_history_days=int(lifecycle.get("min_history_days", 30)),
        promotion_sharpe=float(lifecycle.get("promotion_sharpe", 0.5)),
        promotion_return_pct=float(lifecycle.get("promotion_return_pct", 0.0)),
        promotion_drawdown_pct=float(lifecycle.get("promotion_drawdown_pct", 10.0)),
        maintenance_sharpe=float(lifecycle.get("maintenance_sharpe", 0.0)),
        hard_stop_drawdown_pct=float(lifecycle.get("hard_stop_drawdown_pct", 10.0)),
        evaluation_schedule=str(lifecycle.get("evaluation_schedule", "weekly-monday")),
    )

    if config.min_history_days <= 0:
        raise ValueError("Lifecycle config min_history_days must be > 0")
    if config.promotion_drawdown_pct <= 0 or config.hard_stop_drawdown_pct <= 0:
        raise ValueError("Lifecycle config drawdown thresholds must be > 0")
    if config.evaluation_schedule not in VALID_EVALUATION_SCHEDULES:
        raise ValueError(
            f"Lifecycle config evaluation_schedule '{config.evaluation_schedule}' is invalid. "
            f"Must be one of: {sorted(VALID_EVALUATION_SCHEDULES)}"
        )

    return config


def load_pods(config_path: Optional[Path] = None) -> List[Pod]:
    """Load pod definitions from a YAML config file.

    Validates that each pod references a known analyst from ANALYST_CONFIG.
    Raises on YAML syntax errors or unknown analyst keys.
    """
    from src.utils.analysts import ANALYST_CONFIG

    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or "pods" not in raw:
        raise ValueError(f"pods.yaml at {path} must contain a 'pods' key")

    defaults = raw.get("defaults", {})
    default_enabled = defaults.get("enabled", True)
    default_max_picks = defaults.get("max_picks", 3)
    default_tier = defaults.get("tier", "paper")
    default_starting_capital = defaults.get("starting_capital", None)
    default_schedule = defaults.get("schedule", "nordic-morning")

    pods: List[Pod] = []
    seen_names: set[str] = set()

    for entry in raw["pods"]:
        name = entry.get("name")
        analyst = entry.get("analyst")

        if not name or not analyst:
            raise ValueError(f"Each pod must have 'name' and 'analyst' fields: {entry}")

        if name in seen_names:
            raise ValueError(f"Duplicate pod name: {name}")
        seen_names.add(name)

        if analyst not in ANALYST_CONFIG:
            raise ValueError(f"Pod '{name}' references unknown analyst '{analyst}'. Available: {sorted(ANALYST_CONFIG.keys())}")

        tier = entry.get("tier", default_tier)
        if tier not in VALID_TIERS:
            raise ValueError(f"Pod '{name}' has invalid tier '{tier}'. Must be one of: {sorted(VALID_TIERS)}")

        pods.append(Pod(
            name=name,
            analyst=analyst,
            enabled=entry.get("enabled", default_enabled),
            max_picks=entry.get("max_picks", default_max_picks),
            tier=tier,
            starting_capital=entry.get("starting_capital", default_starting_capital),
            schedule=entry.get("schedule", default_schedule),
        ))

    return pods


def resolve_pods(selection: str, config_path: Optional[Path] = None) -> List[Pod]:
    """Resolve pod selection string to a list of Pod objects.

    selection: "all" | comma-separated pod names | single pod name
    """
    all_pods = load_pods(config_path)

    if selection.strip().lower() == "all":
        return [p for p in all_pods if p.enabled]

    requested = {s.strip() for s in selection.split(",")}
    pod_map = {p.name: p for p in all_pods}

    resolved = []
    for name in requested:
        if name not in pod_map:
            raise ValueError(f"Unknown pod '{name}'. Available: {sorted(pod_map.keys())}")
        resolved.append(pod_map[name])

    return resolved
