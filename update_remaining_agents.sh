#!/bin/bash
# Script to update remaining agents to support next_ticker progress tracking
#
# This script updates agent files to:
# 1. Extract next_ticker from state data
# 2. Pass next_ticker to progress.update_status when calling with "Done" status
#
# Run from the repository root: bash update_remaining_agents.sh

set -e

# List of agent files to update (excluding already updated ones)
AGENTS=(
    "src/agents/charlie_munger.py"
    "src/agents/bill_ackman.py"
    "src/agents/cathie_wood.py"
    "src/agents/peter_lynch.py"
    "src/agents/rakesh_jhunjhunwala.py"
    "src/agents/ben_graham.py"
    "src/agents/mohnish_pabrai.py"
    "src/agents/aswath_damodaran.py"
    "src/agents/fundamentals.py"
    "src/agents/technicals.py"
    "src/agents/sentiment.py"
    "src/agents/valuation.py"
)

echo "Updating ${#AGENTS[@]} agent files to support next_ticker progress tracking..."

for agent_file in "${AGENTS[@]}"; do
    if [ ! -f "$agent_file" ]; then
        echo "⚠️  Skipping $agent_file (not found)"
        continue
    fi

    echo "Processing $agent_file..."

    # Step 1: Add next_ticker extraction after tickers line
    # Pattern: Find "tickers = " or "tickers:" and add next_ticker line after it
    if grep -q "next_ticker.*For progress tracking" "$agent_file"; then
        echo "  ✓ next_ticker extraction already present"
    else
        # Try to find tickers assignment and add next_ticker after it
        if grep -q "tickers.*=.*data\[" "$agent_file" || grep -q "tickers:.*=.*data\[" "$agent_file" || grep -q "tickers = data.get" "$agent_file"; then
            # Use perl for in-place editing with more complex regex
            perl -i -pe 's/(tickers(?::)? = data(?:\.get)?\(["\']tickers["\']\))/\1\n    next_ticker = data.get("next_ticker")  # For progress tracking/' "$agent_file"
            echo "  ✓ Added next_ticker extraction"
        else
            echo "  ⚠️  Could not find tickers assignment pattern"
        fi
    fi

    # Step 2: Update progress.update_status calls with "Done" to include next_ticker
    # Pattern: progress.update_status(..., "Done", ...) -> add next_ticker= parameter
    if grep -E 'progress\.update_status\([^)]*"Done"[^)]*\)' "$agent_file" | grep -q "next_ticker="; then
        echo "  ✓ progress.update_status already updated"
    else
        # Update progress.update_status calls that have "Done" but not next_ticker
        # This matches progress.update_status ending with ) and adds next_ticker before the closing paren
        sed -i'.bak' -E 's/progress\.update_status\(([^)]*), "Done"([^)]*)\)/progress.update_status(\1, "Done"\2, next_ticker=next_ticker)/g' "$agent_file"
        echo "  ✓ Updated progress.update_status calls"
    fi
done

echo ""
echo "✅ Update complete! Updated ${#AGENTS[@]} agent files."
echo ""
echo "To verify changes, run:"
echo "  git diff src/agents/"