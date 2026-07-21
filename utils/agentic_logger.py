#!/usr/bin/env python3
"""Shared logging utility for Python scripts in this project.

@spec-ref: TokenSavingRules.md §Log & Debug File Handling
@spec-why: Centralizes log format and prevents scattered print()/logging calls.
@spec-invariant: Does NOT replace the main agentic_logger SDK — this is for utils/ scripts only.

Canonical format: [ISO-8601] [LEVEL] [module=<name>] [req_id=<id>] message
Multi-line tracebacks wrapped in --- TRACEBACK START/END ---.

Usage:
    from utils.agentic_logger import get_logger
    log = get_logger(__name__)
    log.info("Processing started")
"""

import sys
import os
from datetime import datetime, timezone
from typing import Optional

# Auto-detect if we're in the main package or utils
try:
    from agentic_logger import AgentLogger, ErrorCode
    _USE_MAIN_SDK = True
except ImportError:
    _USE_MAIN_SDK = False


class _SimpleLogger:
    """Fallback logger when main SDK is not available.

    @spec-why: Utils scripts may run before the main package is installed.
    """

    def __init__(self, module: str):
        self.module = module
        self.req_id = os.environ.get("REQ_ID", "none")

    def _format(self, level: str, msg: str) -> str:
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        return f"[{ts}] [{level}] [module={self.module}] [req_id={self.req_id}] {msg}"

    def info(self, msg: str) -> None:
        print(self._format("INFO", msg))

    def warn(self, msg: str) -> None:
        print(self._format("WARN", msg), file=sys.stderr)

    def error(self, msg: str, error_code: Optional[str] = None) -> None:
        code = f" [{error_code}]" if error_code else ""
        print(self._format("ERROR", f"{msg}{code}"), file=sys.stderr)

    def exception(self, msg: str) -> None:
        print(self._format("ERROR", msg), file=sys.stderr)
        print("--- TRACEBACK START ---", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        print("--- TRACEBACK END ---", file=sys.stderr)


def get_logger(module: str):
    """Get a logger instance — main SDK if available, fallback otherwise.

    @spec-ref: TokenSavingRules.md §Log & Debug File Handling
    """
    if _USE_MAIN_SDK:
        return AgentLogger(program=module, command="utils")
    return _SimpleLogger(module)


# Convenience: direct export
__all__ = ["get_logger"]
