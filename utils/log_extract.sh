#!/bin/bash
# Log extract: ±10-line context around matched patterns
#
# @spec-ref: TokenSavingRules.md §Log & Debug File Handling
# @spec-why: Cheaper than reading the full log — pulls only relevant context.
# @spec-invariant: Does NOT parse timestamps or error types — use log_triage.py for that.
#
# Usage: ./utils/log_extract.sh <logfile> [pattern]
# Output: Context windows around matched patterns, preserving timestamps.
#
# Example: ./utils/log_extract.sh logs/app.jsonl "ERROR|TRACEBACK"

set -euo pipefail

# Default pattern: ERROR|WARN|CRITICAL
PATTERN="${2:-ERROR|WARN|CRITICAL}"
CONTEXT_LINES=10

if [ $# -lt 1 ]; then
    echo "Usage: log_extract.sh <logfile> [pattern]" >&2
    exit 1
fi

LOGFILE="$1"

if [ ! -f "$LOGFILE" ]; then
    echo "File not found: $LOGFILE" >&2
    exit 1
fi

# Use grep with context, suppress binary file warnings
grep -n -E -i -C "$CONTEXT_LINES" "$PATTERN" "$LOGFILE" 2>/dev/null | \
    sed 's/^--$/\n---\n/' | \
    head -n 500  # Cap output to prevent token explosion

exit 0
