"""AgentLogger — Main SDK class for Coding Agents.

@spec-ref: spec/03-write-sdk.md — 写入 SDK API 设计
@spec-ref: spec/01-architecture.md — 系统架构概览
@last-changed: 2026-07-21
@log-module: agentic_logger.logger

Usage::

    from agentic_logger import AgentLogger, ErrorCode

    logger = AgentLogger(program="my_agent", command="main")
    logger.info("Processing started")
    logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
    logger.error("Failed", error_code=ErrorCode.IO_NOT_FOUND)

Each :class:`AgentLogger` instance represents one *run* of a program.
It creates a dedicated log file (``{program}_{cmd}_{date}_{time}.jsonl``)
and auto-fills ``ts``, ``pid``, ``rid``, and ``seq`` on every entry so
callers never have to supply those fields manually.
"""

import atexit
import os
import re
import sys
import uuid
import warnings
from datetime import datetime
from pathlib import Path

from agentic_logger.error_codes import ErrorCode
from agentic_logger.fields import AutoFields, auto_module
from agentic_logger.storage.jsonl import JSONLBackend
from agentic_logger.storage.sqlite import SQLiteBackend


def _sanitize_filename_part(s: str, max_len: int = 50) -> str:
    """Sanitise *s* for use inside a log filename.

    Non-word characters (anything other than ``\\w`` and ``-``) are
    replaced with underscores; the result is truncated to *max_len*
    bytes.  (@spec-ref: spec/05-storage.md §2.2 — 评审修复 S10)

    @spec-why: Prevents path traversal and filesystem errors from user-supplied program names.
    @spec-invariant: Does NOT validate the full path — only sanitizes individual components.
    @last-changed: 2026-07-21
    """
    return re.sub(r"[^\w\-]", "_", s)[:max_len]


def _select_backend(log_dir: Path, program: str, command: str | None) -> str:
    """Heuristic backend selection for ``storage="auto"``.

    @spec-ref: spec/05-storage.md §2.3 — 评审修复 AGG-003
    @agent-tag: backend-selection
    @spec-why: Balances performance (JSONL) vs. multi-process safety (SQLite) without requiring manual config.
    @spec-invariant: Does NOT detect concurrent writers at runtime — assumes single-writer unless command keywords suggest batch processing.
    @last-changed: 2026-07-21

    Rules (evaluated in order; first match wins):

    1. **Environment variable** ``AGENTIC_STORAGE`` — overrides everything.
    2. **Multi-process** environment detected → ``"sqlite"``.
    3. **Existing** ``.sqlite`` files for the same *program* → ``"sqlite"``
       (keeps all runs of one program in the same backend).
    4. **Large-log command** keywords (build, test, ci, …) → ``"sqlite"``.
    5. **Default** → ``"jsonl"``.
    """
    # Rule 1: explicit override
    env_hint = os.environ.get("AGENTIC_STORAGE")
    if env_hint in ("jsonl", "sqlite"):
        return env_hint

    # Rule 2: multi-process (MVP: jsonl-only; sqlite is Phase 2)

    # Rule 3: consistency with existing files
    safe_prog = _sanitize_filename_part(program)
    if list(log_dir.glob(f"{safe_prog}*.sqlite")):
        return "sqlite"

    # Rule 4: command patterns that typically produce large logs
    LARGE_LOG_KEYWORDS = {"build", "test", "ci", "deploy", "migrate", "sync", "batch"}
    cmd_lower = (command or "").lower()
    if any(kw in cmd_lower for kw in LARGE_LOG_KEYWORDS):
        return "sqlite"

    # Rule 5: default
    return "jsonl"


