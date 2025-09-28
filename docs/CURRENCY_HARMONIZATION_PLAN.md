# Currency Harmonization Plan for FD/BD Framework

## Executive Summary

The multi-currency analysis reveals critical insights for ensuring accurate cross-platform comparisons between FinancialDatasets (FD) and Börsdata (BD). While FD supports only USD markets, BD provides comprehensive coverage across Nordic currencies (SEK, DKK, NOK) plus USD, requiring sophisticated normalization strategies.

## Currency Coverage Analysis

### Supported Currencies by Platform

| Currency | FinancialDatasets | Börsdata | Exchange Rate | Market Examples |
|----------|-------------------|----------|---------------|-----------------|
| **USD**  | ✅ Full Support   | ✅ Global | 1.000         | AAPL, MSFT, NVDA |
| **SEK**  | ❌ Not Supported  | ✅ Native | 0.091         | AAK, ASSA B, ALFA |
| **DKK**  | ❌ Not Supported  | ✅ Native | 0.145         | DSV, NOVO B, ORSTED |
| **NOK**  | ❌ Not Supported  | ✅ Native | 0.094         | DNB, TEL |
| **EUR**  | ❌ Limited        | ❌ Limited| 1.060         | (Not widely available) |

### Key Findings

1. **Market Coverage Gap**: FD only supports ~3 USD tickers while BD supports 12 tickers across 4 currencies
2. **Currency Native Support**: BD properly identifies and uses native currencies for each market
3. **Scale + Currency Double Impact**: BD market caps need both 1M scaling AND currency normalization

## Currency Normalization Examples

### Before Normalization
```
AAPL (USD): 3,841,523.5M USD
AAK (SEK):  62,969.0M SEK
```

### After Scaling + Currency Normalization to USD
```
AAPL (USD): $3,841,523,510,298 USD
AAK (SEK):  $5,730,180,219 USD  (62.9B SEK * 1M * 0.091 USD/SEK)
```

## Critical Currency Issues Identified

### 1. Comparison Framework Gaps
**Severity**: 🔴 CRITICAL

- **Current State**: FD/BD comparisons only work for USD tickers
- **Impact**: 75% of BD's market coverage cannot be compared with FD
- **Root Cause**: No currency normalization in comparison framework

### 2. Market Cap Currency Inconsistency
**Severity**: 🟡 MODERATE

- **Issue**: BD returns market caps in native currencies (millions)
- **Example**: AAK shows 62,969M SEK vs expected USD equivalent
- **Impact**: Direct comparisons are meaningless without normalization

### 3. Exchange Rate Dependencies
**Severity**: 🟡 MODERATE

- **Current**: Static exchange rates hardcoded in analysis
- **Needed**: Real-time or daily exchange rate feeds
- **Impact**: Normalization accuracy depends on rate freshness

## Recommended Implementation Strategy

### Phase 1: Immediate Fixes (This Week)

#### 1.1 Enhanced Comparison Framework
```python
def normalize_financial_metrics(metrics, target_currency="USD"):
    """Normalize metrics to target currency with proper scaling."""

    # Step 1: Apply BD scaling fix (millions to absolute)
    if metrics.source == "Börsdata":
        metrics.market_cap *= 1_000_000
        metrics.enterprise_value *= 1_000_000

    # Step 2: Currency conversion
    if metrics.currency != target_currency:
        rate = get_exchange_rate(metrics.currency, target_currency)
        metrics.market_cap *= rate
        metrics.enterprise_value *= rate
        metrics.currency = target_currency

    return metrics
```

#### 1.2 Multi-Currency Comparison Support
```python
# Enhanced comparison script
def compare_with_currency_normalization(fd_result, bd_result, target_currency="USD"):
    """Compare results after currency normalization."""

    normalized_fd = normalize_financial_metrics(fd_result, target_currency)
    normalized_bd = normalize_financial_metrics(bd_result, target_currency)

    return calculate_differences(normalized_fd, normalized_bd)
```

### Phase 2: Exchange Rate Integration (Next Week)

