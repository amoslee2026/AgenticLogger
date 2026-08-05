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
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Compact key mapping — kept here (not imported from logger) to avoid
# circular imports and keep the storage layer self-contained.
COMPACT_MAP: dict[str, str] = {
    "ts": "t", "level": "l", "module": "n", "msg": "m",
    "pid": "p", "rid": "r", "seq": "q", "error_code": "e",
    "dur": "d", "tool": "o", "cmd": "c", "exit": "x",
    "op": "w", "path": "h", "ctx": "z", "tid": "i",
    "lines": "s", "funcs": "f", "lang": "g", "choice": "k",
    "alts": "a", "reason": "u", "stdout": "v", "stderr": "b",
    "ok": "y", "size": "j",
}
_EXPAND_MAP: dict[str, str] = {v: k for k, v in COMPACT_MAP.items()}

# Bounded level enum — powers the bytes.count fast path in stats().
_LEVELS: tuple[str, ...] = (
    "INFO", "WARN", "ERROR", "TOOL", "FILE_OP", "DECISION", "CODE_GEN", "CONTEXT", "DEBUG",
)
# Fields stored as unquoted JSON numbers — stats() uses a different capture pattern.
# NOTE: pid is excluded — it is stored as a quoted string (str(os.getpid())).
_NUMERIC_KEYS: frozenset[str] = frozenset({"seq", "dur", "exit", "size"})


def _maybe_expand(entry: dict) -> dict:
    """Expand single-char keys → full names if the entry looks compact.

    Heuristic: if more than half the keys are single-char, treat as compact.
    """
    short_keys = [k for k in entry if len(k) == 1 and k in _EXPAND_MAP]
    if len(short_keys) > len(entry) * 0.4:
        return {_EXPAND_MAP.get(k, k): v for k, v in entry.items()}
    return entry


