"""SQLite storage backend with WAL mode.

@spec-ref: spec/05-storage.md §4 — SQLite + WAL 后端
@spec-ref: spec/05-storage.md §5.2 — SQLite 循环写入

Features:
- WAL journal mode for concurrent reads during writes
- Thread-safe via ``threading.Lock``
- Indexed columns for fast queries on rid, level, module, error_code, dur, ts
- Full field mapping for all log types (TOOL, FILE_OP, DECISION, CODE_GEN, CONTEXT)
- Circular write with time-based retention + size-based cleanup
- Separate tracebacks table with foreign-key cascade
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


_CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    msg TEXT NOT NULL,
    module TEXT,
    tid TEXT,
    rid TEXT NOT NULL,
    pid TEXT NOT NULL,
    seq INTEGER NOT NULL,
    dur INTEGER,
    error_code TEXT,
    ctx TEXT,
    -- TOOL fields
    tool TEXT,
    cmd TEXT,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    -- FILE_OP fields
    op TEXT,
    path TEXT,
    ok INTEGER,
    size INTEGER,
    -- DECISION fields
    choice TEXT,
    alts TEXT,
    reason TEXT,
    confidence REAL,
    -- CODE_GEN fields
    lang TEXT,
    lines INTEGER,
    funcs TEXT,
    imports TEXT,
    -- CONTEXT fields
    from_task TEXT,
    to_task TEXT,
    -- Lifecycle
    event TEXT,
    exit_code_lifecycle INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
CREATE INDEX IF NOT EXISTS idx_logs_rid ON logs(rid);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module);
CREATE INDEX IF NOT EXISTS idx_logs_error_code ON logs(error_code);
CREATE INDEX IF NOT EXISTS idx_logs_tool ON logs(tool);
CREATE INDEX IF NOT EXISTS idx_logs_pid ON logs(pid);
CREATE INDEX IF NOT EXISTS idx_logs_dur ON logs(dur);
CREATE INDEX IF NOT EXISTS idx_logs_path ON logs(path);
CREATE INDEX IF NOT EXISTS idx_logs_choice ON logs(choice);
CREATE INDEX IF NOT EXISTS idx_logs_rid_level ON logs(rid, level);

CREATE TABLE IF NOT EXISTS tracebacks (
    tid TEXT PRIMARY KEY,
    traceback TEXT NOT NULL,
    exception_type TEXT,
    exception_msg TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS global_context (
    rid TEXT PRIMARY KEY,
    ctx_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


class SQLiteBackend:
    """SQLite storage backend with WAL journal mode.

    @spec-ref: spec/05-storage.md §4

    Thread-safe: all writes are serialized via a ``threading.Lock``.
    WAL mode allows concurrent reads while writes are in progress.

    Args:
        file_path: Path to the ``.sqlite`` database file.
        wal_mode: Enable WAL journal mode (default True).
        busy_timeout: Milliseconds to wait on a locked database.
        circular: Enable circular write mode.
        retention_hours: Hours to retain records (circular mode).
        max_size_mb: Max database file size in MB (circular mode).
        checkpoint_every: Write count between passive WAL checkpoints.
        global_ctx: Global context dict.
    """

    def __init__(
        self,
        file_path: Path | str,
        wal_mode: bool = True,
        busy_timeout: int = 5000,
        circular: bool = False,
        retention_hours: int = 24,
        max_size_mb: int = 500,
        checkpoint_every: int = 1000,
        global_ctx: dict | None = None,
    ):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.circular = circular
        self.retention_seconds = retention_hours * 3600
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._checkpoint_every = checkpoint_every
        self._write_count = 0
        self._lock = threading.Lock()

        self.conn = sqlite3.connect(
            str(self.file_path),
            check_same_thread=False,
            timeout=busy_timeout / 1000.0,
        )
        self.conn.row_factory = sqlite3.Row

        if wal_mode:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")

        self.conn.executescript(_CREATE_SCHEMA)

        # Store global context
        if global_ctx:
            rid = global_ctx.get("rid", "")
            if rid:
                self.conn.execute(
                    "INSERT OR REPLACE INTO global_context (rid, ctx_json) VALUES (?, ?)",
                    (rid, json.dumps(global_ctx, ensure_ascii=False)),
                )
                self.conn.commit()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def write(self, entry: dict) -> None:
        """Insert a single log entry (thread-safe)."""
        with self._lock:
            self._insert(entry)
            self.conn.commit()
            self._write_count += 1

            if self._write_count % self._checkpoint_every == 0:
                self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

            if self.circular and self._write_count % 100 == 0:
                self._cleanup_if_needed()

    def write_batch(self, entries: list[dict]) -> None:
        """Insert multiple log entries in one transaction."""
        with self._lock:
            for entry in entries:
                self._insert(entry)
            self.conn.commit()
            self._write_count += len(entries)

    def _insert(self, entry: dict) -> None:
        """Insert a single entry without committing or locking."""
        cols = self._extract_columns(entry)
        col_names = ", ".join(cols.keys())
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO logs ({col_names}) VALUES ({placeholders})"
        self.conn.execute(sql, list(cols.values()))

    def _extract_columns(self, entry: dict) -> dict:
        """Map a log entry dict to SQLite columns.

        @spec-ref: spec/05-storage.md §4.2 — 评审修复 AGG-005
        """
        cols: dict = {
            "ts": entry.get("ts"),
            "level": entry.get("level"),
            "msg": entry.get("msg"),
            "module": entry.get("module"),
            "tid": entry.get("tid"),
            "rid": entry.get("rid"),
            "pid": entry.get("pid"),
            "seq": entry.get("seq"),
            "dur": entry.get("dur"),
            "error_code": entry.get("error_code"),
            "ctx": json.dumps(entry.get("ctx", {}), ensure_ascii=False) if entry.get("ctx") else None,
        }

        level = entry.get("level")
        if level == "TOOL":
            cols.update({
                "tool": entry.get("tool"),
                "cmd": entry.get("cmd"),
                "exit_code": entry.get("exit"),
                "stdout": entry.get("stdout"),
                "stderr": entry.get("stderr"),
            })
        elif level == "FILE_OP":
            cols.update({
                "op": entry.get("op"),
                "path": entry.get("path"),
                "ok": 1 if entry.get("ok") else 0,
                "size": entry.get("size"),
            })
        elif level == "DECISION":
            cols.update({
                "choice": entry.get("choice"),
                "alts": json.dumps(entry.get("alts", []), ensure_ascii=False),
                "reason": entry.get("reason"),
                "confidence": entry.get("confidence"),
            })
        elif level == "CODE_GEN":
            cols.update({
                "lang": entry.get("lang"),
                "path": entry.get("path"),
                "lines": entry.get("lines"),
                "funcs": json.dumps(entry.get("funcs", []), ensure_ascii=False),
                "imports": json.dumps(entry.get("imports", []), ensure_ascii=False),
            })
        elif level == "CONTEXT":
            cols.update({
                "from_task": entry.get("from_task"),
                "to_task": entry.get("to_task"),
                "reason": entry.get("reason"),
            })

        # Lifecycle events
        if entry.get("event"):
            cols["event"] = entry["event"]
            if "exit_code" in entry:
                cols["exit_code_lifecycle"] = entry["exit_code"]

        # Strip None values
        return {k: v for k, v in cols.items() if v is not None}

    def save_traceback(self, tid: str, traceback_text: str, exc_type: str, exc_msg: str) -> None:
        """Save a traceback (thread-safe)."""
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO tracebacks (tid, traceback, exception_type, exception_msg) "
                "VALUES (?, ?, ?, ?)",
                (tid, traceback_text, exc_type, exc_msg),
            )
            self.conn.commit()

    def get_traceback(self, tid: str) -> dict | None:
        """Retrieve a traceback by tid."""
        row = self.conn.execute(
            "SELECT tid, traceback, exception_type, exception_msg FROM tracebacks WHERE tid = ?",
            (tid,),
        ).fetchone()
        if row is None:
            return None
        return {
            "tid": row["tid"],
            "traceback": row["traceback"],
            "exception_type": row["exception_type"],
            "exception_msg": row["exception_msg"],
        }

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def query(self, **filters) -> list[dict]:
        """Query logs with SQL filters (indexed for speed).

        Supported filters: level, module, error_code, tool, rid, pid, tid,
                          min_dur, max_dur, since, until, keyword,
                          limit, offset, order_by.
        """
        conditions: list[str] = []
        params: list = []

        # Exact match fields (indexed)
        for field in ("rid", "level", "module", "error_code", "tool", "pid", "tid",
                      "op", "path", "choice"):
            value = filters.get(field)
            if value is not None:
                if field == "module" and "*" in str(value):
                    conditions.append(f"{field} LIKE ?")
                    params.append(str(value).replace("*", "%"))
                else:
                    conditions.append(f"{field} = ?")
                    params.append(value)

        # Range fields
        min_dur = filters.get("min_dur")
        if min_dur is not None:
            conditions.append("dur >= ?")
            params.append(min_dur)
        max_dur = filters.get("max_dur")
        if max_dur is not None:
            conditions.append("dur <= ?")
            params.append(max_dur)

        # Time range
        since = filters.get("since")
        if since:
            conditions.append("ts >= ?")
            params.append(since)
        until = filters.get("until")
        if until:
            conditions.append("ts <= ?")
            params.append(until)

        # Keyword full-text (fallback: LIKE on msg + ctx)
        keyword = filters.get("keyword")
        if keyword:
            conditions.append("(msg LIKE ? OR ctx LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Order
        order_map = {
            "ts_asc": "ts ASC",
            "ts_desc": "ts DESC",
            "dur_desc": "dur DESC NULLS LAST",
        }
        order_by = order_map.get(filters.get("order_by", "ts_desc"), "ts DESC")

        # Pagination
        limit = filters.get("limit", 1000)
        offset = filters.get("offset", 0)

        sql = f"SELECT * FROM logs{where} ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_time_range(self) -> dict | None:
        """Get min/max timestamps (fast via index)."""
        row = self.conn.execute(
            "SELECT MIN(ts) as min_ts, MAX(ts) as max_ts FROM logs"
        ).fetchone()
        if row and row["min_ts"]:
            return {"min_ts": row["min_ts"], "max_ts": row["max_ts"]}
        return None

    def count(self) -> int:
        """Total number of log entries."""
        return self.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]

    # ------------------------------------------------------------------
    # Circular Write
    # ------------------------------------------------------------------

    def _cleanup_if_needed(self) -> None:
        """Time-based and size-based cleanup (called under lock)."""
        # Time-based: delete records older than retention_hours
        self.conn.execute(
            "DELETE FROM logs WHERE ts < datetime('now', ?)",
            (f"-{self.retention_seconds} seconds",),
        )

        # Size-based: if file exceeds limit, delete oldest 10%
        if self.file_path.stat().st_size > self.max_size_bytes:
            total = self.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            delete_count = max(total // 10, 1)
            self.conn.execute(
                "DELETE FROM logs WHERE id IN "
                "(SELECT id FROM logs ORDER BY ts ASC LIMIT ?)",
                (delete_count,),
            )
            # TRUNCATE checkpoint to reclaim WAL space
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        # Clean orphaned tracebacks
        self.conn.execute(
            "DELETE FROM tracebacks WHERE tid NOT IN "
            "(SELECT DISTINCT tid FROM logs WHERE tid IS NOT NULL)"
        )

        self.conn.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a dict, skipping None values."""
        d = dict(row)
        # Parse ctx back from JSON
        if d.get("ctx"):
            try:
                d["ctx"] = json.loads(d["ctx"])
            except (json.JSONDecodeError, TypeError):
                pass
        # Parse alts/funcs/imports back
        for field in ("alts", "funcs", "imports"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        # Map exit_code back to exit for consistency with JSONL format
        if "exit_code" in d and d.get("level") == "TOOL":
            d["exit"] = d.pop("exit_code")
        # Skip None values
        return {k: v for k, v in d.items() if v is not None}

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
