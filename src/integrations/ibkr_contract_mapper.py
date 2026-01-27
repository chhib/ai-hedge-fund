"""Helpers for resolving IBKR contract overrides safely."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

CONTRACT_MAPPING_FILE = Path(__file__).parent.parent.parent / "data" / "ibkr_contract_mappings.json"


@dataclass(slots=True)
class ContractOverride:
    conid: int
    exchange: Optional[str] = None
    currency: Optional[str] = None


def load_contract_overrides() -> Dict[str, ContractOverride]:
    if not CONTRACT_MAPPING_FILE.exists():
        return {}

    try:
        payload = json.loads(CONTRACT_MAPPING_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    overrides: Dict[str, ContractOverride] = {}
    for ticker, details in payload.get("contracts", {}).items():
        if not isinstance(details, dict):
            continue
        conid = details.get("conid")
        if conid is None:
            continue
        try:
            conid_int = int(conid)
        except (TypeError, ValueError):
            continue
        overrides[ticker.upper()] = ContractOverride(
            conid=conid_int,
            exchange=details.get("exchange"),
            currency=details.get("currency"),
        )
    return overrides


__all__ = ["ContractOverride", "load_contract_overrides", "CONTRACT_MAPPING_FILE"]
