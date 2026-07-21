"""Auto-fill fields: ts, pid, rid, seq.

spec 03-write-sdk.md §2.3: 自动填充字段
"""

import os
import uuid
from datetime import datetime, timezone


class AutoFields:
    """Generates auto-filled fields for each log entry.

    Automatically provides:
    - ts: ISO 8601 timestamp with timezone (millisecond precision)
    - pid: process ID
    - rid: run ID (UUID4, generated once per AgentLogger instance)
    - seq: global sequence number (monotonically increasing)
    """

    def __init__(self, rid: str | None = None):
        """Initialize auto-fields.

        Args:
            rid: Optional run ID. If not provided, generates UUID4.
                 Allows parent processes to propagate rid to children.
        """
        self._rid = rid or uuid.uuid4().hex[:8]
        self._pid = str(os.getpid())
        self._seq = 0

    @property
    def rid(self) -> str:
        """Run ID for this logger instance."""
        return self._rid

    @property
    def pid(self) -> str:
        """Process ID."""
        return self._pid

    def fill(self, entry: dict) -> dict:
        """Fill auto-fields into a log entry (in-place + return).

        Fields that are already set in the entry are NOT overwritten.
        """
        self._seq += 1

        if "ts" not in entry:
            entry["ts"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if "pid" not in entry:
            entry["pid"] = self._pid
        if "rid" not in entry:
            entry["rid"] = self._rid
        if "seq" not in entry:
            entry["seq"] = self._seq

        return entry


def auto_module(depth: int = 2) -> str:
    """Extract module name from call stack.

    spec 03-write-sdk.md: module 自动提取 (评审修复 AGG-007)

    Args:
        depth: How many frames to skip. depth=2 skips this function
               and the direct caller (info/error/etc), returning the
               actual business caller's module.

    Returns:
        Module name string (e.g., "my_agent.parser"), or "unknown".
    """
    import inspect

    try:
        frame = inspect.currentframe()
        for _ in range(depth):
            frame = frame.f_back
            if frame is None:
                return "unknown"
        return frame.f_globals.get("__name__", "unknown")
    finally:
        del frame
