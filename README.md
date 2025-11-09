# AI Hedge Fund – Börsdata Edition

Modernized fork of `virattt/ai-hedge-fund` tuned for Börsdata’s Nordic + Global coverage, long-only portfolio management, and weekly rebalance workflows. All data pulls rely on Börsdata, LLM access is abstracted behind the agents, and Interactive Brokers (IBKR) positions can be imported directly from the Client Portal API.

---

## TL;DR – Weekly Command I Actually Run

```bash
poetry run python src/portfolio_manager.py \
  --portfolio portfolio_20251107_actual.csv \
  --universe portfolios/borsdata_universe.txt \
  --model gpt-5-nano \
  --analysts stanley_druckenmiller,technical_analyst,jim_simons,fundamentals_analyst,news_sentiment_analyst
```

That command (now also available as `poetry run hedge rebalance ...`) is the core workflow: load the current IBKR-exported CSV, score every ticker in `borsdata_universe.txt` with the selected analysts, and save `portfolio_YYYYMMDD.csv` ready for the next week. A new Typer CLI mirrors the legacy Click script but adds shortcuts for IBKR ingestion, transcript exports, and backtesting.

---

## Why This Fork Exists

- **Börsdata-first ingestion**: Nordic + Global tickers, rate limiting, KPI/line-item assemblers, insider trades, calendars, and cached price history.
- **Concentrated long-only portfolios**: 5–10 holdings, multi-currency cost basis, ATR-derived slippage bands, deterministic analysts mixed with LLM personas.
- **Durable analyst queue**: Analyst×ticker tasks are recorded in `data/analyst_tasks.db`, so same-day reruns reuse cached signals even if the previous session crashed or you temporarily lost network access.
- **Agent ergonomics**: 17 analysts (13 legendary investor personas + 4 core analysts + news sentiment) driven via `EnhancedPortfolioManager` with automatic parallel prefetch, caching, and transcript storage.
- **Unified CLI**: `poetry run hedge rebalance` (weekly), `poetry run hedge backtest`, plus the original `src/main.py` (graph-based analysis) and FastAPI app for the React UI.

---

## Installation

```bash
git clone https://github.com/chhib/ai-hedge-fund.git
cd ai-hedge-fund

# install dependencies
curl -sSL https://install.python-poetry.org | python3 -  # if Poetry is missing
poetry install

# configure API keys
cp .env.example .env
$EDITOR .env   # set BORSDATA_API_KEY + preferred LLM keys
```

**Required keys**

| Variable | Purpose |
| --- | --- |
| `BORSDATA_API_KEY` | Mandatory for all data pulls |
| `OPENAI_API_KEY` (or Groq/Anthropic/Deepseek/Ollama) | Needed for LLM-based analysts |

Optional: `IBKR_CLIENT_PORTAL` credentials aren’t stored in `.env`; run the local Client Portal Gateway and supply host/port flags when using `--portfolio-source ibkr`.

---

## Command Surface

| Command | When to use |
| --- | --- |
| `poetry run hedge rebalance ...` | Weekly rebalance (CSV or live IBKR positions) with automatic transcript export option |
| `poetry run python src/portfolio_manager.py ...` | Legacy Click CLI (same functionality, still handy for scripted runs) |
| `poetry run hedge backtest ...` | Headless backtesting using the new Typer CLI (no interactive prompts) |
| `poetry run python src/backtester.py ...` | Original backtester with interactive questionary prompts |
| `poetry run python src/main.py ...` | Run the LangGraph multi-agent workflow for ad-hoc analysis |
| `poetry run uvicorn app.backend.main:app --reload` | Start the FastAPI backend powering the React UI (`app/frontend`) |

### Rebalance (Typer CLI)

```bash
poetry run hedge rebalance \
  --portfolio portfolio_20251107_actual.csv \
  --universe portfolios/borsdata_universe.txt \
  --model gpt-5-nano \
  --analysts stanley_druckenmiller,technical_analyst,jim_simons,fundamentals_analyst,news_sentiment_analyst \
  --export-transcript
```

Key flags:

