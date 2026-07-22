"""Auto-fill fields: ts, pid, rid, seq — and caller module extraction.

@spec-ref: spec/03-write-sdk.md §2.3 — 自动填充字段
@spec-ref: spec/05-storage.md §2.2 — 日志文件命名
@last-changed: 2026-07-21
@log-module: agentic_logger.fields

Every log entry is augmented with four auto-filled fields so the caller
never has to supply them manually:

- **ts**:  ISO 8601 timestamp with timezone (millisecond precision)
- **pid**: OS process ID — distinguishes concurrent writers
- **rid**: Run ID (UUID4 hex[:8]) — chains all entries from one execution
- **seq**: Monotonic sequence number — preserves order within a run

Additionally, :func:`auto_module` inspects the call stack to determine
the caller's ``__name__`` so the ``module`` field is filled automatically.
"""

import inspect
import os
import threading
import uuid
from datetime import datetime, timezone


class AutoFields:
    """Generates auto-filled fields for each log entry.

    One instance per :class:`~agentic_logger.logger.AgentLogger`.
    The ``rid`` is fixed at construction time; ``seq`` increments on
    every :meth:`fill` call.

    Args:
        rid: Optional run ID.  If *None*, a UUID4 hex[:8] is generated.
             Pass a parent's ``rid`` to propagate across subprocesses
             (@spec-ref: spec/03-write-sdk.md — 评审修复 U03).

    @spec-why: Per-instance rid ensures all entries from one execution share the same run ID.
    @spec-invariant: Does NOT generate new rids after construction — rid is immutable per instance.
    @last-changed: 2026-07-21
    """

    def __init__(self, rid: str | None = None):
        self._rid = rid or uuid.uuid4().hex[:8]
        self._pid = str(os.getpid())
        self._seq = 0
        self._lock = threading.Lock()

    @property
    def rid(self) -> str:
        """Run ID for this logger instance."""
        return self._rid

    @property
    def pid(self) -> str:
        """Process ID."""
        return self._pid

    def fill(self, entry: dict) -> dict:
        """Fill auto-fields into *entry* (in-place) and return it.

        Fields already present in *entry* are **not** overwritten, so
        callers can override any auto-field by setting it before calling
        :meth:`fill`.

        @spec-why: In-place mutation avoids creating a new dict per entry (saves allocations).
        @spec-invariant: Does NOT validate field types — assumes caller provides correct types.
        @last-changed: 2026-07-21
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
    """Extract the caller's module name from the call stack.

    @spec-ref: spec/03-write-sdk.md — 评审修复 AGG-007 (module 自动提取)
    @agent-tag: caller-introspection
    @agent-caution: Uses inspect.currentframe() — not guaranteed in all Python implementations (e.g., Jython).
    @spec-why: Stack introspection eliminates manual module parameter passing at every call site.
    @spec-invariant: Does NOT cache module names — re-inspects stack on every call (depth=2 skips info()/warn() wrappers).
    @last-changed: 2026-07-21

    Walks *depth* frames up from the current frame and returns the
    ``__name__`` global of that frame's module.  This lets AgentLogger
    methods accept ``module=None`` and still produce meaningful output.

    Args:
        depth: Number of stack frames to skip.  ``depth=2`` skips this
               function itself **and** the direct caller (e.g. ``info``),
               landing on the actual business code that triggered the log.

    Returns:
        Dotted module name (e.g. ``"my_agent.parser"``), or ``"unknown"``
        if the frame walk fails.
    """
    try:
        frame = inspect.currentframe()
        for _ in range(depth):
            frame = frame.f_back
            if frame is None:
                return "unknown"
        return frame.f_globals.get("__name__", "unknown")
    finally:
        # Prevent reference cycles — CPython docs recommend this for
        # code that touches ``sys._getframe`` / ``currentframe()``.
        del frame
