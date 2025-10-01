# AI Hedge Fund - Börsdata Edition

Enhanced version of [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) with Börsdata API integration for Nordic + Global market support and portfolio management capabilities.

## 🚀 Enhancements

### Börsdata API Integration
- **Nordic + Global market support**: Nordic tickers ("NOVO B", "HM B") + global tickers (SAP, AAPL) US, CA, UK, DE, FR, ES, PT, IT, CH, BE, NL, PL, EE, LV, LT
- **Multi-currency support**: SEK, DKK, NOK, USD, GBP with automatic currency detection

### Portfolio Management
- **Long-only portfolio rebalancing** for concentrated positions (5-10 holdings)
- **Multi-currency portfolios** with automatic currency normalization (GBX/GBP, etc.)
- **Analyst aggregation** - 17 analysts (13 famous investors + 4 core analysts)
- **Automatic portfolio tracking** with cost basis and acquisition dates

### System Capabilities
- **Command-line interface**: 3 CLI tools for analysis, backtesting, and portfolio management

## 🎯 Three Main CLI Tools

### 1. **Analysis CLI** (`src/main.py`)
Real-time market analysis using AI agents to generate trading signals.

### 2. **Backtester CLI** (`src/backtester.py`)
Historical backtesting to evaluate strategy performance over time.

### 3. **Portfolio Manager CLI** (`src/portfolio_manager.py`)
Rebalance existing portfolios using AI analyst consensus.

---

## 🤖 System Overview

The system employs 17 AI agents working together:

### Core Analysis Agents
- **Fundamentals Analyst** - Evaluates company health through financial thresholds (ROE, margins, growth metrics)
- **Technical Analyst** - Combines 5 strategies: trend following, mean reversion, momentum, volatility, statistical arbitrage
- **Sentiment Analyst** - Analyzes insider trades and corporate events to gauge market sentiment
- **Valuation Analyst** - Calculates intrinsic value using DCF, Owner Earnings, EV/EBITDA, and Residual Income models
- **Risk Manager** - Sets position limits based on volatility and correlation analysis