- `--portfolio-source ibkr` – Pull holdings/cash straight from IBKR Client Portal gateway.
- `--ibkr-account U1234567` – Force a specific account (defaults to the first returned account).
- `--no-cache` / `--no-cache-agents` – Control KPI/analyst caching when you need a clean slate.
- `--max-workers 4` – Tune concurrency to stay under the Börsdata 100 calls/10s limit.
- `--export-transcript` – Immediately dump the analyst markdown transcript after the run.

### Rebalance (legacy Click)

Exactly the same options as the Typer CLI, still available if you prefer:

```bash
poetry run python src/portfolio_manager.py --help
```

### Backtest (Typer)

```bash
poetry run hedge backtest \
  --tickers AAPL,MSFT,NVDA \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --initial-capital 150000 \
  --analysts warren_buffett,charlie_munger \
  --model-name gpt-4o
```

Behind the scenes this wires `BacktestEngine` with the same prefetch + analyst graph infrastructure used in live runs.

### LangGraph Analysis CLI

```bash
poetry run python src/main.py --tickers "HM B,TELIA,AAPL" --analysts-all --model-name gpt-4o --model-provider openai
```

### Web UI

```bash
# backend
poetry run uvicorn app.backend.main:app --reload

# frontend (Vite + React)
cd app/frontend && npm install && npm run dev
```

---

## Analyst Architecture

- **Core deterministic analysts**: fundamentals, technicals, valuation, sentiment, news sentiment.
- **Investor personas**: Warren Buffett, Charlie Munger, Stanley Druckenmiller, Peter Lynch, Ben Graham, Phil Fisher, Bill Ackman, Cathie Wood, Michael Burry, Mohnish Pabrai, Rakesh Jhunjhunwala, Aswath Damodaran, Jim Simons.
- **Task Queue**: `src/data/analyst_task_queue.py` records each analyst×ticker×model combo per analysis date so cached outputs are reused if you rerun the same day (post-crash or after toggling analysts back on). Coupled with `src/data/analysis_cache.py` for actual signal storage.
- **Transcript storage**: analyst reasoning per ticker is stored in `app/backend/hedge_fund.db` via `src/data/analysis_storage.py`; export via CLI prompt or `--export-transcript`.

---

## Working With IBKR

1. Start the IBKR Client Portal Gateway locally (default `https://localhost:5000`).
2. Run `poetry run hedge rebalance --portfolio-source ibkr --ibkr-account <acct>` (host/port flags available if you proxy the gateway).
3. The new `IBKRClient` maps positions + ledger cash into the same `Portfolio` dataclass consumed by the manager, so you can switch between CSV snapshots and live pulls without touching downstream logic.

---

## Testing

```bash
PYTHONPATH=. pytest \
  tests/data/test_analyst_task_queue.py \
  tests/integrations/test_ibkr_client.py \
  tests/test_enhanced_portfolio_manager.py
```

- Add Börsdata fixtures under `tests/fixtures/` when covering new endpoints.
- Respect the 100 calls/10 seconds rule in any new integration tests (use recorded fixtures or the cache).

### Manual Smoke Test (30 random tickers)

```bash
tickers=$(python - <<'PY'
import random
from pathlib import Path
universe = [line.strip() for line in Path('portfolios/borsdata_universe.txt').read_text().splitlines() if line.strip() and not line.startswith('#')]
print(','.join(random.sample(universe, 30)))
PY
)

poetry run hedge rebalance \
  --portfolio example_portfolio.csv \
  --universe-tickers "$tickers" \
  --model gpt-5-nano \
  --analysts fundamentals_analyst \
  --dry-run --test --max-workers 1 \
  --export-transcript
```

This verifies Börsdata connectivity, the Typer CLI, transcript exports, and the analyst task queue on a smaller universe before running the full weekly job.

---

## Documentation

- `PROJECT_LOG.md` – authoritative session log + decisions; update at the end of every working session.
- `docs/borsdata_integration_plan.md`, `docs/reference/` – endpoint mappings, KPI schemas, and migration notes.
- `README_Borsdata_API.md` – summarized API instructions pulled from the official swagger.

---

## Disclaimer

Educational research only. No live trading. No warranties. Do your own diligence and consult professionals before investing real capital.

---

## License

Same as upstream (see `LICENSE`).
