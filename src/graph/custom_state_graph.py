from langgraph.graph import StateGraph
from src.graph.state import AgentState
from typing import Any, Dict

class CustomStateGraph(StateGraph):
    """
    A custom StateGraph that implements specific merging logic for AgentState.
    This is necessary for handling complex state updates, especially for nested
    dictionaries like 'analyst_signals' when multiple agents run in parallel.
    """
    def __init__(self, schema: type[AgentState], *args, **kwargs):
        super().__init__(schema, *args, **kwargs)

    def _reducer(self, current_state: AgentState, new_state: AgentState) -> AgentState:
        # Start with a copy of the current state to avoid modifying it directly
        merged_state = current_state.copy()

        # Iterate through the keys in the new state
        for key, value in new_state.items():
            if key == "data":
                # Handle the 'data' key specifically for 'analyst_signals'
                if "data" in merged_state and "analyst_signals" in value.get("data", {}):
                    current_analyst_signals = merged_state["data"].get("analyst_signals", {})
                    new_analyst_signals = value["data"]["analyst_signals"]

                    # Merge analyst_signals: iterate through tickers and update signals
                    merged_analyst_signals = current_analyst_signals.copy()
                    for ticker, signals in new_analyst_signals.items():
                        if ticker in merged_analyst_signals:
                            merged_analyst_signals[ticker].update(signals)
                        else:
                            merged_analyst_signals[ticker] = signals
                    merged_state["data"]["analyst_signals"] = merged_analyst_signals
                else:
                    # If 'analyst_signals' is not in the new 'data' or 'data' is not in merged_state,
                    # just update the 'data' dictionary (or create it if it doesn't exist)
                    if "data" not in merged_state:
                        merged_state["data"] = {}
                    merged_state["data"].update(value["data"])
            else:
                # For other top-level keys, simply update with the new value
                merged_state[key] = value

        return merged_state
