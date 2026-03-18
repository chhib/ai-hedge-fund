# Sessions 91-100 (Current)

_This is the active session file. New sessions should be added here._

## Session 91 (`hedge scorecard` -- Analyst Performance Attribution)
**Date**: 2026-03-15 | **Model**: Claude Opus 4.6

- **Feature**: `hedge scorecard` CLI command -- evaluates analyst prediction accuracy against actual price outcomes
- **Feature**: `src/analytics/scorecard.py` -- scoring engine with Bayesian credibility, directional hit rate, avg alpha, conviction rate
- **Scoring**: Bayesian shrinkage (prior: 50% accuracy, strength 20) prevents small samples from producing extreme credibility scores; credibility range 0.2-2.0
- **Data**: Loads all 12,654 cached signals from `prefetch_cache.db`, fetches prices from Borsdata, computes forward returns over configurable horizon
- **CLI**: `--horizon` (default 7 trading days), `--analyst` (single analyst filter), `--verbose` (per-analyst breakdown), color-coded credibility
- **Results**: Stanley Druckenmiller leads (61.1% hit rate, 1.22 cred), News Sentiment worst (43.4%, 0.87 cred), Jim Simons all-neutral (0% conviction)
- **Pre-step**: Committed `hedge ibkr reconcile` feature (15 tests) as separate commit
- **Tests**: 16/16 scorecard tests + 171/171 full suite
- **Files changed**: `src/analytics/__init__.py` (new), `src/analytics/scorecard.py` (new), `src/cli/hedge.py`, `tests/analytics/__init__.py` (new), `tests/analytics/test_scorecard.py` (new)

## Session 92 (`adaptive portfolio governor` -- Preservation-first autonomous capital control)
**Date**: 2026-03-15 | **Model**: GPT-5 Codex

- **Feature**: `src/services/portfolio_governor.py` -- preservation-first governor with analyst weighting, deployment throttling, trade gating, and SQLite snapshot history in `data/governor_history.db`
- **Feature**: `src/analytics/scorecard.py` now exposes regime-aware scorecard helpers so the governor can reuse analyst credibility and alpha by regime instead of scraping CLI output
- **Rebalance**: `hedge rebalance --use-governor` applies governor-adjusted analyst weights, ticker penalties, deployment scaling, and buy blocking before CSV/IBKR handoff
- **Backtest**: `hedge backtest --use-governor` now intercepts normalized decisions before execution so the governor can block or scale risk-increasing trades without changing the agent contract
- **CLI**: Added `hedge governor status` and `hedge governor status --latest`; rebalance/backtest help now exposes governor flags
- **Output**: Rebalance console output now prints a compact governor summary with regime, deployment, cash buffer, benchmark drawdown, and reasons
- **Tests**: Added governor unit tests, scorecard regime tests, enhanced portfolio manager integration test, and backtesting engine governor test
- **Verification**:
  - `poetry run python -m compileall src tests`
  - `poetry run pytest tests/services/test_portfolio_governor.py tests/analytics/test_scorecard.py tests/test_enhanced_portfolio_manager.py tests/backtesting/test_engine_governor.py`
  - `poetry run hedge rebalance --help`
  - `poetry run hedge governor status --help`
  - `poetry run hedge backtest --help`
  - `poetry run hedge governor status --analysts fundamentals`
  - `poetry run hedge rebalance --portfolio example_portfolio.csv --universe-tickers TTWO --test --dry-run --max-workers 1 --use-governor`
  - `poetry run pytest`
- **Live verification notes**: The dry-run rebalance completed and printed governor state. Existing non-Börsdata holdings in `example_portfolio.csv` still emit the pre-existing AAPL/FDEV lookup warnings; the new governor path remained functional.
- **Files changed**: `src/services/portfolio_governor.py` (new), `src/analytics/scorecard.py`, `src/agents/enhanced_portfolio_manager.py`, `src/services/portfolio_runner.py`, `src/cli/hedge.py`, `src/backtesting/engine.py`, `src/utils/output_formatter.py`, `src/services/__init__.py`, `tests/services/test_portfolio_governor.py` (new), `tests/backtesting/test_engine_governor.py` (new), `tests/analytics/test_scorecard.py`, `tests/test_enhanced_portfolio_manager.py`

## Session 93 (`merge adaptive governor to main`)
**Date**: 2026-03-18 | **Model**: GPT-5 Codex

- **Action**: Merged PR #5 (`feat: add preservation-first adaptive portfolio governor`) into `main`
- **Merge commit**: `97b2f6f8f3d776e1f792f63255d1a99725173ba6`
- **Branch status**: `origin/main` now contains the governor service, rebalance/backtest integration, CLI surfaces, and tests from session 92
- **Notes**: Merge was performed without touching unrelated local worktree changes (`AGENTS.md` and existing untracked files remained outside the merge flow)
