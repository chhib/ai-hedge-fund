# AI Hedge Fund -- Borsdata Edition

Fork of [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) rebuilt around Borsdata's Nordic + Global coverage, concentrated long-only portfolios, 18 analyst agents, and Interactive Brokers execution.

## Quick Start

```bash
poetry run hedge rebalance \
  --portfolio portfolio_20251220_actual.csv \
  --universe portfolios/borsdata_universe.txt \
  --model gpt-5-nano \
  --analysts favorites
```

That's the weekly command: load current holdings CSV, score every ticker in the 206-ticker universe with the selected analysts, and output `portfolio_YYYYMMDD.csv` for next week.

## Why This Fork

- **Borsdata-first**: 108 KPI mappings, Nordic + Global tickers, rate-limited parallel fetcher, insider trades, report calendars, cached price history. Zero legacy FinancialDatasets code.
- **Concentrated long-only**: 5-10 holdings, multi-currency cost basis (SEK default), ATR-derived slippage bands, deterministic analysts mixed with LLM personas.
- **18 analysts**: 13 legendary investor personas + 5 core deterministic analysts (including position-aware news sentiment that analyzes events since each holding's acquisition date).
- **IBKR execution**: Live positions, order preview (`--ibkr-whatif`), execution (`--ibkr-execute`), ISIN-based contract resolution with 96% universe coverage.
- **Crash recovery**: Analyst x ticker tasks recorded in SQLite so same-day reruns reuse cached signals even after crashes or network loss.

## Installation

```bash
git clone https://github.com/chhib/ai-hedge-fund.git
cd ai-hedge-fund
poetry install
cp .env.example .env
$EDITOR .env
```

| Variable | Required | Purpose |
| --- | --- | --- |
| `BORSDATA_API_KEY` | Yes | All data pulls (100 calls/10s rate limit) |
| `OPENAI_API_KEY` | Pick one | LLM-based analysts (OpenAI) |
| `ANTHROPIC_API_KEY` | Pick one | LLM-based analysts (Anthropic) |
| `GROQ_API_KEY` | Pick one | LLM-based analysts (Groq) |
| `DEEPSEEK_API_KEY` | Pick one | LLM-based analysts (DeepSeek) |
| IBKR Gateway | Optional | Live positions and order execution |

IBKR credentials aren't stored in `.env`; run the Client Portal Gateway locally and supply host/port flags.

## CLI Reference

### Primary commands

| Command | Description |
| --- | --- |
| `hedge rebalance` | Weekly rebalance (CSV or live IBKR positions) |
| `hedge backtest` | Headless backtesting with the same analyst pipeline |
| `hedge ibkr check` | Validate all 5 IBKR pipeline stages against the live gateway |
| `hedge ibkr validate` | Check contract overrides for staleness (`--fix` to auto-refresh) |
| `hedge ibkr orders` | Show live orders from the IBKR gateway |
| `hedge cache list` | List all tickers currently in the cache |
| `hedge cache clear` | Clear cache entries (`--tickers DORO,LUND.B` or all) |

### Rebalance flags

| Flag | Default | Description |
| --- | --- | --- |
| `--portfolio` | | Path to current holdings CSV |
| `--universe` | | Path to universe file (e.g. `portfolios/borsdata_universe.txt`) |
| `--universe-tickers` | | Comma-separated tickers inline (alternative to `--universe`) |
| `--analysts` | `all` | Preset name or comma-separated list |
| `--model` | `gpt-4o` | LLM model name |
| `--home-currency` | `SEK` | Reporting currency |
| `--max-workers` | `8` | Parallel workers (also `PARALLEL_MAX_WORKERS` env var) |
| `--no-cache` | | Bypass KPI cache |
| `--no-cache-agents` | | Bypass analyst signal cache |
| `--export-transcript` | | Dump analyst markdown transcript after the run |
| `--portfolio-source` | `csv` | `csv` or `ibkr` |
| `--ibkr-account` | | Force a specific IBKR account ID |
| `--ibkr-whatif` | | Preview orders without placing them |
| `--ibkr-execute` | | Submit orders after preview |
| `--ibkr-yes` | | Auto-confirm orders (skip per-order prompt) |
| `--dry-run` | | Disables execution even if `--ibkr-execute` is set |

### Legacy entry points

| Command | Description |
| --- | --- |
| `python src/main.py` | LangGraph multi-agent workflow for ad-hoc analysis |
| `python src/portfolio_manager.py` | Legacy rebalance CLI (same options as `hedge rebalance`) |
| `poetry run backtester` | Original backtester with interactive prompts |

### Web UI

```bash
# Backend
poetry run uvicorn app.backend.main:app --reload

# Frontend (Vite + React)
cd app/frontend && npm install && npm run dev
```

## Analyst Presets

| Preset | Count | Members |
| --- | --- | --- |
| `favorites` | 5 | fundamentals, technical, jim_simons, news_sentiment, stanley_druckenmiller |
| `core` | 4 | fundamentals, technical, sentiment, valuation |
| `famous` | 13 | All 13 investor personas |
| `all` | 17 | All investor personas + core analysts |
| `basic` | 1 | fundamentals only (fast testing) |

Custom: pass a comma-separated list, e.g. `--analysts warren_buffett,peter_lynch,fundamentals`.

## Analyst Roster

### Investor personas (13, LLM-based)

| Agent | Style |
| --- | --- |
| Warren Buffett | The Oracle of Omaha -- quality compounders at fair prices |
| Charlie Munger | The Rational Thinker -- mental models and margin of safety |
| Stanley Druckenmiller | The Macro Investor -- top-down macro with bottom-up stock picks |
| Peter Lynch | The 10-Bagger Hunter -- growth at a reasonable price |
| Ben Graham | The Father of Value Investing -- deep value and net-nets |
| Phil Fisher | The Scuttlebutt Investor -- qualitative growth analysis |
| Bill Ackman | The Activist Investor -- concentrated positions in catalysts |
| Cathie Wood | The Queen of Growth -- disruptive innovation and ARK-style bets |
| Michael Burry | The Big Short Contrarian -- deep dives into overlooked value |
| Mohnish Pabrai | The Dhandho Investor -- low risk, high uncertainty bets |
| Rakesh Jhunjhunwala | The Big Bull of India -- emerging-market growth plays |
| Aswath Damodaran | The Dean of Valuation -- DCF and intrinsic value models |
| Jim Simons | The Quant King -- statistical arbitrage and mean reversion |

### Core analysts (5, deterministic)

| Agent | Focus |
| --- | --- |
| Fundamentals | Financial statement analysis -- margins, growth, returns |
| Technical | Chart patterns -- moving averages, RSI, volume |
| Sentiment | Market sentiment -- insider activity, report calendars |
| Valuation | Intrinsic value -- DCF, comparables, owner earnings |
| News Sentiment | Position-aware news analysis -- events since acquisition date for existing holdings, last 30 days for new candidates |

## IBKR Integration

### Gateway setup

```bash
cd clientportal.gw && bin/run.sh root/conf.yaml
# Authenticate at https://localhost:5001
```

### Preview and execution

```bash
# Preview only (no trades placed)
poetry run hedge rebalance \
  --portfolio-source ibkr \
  --universe portfolios/borsdata_universe.txt \
  --analysts favorites \
  --ibkr-whatif

# Execute with per-order confirmation
poetry run hedge rebalance \
  --portfolio-source ibkr --ibkr-execute

# Execute without confirmation (use with caution)
poetry run hedge rebalance \
  --portfolio-source ibkr --ibkr-execute --ibkr-yes
```

### Contract overrides

When IBKR returns multiple contract matches for a ticker, execution skips that order for safety. Provide explicit overrides in `data/ibkr_contract_mappings.json`:

```json
{
  "contracts": {
    "LUG": { "conid": 123456, "exchange": "TSE", "currency": "CAD" },
    "FDEV": { "conid": 234567, "exchange": "LSE", "currency": "GBP" }
  }
}
```

Validate overrides haven't gone stale:

```bash
poetry run hedge ibkr validate            # Check all overrides
poetry run hedge ibkr validate --fix      # Auto-refresh invalid contracts
poetry run hedge ibkr orders              # Show live orders
```

### Trading permissions

If preview responses show `No trading permissions`, the preview loop aborts. Update your IBKR trading permissions for the relevant markets and re-run.

## Architecture

```
Borsdata API --> Parallel Fetcher --> 3-Layer Cache --> 18 Analysts --> Portfolio Manager
                                                                             |
                                                                    IBKR Client Portal
                                                                             |
                                                                     Order Execution
```

**Cache layers**: In-memory LLM cache, SQLite KPI/signal cache (`data/prefetch_cache.db`), durable task queue (`data/analyst_tasks.db`).

### Key source files

| File | Purpose |
| --- | --- |
| `src/cli/hedge.py` | Click-based unified CLI |
| `src/services/portfolio_runner.py` | Rebalance orchestration and analyst preset resolution |
| `src/agents/enhanced_portfolio_manager.py` | Portfolio management with parallel LLM coordination |
| `src/data/borsdata_client.py` | Core API client with rate limiting |
| `src/data/parallel_api_wrapper.py` | Parallel data fetching with caching |
| `src/data/borsdata_metrics_mapping.py` | 108 KPI mappings (Borsdata to financial metrics) |
| `src/data/analyst_task_queue.py` | Durable analyst x ticker task tracking |
| `src/data/prefetch_store.py` | SQLite KPI/metrics cache |
| `src/integrations/ibkr_client.py` | IBKR Client Portal integration |
| `src/integrations/ibkr_execution.py` | Order preview and execution |
| `src/integrations/ibkr_contract_mapper.py` | ISIN-based contract resolution |

## Testing

```bash
poetry run pytest                         # All 140 tests
poetry run pytest tests/integrations/     # IBKR tests
poetry run pytest tests/data/             # Data layer tests
poetry run pytest tests/backtesting/      # Backtesting tests
```

### Smoke test (30 random tickers)

```bash
tickers=$(python3 -c "
import random
from pathlib import Path
universe = [l.strip() for l in Path('portfolios/borsdata_universe.txt').read_text().splitlines()
            if l.strip() and not l.startswith('#')]
print(','.join(random.sample(universe, 30)))
")

poetry run hedge rebalance \
  --portfolio example_portfolio.csv \
  --universe-tickers "$tickers" \
  --model gpt-5-nano \
  --analysts fundamentals_analyst \
  --dry-run --test --max-workers 1 \
  --export-transcript
```

## Project Structure

```
ai-hedge-fund/
  app/              Web UI (FastAPI backend + Vite/React frontend)
  clientportal.gw/  IBKR Client Portal Gateway
  data/             Contract mappings, SQLite caches, task queue DB
  docs/             Borsdata endpoint mappings, KPI schemas, migration notes
  logs/             Session logs and project summary
  portfolios/       Universe files and portfolio CSVs
  scripts/          Utility scripts (universe builder, etc.)
  src/
    agents/         18 analyst agents + portfolio managers
    cli/            Click-based hedge CLI
    data/           Borsdata client, caching, KPI assembly
    integrations/   IBKR client, contract mapper, execution
    llm/            LLM provider abstraction and caching
    services/       Rebalance orchestration
    tools/          Agent tool definitions
  tests/            140 tests (data, integrations, backtesting)
```

## Disclaimer

This is an educational research project. No warranties. Do your own due diligence and consult professionals before investing real capital.

## License

Same as upstream (see `LICENSE`).
