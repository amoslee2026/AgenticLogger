"""AgentLogger - Main SDK class for Coding Agents.

spec 03-write-sdk.md: 写入 SDK API 设计

Usage:
    from agentic_logger import AgentLogger, ErrorCode

    logger = AgentLogger(program="my_agent", command="main")
    logger.info("Processing started")
    logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
    logger.error("Failed", error_code=ErrorCode.IO_NOT_FOUND)
"""

import os
import re
import sys
import uuid
import atexit
import warnings
from datetime import datetime
from pathlib import Path

from agentic_logger.error_codes import ErrorCode
from agentic_logger.fields import AutoFields, auto_module
from agentic_logger.storage.jsonl import JSONLBackend


def _sanitize_filename_part(s: str, max_len: int = 50) -> str:
    """Sanitize a string for use in filenames.

    spec 05-storage.md §2.2 + 评审修复 S10/B07:
    - Replace non-word chars with underscore
    - Truncate to max_len
    """
    return re.sub(r"[^\w\-]", "_", s)[:max_len]


def _select_backend(log_dir: Path, program: str, command: str | None) -> str:
    """Select storage backend using heuristic rules.

    spec 05-storage.md §2.3 (评审修复 AGG-003):
    1. Env var AGENTIC_STORAGE overrides all
    2. Multi-process environment → sqlite
    3. Existing sqlite files for same program → sqlite
    4. Large-log command keywords → sqlite
    5. Default → jsonl
    """
    # Rule 1: Environment variable
    env_hint = os.environ.get("AGENTIC_STORAGE")
    if env_hint in ("jsonl", "sqlite"):
        return env_hint

    # Rule 2: Multi-process (always use jsonl for MVP, sqlite is Phase 2)
    # For now, MVP is jsonl-only. This function exists for future sqlite support.

    # Rule 3: Existing sqlite files
    safe_prog = _sanitize_filename_part(program)
    if list(log_dir.glob(f"{safe_prog}*.sqlite")):
        return "sqlite"

    # Rule 4: Large-log command keywords
    LARGE_LOG_KEYWORDS = {"build", "test", "ci", "deploy", "migrate", "sync", "batch"}
    cmd_lower = (command or "").lower()
    if any(kw in cmd_lower for kw in LARGE_LOG_KEYWORDS):
        return "sqlite"

    # Rule 5: Default
    return "jsonl"


