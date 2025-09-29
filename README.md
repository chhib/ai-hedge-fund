# AI Hedge Fund - Enhanced Börsdata Edition

This is a proof of concept for an AI-powered hedge fund with **comprehensive financial data integration**.  The goal of this project is to explore the use of AI to make trading decisions using institutional-grade financial metrics.  This project is for **educational** purposes only and is not intended for real trading or investment.

## 🚀 Major Enhancement: Börsdata Integration

**This fork represents a significant upgrade from the original FinancialDatasets implementation:**

### 🔢 **Data Coverage Expansion**
- **5.2x more financial metrics**: 17 → 89 comprehensive KPI mappings
- **Nordic + Global market support**: European tickers (ATCO B) + US tickers (AAPL)
- **Institutional-grade metrics**: 73 unique KPI IDs covering all major financial categories
- **Advanced ratios**: Beta, Alpha, Cash Flow Stability, Enterprise Value metrics

### 🐛 **Critical Bug Fixes**
- **Fixed percentage inflation**: ROE correctly shows ~151% (vs previous 15,081% bug)
- **Accurate metric conversion**: 33 metrics with proper percentage handling
- **Multi-endpoint validation**: Comprehensive data accuracy across multiple API sources

### 📊 **Trading Decision Impact**
Comparison testing revealed **dramatically different investment strategies**:
- **Enhanced Börsdata**: BUY AAPL (78 shares, 50% confidence)
- **Original FinancialDatasets**: SHORT AAPL (60 shares, 82% confidence)

This demonstrates the critical importance of comprehensive, accurate financial data in algorithmic trading.

## 🚧 System Overview

**This is an enhanced AI hedge fund system with comprehensive market data integration.**

- **Command-line interface**: ✅ **Production Ready** - Full CLI experience with Börsdata data integration for Nordic/European and Global markets
- **Web interface**: ✅ **Operational** - Full-stack web application with streaming UI components and Börsdata integration

The system provides both command-line and web interfaces with comprehensive market analysis capabilities.

This system employs several agents working together:

### Core Analysis Agents
- **Fundamentals Analyst** - Evaluates company health through financial thresholds (ROE, margins, growth metrics)
- **Technical Analyst** - Combines 5 strategies: trend following, mean reversion, momentum, volatility, statistical arbitrage
- **Sentiment Analyst** - Analyzes insider trades and corporate events to gauge market sentiment
- **Valuation Analyst** - Calculates intrinsic value using DCF, Owner Earnings, EV/EBITDA, and Residual Income models
- **Risk Manager** - Sets position limits based on volatility and correlation analysis

### Legendary Investor Agents
- **Warren Buffett** - Value investing with 30% margin of safety using conservative DCF
- **Ben Graham** - Father of value investing, Graham Number and net-net analysis
- **Charlie Munger** - Quality businesses with economic moats and predictable earnings
- **Peter Lynch** - Growth at reasonable price (PEG ratio) with "ten-bagger" potential
- **Phil Fisher** - Growth investing through "scuttlebutt" research and R&D analysis
- **Bill Ackman** - Activist investing targeting operational improvement opportunities
- **Cathie Wood** - Disruptive innovation focus with aggressive growth assumptions
- **Michael Burry** - Contrarian deep value with high free cash flow yields
- **Mohnish Pabrai** - "Heads I win, tails I don't lose much" with downside protection
- **Stanley Druckenmiller** - Macro momentum with growth and risk/reward analysis
- **Rakesh Jhunjhunwala** - High-quality growth with ROE > 20% requirements
- **Aswath Damodaran** - Academic valuation using CAPM and sophisticated DCF models
- **Jim Simons** - Quantitative agent based on multi-factor models

### Portfolio Management
- **Portfolio Manager** - Aggregates all signals and makes final trading decisions within risk limits

For detailed strategy implementations and thresholds, see [Trading Agent Strategies](docs/trading_agent_strategies.md).

<img width="1042" alt="Screenshot 2025-03-22 at 6 19 07 PM" src="https://github.com/user-attachments/assets/cbae3dcf-b571-490d-b0ad-3f0f035ac0d4" />