class JSONLBackend:
    """JSONL storage backend with optional circular rotation.

    @spec-ref: spec/05-storage.md §3 — JSONL 后端
    @agent-tag: storage-backend
    @agent-caution: Circular rotation renames files mid-stream — tail -f processes may see brief gaps.
    @spec-why: One file per run (with optional rotation) balances query performance vs. file-count overhead.
    @spec-invariant: Does NOT support concurrent writers to the same file — use SQLite backend for multi-process scenarios.
    @last-changed: 2026-07-28

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
        compact: When True, entries use single-char field names on disk.
            Reads auto-expand to full names so the query layer is unchanged.
    """

    def __init__(
        self,
        file_path: Path | str,
        max_files: int = 10,
        max_size_mb: int = 500,
        circular: bool = False,
        global_ctx: dict | None = None,
        compact: bool = False,
    ):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_files = max_files
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.circular = circular
        self._compact = compact
        self._global_ctx = global_ctx or {}
        self._write_count = 0
        self._lock = threading.Lock()

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

        Thread-safe via ``self._lock``.  If *circular* mode is enabled and the
        current file has exceeded *max_size_mb*, a safe rotation is performed
        before writing.
        """
        with self._lock:
            if self.circular and self._should_rotate():
                self._safe_rotate()

            line = json.dumps(entry, ensure_ascii=False, default=str)
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._write_count += 1

    def write_batch(self, entries: list[dict]) -> None:
        """Append multiple log entries in a single I/O operation (thread-safe)."""
        with self._lock:
            lines = [json.dumps(e, ensure_ascii=False, default=str) for e in entries]
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self._write_count += len(entries)

    def close(self) -> None:
        """Release resources.

        JSONLBackend writes per-call (no persistent file handle), so this is a
        no-op kept for interface parity with :class:`SQLiteBackend`, allowing
        :class:`~agentic_logger.logger.AgentLogger` to call ``close()``
        polymorphically at shutdown.
        """
        return

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

        # One JSON record per line — eliminates pipe/newline delimiter ambiguity
        # so exc_msg or traceback containing ``|`` or newlines no longer corrupts
        # the sidecar.
        # (@spec-ref: spec/05-storage.md §6 — 评审修复: 管道分隔格式损坏)
        record = {
            "tid": tid,
            "exception_type": exc_type,
            "exception_msg": exc_msg,
            "traceback": traceback_text,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"

        # threading.Lock serialises within-process writers; fcntl.flock
        # serialises cross-process writers appending to the same sidecar.
        with self._lock:
            with open(tb_path, "a", encoding="utf-8") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    f.write(line)
                    f.flush()
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_traceback(self, tid: str) -> dict | None:
        """Look up a traceback by its *tid*.

        Returns ``None`` if no matching record exists.  Reads the current JSONL
        sidecar format and falls back to the legacy pipe-delimited format for
        sidecars written by older versions.
        """
        tb_path = self._traceback_path()
        if not tb_path.exists():
            return None
        with open(tb_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = self._parse_tb_line(line)
                if rec is not None and rec.get("tid") == tid:
                    return rec
        return None

    @staticmethod
    def _parse_tb_line(line: str) -> dict | None:
        """Parse one traceback sidecar line.

        Current format is JSONL (one JSON object per line).  Legacy
        pipe-delimited ``tid|exc_type|exc_msg|tb`` lines are still recognised
        for sidecars written before the JSONL migration.
        """
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
        parts = line.split("|", 3)
        if len(parts) == 4:
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

        Fast path: exact-match filters on string fields (level/error_code/tool/
        rid/pid/tid, and ``module`` without ``*``) narrow candidate lines via byte
        scanning BEFORE ``json.loads`` — a large win for sparse filters (a rid
        narrows 100K lines to ~15). Falls back to a full scan when no exact-match
        filter is present.

        @last-changed: 2026-08-05
        """
        limit = filters.pop("limit", 1000)
        offset = filters.pop("offset", 0)
        order_by = filters.pop("order_by", "ts_desc")

        if not self.file_path.exists():
            return []

        active = {k: v for k, v in filters.items() if v is not None}

        # Exact-match filters whose value is a quoted string in the file — these
        # can narrow candidate lines by byte scanning before json parsing.
        narrowable = {k: active[k] for k in
                      ("level", "error_code", "tool", "rid", "pid", "tid")
                      if k in active}
        if "module" in active and "*" not in str(active["module"]):
            narrowable["module"] = active["module"]

        if narrowable:
            results = self._query_narrowed(active, narrowable)
        else:
            results = self._query_full_scan(active)

        # Sort
        reverse = order_by != "ts_asc"
        if order_by == "dur_desc":
            results.sort(key=lambda x: x.get("dur") or 0, reverse=True)
        else:
            results.sort(key=lambda x: x.get("ts", ""), reverse=reverse)

        return results[offset : offset + limit]

    def _query_full_scan(self, active: dict) -> list[dict]:
        """Reference path: parse every line. Used when no exact-match filter."""
        results: list[dict] = []
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entry = _maybe_expand(entry)
                if self._match(entry, active):
                    results.append(entry)
        return results

    def _query_narrowed(self, active: dict, narrowable: dict) -> list[dict]:
        """Byte-narrow candidate lines by exact-match filters, then json-parse
        only those lines and apply the full ``_match`` for correctness.

        @spec-why: A rid/error_code filter matches O(handful) of 100K lines; parsing
          only those avoids the ~1s full-file json.loads.
        @spec-invariant: Results are identical to _query_full_scan — narrowing only
          skips lines that cannot match (the key:value substring must be present).
        """
        data = self.file_path.read_bytes()
        is_compact = b'"l":' in data[:512] and b'"level":' not in data[:512]
        needles = [
            ('"' + (COMPACT_MAP.get(f, f) if is_compact else f) + f'": "{v}"').encode()
            for f, v in narrowable.items()
        ]

        results: list[dict] = []
        first, rest = needles[0], needles[1:]
        pos = 0
        while True:
            p = data.find(first, pos)
            if p == -1:
                break
            ls = data.rfind(b"\n", 0, p) + 1
            le = data.find(b"\n", p)
            if le == -1:
                le = len(data)
            pos = le + 1  # advance past this line regardless of match
            line_b = data[ls:le]
            if rest and not all(n in line_b for n in rest):
                continue
            try:
                entry = json.loads(line_b)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            entry = _maybe_expand(entry)
            if self._match(entry, active):  # re-verify ALL filters on the candidate
                results.append(entry)
        return results

    def stats(
        self,
        group_by: str,
        since: str | None = None,
        until: str | None = None,
        rid: str | None = None,
    ) -> Counter:
        """Aggregate counts by *group_by* **without materializing every entry**.

        Reads the file once as bytes and counts field values via ``bytes.count``
        (bounded ``level`` enum) or a single C-level ``re`` scan (other fields) —
        skipping the per-line ``json.loads`` that makes :meth:`query` slow at
        100K+ scale (~1.1s -> ~0.1s measured). Fixed-key substrings make the
        byte-level count exact.

        @spec-ref: spec/04-read-interface.md §2.2 — agentic_log_stats (fast path)
        @spec-why: Aggregation must scan every entry but need not *parse* each into
          a dict; compact JSONL keys are stable substrings.
        @spec-invariant: Falls back to :meth:`query` + Counter when *since*/*until*/*rid*
          need per-entry correlation (rare for stats). Does NOT honor ``keyword``.
        @last-changed: 2026-08-05
        """
        if not self.file_path.exists():
            return Counter()

        # Per-entry-correlation filters -> generic path (correctness over speed).
        if since or until or rid:
            counter: Counter = Counter()
            for e in self.query(since=since, until=until, rid=rid, limit=100000):
                if e.get("level") == "__GLOBAL_CTX__":
                    continue
                counter[str(e.get(group_by, "unknown"))] += 1
            return counter

        data = self.file_path.read_bytes()
        # Drop the global-ctx header (always line 1 when present) so it isn't counted.
        nl = data.find(b"\n")
        if nl != -1 and b"__GLOBAL_CTX__" in data[:nl]:
            data = data[nl + 1:]

        # Total data entries = line count (every entry is one newline-terminated line;
        # JSON escapes newlines in values, so no false line breaks).
        total = data.count(b"\n")

        # Auto-detect compact vs full key form from the file head. The backend's
        # ``_compact`` flag is unreliable on reads (readers construct JSONLBackend
        # without it), so probe the bytes — mirrors ``_maybe_expand``'s heuristic.
        is_compact = b'"l":' in data[:512] and b'"level":' not in data[:512]
        key = COMPACT_MAP.get(group_by, group_by) if is_compact else group_by
        key_b = key.encode("utf-8")

        # bytes.count fast path for the bounded level enum (default group_by).
        # Needle `'<key>": "INFO"'` is an exact-value match (closing quote prevents
        # prefix collisions). Custom (non-enum) levels fall through to "unknown".
        if group_by == "level":
            sep = b'"' + key_b + b'": "'
            counts: Counter = Counter({lv: data.count(sep + lv.encode() + b'"') for lv in _LEVELS})
        elif group_by in _NUMERIC_KEYS:
            pattern = b'"' + key_b + b'": ([^,}]+)'
            counts = Counter(v.strip().decode("utf-8", "ignore") for v in re.findall(pattern, data))
        else:
            pattern = b'"' + key_b + b'": "([^"]+)"'
            counts = Counter(v.decode("utf-8", "ignore") for v in re.findall(pattern, data))

        # Entries without the grouped field bucket as "unknown" (matches the legacy
        # query()-based semantics, e.g. INFO entries have no error_code).
        unknown = total - sum(counts.values())
        if unknown > 0:
            counts["unknown"] = unknown
        return counts

    def get_time_range(self) -> dict | None:
        """Return ``{min_ts, max_ts}`` for this file, or *None* if empty.

        Used by the query engine to skip files whose time range does not
        overlap the caller's ``since``/``until`` filter
        (@spec-ref: spec/04-read-interface.md §5.1 — 查询合并方案).

        Byte-level: one ``re.findall`` over the ts field instead of per-line
        ``json.loads`` (~1s -> ~0.1s at 100K). ISO-8601 ts sort lexicographically.

        @last-changed: 2026-08-05
        """
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            return None
        data = self.file_path.read_bytes()
        nl = data.find(b"\n")
        if nl != -1 and b"__GLOBAL_CTX__" in data[:nl]:
            data = data[nl + 1:]
        is_compact = b'"l":' in data[:512] and b'"level":' not in data[:512]
        key = "t" if is_compact else "ts"
        tss = re.findall(b'"' + key.encode() + b'": "([^"]+)"', data)
        if not tss:
            return None
        return {
            "min_ts": min(tss).decode("utf-8", "ignore"),
            "max_ts": max(tss).decode("utf-8", "ignore"),
        }

    def tail(self, n: int = 100) -> list[dict]:
        """Return the last *n* entries by reading a bounded chunk from the file end.

        O(n) — no full scan. File order tracks ts order under the single-writer
        invariant; callers needing strict ts order should sort the result.

        @spec-why: ``query(limit=n)`` with no filter scans the whole file; ``tail``
          semantics only need the most recent entries, so seek from the end. This
          matters especially for ``tail --follow`` which otherwise re-scans every poll.
        @last-changed: 2026-08-05
        """
        if not self.file_path.exists():
            return []
        size = self.file_path.stat().st_size
        # avg ~200 B/entry; pad so n entries comfortably fit in the chunk.
        chunk = min(size, max(n * 512, 8192))
        with open(self.file_path, "rb") as f:
            if size > chunk:
                f.seek(-chunk, os.SEEK_END)
            data = f.read()
        lines = data.splitlines()
        if size > chunk and lines:
            lines = lines[1:]  # first line is partial (seek landed mid-line)
        out: list[dict] = []
        for line_b in lines[-n:]:
            try:
                entry = json.loads(line_b)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            out.append(_maybe_expand(entry))
        return out

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
        original_path = self.file_path
        rotating_path = original_path.with_suffix(".jsonl.rotating")

        # Step 1: rename → .rotating
        try:
            original_path.rename(rotating_path)
        except FileNotFoundError:
            return  # Someone else rotated concurrently; nothing to do.

        new_path = None
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

            # Step 4: finalise the renamed file.
            # Strip the ``.rotating`` marker (NOT replace with ``.jsonl`` — that
            # yields a double extension ``x.jsonl.jsonl`` and breaks traceback
            # sidecar lookup).  ``with_suffix("")`` restores the original name.
            # (@spec-ref: spec/05-storage.md §5.1 — 评审修复: 双扩展名 bug)
            final_path = rotating_path.with_suffix("")
            rotating_path.rename(final_path)

        except OSError as e:
            # Rollback: remove the orphan new file, restore ``file_path`` and
            # the original file to its pre-rotation location/name.  The old
            # rollback renamed rotating onto the (already-reassigned) new_path,
            # leaving an orphan and losing the original filename.
            # (@spec-ref: spec/05-storage.md §5.1 — 评审修复: 回滚留孤儿文件)
            if new_path is not None and new_path.exists():
                new_path.unlink(missing_ok=True)
            self.file_path = original_path
            if rotating_path.exists():
                rotating_path.rename(original_path)
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
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": "__GLOBAL_CTX__",
            "msg": "Global context",
            "module": "__system__",
            "rid": self._global_ctx.get("rid", ""),
            "pid": str(os.getpid()),
            "seq": 0,
            **self._global_ctx,
        }
        # Compact mode: compress the header too (keeps the file uniform).
        if self._compact:
            ctx_entry = {COMPACT_MAP.get(k, k): v for k, v in ctx_entry.items()}
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
                # Entries without a dur are excluded from a dur range
                # (``dur or 0`` previously conflated missing-dur with dur=0).
                dur = entry.get("dur")
                if dur is None or dur < value:
                    return False
            elif key == "max_dur":
                dur = entry.get("dur")
                if dur is None or dur > value:
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
            # Exact-match: the entry must CONTAIN the key and it must match.
            # (Previously a missing key let the entry pass — which leaked the
            # __GLOBAL_CTX__ header and non-matching entries through filters
            # on optional fields like error_code / path / tid.)
            elif key not in entry or str(entry[key]) != str(value):
                return False
        return True