#### 2.1 Real-Time Exchange Rate Service
```python
class ExchangeRateService:
    """Provides real-time exchange rates for financial normalization."""

    def __init__(self):
        self.cache_ttl = 3600  # 1 hour cache
        self.providers = ["exchangerate-api.com", "fixer.io"]

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """Get current exchange rate with fallback providers."""
        pass
```

#### 2.2 Currency-Aware Financial Metrics
```python
@dataclass
class CurrencyNormalizedMetrics:
    """Financial metrics with currency normalization support."""

    original_currency: str
    normalized_currency: str
    exchange_rate_used: float
    normalization_timestamp: str

    # All monetary values in normalized currency
    market_cap: float
    enterprise_value: float
```

### Phase 3: Advanced Multi-Currency Features (Month 1)

#### 3.1 Currency Portfolio Analysis
- Support for portfolios with mixed-currency holdings
- Real-time currency exposure reporting
- Currency hedging analysis for international investments

#### 3.2 Historical Currency Impact Analysis
- Track how currency fluctuations affect investment decisions
- Currency-adjusted performance metrics
- Multi-currency risk assessment

## Implementation Priority Matrix

| Feature | Impact | Effort | Priority | Timeline |
|---------|--------|--------|----------|----------|
| Currency Normalization in Comparison | High | Medium | 🔴 P0 | This Week |
| Exchange Rate Service Integration | High | Medium | 🟠 P1 | Next Week |
| Multi-Currency Portfolio Support | Medium | High | 🟡 P2 | Month 1 |
| Historical Currency Analysis | Low | High | 🔵 P3 | Month 2 |

## Testing & Validation Strategy

### Multi-Currency Test Suite
```python
CURRENCY_TEST_CASES = {
    "USD_BD_vs_FD": {
        "tickers": ["AAPL", "MSFT", "NVDA"],
        "expected_variance": "<5% after normalization"
    },
    "SEK_BD_only": {
        "tickers": ["AAK", "ASSA B", "ALFA"],
        "validation": "Currency consistency, proper scaling"
    },
    "DKK_BD_only": {
        "tickers": ["DSV", "NOVO B", "ORSTED"],
        "validation": "Cross-currency normalization accuracy"
    },
    "Mixed_Currency_Portfolio": {
        "portfolio": {"AAPL": "USD", "AAK": "SEK", "DSV": "DKK"},
        "validation": "Portfolio-level currency normalization"
    }
}
```

### Success Metrics

#### Short-term (1 week)
- [ ] USD ticker comparisons maintain <5% variance after currency normalization
- [ ] SEK/DKK tickers properly normalized to USD equivalent
- [ ] Exchange rate service integration functional

#### Medium-term (1 month)
- [ ] Real-time exchange rates reduce normalization variance to <2%
- [ ] Multi-currency portfolio analysis operational
- [ ] Currency impact on agent decisions documented

#### Long-term (3 months)
- [ ] Historical currency analysis reveals investment decision patterns
- [ ] Currency hedging recommendations integrated
- [ ] Full Nordic + US market analysis framework operational

## Risk Mitigation

### Exchange Rate Accuracy
- **Risk**: Stale or inaccurate exchange rates affecting normalization
- **Mitigation**: Multiple provider fallbacks, rate staleness alerts

### Currency Market Volatility
- **Risk**: Rapid currency changes affecting comparison validity
- **Mitigation**: Timestamp-based normalization, volatility alerts

### Data Source Currency Mismatches
- **Risk**: BD vs FD using different base currencies for same company
- **Mitigation**: Currency validation, source currency documentation

## Immediate Next Actions

1. **Today**: Implement currency normalization in `fd_bd_direct_comparison.py`
2. **Tomorrow**: Add exchange rate service integration
3. **This Week**: Update PROJECT_LOG.md with currency considerations
4. **Next Week**: Deploy multi-currency comparison framework

---

**Generated**: 2025-09-28
**Status**: Ready for immediate implementation
**Coverage**: USD, SEK, DKK, NOK confirmed operational