Note: the system does not actually make any trades.

[![Twitter Follow](https://img.shields.io/twitter/follow/virattt?style=social)](https://twitter.com/virattt)

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Creator assumes no liability for financial losses
- Consult a financial advisor for investment decisions
- Past performance does not indicate future results

By using this software, you agree to use it solely for learning purposes.

## Table of Contents
- [How to Install](#how-to-install)
- [How to Run](#how-to-run)
  - [⌨️ Command Line Interface](#️-command-line-interface)
  - [🖥️ Web Application](#️-web-application)
- [How to Contribute](#how-to-contribute)
- [Feature Requests](#feature-requests)
- [License](#license)

## How to Install

Before you can run the AI Hedge Fund, you'll need to install it and set up your API keys. These steps are common to both the full-stack web application and command line interface.

### 1. Clone the Repository

```bash
git clone https://github.com/chhib/ai-hedge-fund.git
cd ai-hedge-fund
```

### 2. Set up API keys

Create a `.env` file for your API keys:
```bash
# Create .env file for your API keys (in the root directory)
cp .env.example .env
```

Open and edit the `.env` file to add your API keys:
```bash
# For running LLMs hosted by openai (gpt-4o, gpt-4o-mini, etc.)
OPENAI_API_KEY=your-openai-api-key

# For getting financial data to power the hedge fund
BORSDATA_API_KEY=your-borsdata-api-key
```

**Important**: You must set at least one LLM API key (e.g. `OPENAI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, or `DEEPSEEK_API_KEY`) for the hedge fund to work. 

**Financial Data**: All Börsdata endpoints require the `BORSDATA_API_KEY`. Set this value in your `.env` file before running the application.

## How to Run

### ⌨️ Command Line Interface

You can run the AI Hedge Fund directly via terminal. This approach offers more granular control and is useful for automation, scripting, and integration purposes.

<img width="992" alt="Screenshot 2025-01-06 at 5 50 17 PM" src="https://github.com/user-attachments/assets/e8ca04bf-9989-4a7d-a8b4-34e04666663b" />

#### Quick Start

1. Install Poetry (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:
```bash
poetry install
```

#### Run the AI Hedge Fund

The system supports both Nordic/European and global company analysis:

**Important**: Use exact ticker symbols as they appear in Börsdata. Nordic tickers with spaces (like "HM B", "MTG B") must be quoted.

**Nordic/European companies** (via Börsdata Nordic instruments):
```bash
# Swedish companies (note the space in ticker symbols like "HM B", "MTG B")
poetry run python src/main.py --tickers-nordics "HM B,MTG B,TELIA,ADVT"

# Norwegian/Danish companies
poetry run python src/main.py --tickers-nordics "FRO,ZAL,TRMD A"
```

**Global companies** (via Börsdata Global instruments):
```bash
# US tech stocks
poetry run python src/main.py --tickers AAPL,MSFT,NVDA,META,TSLA

# Mixed global companies
poetry run python src/main.py --tickers AAPL,UBI,BABA
```

**Mixed analysis** (both Nordic and global companies in one command):
```bash
poetry run python src/main.py --tickers-nordics "HM B,TELIA" --tickers "AAPL,META"
```

**Quick test mode** (uses gpt-5 with fundamentals, technical, and sentiment analysts):
```bash
# Test with Nordic company
poetry run python src/main.py --tickers-nordics "HM B" --test

# Test with global company
poetry run python src/main.py --tickers AAPL --test

# Test with mixed tickers
poetry run python src/main.py --tickers-nordics "BAHN B,TELIA" --tickers "AAPL,TSLA" --test
```

You can also specify a `--ollama` flag to run the AI hedge fund using local LLMs.

```bash
poetry run python src/main.py --tickers AAPL,MSFT,NVDA --ollama
```

You can optionally specify the start and end dates to make decisions over a specific time period.

```bash
poetry run python src/main.py --tickers AAPL,MSFT,NVDA --start-date 2024-01-01 --end-date 2024-03-01
```

#### Additional CLI Arguments

-   **`--model-name` and `--model-provider`**: Allows non-interactive selection of the LLM model.
    ```bash
    poetry run python src/main.py --tickers AAPL --model-name gpt-4o --model-provider openai
    ```
-   **`--initial-currency`**: Specifies the target currency for all monetary values in the backtester.
    ```bash
    poetry run python src/backtester.py --tickers-nordics TELIA --initial-currency SEK
    ```

#### Run the Backtester

**Nordic/European companies:**
```bash
poetry run python src/backtester.py --tickers-nordics TELIA,VOLV-B,ADVT
```

**Global companies:**
```bash
poetry run python src/backtester.py --tickers AAPL,MSFT,NVDA
```

**Mixed analysis:**
```bash
poetry run python src/backtester.py --tickers-nordics TELIA,ADVT --tickers AAPL,META
```

**Example Output:**
<img width="941" alt="Screenshot 2025-01-06 at 5 47 52 PM" src="https://github.com/user-attachments/assets/00e794ea-8628-44e6-9a84-8f8a31ad3b47" />


Note: The `--ollama`, `--start-date`, and `--end-date` flags work for the backtester, as well!

### 🖥️ Web Application

The new way to run the AI Hedge Fund is through our web application that provides a user-friendly interface. This is recommended for users who prefer visual interfaces over command line tools.

Please see detailed instructions on how to install and run the web application [here](https://github.com/chhib/ai-hedge-fund/tree/main/app).

<img width="1721" alt="Screenshot 2025-06-28 at 6 41 03 PM" src="https://github.com/user-attachments/assets/b95ab696-c9f4-416c-9ad1-51feb1f5374b" />


## 🔧 Technical Architecture: Enhanced KPI System

### Multi-Endpoint Data Strategy

The enhanced system uses a hierarchical approach to maximize financial data coverage:

1. **KPI Summary Endpoint** (Primary): Fast bulk retrieval of core metrics
2. **Bulk Screener Values** (Secondary): Comprehensive KPI collection via `get_all_kpi_screener_values()`  
3. **Individual Screener Calls** (Tertiary): Targeted retrieval for missing KPIs
4. **Holdings Endpoint** (Fallback): Final attempt for comprehensive coverage

### Financial Metrics Coverage

| Category | Before | After | Examples |
|----------|--------|-------|----------|
| Valuation | 4 | 12 | P/E, EV/EBITDA, PEG |
| Profitability | 3 | 10 | ROE, ROA, EBITDA margin |
| Liquidity | 0 | 8 | Current ratio, Debt/Equity |
| Efficiency | 2 | 6 | Asset turnover, DSO |
| Growth | 3 | 8 | Revenue growth, FCF growth |
| Per-Share | 3 | 8 | EPS, BVPS, FCF/share |
| Cash Flow | 1 | 7 | FCF, OCF, Cash stability |
| Risk/Market | 0 | 4 | Beta, Volatility |

### Key Files Enhanced

- **`src/data/borsdata_client.py`**: Added 4 new API endpoints for comprehensive data retrieval
- **`src/data/borsdata_metrics_mapping.py`**: 89 KPI mappings with proper percentage conversion flags
- **`src/data/models.py`**: Extended FinancialMetrics model with 25+ new fields
- **`src/data/borsdata_kpis.py`**: Enhanced assembly logic with multi-endpoint fallback strategy

### Validation & Testing

The system has been validated with both Nordic (ATCO B) and Global (AAPL) tickers, showing:
- 50+ non-null metrics retrieved per ticker
- Correct percentage conversion (fixed 100x inflation bug)
- Multi-market support for diverse portfolio strategies

This comprehensive financial analysis system provides institutional-grade capabilities for algorithmic trading research and education.

## How to Contribute

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: Please keep your pull requests small and focused.  This will make it easier to review and merge.

## Feature Requests

If you have a feature request, please open an [issue](https://github.com/chhib/ai-hedge-fund/issues) and make sure it is tagged with `enhancement`.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