### Legendary Investor Agents (13 personas)
- **Warren Buffett** - Value investing with 30% margin of safety
- **Ben Graham** - Father of value investing, Graham Number and net-net analysis
- **Charlie Munger** - Quality businesses with economic moats
- **Peter Lynch** - Growth at reasonable price (PEG ratio) with "ten-bagger" potential
- **Phil Fisher** - Growth investing through "scuttlebutt" research
- **Bill Ackman** - Activist investing targeting operational improvements
- **Cathie Wood** - Disruptive innovation focus
- **Michael Burry** - Contrarian deep value with high FCF yields
- **Mohnish Pabrai** - "Heads I win, tails I don't lose much" with downside protection
- **Stanley Druckenmiller** - Macro momentum with growth and risk/reward analysis
- **Rakesh Jhunjhunwala** - High-quality growth with ROE > 20%
- **Aswath Damodaran** - Academic valuation using CAPM and sophisticated DCF models
- **Jim Simons** - Quantitative agent based on multi-factor models. [From fork made by **ak4631**](https://github.com/ak4631/ai-hedge-fund/tree/feature/jim_simons).

### Portfolio Management
- **Portfolio Manager** - Aggregates all signals and makes final trading decisions within risk limits

For detailed strategy implementations and thresholds, see [Trading Agent Strategies](docs/trading_agent_strategies.md).

**Note**: The system does not actually make any trades - all outputs are for educational purposes only.

[![Twitter Follow](https://img.shields.io/twitter/follow/virattt?style=social)](https://twitter.com/virattt)

---

## 📋 Table of Contents
- [Disclaimer](#disclaimer)
- [How to Install](#how-to-install)
- [How to Run](#how-to-run)
  - [1. Analysis CLI](#1-analysis-cli)
  - [2. Backtester CLI](#2-backtester-cli)
  - [3. Portfolio Manager CLI](#3-portfolio-manager-cli)
  - [Web Application](#web-application)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## ⚠️ Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Creator assumes no liability for financial losses
- Consult a financial advisor for investment decisions
- Past performance does not indicate future results

By using this software, you agree to use it solely for learning purposes.

---

## 📦 How to Install

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

**Financial Data**: All Börsdata endpoints require the `BORSDATA_API_KEY`. Get yours at https://borsdata.se/en/mypage/api

### 3. Install Dependencies

```bash
# Install Poetry (if not already installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install
```

---

## 🚀 How to Run

## 1. Analysis CLI

Real-time market analysis using AI agents to generate trading signals for specific tickers.

### Basic Usage

**Nordic/European companies** (via Börsdata Nordic instruments):
```bash
# Swedish companies (note the space in ticker symbols like "HM B", "MTG B")
poetry run python src/main.py --tickers "HM B,MTG B,TELIA,ADVT"

# Norwegian/Danish companies
poetry run python src/main.py --tickers "FRO,ZAL,TRMD A"
```

**Global companies** (via Börsdata Global instruments):
```bash
# US tech stocks
poetry run python src/main.py --tickers AAPL,MSFT,NVDA,META,TSLA

# Mixed global companies
poetry run python src/main.py --tickers AAPL,UBI,BABA
```

**Mixed analysis** (both Nordic and global - auto-detected):
```bash
poetry run python src/main.py --tickers "HM B,TELIA,AAPL,META"
```

**Quick test mode** (uses gpt-5-nano with fundamentals, technical, and sentiment analysts):
```bash
poetry run python src/main.py --tickers AAPL --test
```

### All CLI Options

```bash
poetry run python src/main.py \
  --tickers AAPL,MSFT \                    # Comma-separated tickers (auto-detects Nordic/Global)
  --analysts warren_buffett,peter_lynch \  # Specific analysts to use
  --analysts-all \                         # Use all 17 analysts
  --test \                                 # Quick test mode (gpt-5-nano, 3 analysts)
  --start-date 2024-01-01 \               # Analysis start date
  --end-date 2024-03-01 \                 # Analysis end date
  --initial-cash 100000 \                 # Starting capital
  --margin-requirement 0.5 \              # Margin requirement for shorts (50%)
  --show-reasoning \                      # Display agent reasoning
  --verbose \                             # Detailed logging
  --model-name gpt-4o \                   # Specific LLM model
  --model-provider openai                 # LLM provider (openai, anthropic, groq, ollama)
```

### Using Local LLMs (Ollama)

```bash
poetry run python src/main.py --tickers AAPL,MSFT,NVDA --ollama
```

---

## 2. Backtester CLI

Historical backtesting to evaluate strategy performance over time.

### Basic Usage

**Nordic/European companies:**
```bash
poetry run backtester --tickers TELIA,VOLV-B,ADVT
```

**Global companies:**
```bash
poetry run backtester --tickers AAPL,MSFT,NVDA
```

**Mixed analysis:**
```bash
poetry run backtester --tickers "TELIA,ADVT,AAPL,META"
```

### All CLI Options

```bash
poetry run backtester \
  --tickers AAPL,MSFT \                    # Comma-separated tickers (auto-detects Nordic/Global)
  --analysts fundamentals,technical \      # Specific analysts
  --analysts-all \                         # Use all analysts
  --test \                                 # Quick test mode
  --start-date 2024-01-01 \               # Backtest start date
  --end-date 2024-12-31 \                 # Backtest end date
  --initial-cash 100000 \                 # Starting capital
  --margin-requirement 0.5 \              # Margin for shorts
  --verbose \                             # Detailed output
  --model-name gpt-4o \                   # LLM model
  --model-provider openai                 # LLM provider
```

**Example Output:**

<img width="941" alt="Backtester Output" src="https://github.com/user-attachments/assets/00e794ea-8628-44e6-9a84-8f8a31ad3b47" />

---

## 3. Portfolio Manager CLI

Rebalance existing portfolios using AI analyst consensus for long-only concentrated positions (5-10 holdings).

### Basic Usage

**Starting from scratch (empty portfolio):**
```bash
poetry run python src/portfolio_manager.py \
  --portfolio portfolios/empty_portfolio.csv \
  --universe-tickers "AAPL,MSFT,NVDA,META,TSLA" \
  --analysts all
```

**Multi-currency portfolio with automatic market detection:**
```bash
poetry run python src/portfolio_manager.py \
  --portfolio example_portfolio.csv \
  --universe-tickers "FDEV,TRMD A,AAPL,META,STNG,SBOK,HIVE,MKO" \
  --analysts stanley_druckenmiller,technical_analyst,jim_simons,fundamentals_analyst \
  --model gpt-5-nano \
  --model-provider openai
```

**Output Example:**
```
ticker   shares  cost_basis  currency  date_acquired
TRMD A   77      500.0       DKK       2025-01-15
FDEV     2228    250.0       GBP       2025-01-15
CASH     100.0               SEK
SBOK     228     43.4        SEK       2025-10-01
CASH     48.19               USD
META     5       514.57      USD       2025-01-15
STNG     74      56.05       USD       2025-10-01
```

**Note**: The system automatically fetches correct currencies (GBP, DKK, SEK, USD) from Börsdata and rounds share quantities to whole numbers.

**Quick test with limited analysts:**
```bash
poetry run python src/portfolio_manager.py \
  --portfolio portfolio.csv \
  --universe-tickers "AAPL,MSFT" \
  --test
```

### All CLI Options

```bash
poetry run python src/portfolio_manager.py \
  --portfolio portfolio.csv \                # Path to current portfolio CSV
  --universe-tickers "AAPL,MSFT,TELIA" \    # Tickers to consider (auto-detected)
  --universe portfolio_universe.txt \       # Or path to universe file
  --analysts all \                          # Analyst selection (see below)
  --model gpt-4o \                          # LLM model
  --model-provider openai \                 # LLM provider
  --max-holdings 8 \                        # Maximum positions (default: 8)
  --max-position 0.25 \                     # Max position size (25%)
  --min-position 0.05 \                     # Min position size (5%)
  --min-trade 500 \                         # Min trade size in USD
  --verbose \                               # Show detailed analysis
  --dry-run \                               # Preview without saving
  --test                                    # Quick test mode (fundamentals only)
```

### Analyst Selection Options

- `"all"` - All 17 analysts with full LLM analysis (comprehensive consensus)
- `"famous"` - 13 famous investor personas (Buffett, Munger, Druckenmiller, etc.)
- `"core"` - 4 core analysts (Fundamentals, Technical, Sentiment, Valuation)
- `"basic"` - Fundamentals only (fast testing)
- Comma-separated list: `"warren_buffett,peter_lynch,fundamentals_analyst"`

### Portfolio CSV Format

**Input Portfolio:**
```csv
ticker,shares,cost_basis,currency,date_acquired
AAPL,100,150.50,USD,2024-01-15
MSFT,50,350.00,USD,2024-02-20
CASH,50000,,USD,
```

**Output** (automatically saved to `portfolio_YYYYMMDD.csv`):
```csv
ticker,shares,cost_basis,currency,date_acquired
AAPL,120,152.25,USD,2024-01-15
MSFT,50,350.00,USD,2024-02-20
NVDA,25,580.00,USD,2025-10-01
CASH,10000,,USD,
```

The system automatically saves rebalanced portfolios with today's date for iterative rebalancing.

---

## 🖥️ Web Application

The web application provides a user-friendly interface for those who prefer visual tools over command line.

Please see detailed instructions on how to install and run the web application [here](https://github.com/chhib/ai-hedge-fund/tree/main/app).

<img width="1721" alt="Web Interface" src="https://github.com/user-attachments/assets/b95ab696-c9f4-416c-9ad1-51feb1f5374b" />

---

## 📚 Documentation

### Börsdata API
- [Börsdata Documentation](docs/borsdata/) - Complete API reference, metrics mappings, and integration guide
- [Börsdata Swagger](docs/reference/swagger_v1.json) - OpenAPI specification

### Trading Strategies
- [Trading Agent Strategies](docs/trading_agent_strategies.md) - Detailed strategy implementations and thresholds for all 17 agents

### Project Documentation
- [docs/README.md](docs/README.md) - Full documentation index
- [docs/archive/](docs/archive/) - Historical migration documents

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: Please keep your pull requests small and focused. This will make it easier to review and merge.

---

## 💡 Feature Requests

If you have a feature request, please open an [issue](https://github.com/chhib/ai-hedge-fund/issues) and make sure it is tagged with `enhancement`.

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