class AgentLogger:
    """Structured logger for Coding Agents.

    Each instance creates a separate log file per run, named:
        {program}_{command}_{YYYYMMDD}_{HHmmssffffff}.jsonl

    Args:
        program: Program name (used in filename). Required.
        command: Sub-command name (used in filename). Auto-derived from PID if None.
        log_dir: Directory for log files. Default: ./logs
        storage: "jsonl", "sqlite", or "auto". Default: "auto".
        rid: Run ID. Auto-generated UUID4 hex[:8] if None.
             Pass parent's rid for cross-process tracing (评审修复 U03).
        circular: Enable circular write mode. Default: False.
        max_files: Max log files to keep (circular). Default: 10.
        max_size_mb: Max file size in MB before rotation. Default: 500.
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

        # Auto-fields (ts, pid, rid, seq)
        self._fields = AutoFields(rid=rid)

        # Generate filename
        filename = self._generate_filename(storage)
        self._file_path = self.log_dir / filename

        # Global context (written to file header)
        self._global_ctx: dict = {
            "program": self.program,
            "command": self.command,
            "pid": self._fields.pid,
            "rid": self._fields.rid,
        }

        # Select and initialize backend (MVP: JSONL only)
        self._backend = JSONLBackend(
            file_path=self._file_path,
            max_files=max_files,
            max_size_mb=max_size_mb,
            circular=circular,
            global_ctx=self._global_ctx,
        )

        # Lifecycle tracking
        self._run_started = False
        self._run_ended = False
        atexit.register(self._auto_run_end)

    # --- Properties ---

    @property
    def rid(self) -> str:
        """Run ID for this logger instance."""
        return self._fields.rid

    @property
    def file_path(self) -> Path:
        """Path to the current log file."""
        return self._file_path

    # --- Basic log methods ---

    def info(
        self,
        msg: str,
        module: str | None = None,
        dur: int | None = None,
        error_code: str | ErrorCode | None = None,
        ctx: dict | None = None,
        tid: str | None = None,
    ) -> None:
        """Log an info message."""
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

        spec 03-write-sdk.md (评审修复 AGG-002):
        error_code defaults to "UNKNOWN" with a warning if not provided.
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
        """Log an exception with auto-captured traceback.

        spec 03-write-sdk.md (评审修复 U07): 一步完成异常记录。
        Must be called inside an except block.
        """
        exc_info = sys.exc_info()
        if exc_info[1] is None:
            raise ValueError("exception() must be called inside an except block")

        exc_type = type(exc_info[1]).__name__
        exc_msg = str(exc_info[1])

        import traceback
        tb_text = "".join(traceback.format_exception(*exc_info))
        tid = self.save_traceback_text(tb_text, exc_type, exc_msg)

        self._write(
            "ERROR", msg, module=module, error_code=error_code, tid=tid, ctx=ctx
        )

    # --- Specialized methods ---

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
        """Log a tool call.

        spec 03-write-sdk.md (评审修复 AGG-016):
        error_code required when exit != 0.
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
            entry["stdout"] = stdout[:65536]  # B01: 截断 64KB
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
        """Log a file operation.

        spec 03-write-sdk.md (评审修复 AGG-016):
        error_code required when ok is False.
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
        """Log a decision point."""
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
        """Log a code generation event."""
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
        """Log a context/task switch."""
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

    # --- Traceback ---

    def save_traceback(self, exc: BaseException) -> str:
        """Save exception traceback, return tid reference.

        Returns a tid string that can be passed to error() calls.
        """
        import traceback
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        return self.save_traceback_text(tb_text, exc_type, exc_msg)

    def save_traceback_text(self, tb_text: str, exc_type: str, exc_msg: str) -> str:
        """Save raw traceback text, return tid reference."""
        tid = f"tb_{uuid.uuid4().hex[:8]}"
        self._backend.save_traceback(tid, tb_text, exc_type, exc_msg)
        return tid

    # --- Global context ---

    def set_global_context(self, **kwargs) -> None:
        """Set global context fields (written to file header).

        These are included in the __GLOBAL_CTX__ entry at the top of the file.
        """
        self._global_ctx.update(kwargs)

    # --- Lifecycle ---

    def run_start(self, msg: str = "Run started", ctx: dict | None = None) -> None:
        """Mark the start of a run."""
        self._run_started = True
        entry = {
            "level": "INFO",
            "msg": msg,
            "module": "__lifecycle__",
            "event": "run_start",
        }
        if ctx:
            entry.update(ctx)
        self._write_entry(entry)

    def run_end(
        self, msg: str = "Run finished", exit_code: int = 0, dur: int | None = None,
        ctx: dict | None = None,
    ) -> None:
        """Mark the end of a run."""
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

    # --- Internal ---

    def _generate_filename(self, storage: str) -> str:
        """Generate log filename.

        spec 05-storage.md §2.2: {program}_{command}_{YYYYMMDD}_{HHmmssffffff}.{ext}
        """
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S") + f"{now.microsecond:06d}"

        safe_program = _sanitize_filename_part(self.program)
        safe_command = _sanitize_filename_part(self.command)

        backend = _select_backend(self.log_dir, self.program, self.command) \
            if storage == "auto" else storage
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
        """Write a basic log entry (info/warn/error)."""
        entry = {
            "level": level,
            "msg": msg[:4096],  # B01: 截断 4KB
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
        """Write a fully-formed entry with auto-fields."""
        # Fill module if missing
        if "module" not in entry or entry["module"] is None:
            entry["module"] = module or auto_module(depth=3)

        # Fill standard fields
        entry["tid"] = tid
        entry["dur"] = dur
        entry["error_code"] = str(error_code) if error_code else None
        if ctx:
            entry["ctx"] = ctx

        # Auto-fill ts/pid/rid/seq
        self._fields.fill(entry)

        # Remove None values to save tokens (评审修复 R06)
        entry = {k: v for k, v in entry.items() if v is not None}

        try:
            self._backend.write(entry)
        except Exception as e:
            # 评审修复 S15: 写入失败不静默
            print(f"[agentic_logger] Write failed: {e}", file=sys.stderr)

    def _auto_run_end(self) -> None:
        """atexit hook: auto-close run if not ended."""
        if self._run_started and not self._run_ended:
            try:
                self.run_end(msg="Process exited unexpectedly", exit_code=1)
            except Exception:
                pass
