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
