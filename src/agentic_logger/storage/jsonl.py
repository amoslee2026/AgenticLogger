"""JSONL (JSON Lines) storage backend.

@spec-ref: spec/05-storage.md §3  — JSONL 后端
@spec-ref: spec/05-storage.md §5.1 — JSONL 循环写入
@spec-ref: spec/05-storage.md §6   — 堆栈跟踪分离存储
@last-changed: 2026-07-21
@log-module: agentic_logger.storage.jsonl

Each log entry is a single line of JSON, appended to the file.  The
backend supports:

- **Streaming append** — one ``open(…, 'a')`` per write; safe for
  ``tail -f`` consumers.
- **Safe circular rotation** — rename → create → delete ordering
  eliminates the data-loss window if the process crashes mid-rotation.
- **Separate traceback storage** — large stack traces live in a
  ``.tracebacks`` sidecar file keyed by ``tid``; the main log stays
  lightweight.
- **Multi-process safety** — ``fcntl.flock`` guards traceback writes
  when several processes append to the same sidecar.
"""

import fcntl
import json
import os
import re
from datetime import datetime
from pathlib import Path


class JSONLBackend:
    """JSONL storage backend with optional circular rotation.

    @spec-ref: spec/05-storage.md §3 — JSONL 后端
    @agent-tag: storage-backend
    @agent-caution: Circular rotation renames files mid-stream — tail -f processes may see brief gaps.
    @spec-why: One file per run (with optional rotation) balances query performance vs. file-count overhead.
    @spec-invariant: Does NOT support concurrent writers to the same file — use SQLite backend for multi-process scenarios.
    @last-changed: 2026-07-21

    Args:
        file_path: Path to the ``.jsonl`` log file.  Parent directories
            are created automatically.
        max_files: Maximum number of rotated files to retain.  Only
            meaningful when *circular=True*.
        max_size_mb: File-size threshold (MiB) that triggers rotation.
        circular: Enable circular write mode.  When *False* (default),
            the file grows without bound.
        global_ctx: Arbitrary key-value pairs written as the first line
            of a new log file (``level="__GLOBAL_CTX__"``).  Useful for
            recording the program name, command, git branch, etc.
    """

    def __init__(
        self,
        file_path: Path | str,
        max_files: int = 10,
        max_size_mb: int = 500,
        circular: bool = False,
        global_ctx: dict | None = None,
    ):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_files = max_files
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.circular = circular
        self._global_ctx = global_ctx or {}
        self._write_count = 0

        # Recover from a rotation that was interrupted by a crash on a
        # previous run (see _safe_rotate for the forward path).
        self._recover_from_interrupted_rotation()

        # Write global context header only when the file is brand new.
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            self._write_global_context()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def write(self, entry: dict) -> None:
        """Append a single log entry as one JSON line.

        If *circular* mode is enabled and the current file has exceeded
        *max_size_mb*, a safe rotation is performed before writing.
        """
        if self.circular and self._should_rotate():
            self._safe_rotate()

        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._write_count += 1

    def write_batch(self, entries: list[dict]) -> None:
        """Append multiple log entries in a single I/O operation."""
        lines = [json.dumps(e, ensure_ascii=False, default=str) for e in entries]
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self._write_count += len(entries)

    def save_traceback(
        self, tid: str, traceback_text: str, exc_type: str, exc_msg: str
    ) -> None:
        """Persist a stack trace to the ``.tracebacks`` sidecar file.

        @spec-ref: spec/05-storage.md §6 — 堆栈跟踪分离存储
        @agent-tag: traceback-storage
        @agent-caution: Uses fcntl.flock for multi-process safety — may block on concurrent writes.
        @spec-why: Separating tracebacks from main log keeps JSONL files lightweight and parseable.
        @spec-invariant: Does NOT compress traceback text — newlines are escaped to preserve one-record-per-line invariant.
        @last-changed: 2026-07-21

        Newlines inside *traceback_text* are escaped to ``\\n`` so that
        each traceback record stays on exactly one line (preserving the
        JSONL invariant of the main log).

        Multi-process safety is achieved with ``fcntl.flock(LOCK_EX)``:
        if two processes try to save tracebacks concurrently, the second
        one blocks until the first releases the lock.
        """
        tb_path = self._traceback_path()
        tb_path.parent.mkdir(parents=True, exist_ok=True)

        # Escape newlines so one traceback == one line in the sidecar.
        safe_tb = traceback_text.replace("\n", "\\n")
        line = f"{tid}|{exc_type}|{exc_msg}|{safe_tb}\n"

        with open(tb_path, "a", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_traceback(self, tid: str) -> dict | None:
        """Look up a traceback by its *tid*.

        Returns ``None`` if no matching record exists.
        """
        tb_path = self._traceback_path()
        if not tb_path.exists():
            return None
        with open(tb_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|", 3)
                if len(parts) == 4 and parts[0] == tid:
                    return {
                        "tid": parts[0],
                        "exception_type": parts[1],
                        "exception_msg": parts[2],
                        "traceback": parts[3].replace("\\n", "\n"),
                    }
        return None

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def query(self, **filters) -> list[dict]:
        """Scan the log file and return entries matching *filters*.

        Supported filter keys:
            level, module, error_code, tool, rid, pid, tid,
            min_dur, max_dur, since, until, keyword,
            limit (default 1000), offset, order_by.

        The ``module`` filter supports ``*`` glob wildcards
        (e.g. ``"agent.*"``).  The ``keyword`` filter performs a
        case-insensitive substring search across the entire serialised
        entry (including nested ``ctx`` values).
        """
        limit = filters.pop("limit", 1000)
        offset = filters.pop("offset", 0)
        order_by = filters.pop("order_by", "ts_desc")

        if not self.file_path.exists():
            return []

        results = []
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if self._match(entry, filters):
                    results.append(entry)

        # Sort
        reverse = order_by != "ts_asc"
        if order_by == "dur_desc":
            results.sort(key=lambda x: x.get("dur") or 0, reverse=True)
        else:
            results.sort(key=lambda x: x.get("ts", ""), reverse=reverse)

        return results[offset : offset + limit]

    def get_time_range(self) -> dict | None:
        """Return ``{min_ts, max_ts}`` for this file, or *None* if empty.

        Used by the query engine to skip files whose time range does not
        overlap the caller's ``since``/``until`` filter
        (@spec-ref: spec/04-read-interface.md §5.1 — 查询合并方案).
        """
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            return None
        min_ts = max_ts = None
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ts = json.loads(line).get("ts")
                except json.JSONDecodeError:
                    continue
                if ts:
                    if min_ts is None or ts < min_ts:
                        min_ts = ts
                    if max_ts is None or ts > max_ts:
                        max_ts = ts
        return {"min_ts": min_ts, "max_ts": max_ts} if min_ts else None

    # ------------------------------------------------------------------
    # Internal — Circular Rotation
    # ------------------------------------------------------------------

    def _should_rotate(self) -> bool:
        return (
            self.file_path.exists()
            and self.file_path.stat().st_size > self.max_size_bytes
        )

    def _safe_rotate(self) -> None:
        """Perform a crash-safe file rotation.

        @spec-ref: spec/05-storage.md §5.1 — 评审修复 AGG-001
        @agent-tag: file-rotation
        @agent-caution: Four-step protocol (rename → create → delete → finalize) — interruption at any step leaves recoverable state.
        @spec-why: Prevents data loss if process crashes mid-rotation — naive delete-then-create has a permanent-loss window.
        @spec-invariant: Does NOT lock the file during rotation — assumes single-writer per file (JSONL invariant).
        @last-changed: 2026-07-21

        The naive "delete-oldest then create-new" order has a window
        where data is permanently lost if the process crashes between
        the two operations.  This method uses a four-step protocol
        that is safe against that scenario:

        1. **Rename** the current file to ``*.rotating`` (marks it as
           "being rotated away").
        2. **Create** a new file and write the global-context header.
           If this step fails (disk full, permission error), the rename
           is rolled back and the original file is restored.
        3. **Delete** the oldest completed files until the count is
           within *max_files*.  Their ``.tracebacks`` sidecars are
           deleted as well.
        4. **Finalise** by renaming the ``*.rotating`` file back to
           ``*.jsonl`` (without the ``.rotating`` marker).
        """
        rotating_path = self.file_path.with_suffix(".jsonl.rotating")

        # Step 1: rename → .rotating
        try:
            self.file_path.rename(rotating_path)
        except FileNotFoundError:
            return  # Someone else rotated concurrently; nothing to do.

        try:
            # Step 2: create new file (validates write permission, disk space)
            new_path = self._generate_next_filename()
            new_path.touch()
            self.file_path = new_path
            self._write_global_context()

            # Step 3: prune oldest completed files
            files = sorted(self._get_completed_files())
            while len(files) >= self.max_files:
                oldest = files[0]
                oldest.unlink(missing_ok=True)
                tb_file = oldest.with_suffix(".tracebacks")
                if tb_file.exists():
                    tb_file.unlink()
                files = sorted(self._get_completed_files())

            # Step 4: finalise the renamed file
            final_path = rotating_path.with_suffix(".jsonl")
            rotating_path.rename(final_path)

        except OSError as e:
            # Rollback: the new file could not be created, so restore
            # the original to avoid losing in-flight log data.
            if rotating_path.exists():
                rotating_path.rename(self.file_path)
            raise RuntimeError(
                f"Rotation failed, original file restored: {e}"
            ) from e

    def _recover_from_interrupted_rotation(self) -> None:
        """Recover ``*.rotating`` files left behind by a previous crash.

        A ``.rotating`` file means the previous process completed step 1
        (rename) but never reached step 4 (finalise).  We undo the
        rename by stripping the ``.rotating`` suffix — i.e. the file
        reverts to its original ``.jsonl`` name.
        """
        parent = self.file_path.parent
        for f in parent.glob("*.rotating"):
            # f.stem strips the last suffix (.rotating), yielding the
            # original filename (e.g. "name.jsonl").
            original = f.parent / f.stem
            if not original.exists():
                f.rename(original)
            else:
                # Original already exists (step 4 succeeded but the
                # .rotating file was not cleaned up) — discard the
                # stale marker.
                f.unlink(missing_ok=True)

    def _generate_next_filename(self) -> Path:
        """Produce a timestamped filename for the next rotation slot.

        Uses microsecond precision to avoid collisions when multiple
        rotations happen within the same second
        (@spec-ref: spec/05-storage.md §2.3 — 评审修复 B07).
        """
        base = self.file_path.stem
        match = re.match(r"(.+?)_\d{8}_\d+$", base)
        base_pattern = match.group(1) if match else base

        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S") + f"{now.microsecond:06d}"
        name = f"{base_pattern}_{date_str}_{time_str}.jsonl"
        return self.file_path.parent / name

    def _get_completed_files(self) -> list[Path]:
        """List all finished log files matching this run's base pattern.

        Excludes files that are currently being rotated (``.rotating``).
        """
        pattern = self.file_path.stem
        match = re.match(r"(.+?)_\d{8}_\d+$", pattern)
        base_pattern = match.group(1) if match else pattern

        return sorted(
            f
            for f in self.file_path.parent.glob(f"{base_pattern}_*.jsonl")
            if not f.name.endswith(".rotating")
        )

    def _write_global_context(self) -> None:
        """Write the global-context record as the first line of the file.

        The record uses ``level="__GLOBAL_CTX__"`` so that query filters
        can skip it when counting data entries.
        """
        if not self._global_ctx:
            return
        ctx_entry = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": "__GLOBAL_CTX__",
            "msg": "Global context",
            "module": "__system__",
            "tid": None,
            "rid": self._global_ctx.get("rid", ""),
            "pid": str(os.getpid()),
            "seq": 0,
            "dur": None,
            "error_code": None,
            **self._global_ctx,
        }
        line = json.dumps(ctx_entry, ensure_ascii=False, default=str)
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ------------------------------------------------------------------
    # Internal — Query Helpers
    # ------------------------------------------------------------------

    def _traceback_path(self) -> Path:
        return self.file_path.with_suffix(".tracebacks")

    # Fields that are level-specific: an entry must HAVE the field
    # for the filter to match.  (e.g. only TOOL entries have "tool",
    # only FILE_OP entries have "op".)
    _LEVEL_SPECIFIC_KEYS = {"tool", "op", "choice", "exit", "lang"}

    @staticmethod
    def _match(entry: dict, filters: dict) -> bool:
        """Return True if *entry* satisfies every filter in *filters*.

        Special filter keys:
        - ``min_dur`` / ``max_dur`` — range check on ``entry["dur"]``
        - ``module`` with ``*`` — fnmatch glob (prefix or suffix)
        - ``keyword`` — case-insensitive substring over the full entry
        - Level-specific keys (``tool``, ``op``, etc.) — entry must
          contain the key *and* it must match.
        """
        for key, value in filters.items():
            if value is None:
                continue
            if key == "min_dur":
                if (entry.get("dur") or 0) < value:
                    return False
            elif key == "max_dur":
                if (entry.get("dur") or 0) > value:
                    return False
            elif key == "since":
                # ISO 8601 string compare (valid when ts share the same tz offset —
                # enforced by UTC everywhere, see P1 timezone fix).
                # (@spec-ref: spec/04-read-interface.md — 评审修复: since/until 原被静默忽略)
                if entry.get("ts", "") < str(value):
                    return False
            elif key == "until":
                if entry.get("ts", "") > str(value):
                    return False
            elif key == "module" and "*" in str(value):
                import fnmatch
                if not fnmatch.fnmatch(entry.get("module", ""), value):
                    return False
            elif key == "keyword":
                text = json.dumps(entry, ensure_ascii=False).lower()
                if str(value).lower() not in text:
                    return False
            elif key in JSONLBackend._LEVEL_SPECIFIC_KEYS:
                # Level-specific: must be present AND match
                if key not in entry or str(entry[key]) != str(value):
                    return False
            elif key in entry and str(entry[key]) != str(value):
                return False
        return True
