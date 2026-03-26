---
title: "README drift: six pod-shop features shipped without documentation updates"
category: "integration-issues"
date: "2026-03-26"
tags:
  - documentation-gap
  - readme
  - pods
  - daemon
  - paper-trading
  - lifecycle-automation
  - web-dashboard
  - decision-db
  - onboarding
  - operator-experience
severity: "high"
component: "README.md"
problem_type: "documentation-gap"
---

# README Drift: Six Pod-Shop Features Shipped Without Documentation Updates

## Problem

The AI hedge fund project evolved from a single `hedge rebalance` CLI into a full trading pod shop (18 pods, daemon scheduler, paper trading, lifecycle automation, web dashboard, Decision DB) across sessions 117-124. The README still centered on the original rebalance workflow. The operator said "I have no idea how to even run this."

Six major features were shipped without any README updates:
1. Decision DB (Session 117)
2. Pod Abstraction + EPM Decomposition (Session 118)
3. Paper Trading (Session 119)
4. Daemon Mode (Session 120)
5. Governor Pod Lifecycle (Sessions 122-123)
6. Web UI Pod Dashboard (Session 124)

## Root Cause

Feature development outpaced documentation. The existing workflow (brainstorm -> plan -> implement -> review -> merge) had no gate requiring README updates. Each feature had brainstorm docs, plans, and session logs, but none of those are operator-facing. Multiple LLMs contributed across sessions, and no LLM checked README staleness on session start.

## Investigation Steps

1. Read `PROJECT_SUMMARY.md` and latest session log -- confirmed all six features shipped to main.
2. Searched for existing guides or setup docs (`docs/**/*guide*`, `docs/**/*setup*`) -- none found.
3. Read current `README.md` -- covered rebalance and IBKR but was missing pods, daemon, paper trading, lifecycle, web dashboard, and Decision DB.
4. Checked CLI help: `hedge serve`, `hedge pods status/promote/demote` all existed but had no README coverage.
5. Gathered system details: daemon two-phase cycle, 4 schedule presets, lifecycle thresholds, 11 Decision DB tables, 6 web API pod endpoints.
6. Verified pod config functions -- discovered `load_pod_config` does not exist; correct functions are `load_pods` and `load_lifecycle_config` from `src.config.pod_config`.

## Solution

### 1. Preserve the old README

```bash
cp README.md README_LEGACY.md
```

### 2. Write a pod-first README

New README structure centers on the daemon/pod operating model:

- **Quick Start** -- leads with `hedge serve`, not `hedge rebalance`
- **Concepts** -- pods, tiers (paper/live), lifecycle automation
- **Configuration** -- `pods.yaml` reference (defaults, lifecycle thresholds, schedule presets)
- **CLI Reference** -- all commands including `serve`, `pods status/promote/demote`, `scorecard`
- **Web Dashboard** -- startup commands and 6 API endpoints
- **Testing & Validation** -- 3 progressive tiers
- **Decision DB** -- 11-table reference
- **Legacy CLI** -- pointer to `README_LEGACY.md`

### 3. Progressive testing tiers

Key design decision: structure testing so the operator can validate without IBKR:

| Tier | Requires | What it validates |
| --- | --- | --- |
| Tier 1 (Offline) | Nothing | pytest, config loading, CLI parsing |
| Tier 2 (Paper) | Borsdata + LLM key | Dry-run daemon, single pod cycle, Decision DB |
| Tier 3 (IBKR) | Gateway running | Pipeline check, what-if preview, live execution |

### 4. Caught incorrect function name

The initial validation command used `load_pod_config` which doesn't exist:

```python
# WRONG
from src.config.pod_config import load_pod_config

# CORRECT
from src.config.pod_config import load_pods, load_lifecycle_config
pods = load_pods()
lifecycle = load_lifecycle_config()
```

## Prevention Strategies

### 1. Session Log Instruction Amendment (highest priority, zero cost)

Add to CLAUDE.md "Start Here" block:

> 5. Skim README.md and check whether it reflects current reality. If any documented commands, flags, or features are stale, fix before starting new work.

Add to "When wrapping up a session":

> 4. If this session added or changed any user-facing feature, update README.md before committing.

This activates on every session for every LLM. It alone would have prevented this failure -- any LLM starting session 120 would have noticed README staleness.

### 2. README Update as PR Merge Gate

Add a documentation checklist to the PR workflow:

- [ ] README.md updated with new/changed CLI commands
- [ ] README.md updated with new/changed environment variables
- [ ] README.md updated with new/changed configuration options
- [ ] No user-facing changes (explain why)

### 3. Brainstorm Template "Docs Impact" Field

Add to the brainstorm requirements template:

```markdown
## Documentation Impact
- README sections affected: [list]
- New CLI commands/flags: [list]
- New environment variables: [list]
```

This front-loads documentation planning when feature design is freshest.

## Related Documentation

- `docs/solutions/integration-issues/multi-llm-pod-dashboard-review-gaps.md` -- similar pattern: multi-LLM workflow gaps in review/documentation
- `docs/brainstorms/2026-03-25-ops-readme-rewrite-requirements.md` -- requirements doc for this fix
- `docs/solutions/architecture/monolith-decomposition-pod-abstraction.md` -- pod system architecture
- `docs/solutions/architecture/paper-trading-virtual-execution-engine.md` -- paper trading design with shadow-book rationale
- `docs/brainstorms/2026-03-24-pod-abstraction-requirements.md` -- pod system spec (shipped)
- `docs/brainstorms/2026-03-25-daemon-mode-requirements.md` -- daemon spec (shipped)
- `docs/brainstorms/2026-03-25-governor-pod-lifecycle-requirements.md` -- lifecycle spec (shipped)
