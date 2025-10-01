# Documentation

This directory contains comprehensive documentation for the AI Hedge Fund project.

## Quick Navigation

### 📊 Trading Strategies
- **[trading_agent_strategies.md](trading_agent_strategies.md)** - Detailed implementations of all 17 trading agents
  - Core analysis agents (Fundamentals, Technical, Sentiment, Valuation, Risk)
  - 13 legendary investor personas (Buffett, Graham, Munger, Lynch, Fisher, etc.)
  - Portfolio Manager aggregation logic

### 🔌 Börsdata API Integration
- **[borsdata/](borsdata/)** - Complete Börsdata API documentation
  - [borsdata/API.md](borsdata/API.md) - Full API reference (rate limits, endpoints, authentication)
  - [borsdata/metrics_mapping.md](borsdata/metrics_mapping.md) - Quick KPI ID lookup table
  - [borsdata/metrics_mapping_detailed.md](borsdata/metrics_mapping_detailed.md) - Implementation guide with fallback strategies
  - [borsdata/endpoint_mapping.md](borsdata/endpoint_mapping.md) - API endpoint catalog

### 📖 Technical Reference
- **[reference/](reference/)** - API specifications and technical references
  - [reference/swagger_v1.json](reference/swagger_v1.json) - Börsdata OpenAPI specification
  - [reference/borsdata_swagger_v1.json](reference/borsdata_swagger_v1.json) - Alternative Swagger spec

### 📁 Historical Documents
- **[archive/](archive/)** - Legacy migration documentation
  - [archive/FD_BD_COMPARISON_ANALYSIS.md](archive/FD_BD_COMPARISON_ANALYSIS.md) - FinancialDatasets → Börsdata migration analysis
  - [archive/CURRENCY_HARMONIZATION_PLAN.md](archive/CURRENCY_HARMONIZATION_PLAN.md) - Multi-currency implementation plan
  - [archive/borsdata_financial_metrics_mapping_analysis.md](archive/borsdata_financial_metrics_mapping_analysis.md) - Historical KPI coverage analysis

## Documentation Organization

### Active Documentation
Documents that are actively maintained and referenced:
- Trading agent strategies
- Börsdata API integration guides
- Metrics mappings
- Endpoint references

### Archived Documentation
Historical documents preserved for reference but no longer actively maintained:
- FinancialDatasets comparison analysis
- Currency harmonization planning
- Migration feasibility studies

## Key Topics

### For Users
- **Getting Started**: See [main README](../README.md) for installation and CLI usage
- **Understanding Agents**: Read [trading_agent_strategies.md](trading_agent_strategies.md)
- **API Reference**: Browse [borsdata/](borsdata/) for Börsdata integration details

### For Developers
- **Implementation Details**: See [borsdata/metrics_mapping_detailed.md](borsdata/metrics_mapping_detailed.md)
- **API Endpoints**: Reference [borsdata/endpoint_mapping.md](borsdata/endpoint_mapping.md)
- **Migration History**: Review [archive/](archive/) for design decisions

## Additional Resources

### External Links
- [Börsdata API Documentation](https://apidoc.borsdata.se/swagger/index.html) - Official Swagger documentation
- [Börsdata Main Site](https://borsdata.se) - API key registration and account management
- [Original Project](https://github.com/virattt/ai-hedge-fund) - Upstream repository (FinancialDatasets-based)

### Project Files
- [pyproject.toml](../pyproject.toml) - Python dependencies and project metadata
- [.env.example](../.env.example) - Required environment variables
- [PROJECT_LOG.md](../PROJECT_LOG.md) - Detailed development session history

## Contributing to Documentation

When adding new documentation:
1. **API/Integration docs** → `borsdata/` directory
2. **Agent strategies** → Update `trading_agent_strategies.md`
3. **Migration/historical** → `archive/` directory
4. **Technical specs** → `reference/` directory

Keep documentation:
- Concise and actionable
- Up-to-date with code changes
- Well-organized with clear navigation
- Cross-referenced appropriately
