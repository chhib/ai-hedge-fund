# AI Hedge Fund -- Pod Shop

Fork of [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) rebuilt as a **trading pod shop**: 18 independent analyst pods, each proposing its own portfolio, tracked through paper trading, automatically promoted to live execution when they prove themselves, and managed by an always-on daemon scheduler.

Built on Borsdata (Nordic + Global data), Interactive Brokers execution, and a Decision DB that records every signal, aggregation, and trade as an append-only audit trail.

## Quick Start

```bash
# 1. Install
git clone https://github.com/chhib/ai-hedge-fund.git && cd ai-hedge-fund
poetry install
cp .env.example .env && $EDITOR .env   # At minimum: BORSDATA_API_KEY + one LLM key

# 2. Check pod configuration
poetry run hedge pods status

# 3. Start the daemon in dry-run (no trades, no LLM calls -- just scheduling)
poetry run hedge serve --dry-run

# 4. Run a real cycle for one pod with paper trading
poetry run hedge serve --pods fundamentals --model gpt-5-nano

# 5. When ready: run all pods
poetry run hedge serve --model gpt-5-nano --use-governor
```

The daemon runs a two-phase daily cycle per pod:
- **Phase 1 (Analysis)**: Pre-open -- run analysts, generate portfolio proposals
- **Phase 2 (Execution)**: Post-open -- validate price drift, execute trades (paper or live)

## Concepts

### Pods

A **pod** is one analyst wrapped in its own portfolio. Each pod independently:
- Analyzes the ticker universe through its analyst lens
- Proposes a portfolio (top picks with target weights)
- Tracks paper P&L with virtual positions and mark-to-market snapshots

All 18 pods are defined in `config/pods.yaml`. 1 pod = 1 analyst = 1 independent portfolio.

### Tiers: Paper and Live

Every pod starts on the **paper** tier (virtual trading only). Pods that prove themselves get promoted to **live** (real IBKR execution). Demoted pods go back to paper.

Even live pods maintain a **shadow paper portfolio** so their performance can always be measured for demotion decisions.

### Lifecycle Automation

The daemon evaluates pods automatically:

| Event | When | Criteria |
| --- | --- | --- |
| **Promotion** | Weekly (Monday 06:00 CET) | 30+ days history, Sharpe > 0.5, positive return, drawdown < 10% |
| **Maintenance demotion** | Weekly (Monday 06:00 CET) | Sharpe < 0.0 or drawdown > 10% |
| **Hard-stop demotion** | Every run (after Phase 2) | Drawdown > 10% from high-water mark |

Manual overrides: `hedge pods promote <pod>` / `hedge pods demote <pod>`. Overrides persist until the next automated evaluation.

### Decision DB

Every decision the system makes is recorded in `data/decisions.db` (SQLite, append-only):

| Table | What it stores |
| --- | --- |
| `runs` | Session metadata (pod, date, config) |
| `signals` | Per-analyst per-ticker signals with reasoning |
| `aggregations` | Weighted consensus scores |
| `governor_decisions` | Risk regime, deployment ratio, overrides |
| `trade_recommendations` | Final portfolio targets |
| `execution_outcomes` | Fill prices, rejections, order IDs |
| `pod_proposals` | Each pod's top picks and weights |
| `paper_positions` | Virtual portfolio holdings |
| `paper_snapshots` | Portfolio value time series |
| `pod_lifecycle_events` | Promotion/demotion audit trail |
| `daemon_runs` | Scheduling and phase execution state |

## Configuration

### config/pods.yaml

```yaml
defaults:
  max_picks: 3           # Picks per pod per cycle
  enabled: true
  tier: paper            # Starting tier
  starting_capital: 100000  # SEK
  schedule: nordic-morning

lifecycle:
  min_history_days: 30           # Days before promotion eligible
  promotion_sharpe: 0.5          # Annualized Sharpe threshold
  promotion_return_pct: 0.0      # Minimum cumulative return %
  promotion_drawdown_pct: 10.0   # Max drawdown from HWM
  maintenance_sharpe: 0.0        # Sharpe floor for live pods
  hard_stop_drawdown_pct: 10.0   # Immediate demotion trigger
  evaluation_schedule: weekly-monday

pods:
  - name: warren_buffett
    analyst: warren_buffett
  - name: fundamentals
    analyst: fundamentals_analyst
  # ... 18 pods total (13 famous investors + 4 core + 1 news sentiment)
```

### Schedule Presets

| Preset | Analysis | Execution | Days | Markets |
| --- | --- | --- | --- | --- |
| `nordic-morning` | 08:00 CET | 10:00 CET | Mon-Fri | SFB, CPH, OSE, HEL |
| `us-morning` | 09:00 ET | 10:30 ET | Mon-Fri | NYSE, NASDAQ, AMEX |
| `europe-morning` | 08:00 CET | 10:00 CET | Mon-Fri | XETRA, LSE, AEB |
| `weekly-nordic` | 08:00 CET | 10:00 CET | Monday | SFB, CPH, OSE, HEL |

Custom cron: set `schedule: "0 8 * * 1-5"` on any pod.

### Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `BORSDATA_API_KEY` | Yes | All data pulls (100 calls/10s rate limit) |
| `OPENAI_API_KEY` | Pick one | LLM-based analysts (OpenAI) |
| `ANTHROPIC_API_KEY` | Pick one | LLM-based analysts (Anthropic) |
| `GROQ_API_KEY` | Pick one | LLM-based analysts (Groq) |
| `DEEPSEEK_API_KEY` | Pick one | LLM-based analysts (DeepSeek) |

IBKR credentials are not stored in `.env` -- run the Client Portal Gateway locally and supply host/port flags.

## CLI Reference

### Daemon

```bash
hedge serve [OPTIONS]
```

Start the always-on pod scheduler. Runs in foreground; Ctrl-C to stop.

| Flag | Default | Description |
| --- | --- | --- |
| `--pods` | `all` | Pod selection: `all` or comma-separated names |
| `--dry-run` | | Log scheduling without executing |
| `--model` | `gpt-4o` | LLM model name |
| `--drift-threshold` | `0.05` | Price drift tolerance for Phase 2 revalidation |
| `--use-governor` | | Enable preservation-first portfolio governor |
| `--portfolio-source` | `csv` | `csv` or `ibkr` |
| `--universe` | | Path to universe file |
| `--max-workers` | `50` | Parallel worker cap |
| `--max-holdings` | `8` | Maximum holdings per pod |
| `--verbose` | | Show detailed output |

### Pod Management

```bash
hedge pods status                  # Show all pods with tier, metrics, lifecycle events
hedge pods promote <pod_name>      # Manually promote to live
hedge pods demote <pod_name>       # Manually demote to paper
```

`hedge pods status` displays per pod: effective tier, days in tier, next evaluation date, latest lifecycle event, and performance metrics (value, return%, Sharpe, drawdown, win rate, trades).

### Rebalance (single run)

```bash
hedge rebalance [OPTIONS]
```

Run a single analysis + execution cycle instead of the daemon loop. Useful for testing.

| Flag | Default | Description |
| --- | --- | --- |
| `--portfolio` | | Current holdings CSV |
| `--universe` | | Universe file path |
| `--pods` | | Pod selection (all or comma-separated) |
| `--model` | `gpt-4o` | LLM model |
| `--analysts` | `all` | Analyst preset or comma-separated list |
| `--dry-run` | | Show recommendations without saving |
| `--test` | | Quick validation (fundamentals only) |
| `--export-transcript` | | Dump analyst reasoning to markdown |
| `--use-governor` | | Enable portfolio governor |
| `--portfolio-source` | `csv` | `csv` or `ibkr` |
| `--ibkr-whatif` | | Preview orders without placing |
| `--ibkr-execute` | | Submit orders after preview |
| `--ibkr-yes` | | Auto-confirm (skip per-order prompt) |
| `--tier` | | Override pod tier (paper/live) |

### IBKR Tools

```bash
hedge ibkr check                   # Validate all 5 IBKR pipeline stages
hedge ibkr validate                # Check contract overrides for staleness
hedge ibkr validate --fix          # Auto-refresh invalid contracts
hedge ibkr orders                  # Show live orders from the gateway
```

### Other Commands

```bash
hedge backtest                     # Historical backtesting with analyst pipeline
hedge governor status              # Show governor state (regime, deployment ratio)
hedge scorecard                    # Analyst prediction accuracy (hit rate, alpha)
hedge cache list                   # Show cached tickers
hedge cache clear                  # Clear cache (--tickers DORO,LUND.B for specific)
```

### Analyst Presets

| Preset | Count | Members |
| --- | --- | --- |
| `favorites` | 5 | fundamentals, technical, jim_simons, news_sentiment, stanley_druckenmiller |
| `core` | 4 | fundamentals, technical, sentiment, valuation |
| `famous` | 13 | All 13 investor personas |
| `all` | 17 | All personas + core analysts |
| `basic` | 1 | fundamentals only (fast testing) |

## Web Dashboard

```bash
# Backend (FastAPI)
poetry run uvicorn app.backend.main:app --reload

# Frontend (Vite + React) -- separate terminal
cd app/frontend && npm install && npm run dev
```

The pod dashboard shows all pods with status cards, lifecycle history, promote/demote actions, and portfolio proposals.

### API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/pods` | List all pods with status and metrics |
| `GET` | `/pods/config` | Lifecycle configuration |
| `GET` | `/pods/{pod_id}/history` | Lifecycle event history |
| `GET` | `/pods/{pod_id}/proposals` | Latest portfolio proposals |
| `POST` | `/pods/{pod_id}/promote` | Manually promote pod |
| `POST` | `/pods/{pod_id}/demote` | Manually demote pod |

## Testing & Validation

### Tier 1: Offline (no external services needed)

```bash
# Run the full test suite
poetry run pytest

# Validate pod configuration loads correctly
poetry run python -c "from src.config.pod_config import load_pods, load_lifecycle_config; pods = load_pods(); lc = load_lifecycle_config(); print(f'{len(pods)} pods loaded, lifecycle: sharpe>{lc.promotion_sharpe}, dd<{lc.promotion_drawdown_pct}%')"

# Verify CLI commands parse
poetry run hedge --help
poetry run hedge serve --help
poetry run hedge pods --help
```