class AgentLogger:
    """Structured logger for Coding Agents.

    @spec-ref: spec/03-write-sdk.md — AgentLogger API
    @agent-tag: core-logger
    @spec-why: One instance per run ensures run-level isolation (rid, seq) without cross-run contamination.
    @spec-invariant: Does NOT support shared state across processes — each process must create its own instance.
    @last-changed: 2026-07-21

    Each instance creates a separate log file per run, named::

        {program}_{command}_{YYYYMMDD}_{HHmmssffffff}.jsonl

    Microsecond precision in the timestamp avoids collisions when
    multiple instances are created within the same wall-clock second.

    Args:
        program: Program name used in the filename.  **Required.**
        command: Sub-command name (or *None* → ``pid<PID>``).
        log_dir: Directory for log files.  Default: ``./logs``.
        storage: ``"jsonl"``, ``"sqlite"``, or ``"auto"``.
        rid: Run ID.  Auto-generated if *None*.  Pass a parent's rid
            to propagate across subprocesses
            (@spec-ref: spec/03-write-sdk.md — 评审修复 U03).
        circular: Enable circular write mode.
        max_files: Max log files to keep when *circular=True*.
        max_size_mb: Max file size (MiB) before rotation triggers.
    """

    def __init__(
        self,
        program: str,
        command: str | None = None,
        log_dir: str | Path = "./logs",
        storage: str = "auto",
        rid: str | None = None,
        circular: bool = False,
        max_files: int = 10,
        max_size_mb: int = 500,
    ):
        self.program = program
        self.command = command or f"pid{os.getpid()}"
        self.log_dir = Path(log_dir)

        # Auto-fields: ts / pid / rid / seq
        self._fields = AutoFields(rid=rid)

        # Filename
        filename = self._generate_filename(storage)
        self._file_path = self.log_dir / filename

        # Global context (written to the file header once at init)
        self._global_ctx: dict = {
            "program": self.program,
            "command": self.command,
            "pid": self._fields.pid,
            "rid": self._fields.rid,
        }

        # Backend selection
        backend_type = _select_backend(self.log_dir, self.program, self.command) \
            if storage == "auto" else storage

        if backend_type == "sqlite":
            self._backend = SQLiteBackend(
                file_path=self._file_path,
                circular=circular,
                max_size_mb=max_size_mb,
                global_ctx=self._global_ctx,
            )
        else:
            self._backend = JSONLBackend(
                file_path=self._file_path,
                max_files=max_files,
                max_size_mb=max_size_mb,
                circular=circular,
                global_ctx=self._global_ctx,
            )

        # Lifecycle tracking + atexit safety net
        self._run_started = False
        self._run_ended = False
        atexit.register(self._auto_run_end)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def rid(self) -> str:
        """Run ID for this logger instance."""
        return self._fields.rid

    @property
    def file_path(self) -> Path:
        """Absolute path to the current (active) log file.

        Delegates to the backend so the value stays correct after a JSONL
        rotation — the backend reassigns its own ``file_path`` on rotate,
        whereas the ``self._file_path`` captured at construction would go stale.
        (@spec-ref: spec/05-storage.md — 评审修复: 旋转后 file_path 失效)
        """
        return self._backend.file_path

    # ------------------------------------------------------------------
    # Basic log methods
    # ------------------------------------------------------------------

    def info(
        self,
        msg: str,
        module: str | None = None,
        dur: int | None = None,
        error_code: str | ErrorCode | None = None,
        ctx: dict | None = None,
        tid: str | None = None,
    ) -> None:
        """Log an informational message.

        Args:
            msg: One-line summary (truncated to 4 KB).
            module: Dotted module path.  Auto-detected from the call
                stack if *None* (@spec-ref: spec/03-write-sdk.md — 评审修复 AGG-007).
            dur: Operation duration in milliseconds.
            error_code: Optional structured error code.
            ctx: Small key-value context (keep minimal — only fields
                that help reproduce the issue).
            tid: Traceback reference ID (from :meth:`save_traceback`).
        """
        self._write("INFO", msg, module=module, dur=dur, error_code=error_code, ctx=ctx, tid=tid)

    def warn(
        self,
        msg: str,
        module: str | None = None,
        dur: int | None = None,
        error_code: str | ErrorCode | None = None,
        ctx: dict | None = None,
        tid: str | None = None,
    ) -> None:
        """Log a warning."""
        self._write("WARN", msg, module=module, dur=dur, error_code=error_code, ctx=ctx, tid=tid)

    def error(
        self,
        msg: str,
        module: str | None = None,
        error_code: str | ErrorCode | None = None,
        tid: str | None = None,
        dur: int | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Log an error.

        @spec-ref: spec/03-write-sdk.md — 评审修复 AGG-002
        @agent-tag: error-handling
        @agent-caution: Emits UserWarning if error_code is None — forces callers to acknowledge missing error taxonomy.
        @spec-why: Warning (not exception) preserves backward compatibility while encouraging proper error_code usage.
        @spec-invariant: Does NOT raise exceptions for missing error_code — logs the error regardless, with UNKNOWN fallback.
        @last-changed: 2026-07-21

        If *error_code* is not provided, a ``UserWarning`` is emitted
        and the code defaults to :attr:`ErrorCode.UNKNOWN`.  Supplying
        a proper code (from the standard taxonomy or a project-specific
        one) is strongly recommended so that downstream analysis can
        aggregate by error type.
        """
        if error_code is None:
            warnings.warn(
                f"error_code not provided for error: {msg}. "
                "Using UNKNOWN. Consider using ErrorCode enum.",
                stacklevel=2,
            )
            error_code = ErrorCode.UNKNOWN
        self._write(
            "ERROR", msg, module=module, error_code=error_code, tid=tid, dur=dur, ctx=ctx
        )

    def exception(
        self,
        msg: str,
        module: str | None = None,
        error_code: str | ErrorCode | None = ErrorCode.INTERNAL_UNEXPECTED,
        ctx: dict | None = None,
    ) -> None:
        """Log the currently-handled exception in one step.

        @spec-ref: spec/03-write-sdk.md — 评审修复 U07
        @agent-tag: exception-handling
        @agent-caution: Must be called inside an except block — raises ValueError otherwise.
        @spec-why: Single-call convenience for exception logging (capture + save traceback + write ERROR entry).
        @spec-invariant: Does NOT re-raise the exception — caller must handle propagation explicitly.
        @last-changed: 2026-07-21

        Must be called **inside** an ``except`` block.  Automatically
        captures the traceback via :func:`sys.exc_info`, saves it to
        the ``.tracebacks`` sidecar, and writes an ``ERROR`` entry
        whose ``tid`` references the saved traceback.

        Raises:
            ValueError: If called outside an ``except`` block.
        """
        exc_info = sys.exc_info()
        if exc_info[1] is None:
            raise ValueError("exception() must be called inside an except block")

        import traceback as _tb
        exc_type = type(exc_info[1]).__name__
        exc_msg = str(exc_info[1])
        tb_text = "".join(_tb.format_exception(*exc_info))

        tid = self.save_traceback_text(tb_text, exc_type, exc_msg)
        self._write("ERROR", msg, module=module, error_code=error_code, tid=tid, ctx=ctx)

    # ------------------------------------------------------------------
    # Specialized methods
    # ------------------------------------------------------------------

    def tool_call(
        self,
        tool: str,
        cmd: str,
        exit: int,
        dur: int,
        tid: str | None = None,
        error_code: str | ErrorCode | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Log a tool / command invocation.

        @spec-ref: spec/03-write-sdk.md — tool_call
        @agent-tag: tool-execution
        @agent-caution: Raises ValueError if exit != 0 and error_code is None — enforces error taxonomy for failures.
        @spec-why: Explicit error_code requirement for failures prevents silent error aggregation under UNKNOWN.
        @spec-invariant: Does NOT capture stdout/stderr automatically — caller must provide summaries (truncated to 64KB).
        @last-changed: 2026-07-21

        Args:
            tool: Tool name (``"bash"``, ``"read"``, ``"write"``, …).
            cmd: The actual command or path.
            exit: Exit code (0 = success).
            dur: Duration in milliseconds.
            error_code: **Required** when *exit* != 0
                (@spec-ref: spec/03-write-sdk.md — 评审修复 AGG-016).
            stdout: Standard-output summary (truncated to 64 KB).
            stderr: Standard-error summary (truncated to 64 KB).

        Raises:
            ValueError: If *exit* != 0 and *error_code* is *None*.
        """
        if exit != 0 and error_code is None:
            raise ValueError("error_code is required when exit != 0")
        entry = {
            "level": "TOOL",
            "msg": f"Tool {tool} {'succeeded' if exit == 0 else 'failed'}",
            "tool": tool,
            "cmd": cmd,
            "exit": exit,
            "dur": dur,
        }
        if stdout is not None:
            entry["stdout"] = stdout[:65536]
        if stderr is not None:
            entry["stderr"] = stderr[:65536]
        self._write_entry(entry, error_code=error_code, tid=tid, ctx=ctx)

    def file_op(
        self,
        op: str,
        path: str,
        ok: bool,
        size: int | None = None,
        error_code: str | ErrorCode | None = None,
        tid: str | None = None,
        dur: int | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Log a file-system operation.

        @spec-ref: spec/03-write-sdk.md — file_op

        Args:
            op: One of ``"read"``, ``"write"``, ``"delete"``, ``"move"``, ``"copy"``.
            path: Absolute or relative file path.
            ok: Whether the operation succeeded.
            size: File size in bytes (when applicable).
            error_code: **Required** when *ok* is *False*
                (@spec-ref: spec/03-write-sdk.md — 评审修复 AGG-016).

        Raises:
            ValueError: If *ok* is *False* and *error_code* is *None*.
        """
        if not ok and error_code is None:
            raise ValueError("error_code is required when ok is False")
        entry = {
            "level": "FILE_OP",
            "msg": f"File {op} {'succeeded' if ok else 'failed'}: {path}",
            "op": op,
            "path": path,
            "ok": ok,
        }
        if size is not None:
            entry["size"] = size
        self._write_entry(entry, error_code=error_code, tid=tid, dur=dur, ctx=ctx)

    def decision(
        self,
        choice: str,
        alts: list[str] | None = None,
        reason: str | None = None,
        confidence: float | None = None,
        module: str | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Record an architectural or strategic decision.

        @spec-ref: spec/03-write-sdk.md — decision

        Args:
            choice: The option ultimately selected.
            alts: Other options that were considered.
            reason: Free-text rationale for the choice.
            confidence: Estimated confidence in the choice (0.0–1.0).
        """
        entry = {
            "level": "DECISION",
            "msg": f"Decision: {choice}",
            "choice": choice,
        }
        if alts is not None:
            entry["alts"] = alts
        if reason is not None:
            entry["reason"] = reason
        if confidence is not None:
            entry["confidence"] = confidence
        self._write_entry(entry, module=module, ctx=ctx)

    def code_gen(
        self,
        lang: str,
        path: str,
        lines: int | None = None,
        funcs: list[str] | None = None,
        imports: list[str] | None = None,
        module: str | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Record a code-generation event.

        @spec-ref: spec/03-write-sdk.md — code_gen
        """
        entry = {
            "level": "CODE_GEN",
            "msg": f"Generated {lang} code: {path}",
            "lang": lang,
            "path": path,
        }
        if lines is not None:
            entry["lines"] = lines
        if funcs is not None:
            entry["funcs"] = funcs
        if imports is not None:
            entry["imports"] = imports
        self._write_entry(entry, module=module, ctx=ctx)

    def context_switch(
        self,
        to_task: str,
        from_task: str | None = None,
        reason: str | None = None,
        module: str | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Record a task / context switch.

        @spec-ref: spec/03-write-sdk.md — context_switch
        """
        entry = {
            "level": "CONTEXT",
            "msg": f"Switching to: {to_task}",
            "to_task": to_task,
        }
        if from_task is not None:
            entry["from_task"] = from_task
        if reason is not None:
            entry["reason"] = reason
        self._write_entry(entry, module=module, ctx=ctx)

    # ------------------------------------------------------------------
    # Traceback management
    # ------------------------------------------------------------------

    def save_traceback(self, exc: BaseException) -> str:
        """Persist an exception's traceback and return its *tid*.

        The returned *tid* can be passed to :meth:`error` so that the
        log entry references the full stack trace without bloating the
        main log file.
        """
        import traceback as _tb
        tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
        return self.save_traceback_text(
            tb_text, type(exc).__name__, str(exc)
        )

    def save_traceback_text(self, tb_text: str, exc_type: str, exc_msg: str) -> str:
        """Persist raw traceback text and return its *tid*."""
        tid = f"tb_{uuid.uuid4().hex[:8]}"
        self._backend.save_traceback(tid, tb_text, exc_type, exc_msg)
        return tid

    # ------------------------------------------------------------------
    # Global context
    # ------------------------------------------------------------------

    def set_global_context(self, **kwargs) -> None:
        """Add key-value pairs to the global-context header.

        These are written once at file creation (``level="__GLOBAL_CTX__"``)
        and are available to any reader that opens the file.
        """
        self._global_ctx.update(kwargs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run_start(self, msg: str = "Run started", ctx: dict | None = None) -> None:
        """Emit a ``run_start`` lifecycle entry.

        Registers an :mod:`atexit` hook that automatically emits a
        ``run_end`` entry if the process exits without an explicit
        :meth:`run_end` call (e.g. on unhandled exceptions).
        """
        self._run_started = True
        entry = {"level": "INFO", "msg": msg, "module": "__lifecycle__", "event": "run_start"}
        if ctx:
            entry.update(ctx)
        self._write_entry(entry)

    def run_end(
        self,
        msg: str = "Run finished",
        exit_code: int = 0,
        dur: int | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Emit a ``run_end`` lifecycle entry."""
        self._run_ended = True
        entry = {
            "level": "INFO",
            "msg": msg,
            "module": "__lifecycle__",
            "event": "run_end",
            "exit_code": exit_code,
        }
        if dur is not None:
            entry["dur"] = dur
        if ctx:
            entry.update(ctx)
        self._write_entry(entry)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_filename(self, storage: str) -> str:
        """Build the log filename.

        @spec-ref: spec/05-storage.md §2.2 — {program}_{cmd}_{YYYYMMDD}_{HHmmssffffff}.{ext}
        """
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S") + f"{now.microsecond:06d}"

        safe_program = _sanitize_filename_part(self.program)
        safe_command = _sanitize_filename_part(self.command)

        backend = (
            _select_backend(self.log_dir, self.program, self.command)
            if storage == "auto"
            else storage
        )
        ext = "sqlite" if backend == "sqlite" else "jsonl"

        return f"{safe_program}_{safe_command}_{date_str}_{time_str}.{ext}"

    def _write(
        self,
        level: str,
        msg: str,
        module: str | None = None,
        tid: str | None = None,
        dur: int | None = None,
        error_code: str | ErrorCode | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Write a basic log entry (info / warn / error).

        Truncates *msg* to 4 KB (@spec-ref: spec/02-log-format.md — 评审修复 B01).
        """
        entry = {
            "level": level,
            "msg": msg[:4096],
            "module": module or auto_module(depth=3),
        }
        self._write_entry(entry, tid=tid, dur=dur, error_code=error_code, ctx=ctx)

    def _write_entry(
        self,
        entry: dict,
        module: str | None = None,
        tid: str | None = None,
        dur: int | None = None,
        error_code: str | ErrorCode | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Fill auto-fields, strip *None* values, and persist.

        Fields that are already present in *entry* are **not**
        overwritten by the keyword arguments, so specialised methods
        (``tool_call``, ``file_op``, etc.) can pre-set ``dur``, ``tid``,
        etc. and have them pass through unchanged.
        """
        if "module" not in entry or entry["module"] is None:
            entry["module"] = module or auto_module(depth=3)

        # Fill standard fields only when absent
        if "tid" not in entry:
            entry["tid"] = tid
        if "dur" not in entry:
            entry["dur"] = dur
        if "error_code" not in entry:
            entry["error_code"] = str(error_code) if error_code else None
        if ctx and "ctx" not in entry:
            entry["ctx"] = ctx

        # Auto-fill ts / pid / rid / seq
        self._fields.fill(entry)

        # Omit None values to save tokens
        # (@spec-ref: spec/03-write-sdk.md — 评审修复 R06)
        entry = {k: v for k, v in entry.items() if v is not None}

        try:
            self._backend.write(entry)
        except Exception as e:
            # Do NOT swallow silently — emit to stderr so the failure
            # is at least observable.
            # (@spec-ref: spec/05-storage.md — 评审修复 S15)
            print(f"[agentic_logger] Write failed: {e}", file=sys.stderr)

    def _auto_run_end(self) -> None:
        """``atexit`` hook: emit ``run_end`` if the run was never closed."""
        if self._run_started and not self._run_ended:
            try:
                self.run_end(msg="Process exited unexpectedly", exit_code=1)
            except Exception:
                pass
