"""Pod configuration: dataclass + YAML loader."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "pods.yaml"


@dataclass(slots=True)
class Pod:
    name: str
    analyst: str
    enabled: bool = True
    max_picks: int = 3


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

        pods.append(Pod(
            name=name,
            analyst=analyst,
            enabled=entry.get("enabled", default_enabled),
            max_picks=entry.get("max_picks", default_max_picks),
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
