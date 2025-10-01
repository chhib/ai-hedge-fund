# Börsdata API Documentation

This directory contains all documentation related to the Börsdata API integration.

## Overview

The AI Hedge Fund uses Börsdata as the sole data provider for both Nordic/European and Global market analysis. This includes price data, financial metrics, corporate events (reports, dividends), and insider trading data.

## Documentation Files

### API Reference
- **[API.md](API.md)** - Complete Börsdata REST API documentation
  - Rate limits (100 calls/10 seconds)
  - Available endpoints
  - Authentication requirements
  - Sample code links

### Data Mappings
- **[metrics_mapping.md](metrics_mapping.md)** - Simple KPI ID lookup table
  - Quick reference for metric name → Börsdata KPI ID
  - Shows which metrics are available vs. derived

- **[metrics_mapping_detailed.md](metrics_mapping_detailed.md)** - Detailed implementation guide
  - Complete mapping from FinancialMetrics model to Börsdata endpoints
  - Implementation notes for each metric
  - Report type mapping (ttm, annual, quarterly)
  - Fallback strategies for missing data

- **[endpoint_mapping.md](endpoint_mapping.md)** - API endpoint catalog
  - Maps Börsdata endpoints to internal functions
  - Shows which endpoints are used for each data type

### Additional References
- **[../reference/swagger_v1.json](../reference/swagger_v1.json)** - Official Swagger/OpenAPI specification

## Quick Start

### Getting an API Key

1. Sign up for Börsdata PRO+ at https://borsdata.se/en/info/api/api_page
2. Get your API key from https://borsdata.se/en/mypage/api
3. Add to your `.env` file:
   ```bash
   BORSDATA_API_KEY=your-api-key-here
   ```

### Market Coverage

- **Nordic Markets**: Sweden, Norway, Denmark, Finland (native currencies: SEK, NOK, DKK)
- **Global Markets**: US, UK, and other international companies (USD, GBP)

### Usage in Code

The system automatically detects whether a ticker is Nordic or Global:

```bash
# Nordic tickers (quotes needed for tickers with spaces)
poetry run python src/main.py --tickers "HM B,TELIA,VOLV B"

# Global tickers
poetry run python src/main.py --tickers AAPL,MSFT,NVDA

# Mixed (auto-detected)
poetry run python src/main.py --tickers "AAPL,TELIA,HM B"
```

## Implementation Details

### Rate Limiting
- **Limit**: 100 API calls per 10 seconds
- **Response**: HTTP 429 when limit exceeded
- **Retry-After**: Check response header for wait time

### Currency Handling
- Nordic instruments return values in native currencies (SEK, DKK, NOK)
- Global instruments return values in USD or GBP
- Market caps and enterprise values are in millions (multiply by 1,000,000)
- The system handles currency conversion automatically via `ExchangeRateService`

### Data Freshness
- Stock prices: Real-time (with slight delay)
- Financial metrics: Updated quarterly/annually per company reporting schedule
- Corporate events: Calendar updated as companies announce
- Insider trades: Updated within days of regulatory filing

## See Also

- [Trading Agent Strategies](../trading_agent_strategies.md) - How agents use this financial data
- [Main README](../../README.md) - Overall project documentation