### Tier 2: Paper Trading (needs Borsdata API key + LLM key)

```bash
# 1. Check pod status (will show empty metrics if no runs yet)
poetry run hedge pods status

# 2. Start daemon in dry-run to verify scheduling
poetry run hedge serve --dry-run --verbose

# 3. Run a single pod cycle (paper trading, one cheap analyst)
poetry run hedge rebalance \
  --pods fundamentals \
  --universe portfolios/borsdata_universe.txt \
  --model gpt-5-nano \
  --tier paper \
  --verbose

# 4. Check that paper positions and proposals were recorded
poetry run hedge pods status

# 5. Run the daemon for one pod to verify the full two-phase cycle
poetry run hedge serve --pods fundamentals --model gpt-5-nano --verbose
# Wait for Phase 1 + Phase 2 to complete, then Ctrl-C

# 6. Verify Decision DB has data
sqlite3 data/decisions.db "SELECT pod_id, COUNT(*) FROM pod_proposals GROUP BY pod_id;"
sqlite3 data/decisions.db "SELECT pod_id, total_value, cumulative_return_pct FROM paper_snapshots ORDER BY created_at DESC LIMIT 5;"
```

### Tier 3: IBKR Integration (when gateway is available)

```bash
# 1. Start the Client Portal Gateway
cd clientportal.gw && bin/run.sh root/conf.yaml
# Authenticate at https://localhost:5001

# 2. Validate all 5 pipeline stages
poetry run hedge ibkr check

# 3. Validate contract overrides
poetry run hedge ibkr validate

# 4. Preview orders (what-if, no trades placed)
poetry run hedge rebalance \
  --portfolio-source ibkr \
  --universe portfolios/borsdata_universe.txt \
  --model gpt-5-nano \
  --analysts favorites \
  --use-governor \
  --ibkr-whatif

# 5. Run daemon with IBKR (still paper tier -- no live trades)
poetry run hedge serve \
  --portfolio-source ibkr \
  --model gpt-5-nano \
  --use-governor \
  --verbose

# 6. When a pod is promoted to live, orders go to IBKR
#    Monitor with:
poetry run hedge ibkr orders
```

### Quick Smoke Test (30 random tickers, ~2 min)

```bash
tickers=$(python3 -c "
import random
from pathlib import Path
universe = [l.strip() for l in Path('portfolios/borsdata_universe.txt').read_text().splitlines()
            if l.strip() and not l.startswith('#')]
print(','.join(random.sample(universe, 30)))
")

poetry run hedge rebalance \
  --universe-tickers "$tickers" \
  --model gpt-5-nano \
  --analysts fundamentals_analyst \
  --dry-run --test --max-workers 1 \
  --export-transcript
```

## Architecture

```
Borsdata API --> Parallel Fetcher --> 3-Layer Cache --> 18 Analyst Pods --> Pod Proposals
                                                                               |
                                                                    Decision DB (audit trail)
                                                                               |
                                                              Portfolio Governor (risk gating)
                                                                               |
                                                               Paper Engine / IBKR Execution
                                                                               |
                                                               Daemon Scheduler (APScheduler)
                                                                               |
                                                               Lifecycle Evaluator (promote/demote)
```

**Cache layers**: In-memory LLM cache, SQLite KPI/signal cache (`data/prefetch_cache.db`), durable task queue (`data/analyst_tasks.db`).

## Legacy CLI

The original `hedge rebalance` workflow (single-run, CSV portfolio, no pods) still works. See [README_LEGACY.md](README_LEGACY.md) for the full reference.

```bash
# Legacy single-run rebalance
poetry run hedge rebalance \
  --portfolio portfolio_20251220_actual.csv \
  --universe portfolios/borsdata_universe.txt \
  --model gpt-5-nano \
  --analysts favorites \
  --use-governor
```

## Project Structure

```
ai-hedge-fund/
  app/              Web UI (FastAPI backend + Vite/React frontend)
  clientportal.gw/  IBKR Client Portal Gateway
  config/           pods.yaml (pod definitions, lifecycle thresholds, schedules)
  data/             decisions.db, contract mappings, SQLite caches
  docs/             Brainstorms, plans, solutions, Borsdata docs
  logs/             Session logs and PROJECT_SUMMARY.md
  portfolios/       Universe files and portfolio CSVs
  src/
    agents/         18 analyst agents + portfolio managers
    cli/            Click-based hedge CLI (hedge.py)
    config/         Pod config loader (pod_config.py)
    data/           Borsdata client, Decision DB store, caching
    integrations/   IBKR client, contract mapper, execution
    llm/            LLM provider abstraction and caching
    services/       Daemon, pod lifecycle, paper trading, portfolio runner
    tools/          Agent tool definitions
  tests/            pytest suite
```

## Disclaimer

This is an educational research project. No warranties. Do your own due diligence and consult professionals before investing real capital.

## License

Same as upstream (see `LICENSE`).
