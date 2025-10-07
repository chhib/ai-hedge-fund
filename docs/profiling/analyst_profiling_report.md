# Analyst Profiling Report

**Date:** 2025-10-01
**Branch:** feature/analyst-profiling
**Test Ticker:** ERIC B (Ericsson B - Swedish stock)
**Iterations:** 100 per function for statistical significance

## Executive Summary

Profiled CPU-heavy analyst routines (Jim Simons and Stanley Druckenmiller) to identify performance bottlenecks. Key findings:

1. **Stanley Druckenmiller's `analyze_risk_reward`** is the **slowest function** at 0.046s per 100 iterations
2. **Jim Simons' `analyze_statistical_patterns`** is second at 0.029s per 100 iterations
3. Main bottlenecks are **Python's `statistics.pstdev`** and **numpy correlation/covariance** calculations
4. Significant time spent in **attribute access** (`getattr`) due to dynamic Pydantic model access

---

## Detailed Performance Analysis

### Jim Simons Agent Functions

#### 1. `analyze_statistical_patterns` - **HIGHEST JIM SIMONS OVERHEAD**
- **Time:** 0.029s for 100 iterations (0.29ms per call)
- **Hotspots:**
  - `numpy.corrcoef` - 0.013s (45% of time) - Computing autocorrelation
  - `numpy.cov` - 0.009s (31% of time) - Covariance calculations
  - `numpy.polyfit` - 0.005s (17% of time) - Linear trend fitting
  - `numpy.std` - 0.003s (10% of time) - Volatility metrics
- **Optimization Opportunities:**
  - ✅ **Already vectorized** - using numpy efficiently
  - Consider caching correlation matrices if data doesn't change between calls
  - Could reduce number of autocorrelation lags if current precision isn't critical

#### 2. `analyze_mean_reversion` - MEDIUM OVERHEAD
- **Time:** 0.016s for 100 iterations (0.16ms per call)
- **Hotspots:**
  - 13,000 `__getattr__` calls (4ms) - Pydantic model attribute access
  - `numpy.std` calculations - z-score computations
  - `numpy.mean` calculations
- **Optimization Opportunities:**
  - ⚠️ **High attribute access overhead** - cache frequently accessed attributes
  - Convert Pydantic models to dicts or numpy arrays before processing
  - Use direct field access instead of `getattr(item, "field", default)`

#### 3. Other Functions (Fast)
- `analyze_momentum_indicators` - 0.002s (minimal overhead)
- `analyze_anomalies` - 0.006s (acceptable)
- `analyze_cross_sectional_factors` - 0.001s (very fast)
- `compute_risk_metrics` - 0.004s (acceptable)

---

### Stanley Druckenmiller Agent Functions

#### 1. `analyze_risk_reward` - **CRITICAL BOTTLENECK** 🔴
- **Time:** 0.046s for 100 iterations (0.46ms per call)
- **Hotspots:**
  - `statistics.pstdev` - 0.032s (70% of total!) - **MAJOR PROBLEM**
  - `statistics._ss` (sum of squares) - 0.031s
  - Fraction arithmetic overhead - 0.010s
  - Uses Python's `statistics` module instead of numpy!
- **Root Cause:**
  - Line 422 in `stanley_druckenmiller.py`: `stdev = statistics.pstdev(daily_returns)`
  - Python's `statistics.pstdev` uses high-precision fraction arithmetic
  - For 250 prices → 249 returns, this creates ~3,500 Fraction objects
- **Optimization Opportunity:** 🎯 **HIGH IMPACT**
  - Replace `statistics.pstdev(daily_returns)` with `np.std(daily_returns)`
  - **Expected speedup:** 10-20x (0.046s → 0.002-0.004s)
  - **Risk:** Low - numpy provides sufficient precision for volatility calculations

#### 2. `analyze_druckenmiller_valuation` - MEDIUM OVERHEAD
- **Time:** 0.008s for 100 iterations (0.08ms per call)
- **Hotspots:**
  - 12,000 `getattr` calls - 0.007s (87.5% of time)
  - Pydantic model access for financial line items
- **Optimization Opportunities:**
  - Same as mean reversion - extract data to arrays/dicts first
  - Cache computed ratios (P/E, P/FCF, EV/EBIT, EV/EBITDA)

#### 3. `analyze_growth_and_momentum` - ACCEPTABLE
- **Time:** 0.007s for 100 iterations (0.07ms per call)
- **Hotspots:**
  - `sorted(prices, key=lambda p: p.time)` - 0.003s
  - List comprehension over prices - 0.002s
- **Status:** Not a bottleneck, but could pre-sort prices once

#### 4. Other Functions (Fast)
- `analyze_insider_activity` - 0.001s (very fast)
- `analyze_calendar_context` - 0.002s (very fast)

---

## Combined Workflow Performance

