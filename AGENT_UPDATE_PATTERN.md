# Agent Update Pattern for next_ticker Support

## Overview
To support the new progress tracking with "Next up: TICKER" display, agents need two small changes:

1. Extract `next_ticker` from state data
2. Pass `next_ticker` to `progress.update_status()` when calling with "Done" status

## Already Updated Agents
✅ stanley_druckenmiller.py
✅ jim_simons.py
✅ warren_buffett.py
✅ michael_burry.py
✅ phil_fisher.py
✅ charlie_munger.py
✅ bill_ackman.py
✅ cathie_wood.py
✅ peter_lynch.py
✅ rakesh_jhunjhunwala.py
✅ ben_graham.py
✅ mohnish_pabrai.py
✅ aswath_damodaran.py
✅ fundamentals.py
✅ technicals.py
✅ sentiment.py
✅ valuation.py

## Agents Not Requiring Updates
❌ risk_manager.py - Not applicable (does not follow per-ticker Done pattern)
❌ portfolio_manager.py - Not applicable (does not follow per-ticker Done pattern)
❌ enhanced_portfolio_manager.py - Already handles next_ticker correctly

## Update Pattern

### Step 1: Extract next_ticker from state data

Find this section near the top of the agent function:
```python
def some_agent(state: AgentState):
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
```

Add this line after `tickers`:
```python
    next_ticker = data.get("next_ticker")  # For progress tracking
```

### Step 2: Update progress.update_status calls

Find this line (typically near the end of the ticker loop):
```python
progress.update_status(agent_name, ticker, "Done", analysis=...)
```

Change to:
```python
progress.update_status(agent_name, ticker, "Done", analysis=..., next_ticker=next_ticker)
```

## Example

### Before:
```python
def some_agent(state: AgentState):
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]

    for ticker in tickers:
        # ... analysis code ...

        progress.update_status(agent_name, ticker, "Done", analysis=result.reasoning)
```

### After:
```python
def some_agent(state: AgentState):
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    next_ticker = data.get("next_ticker")  # For progress tracking

    for ticker in tickers:
        # ... analysis code ...

        progress.update_status(agent_name, ticker, "Done", analysis=result.reasoning, next_ticker=next_ticker)
```

## Quick Update Commands

For each agent file, you can use these sed commands:

```bash
# Add next_ticker extraction (after tickers line)
sed -i'.bak' '/tickers = data\["tickers"\]/a\    next_ticker = data.get("next_ticker")  # For progress tracking' src/agents/AGENT_FILE.py

# Update progress.update_status calls
sed -i'.bak' 's/progress\.update_status(\(.*\), "Done", analysis=\(.*\))/progress.update_status(\1, "Done", analysis=\2, next_ticker=next_ticker)/' src/agents/AGENT_FILE.py
```

Replace `AGENT_FILE.py` with the actual filename.

## Verification

After updating, verify the changes work by:
1. Running the hedge fund with the agent: `poetry run python src/main.py --tickers AAPL`
2. Check that progress display shows "Next up: TICKER" format
3. Ensure no errors about missing `next_ticker` parameter

## Notes

- The `next_ticker` parameter is optional, so agents will still work without it (they just won't show "Next up" indicator)
- If an agent processes only one ticker, `next_ticker` will be `None` and that's fine
- enhanced_portfolio_manager.py already handles next_ticker correctly