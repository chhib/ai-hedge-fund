# Performance Profiling Reports

This directory contains performance analysis and optimization reports for the AI hedge fund system.

## Reports

### [Lazy Loading Implementation](./lazy_loading_implementation.md)
**Date:** 2025-10-01
**Impact:** 68% startup time improvement (3.43s → 1.10s)

Documents the implementation of lazy agent loading that eliminated 2.3s of unnecessary imports at startup. Agents are now only loaded when selected, providing dramatic performance improvements for users who only need 2-3 analysts.

**Key Achievement:** 749x faster config loading, backward compatible, zero breaking changes.

### [Analyst Function Profiling](./analyst_profiling_report.md)
**Date:** 2025-10-01
**Focus:** Jim Simons and Stanley Druckenmiller agents

Detailed cProfile analysis of CPU-heavy analyst functions identifying specific bottlenecks:
- Stanley Druckenmiller's `analyze_risk_reward` using slow `statistics.pstdev` (Priority 1 fix)
- High `getattr` overhead from Pydantic model access
- Numpy correlation/covariance calculations in statistical pattern analysis

**Impact:** Provides actionable optimization targets with specific line numbers and code examples.

### [Comprehensive Agent Profiling](./comprehensive_profiling_report.md)
**Date:** 2025-10-01
**Coverage:** All 17 analyst agents end-to-end

Complete system profiling including data fetching, computation, and LLM calls:
- Identified and fixed 3 agents with AttributeError crashes
- Documented LLM cache effectiveness (1,000x-15,000x speedup on cache hits)
- Profiled startup time breakdown (77% imports, 23% cache population)
- Categorized agents by performance (15 fast, 2 slow)

**Key Finding:** Warren Buffett agent (18.4s) needs optimization; most agents are sub-second with cache.

## Profiling Scripts

The following reusable profiling scripts are available in `scripts/`:

- **`profile_all_agents.py`** - Profile all 17 agents end-to-end with real data
- **`profile_analysts.py`** - Function-level profiling for Jim Simons and Stanley Druckenmiller
- **`profile_startup_time.py`** - Detailed startup and import time analysis

### Running Profiling

```bash
# Profile all agents with real Börsdata data
poetry run python scripts/profile_all_agents.py

# Profile individual analyst functions (CPU hotspots)
poetry run python scripts/profile_analysts.py

# Analyze startup and import overhead
poetry run python scripts/profile_startup_time.py
```

## Key Optimizations Implemented

1. ✅ **Lazy Agent Loading** - 68% startup improvement
2. ✅ **LLM Response Caching** - 7-day TTL, 1,000x-15,000x speedup on cache hits
3. ✅ **Data Prefetching** - 95% API call reduction, true parallel processing
4. ✅ **AttributeError Fixes** - All 17 agents now work reliably

## Future Optimization Opportunities

From the profiling reports:

- **Priority 1:** Optimize Warren Buffett agent (currently 18.4s, target 5s)
- **Priority 2:** Replace `statistics.pstdev` with `np.std` in Stanley Druckenmiller
- **Priority 3:** Reduce Pydantic `getattr` overhead with array extraction
- **Priority 4:** Persistent instrument cache with TTL

## Performance Benchmarks

**Startup Time:**
- Before optimization: 3.43s
- After lazy loading: 1.10s
- Improvement: 68% faster

**Multi-Agent Analysis (with LLM cache):**
- Cold start (14 LLM agents): ~75s
- Warm start (cache hits): ~27s
- Improvement: 65% faster

**Data Fetching:**
- With prefetching: 3.6-3.8s (acceptable)
- Without prefetching: Would be 30-40s (eliminated)
