---
date: 2026-03-25
topic: ops-readme-rewrite
---

# Operations README Rewrite

## Problem Frame

The system has grown from a single rebalance CLI into a full pod shop (18 pods, daemon scheduler, paper trading, lifecycle automation, web dashboard), but the README still centers on the original `hedge rebalance` workflow. The operator cannot figure out how to run, test, or validate the pod system from existing documentation alone.

## Requirements

- R1. Move the current `README.md` to `README_LEGACY.md` to preserve the original reference.
- R2. Write a new `README.md` that leads with the pod/daemon operating model as the primary workflow. Structure: quick start (daemon), then pods, then paper trading, then lifecycle, then web dashboard, then IBKR, then legacy CLI.
- R3. Include a backwards compatibility section that explains the old `hedge rebalance` workflow still works and points to `README_LEGACY.md` for full details.
- R4. Include a "Testing & Validation" section structured in progressive tiers:
  - Tier 1 (Offline): `poetry run pytest`, pod config validation, dry-run daemon
  - Tier 2 (Paper): `hedge serve --dry-run`, `hedge pods status`, paper trading verification
  - Tier 3 (IBKR): Gateway setup, `hedge ibkr check`, what-if preview, live execution -- clearly marked as "when gateway is available"
- R5. Document all CLI commands including the newer ones missing from the current README: `hedge pods status`, `hedge pods promote`, `hedge pods demote`, `hedge serve`, plus the web UI startup.
- R6. Include configuration reference for `config/pods.yaml` (pod definitions, lifecycle thresholds, schedule presets).
- R7. Document the Decision DB (`data/decisions.db`) as the audit trail / source of truth.

## Success Criteria

- A new operator can start the daemon in dry-run mode and see pod proposals within 10 minutes of reading the README.
- Testing steps in Tier 1 and Tier 2 are executable without IBKR gateway.
- All `hedge` subcommands are documented with at least a one-liner and key flags.

## Scope Boundaries

- NOT rewriting legacy code or changing CLI behavior -- documentation only
- NOT adding new tests -- documenting how to run existing ones
- NOT a full ops runbook with alerting/monitoring -- that's future work

## Key Decisions

- **Pod-first README**: The daemon/pod system is the intended operating model going forward. The old rebalance CLI is backwards compatibility, not the lead.
- **Progressive testing tiers**: Lets the operator validate incrementally without needing IBKR up front.

## Next Steps

-> `/ce:plan` for structured implementation planning, or proceed directly to work (this is documentation-only, no code changes beyond renaming a file).
