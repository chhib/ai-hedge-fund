---
title: "Pod Dashboard: Multi-category defects from unreviewed cross-LLM handoff"
category: integration-issues
date: 2026-03-25
tags:
  - cross-llm-handoff
  - fastapi
  - react
  - code-review
  - async-sync-mismatch
  - event-type-contract
  - input-validation
  - error-isolation
  - service-layer-extraction
modules:
  - app/backend/routes/pods.py
  - app/backend/services/pod_service.py
  - app/backend/models/schemas.py
  - app/frontend/src/components/pods/PodsDashboard.tsx
  - app/frontend/src/services/pods-api.ts
  - app/frontend/src/types/pod.ts
severity: critical
symptoms:
  - Build/runtime error from missing Shield import in PodsDashboard.tsx
  - Policy dialog never opens due to missing DialogTrigger
  - Event loop blocked by sync I/O in async def FastAPI endpoints
  - Audit trail corrupted by event type mismatch between API and CLI
  - No confirmation before promote/demote actions controlling real capital
  - Single pod failure crashes entire list endpoint
  - Verbose exception details leaked in 500 responses
  - No input validation on pod_id path parameter
root_cause_summary: "Unreviewed cross-LLM handoff shipped broken imports, dead UI bindings, sync-in-async blocking, and CLI/API event-type contract drift"
---

# Pod Dashboard: Multi-category defects from unreviewed cross-LLM handoff

## Problem

Gemini CLI implemented a full-stack Web UI Pod Dashboard (FastAPI backend + React frontend) for the AI hedge fund. The agent session was stopped before any review or verification ran. When Claude Opus 4.6 picked up the uncommitted work and ran an 8-agent code review, 14 bugs and architectural issues were found spanning build errors, dead UI, event-loop blocking, audit trail corruption, missing safety gates, and type safety violations.

**Symptoms observed:**
- `Shield` used but never imported -- build/runtime failure
- Policy `<Dialog>` had no `<DialogTrigger>` -- dead UI that could never open
- All 5 FastAPI endpoints declared `async def` but called synchronous YAML reads and SQLite queries -- blocks the event loop under concurrent load
- API recorded `event_type="promotion"` while CLI used `"manual_promotion"` -- corrupts the audit trail and may cause the effective-tier resolver to compute different tiers
- Single click deploys real capital with no confirmation dialog
- One pod's corrupted lifecycle data crashes the entire `/pods` list endpoint
- `str(e)` in HTTP 500 responses leaks file paths, DB schemas, and Python internals

## Root Cause

Multi-LLM workflow gap: Gemini CLI implemented the feature rapidly without full knowledge of codebase conventions -- specifically the service layer pattern (`app/backend/services/`), CLI event type schema (`manual_promotion`/`manual_demotion` in `src/cli/hedge.py:_record_manual_pod_transition()`), and async/sync correctness in FastAPI. No code review or verification step ran before the session ended, leaving all defects undetected.

## Investigation

An 8-agent parallel code review analyzed all files in PR #12:

| Agent | Key findings |
|---|---|
| **kieran-python-reviewer** | async endpoints blocking event loop, no service layer, hardcoded tiers, exception leakage |
| **kieran-typescript-reviewer** | missing Shield import, broken DialogTrigger, `catch(error: any)`, unused imports, `[key: string]: any` |
| **security-sentinel** | no input validation on pod_id, stack traces in 500 responses, no CSRF, no confirmation for capital-deploying actions |
| **performance-oracle** | N+1 query pattern (90 queries for 18 pods), no caching, full re-fetch on promote/demote |
| **architecture-strategist** | business logic in route handlers violates service layer pattern, promote/demote logic diverges from CLI |
| **agent-native-reviewer** | event type mismatch (`promotion` vs `manual_promotion`), missing proposals endpoint, API returns less data than CLI |
| **learnings-researcher** | Passive Observer Pattern (per-pod error isolation), Shadow Book Continuity (live pods keep paper metrics), event type schema from lifecycle plan |
| **code-simplicity-reviewer** | duplicated promote/demote code, duplicated grid rendering, broken Policy dialog is dead code |

## Solution

### 1. Async to sync (event loop blocking)

Changed all route handlers from `async def` to `def`. FastAPI runs `def` endpoints in a threadpool automatically, while `async def` endpoints that call blocking I/O starve the event loop.

### 2. Service layer extraction

Created `app/backend/services/pod_service.py` with dedicated functions. Route handlers became thin wrappers:

```python
# Route (thin)
@router.get("", response_model=list[PodResponse])
def list_pods():
    try:
        return list_pods_with_status()
    except Exception:
        logger.exception("Failed to list pods")
        raise HTTPException(status_code=500, detail="Failed to load pods")
```

