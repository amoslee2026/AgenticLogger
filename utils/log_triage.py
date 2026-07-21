#!/usr/bin/env python3
"""Log triage: error-type summary (count + first occurrence).

@spec-ref: TokenSavingRules.md §Log & Debug File Handling
@spec-why: Reads full log in one pass to extract error patterns without manual tail/grep cycles.
@spec-invariant: Does NOT extract context — use log_extract.sh for that.

Usage: ./utils/log_triage.py <logfile>
Output: Error type counts with first occurrence timestamps.
"""

import sys
import re
from collections import defaultdict
from pathlib import Path

# Error patterns to detect
ERROR_PATTERNS = [
    (r"\bERROR\b", "ERROR"),
    (r"\bWARN(?:ING)?\b", "WARN"),
    (r"\bCRITICAL\b", "CRITICAL"),
    (r"\bFATAL\b", "FATAL"),
    (r"\bEXCEPTION\b", "EXCEPTION"),
    (r"\bTRACEBACK\b", "TRACEBACK"),
    (r"exit[_\s]?code[:\s]+[1-9]", "EXIT_NONZERO"),
    (r"failed|failure", "FAILED"),
]

def triage_log(filepath: str) -> dict:
    """Parse log file and return error-type summary.

    @spec-ref: TokenSavingRules.md §Log & Debug File Handling
    """
    path = Path(filepath)
    if not path.exists():
        return {"error": f"File not found: {filepath}"}

    errors = defaultdict(lambda: {"count": 0, "first_ts": None, "first_line": None})

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line_num, line in enumerate(f, 1):
            # Extract timestamp if present (ISO 8601)
            ts_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
            ts = ts_match.group(0) if ts_match else f"line:{line_num}"

            for pattern, error_type in ERROR_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    entry = errors[error_type]
                    entry["count"] += 1
                    if entry["first_ts"] is None:
                        entry["first_ts"] = ts
                        entry["first_line"] = line_num
                    break  # One match per line

    return dict(errors)


def main():
    if len(sys.argv) < 2:
        print("Usage: log_triage.py <logfile>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    result = triage_log(filepath)

    if "error" in result:
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    if not result:
        print("No errors found.")
        sys.exit(0)

    # Dense output: error type, count, first occurrence
    print(f"{'Type':<15} {'Count':>6}  First Occurrence")
    print("-" * 50)
    for error_type, data in sorted(result.items(), key=lambda x: -x[1]["count"]):
        print(f"{error_type:<15} {data['count']:>6}  {data['first_ts']} (line {data['first_line']})")

    sys.exit(0)


if __name__ == "__main__":
    main()