### Jim Simons Complete Workflow
- **Total:** 0.005s for 10 iterations (0.5ms per complete analysis)
- **Breakdown:**
  - Statistical patterns: 40%
  - Mean reversion: 20%
  - Other functions: 40%

### Stanley Druckenmiller Complete Workflow
- **Total:** 0.007s for 10 iterations (0.7ms per complete analysis)
- **Breakdown:**
  - Risk/reward: 71% (5ms out of 7ms) ← **Dominates execution time**
  - Valuation: 14%
  - Growth/momentum: 14%
  - Other: <1%

---

## Recommendations

### Priority 1: CRITICAL - Fix Stanley Druckenmiller Risk Analysis 🔴
**File:** `src/agents/stanley_druckenmiller.py:422`

```python
# BEFORE (slow - 0.032s)
stdev = statistics.pstdev(daily_returns)

# AFTER (fast - ~0.002s)
stdev = np.std(daily_returns, ddof=0)  # ddof=0 for population std
```

**Impact:** 10-20x speedup on the slowest function
**Risk:** Minimal - numpy precision is sufficient for volatility calculations
**Effort:** 1 line change + import numpy as np

### Priority 2: MEDIUM - Reduce Attribute Access Overhead ⚠️
**Files:**
- `src/agents/jim_simons.py` (analyze_mean_reversion, analyze_cross_sectional_factors)
- `src/agents/stanley_druckenmiller.py` (analyze_druckenmiller_valuation)

**Pattern:**
```python
# BEFORE (slow - many getattr calls)
for item in financial_line_items:
    if getattr(item, "revenue", None):
        revenue = item.revenue
    if getattr(item, "net_income", None):
        income = item.net_income

# AFTER (fast - extract once)
revenues = np.array([item.revenue for item in financial_line_items if item.revenue is not None])
incomes = np.array([item.net_income for item in financial_line_items if item.net_income is not None])
```

**Impact:** 2-3x speedup on mean reversion and valuation functions
**Risk:** Low
**Effort:** Moderate - requires refactoring loops to work with arrays

### Priority 3: LOW - Cache Correlation Matrices
**File:** `src/agents/jim_simons.py` (analyze_statistical_patterns)

If the same financial data is analyzed multiple times (e.g., backtesting), cache:
- Autocorrelation coefficients
- Covariance matrices
- Polynomial fit coefficients

**Impact:** Variable (depends on reuse patterns)
**Risk:** Medium - need to invalidate cache when data changes
**Effort:** High - implement caching layer

---

## Performance Comparison

### Current Performance (100 iterations)
| Function | Time | % of Total | Priority |
|----------|------|-----------|----------|
| `analyze_risk_reward` | 0.046s | 48% | 🔴 CRITICAL |
| `analyze_statistical_patterns` | 0.029s | 30% | ⚠️ MEDIUM |
| `analyze_mean_reversion` | 0.016s | 17% | ⚠️ MEDIUM |
| `analyze_druckenmiller_valuation` | 0.008s | 8% | ⚠️ MEDIUM |
| Other functions | 0.015s | 16% | ✅ OK |
| **TOTAL** | 0.096s | 100% | |

### After Priority 1 Fix (Estimated)
| Function | Time | Speedup | % of Total |
|----------|------|---------|-----------|
| `analyze_risk_reward` | **0.002s** | **23x** | 3% |
| `analyze_statistical_patterns` | 0.029s | - | 48% |
| `analyze_mean_reversion` | 0.016s | - | 27% |
| `analyze_druckenmiller_valuation` | 0.008s | - | 13% |
| Other functions | 0.015s | - | 25% |
| **TOTAL** | **0.052s** | **1.8x** | 100% |

**Overall Expected Improvement:** 46% faster (96ms → 52ms per 100 analyst calls)

---

## Testing Notes

**Data used:**
- Ticker: ERIC B (Ericsson B shares)
- 10 financial line items (quarterly/annual reports)
- 5 annual metrics
- 250 price points (1 year of daily data)
- 50 insider trades
- 50 calendar events

**Results:**
- All functions executed successfully
- Jim Simons detected patterns: revenue autocorrelation 0.444, low volatility
- Druckenmiller analysis showed negative growth but high calendar activity
- No crashes or numerical errors

---

## Next Steps

1. ✅ **Implement Priority 1 fix** - Replace `statistics.pstdev` with `np.std`
2. ⏳ **Benchmark improvements** - Re-run profiling after fix
3. ⏳ **Consider Priority 2** - Optimize attribute access patterns if still needed
4. ⏳ **Profile end-to-end workflow** - Test with multi-ticker, multi-analyst scenarios
5. ⏳ **Monitor production performance** - Add timing metrics to actual agent runs

---

## Appendix: Profiling Command

```bash
poetry run python scripts/profile_analysts.py
```

The profiling script (`scripts/profile_analysts.py`) loads real data from Börsdata and executes each analyst function 100 times to generate statistically significant timing data.
