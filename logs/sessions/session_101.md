# Sessions 101-110 (Current)

_This is the active session file. New sessions should be added here._

## Session 101 (`IBKR live cleanup` -- cancel remaining open buy order)
**Date**: 2026-03-18 | **Model**: GPT-5 Codex

- **Action**: Cancelled the remaining live open buy order on account `U22372535`: `RANA` order `1209662283`
- **Result**: The IBKR cancel request returned `Request was submitted`, and a direct status check then showed `order_status: Cancelled` with `0/15` filled
- **Order state review**: `HAS` order `1209662279` was already cancelled by IBKR earlier; the other March 18 rebalance orders checked (`DHT`, `SFL`, `LUG`, `NVEC`, `HOVE`) were already `Filled`
- **Verification**:
  - `poetry run hedge ibkr orders`
  - `poetry run python - <<'PY' ... client.cancel_order('U22372535', '1209662283') ... PY`
  - `poetry run python - <<'PY' ... client.get_order_status('1209662283') ... PY`

## Session 102 (`main` commit requested -- snapshot full local worktree)
**Date**: 2026-03-18 | **Model**: GPT-5 Codex

- **Action**: User requested that the entire current worktree be committed directly onto `main`
- **Scope**: This commit snapshots the accumulated local changes already present in the worktree, including the March 18 IBKR execution/CLI hardening, Swedish-stock skip guard, session log rollover, and the remaining untracked local files currently in the repository root
- **Branch state**: Verified the active branch is `main` before staging

## Session 103 (`hedge rebalance` -- friendly IBKR re-login failure on 401)
**Date**: 2026-03-18 | **Model**: GPT-5 Codex

- **Diagnosis**: The `poetry run hedge rebalance --portfolio-source ibkr --universe portfolios/borsdata_universe.txt --analysts favorites --model gpt-5-nano --ibkr-execute` failure occurred after preview succeeded but before the first live submission; the live gateway now returns `401` from `/iserver` auth endpoints, meaning the IBKR session expired or became unauthenticated during execution
- **Fix**: `src/integrations/ibkr_client.py` now turns IBKR `401` responses into a direct re-login instruction (`Open https://localhost:5001 and log in again, then rerun the command`) instead of surfacing a blank `IBKR API error 401:`
- **Fix**: `src/integrations/ibkr_execution.py` now calls `ensure_authenticated()` immediately before `place_order()` and before reply confirmations, so the execute path aborts cleanly before the first live order call when the `/iserver` session has gone stale
- **Tests**: Added client coverage for the new 401/auth-status message and execution coverage that verifies submission stops before placing an order when authentication has expired
- **Verification**:
  - `poetry run pytest tests/integrations/test_ibkr_client.py tests/integrations/test_ibkr_execution.py`
  - `poetry run python - <<'PY' ... client.get_orders() ... PY` against the live unauthenticated gateway, confirming the new re-login message

## Session 104 (`IBKR contract overrides` -- rebuild Börsdata mappings and purge false positives)
**Date**: 2026-03-19 | **Model**: GPT-5 Codex

- **Diagnosis**: The live IBKR override for `LUG` was wrong (`conid 603525823`, exchange `FWB2`, company `TRIUMPH NEW ENERGY CO LTD-H`) because `scripts/build_ibkr_contract_overrides.py` collapsed duplicate Börsdata tickers by bare symbol and lost the market/company metadata from `portfolios/borsdata_universe.txt`
- **Fix**: `scripts/build_ibkr_contract_overrides.py` now parses universe entries with market/company context, selects the matching Börsdata instrument for duplicate symbols, prefers Nordic exchanges for Nordic universe entries, and rejects lone ISIN hits whose IBKR symbol/company name do not match the Börsdata target
- **Fix**: Added `--refresh-existing` so the override builder can re-resolve the entire universe in place, and when a refreshed ticker becomes ambiguous the script now removes the stale stored override instead of preserving a bad old contract
- **Data refresh**: Rebuilt `data/ibkr_contract_mappings.json` against the live authenticated gateway; `LUG` now resolves to Lundin Gold on `SFB` (`conid 177584482`) and the stale `FWB2` false positives for `BRIGHT`, `GGEO`, `QIIWI`, and `SPOTR` were removed from the override map
- **Coverage**: Clean override coverage is now `190/206` tickers, with `17` unresolved/ambiguous names written to `data/ibkr_contract_candidates.json` for follow-up instead of silently mapping to the wrong company
- **Ambiguous set after refresh**: `ADVT`, `AMH2 B`, `BEYOND`, `BRIGHT`, `BRK.B`, `CLA`, `DB7`, `GGEO`, `GOFORE`, `META`, `NOVU`, `QIIWI`, `RECY B`, `SPLTN`, `SPOTR`, `TCC A`, `VIAFIN`
- **Tests**: Added `tests/scripts/test_build_ibkr_contract_overrides.py` covering universe parsing, duplicate ticker handling, market-aware Börsdata selection, Nordic-preferred `LUG` resolution, and rejection of mismatched single-candidate ISIN hits
- **Verification**:
  - `poetry run python -m py_compile scripts/build_ibkr_contract_overrides.py tests/scripts/test_build_ibkr_contract_overrides.py`
  - `poetry run pytest tests/scripts/test_build_ibkr_contract_overrides.py`
  - `poetry run python scripts/build_ibkr_contract_overrides.py --input <tmp LUG universe> --output <tmp> --report <tmp> --limit 1 --refresh-existing`
  - `PYTHONWARNINGS=ignore poetry run python scripts/build_ibkr_contract_overrides.py --refresh-existing`
  - `poetry run python - <<'PY' ... inspect data/ibkr_contract_mappings.json / data/ibkr_contract_candidates.json ... PY`
