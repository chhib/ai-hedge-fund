"""Helpers for resolving IBKR contract overrides safely."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

CONTRACT_MAPPING_FILE = Path(__file__).parent.parent.parent / "data" / "ibkr_contract_mappings.json"


@dataclass(slots=True)
class ContractOverride:
    conid: int
    exchange: Optional[str] = None
    currency: Optional[str] = None
    description: Optional[str] = None


@dataclass(slots=True)
class ValidationResult:
    ticker: str
    conid: int
    status: str  # "valid", "invalid", "exchange_changed", "error"
    stored_exchange: Optional[str] = None
    live_exchange: Optional[str] = None
    stored_description: Optional[str] = None
    live_description: Optional[str] = None
    error: Optional[str] = None


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
            description=details.get("description"),
        )
    return overrides


def validate_contract(client, ticker: str, override: ContractOverride) -> ValidationResult:
    """Validate a single contract override against the live IBKR gateway."""
    from src.integrations.ibkr_client import IBKRError

    try:
        info = client.get_contract_info(override.conid)
    except IBKRError as exc:
        return ValidationResult(
            ticker=ticker,
            conid=override.conid,
            status="invalid",
            stored_exchange=override.exchange,
            stored_description=override.description,
            error=str(exc),
        )
    except Exception as exc:
        return ValidationResult(
            ticker=ticker,
            conid=override.conid,
            status="error",
            stored_exchange=override.exchange,
            stored_description=override.description,
            error=str(exc),
        )

    if not info or not isinstance(info, dict):
        return ValidationResult(
            ticker=ticker,
            conid=override.conid,
            status="invalid",
            stored_exchange=override.exchange,
            stored_description=override.description,
            error="empty response from gateway",
        )

    live_exchange = info.get("exchange") or info.get("listing_exchange")
    live_description = info.get("company_name") or info.get("con_desc")

    if override.exchange and live_exchange and override.exchange.upper() != live_exchange.upper():
        return ValidationResult(
            ticker=ticker,
            conid=override.conid,
            status="exchange_changed",
            stored_exchange=override.exchange,
            live_exchange=live_exchange,
            stored_description=override.description,
            live_description=live_description,
        )

    return ValidationResult(
        ticker=ticker,
        conid=override.conid,
        status="valid",
        stored_exchange=override.exchange,
        live_exchange=live_exchange,
        stored_description=override.description,
        live_description=live_description,
    )


def validate_all_contracts(
    client,
    overrides: Dict[str, ContractOverride],
    delay: float = 0.15,
    progress_cb: Optional[Callable[[str, ValidationResult], None]] = None,
) -> List[ValidationResult]:
    """Validate all contract overrides, sleeping between calls."""
    results: List[ValidationResult] = []
    for i, (ticker, override) in enumerate(overrides.items()):
        if i > 0:
            time.sleep(delay)
        result = validate_contract(client, ticker, override)
        results.append(result)
        if progress_cb:
            progress_cb(ticker, result)
    return results


def save_contract_overrides(overrides: Dict[str, ContractOverride]) -> None:
    """Write contract overrides back to the mappings file."""
    contracts: Dict[str, dict] = {}
    for ticker, ov in sorted(overrides.items()):
        contracts[ticker] = {
            "conid": ov.conid,
            "currency": ov.currency,
            "description": ov.description,
            "exchange": ov.exchange,
        }
    payload = {"contracts": contracts}
    CONTRACT_MAPPING_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


__all__ = [
    "ContractOverride",
    "ValidationResult",
    "load_contract_overrides",
    "save_contract_overrides",
    "validate_contract",
    "validate_all_contracts",
    "CONTRACT_MAPPING_FILE",
]
