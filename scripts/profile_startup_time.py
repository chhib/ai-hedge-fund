#!/usr/bin/env python3
"""
Profile startup and initialization time for the AI hedge fund system.

Measures:
- Python startup time
- Import times for key modules
- Client initialization time
- Cache loading time
"""

import time
import sys
import os

# Measure basic Python startup
_script_start = time.time()

print("="*80)
print("STARTUP TIME PROFILING")
print("="*80)
print(f"\nScript started at: {time.time():.3f}")

# Measure environment loading
env_start = time.time()
from dotenv import load_dotenv
load_dotenv()
env_time = time.time() - env_start
print(f"✓ Load .env:                    {env_time:6.3f}s")

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Measure imports individually
print("\nImporting core modules...")

import_start = time.time()
from datetime import datetime, timedelta
datetime_time = time.time() - import_start
print(f"  datetime:                     {datetime_time:6.3f}s")

import_start = time.time()
import numpy as np
import pandas as pd
numpy_time = time.time() - import_start
print(f"  numpy + pandas:               {numpy_time:6.3f}s")

import_start = time.time()
from pydantic import BaseModel
pydantic_time = time.time() - import_start
print(f"  pydantic:                     {pydantic_time:6.3f}s")

import_start = time.time()
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
langchain_time = time.time() - import_start
print(f"  langchain:                    {langchain_time:6.3f}s")

print("\nImporting project modules...")

import_start = time.time()
from src.data.borsdata_client import BorsdataClient
borsdata_client_time = time.time() - import_start
print(f"  src.data.borsdata_client:     {borsdata_client_time:6.3f}s")

import_start = time.time()
from src.tools.api import (
    search_line_items, get_financial_metrics, get_prices,
    get_insider_trades, get_company_events, get_market_cap, set_ticker_markets
)
api_time = time.time() - import_start
print(f"  src.tools.api:                {api_time:6.3f}s")

import_start = time.time()
from src.graph.state import AgentState
state_time = time.time() - import_start
print(f"  src.graph.state:              {state_time:6.3f}s")

import_start = time.time()
from src.utils.analysts import ANALYST_CONFIG
analysts_time = time.time() - import_start
print(f"  src.utils.analysts:           {analysts_time:6.3f}s")

# Measure individual agent imports
print("\nImporting agent modules...")
agent_import_times = {}

agents = [
    ("aswath_damodaran", "src.agents.aswath_damodaran"),
    ("ben_graham", "src.agents.ben_graham"),
    ("bill_ackman", "src.agents.bill_ackman"),
    ("cathie_wood", "src.agents.cathie_wood"),
    ("charlie_munger", "src.agents.charlie_munger"),
    ("fundamentals", "src.agents.fundamentals"),
    ("michael_burry", "src.agents.michael_burry"),
    ("phil_fisher", "src.agents.phil_fisher"),
    ("peter_lynch", "src.agents.peter_lynch"),
    ("sentiment", "src.agents.sentiment"),
    ("stanley_druckenmiller", "src.agents.stanley_druckenmiller"),
    ("technicals", "src.agents.technicals"),
    ("valuation", "src.agents.valuation"),
    ("warren_buffett", "src.agents.warren_buffett"),
    ("rakesh_jhunjhunwala", "src.agents.rakesh_jhunjhunwala"),
    ("mohnish_pabrai", "src.agents.mohnish_pabrai"),
    ("jim_simons", "src.agents.jim_simons"),
]

total_agent_import_time = 0
for agent_name, module_path in agents:
    import_start = time.time()
    __import__(module_path)
    import_time = time.time() - import_start
    agent_import_times[agent_name] = import_time
    total_agent_import_time += import_time
    print(f"  {module_path:<40} {import_time:6.3f}s")

print(f"\n  Total agent imports:          {total_agent_import_time:6.3f}s")

# Measure client initialization
print("\nInitializing Börsdata client...")

init_start = time.time()
client = BorsdataClient()
client_init_time = time.time() - init_start
print(f"  BorsdataClient():             {client_init_time:6.3f}s")

# Measure cache population
print("\nPopulating instrument caches...")

cache_start = time.time()
client.get_instruments()
nordic_cache_time = time.time() - cache_start
print(f"  get_instruments() [Nordic]:   {nordic_cache_time:6.3f}s")

cache_start = time.time()
client.get_all_instruments()
global_cache_time = time.time() - cache_start
print(f"  get_all_instruments() [Global]: {global_cache_time:6.3f}s")

total_cache_time = nordic_cache_time + global_cache_time
print(f"  Total cache population:       {total_cache_time:6.3f}s")

# Calculate totals
total_startup_time = time.time() - _script_start
total_import_time = (env_time + datetime_time + numpy_time + pydantic_time +
                    langchain_time + borsdata_client_time + api_time +
                    state_time + analysts_time + total_agent_import_time)

print("\n" + "="*80)
print("SUMMARY")
print("="*80)

print(f"\nTotal startup time:             {total_startup_time:6.3f}s")
print(f"\nBreakdown:")
print(f"  Environment + imports:        {total_import_time:6.3f}s  ({total_import_time/total_startup_time*100:5.1f}%)")
print(f"  Client initialization:        {client_init_time:6.3f}s  ({client_init_time/total_startup_time*100:5.1f}%)")
print(f"  Cache population:             {total_cache_time:6.3f}s  ({total_cache_time/total_startup_time*100:5.1f}%)")
print(f"  Overhead:                     {total_startup_time - total_import_time - client_init_time - total_cache_time:6.3f}s")

print("\n" + "-"*80)
print("TOP 5 SLOWEST IMPORTS")
print("-"*80)

all_imports = {
    "numpy + pandas": numpy_time,
    "langchain": langchain_time,
    "pydantic": pydantic_time,
    "src.data.borsdata_client": borsdata_client_time,
    "src.tools.api": api_time,
    "src.graph.state": state_time,
    "src.utils.analysts": analysts_time,
}
all_imports.update({f"agent.{k}": v for k, v in agent_import_times.items()})

sorted_imports = sorted(all_imports.items(), key=lambda x: x[1], reverse=True)
for i, (module, import_time) in enumerate(sorted_imports[:5], 1):
    print(f"{i}. {module:<40} {import_time:6.3f}s")

print("\n" + "-"*80)
print("OPTIMIZATION RECOMMENDATIONS")
print("-"*80)

print("\n1. LAZY LOADING:")
print("   Only import agents when they're actually selected, not all upfront")
print(f"   Potential savings: ~{total_agent_import_time:.2f}s if not all agents used")

print("\n2. CACHE STRATEGIES:")
print("   - Cache population happens every run (3.8s overhead)")
print("   - Consider persistent cache with TTL to avoid repeated API calls")

print("\n3. IMPORT OPTIMIZATION:")
if langchain_time > 0.5:
    print(f"   - Langchain import is slow ({langchain_time:.2f}s)")
    print("   - Consider lazy imports or lighter LLM client")

if numpy_time > 0.3:
    print(f"   - Numpy/pandas import overhead ({numpy_time:.2f}s)")
    print("   - This is expected but unavoidable for numerical agents")

print("\n" + "="*80)
print(f"Profiling complete at: {time.time():.3f}")
print("="*80)