### 3. Event type alignment with CLI

```python
# Before (mismatched)
event_type="promotion"    # API
event_type="manual_promotion"  # CLI

# After (aligned)
event_type="manual_promotion"   # Both API and CLI
event_type="manual_demotion"    # Both API and CLI
```

### 4. Tier ladder computation

Replaced hardcoded `new_tier="live"` / `new_tier="paper"` with a ladder lookup:

```python
TIER_LADDER = ["paper", "live"]
idx = TIER_LADDER.index(old_tier)
new_tier = TIER_LADDER[idx + 1]  # promote
new_tier = TIER_LADDER[idx - 1]  # demote
```

### 5. Per-pod error isolation (Passive Observer Pattern)

```python
for pod in pods:
    try:
        status = get_lifecycle_status(...)
        evaluation = evaluate_pod_lifecycle(...)
        results.append({...pod_data..., "error": None})
    except Exception:
        logger.exception("Failed to load pod %s", pod.name)
        results.append({...fallback_data..., "error": "Failed to load lifecycle data"})
```

### 6. Frontend fixes

- Added `Shield` to lucide-react import
- Wrapped Policy button in `<DialogTrigger asChild>`
- Added confirmation `<Dialog>` with state `confirmAction: { podId, action }` before promote/demote
- Replaced `catch (error: any)` with `error instanceof Error` pattern
- Removed `[key: string]: any` index signature from PodMetrics
- Added `encodeURIComponent(podId)` in URL paths
- Used `config.evaluation_schedule` instead of hardcoded "Weekly Monday"

### 7. Input validation and generic errors

```python
POD_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"

@router.get("/{pod_id}/history")
def get_history(pod_id: str = Path(..., pattern=POD_ID_PATTERN)):
    ...

except Exception:
    logger.exception("Failed to list pods")
    raise HTTPException(status_code=500, detail="Failed to load pods")  # generic, not str(e)
```

### 8. Tests

19 tests in `tests/backend/test_pods_routes.py` covering all 6 endpoints, per-pod error isolation, input validation, path traversal rejection, tier no-ops, 404s, and event type correctness.

## Prevention Strategies

### For multi-LLM workflows

1. **Canonical patterns in CLAUDE.md**: Add a "Canonical Patterns" section covering service layer, event types, async/sync rules, error handling, and TypeScript strictness. All LLM agents (Claude, Gemini, Codex) should be configured to read this before writing code.

2. **Verification policy update**: Add `npx tsc --noEmit` for frontend code and `python -c "from module import router"` for backend code to the existing verification policy.

3. **Diff audit on handoff**: When one LLM picks up after another, run `git diff main` and compare each new file's structure against the closest existing equivalent before writing more code.

### For new resource endpoints

**Backend checklist:**
- [ ] Endpoints use `def` (not `async def`) unless all I/O is genuinely async
- [ ] All imports verified with import check
- [ ] Path parameters validated (regex or allow-list)
- [ ] Error responses generic; full errors logged server-side
- [ ] Event types match the canonical CLI enum
- [ ] Business logic in service layer, not route handlers

**Frontend checklist:**
- [ ] TypeScript interfaces explicit; no `any` or index signatures
- [ ] `catch (error: unknown)` with `instanceof Error` guard
- [ ] Destructive actions require confirmation dialog
- [ ] List views isolate per-item rendering errors
- [ ] All dialogs have a trigger or programmatic open-state binding
- [ ] `tsc --noEmit` clean

### Anti-patterns to ban

| Anti-pattern | Replacement |
|---|---|
| `async def` with synchronous I/O | `def` endpoint (FastAPI threadpool) |
| `catch (error: any)` | `catch (error: unknown)` + instanceof guard |
| `[key: string]: any` | Explicit fields; `Record<string, unknown>` only for dynamic data |
| `raise HTTPException(detail=str(e))` | Generic message + `logger.exception()` |
| `<Dialog>` without `<DialogTrigger>` | Always pair or wire programmatic open state |

## Related Documentation

- `docs/solutions/architecture/monolith-decomposition-pod-abstraction.md` -- Pod dataclass, Passive Observer Pattern, `dict.update()` ban
- `docs/solutions/architecture/paper-trading-virtual-execution-engine.md` -- Shadow book continuity (live pods keep paper metrics)
- `docs/brainstorms/2026-03-25-governor-pod-lifecycle-requirements.md` -- R5 event type definitions
- `docs/plans/2026-03-25-003-feat-governor-pod-lifecycle-automation-plan.md` -- Lifecycle events schema, CLI promote/demote
- `docs/brainstorms/2026-03-24-decision-db-requirements.md` -- R1 append-only constraint, R9 passive observer pattern
