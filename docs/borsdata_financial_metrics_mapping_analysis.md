# Börsdata Financial Metrics Mapping Analysis

## Overview
Analysis of available Börsdata KPIs against existing financial metrics mapping to identify coverage gaps and optimization opportunities.

## Current Coverage Analysis

### ✅ Well-Covered Metrics (Direct KPI Match)
These metrics have direct correspondence in Börsdata's KPI screener list:

| Internal Metric | Börsdata KPI | KPI ID | Status |
|----------------|--------------|--------|---------|
| `dividend_yield` | Dividend Yield | 1 | ✅ Direct match |
| `enterprise_value_to_ebit_ratio` | EV/EBIT | 10 | ✅ Direct match |
| `enterprise_value_to_ebitda_ratio` | EV/EBITDA | 11 | ✅ Direct match |
| `enterprise_value_to_revenue_ratio` | EV/S | 13 | ✅ Direct match |
| `price_to_book_ratio` | Price/Book | 14 | ✅ Direct match |
| `price_to_earnings_ratio` | Price/Earnings | 15 | ✅ Direct match |
| `price_to_sales_ratio` | Price/Sales | 17 | ✅ Direct match |
| `debt_to_equity` | Debt/Equity | 18 | ✅ Direct match |
| `operating_margin` | Operating Margin % | 19 | ✅ Direct match |
| `net_margin` | Profit Margin % | 20 | ✅ Direct match |
| `return_on_assets` | Return on Assets % | 21 | ✅ Direct match |
| `return_on_equity` | Return on Equity % | 22 | ✅ Direct match |
| `return_on_invested_capital` | Return on Invested Capital % | 23 | ✅ Direct match |
| `gross_margin` | Gross Margin % | 24 | ✅ Direct match |
| `revenue_growth` | Sales Growth % | 26 | ✅ Direct match |
| `earnings_growth` | EPS Growth % | 27 | ✅ Direct match |

### 📊 Historical Data Available (Screener History)
These per-share metrics are available with 10-year historical data:

| Internal Metric | Börsdata KPI | KPI ID | Historical Periods |
|----------------|--------------|--------|-------------------|
| `earnings_per_share` | Earnings/share | 6 | Year1-10, RQ1-10, Q1-10 |
| `revenue_per_share` | Revenue/share | 5 | Year1-10, RQ1-10, Q1-10 |
| `book_value_per_share` | Book value/share | 8 | Year1-10, Q1-10 |
| `free_cash_flow_per_share` | Free Cash Flow/share | 28 | Year1-10, RQ1-10, Q1-10 |

### 🔄 Holdings & Alternative Data Available
Unique metrics available through Börsdata Holdings API:

| Metric Category | KPI ID | Description |
|----------------|--------|-------------|
| Institutional Activity | 110 | Buyers/Sellers, Share volumes, Value flows |
| Short Interest | 146 | Short ratios, Days to cover, Capital values |
| Retail Demographics | 145 | Age, gender, engagement, geography |

## ⚠️ Metrics Requiring Derived Calculations

### Missing Direct KPIs (Need Custom Implementation)
| Internal Metric | Current Status | Recommendation |
|----------------|----------------|----------------|
| `market_cap` | Derived | ✅ Keep current approach (price × shares) |
| `enterprise_value` | KPI lookup | ⚠️ Verify KPI availability |
| `free_cash_flow_yield` | KPI lookup | ⚠️ Needs validation |
| `peg_ratio` | Screener calc | ✅ Current approach works |
| `asset_turnover` | KPI lookup | ⚠️ Verify availability |
| `inventory_turnover` | KPI lookup | ⚠️ Verify availability |
| `receivables_turnover` | KPI lookup | ⚠️ Verify availability |
| `current_ratio` | KPI lookup | ⚠️ Verify availability |
| `quick_ratio` | KPI lookup | ⚠️ Verify availability |
| `cash_ratio` | KPI lookup | ⚠️ Verify availability |
| `interest_coverage` | KPI lookup | ⚠️ Verify availability |

## 🚀 Optimization Opportunities

### 1. Switch from Derived to Direct KPI
These metrics are currently calculated but have direct KPI equivalents:

```python
# Current (derived)
"price_to_earnings_ratio": {
    "source": "derived",
    "derivation": "price_divided_by_eps",
    "dependencies": ["latest_close_price", "earnings_per_share"]
}

# Recommended (direct KPI)
"price_to_earnings_ratio": {
    "source": "kpi",
    "metadata_match": ["Price/Earnings"],
    "kpi_id": 15,
    "default_report_type": "r12"
}
```

### 2. Leverage Calculation Groups
Börsdata provides pre-calculated statistics (high, low, mean, CAGR) over multiple periods:

- **15year, 10year, 7year, 5year, 3year, 1year**: Historical analysis
- **last**: Most recent values
- **Calculations**: high, low, mean, sum, cagr, latest

### 3. Enhanced Growth Metrics
Current growth calculations can leverage Börsdata's screener calculations:

```python
"revenue_growth": {
    "source": "screener",
    "metadata_match": ["Sales Growth %"],
    "kpi_id": 26,
    "screener_calc_group": "1year",  # or 3year, 5year, etc.
    "screener_calc": "cagr"  # or mean, latest
}
```

## 🎯 Recommended Next Steps

1. **Verify KPI Availability**: Test API calls for metrics marked as "⚠️ Verify availability"
2. **Update Direct Mappings**: Switch derived P/E, P/B, P/S ratios to direct KPI calls
3. **Implement Holdings Metrics**: Add institutional and short interest tracking
4. **Historical Analysis**: Leverage 10-year historical data for trend analysis
5. **Performance Testing**: Compare derived vs direct KPI response times

## 📈 New Metric Opportunities

Börsdata offers metrics not currently in your system:

- **Cash/Price Ratio** (KPI 25)
- **Price/FCF** (KPI 16) 
- **Holdings Activity Tracking** (KPI 110)
- **Short Interest Analytics** (KPI 146)
- **Retail Shareholder Demographics** (KPI 145)

## Rate Limiting Considerations

Börsdata rate limit: 100 calls/10 seconds
- Screener endpoints: Single call for multiple metrics
- Individual KPI calls: One per metric
- Historical data: Bulk retrieval recommended

## Implementation Priority

1. **High**: Verify and switch P/E, P/B, P/S to direct KPIs (IDs 14, 15, 17)
2. **Medium**: Implement EPS and revenue growth using screener calculations (IDs 26, 27)
3. **Low**: Add holdings and short interest metrics for institutional analysis