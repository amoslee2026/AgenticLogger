"""Tests for SQLite backend."""

import tempfile
from pathlib import Path

import pytest

from agentic_logger import AgentLogger, ErrorCode
from agentic_logger.storage.sqlite import SQLiteBackend


class TestSQLiteBackend:
    """Test SQLite storage backend with WAL mode."""

    def test_sqlite_backend_write_and_query(self, tmp_path: Path):
        """Test basic write and query operations."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)

        # Write entries
        entries = [
            {"ts": "2026-01-01T00:00:00Z", "level": "INFO", "msg": "Test 1", "rid": "rid1", "pid": "12345", "seq": 1},
            {"ts": "2026-01-01T00:00:01Z", "level": "ERROR", "msg": "Test 2", "rid": "rid1", "pid": "12345", "seq": 2},
            {"ts": "2026-01-01T00:00:02Z", "level": "INFO", "msg": "Test 3", "rid": "rid2", "pid": "12345", "seq": 3},
        ]
        for entry in entries:
            backend.write(entry)

        # Query all
        results = backend.query()
        assert len(results) == 3

        # Query by level
        errors = backend.query(level="ERROR")
        assert len(errors) == 1
        assert errors[0]["msg"] == "Test 2"

        # Query by rid
        rid1_logs = backend.query(rid="rid1")
        assert len(rid1_logs) == 2

        backend.close()

    def test_sqlite_backend_tool_call(self, tmp_path: Path):
        """Test tool call entries with exit code."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)

        entry = {
            "ts": "2026-01-01T00:00:00Z",
            "level": "TOOL",
            "msg": "bash ls",
            "rid": "rid1",
            "pid": "12345",
            "seq": 1,
            "tool": "bash",
            "cmd": "ls",
            "exit": 0,
            "duration_ms": 100,
        }
        backend.write(entry)

        # Query by tool
        results = backend.query(tool="bash")
        assert len(results) == 1
        assert results[0]["tool"] == "bash"
        assert results[0]["exit"] == 0

        backend.close()

    def test_sqlite_backend_error_code(self, tmp_path: Path):
        """Test error code indexing and query."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)

        entries = [
            {"ts": "2026-01-01T00:00:00Z", "level": "ERROR", "msg": "E1", "rid": "r1", "pid": "12345", "seq": 1, "error_code": "IO_NOT_FOUND"},
            {"ts": "2026-01-01T00:00:01Z", "level": "ERROR", "msg": "E2", "rid": "r1", "pid": "12345", "seq": 2, "error_code": "EXEC_NON_ZERO"},
            {"ts": "2026-01-01T00:00:02Z", "level": "ERROR", "msg": "E3", "rid": "r1", "pid": "12345", "seq": 3, "error_code": "IO_NOT_FOUND"},
        ]
        for entry in entries:
            backend.write(entry)

        # Query by error_code
        results = backend.query(error_code="IO_NOT_FOUND")
        assert len(results) == 2

        backend.close()

    def test_sqlite_backend_traceback(self, tmp_path: Path):
        """Test traceback storage and retrieval."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)

        # Save traceback
        tid = "tb_123"
        traceback_text = "Traceback (most recent call last):\n  File 'test.py', line 1\nValueError: test"
        backend.save_traceback(tid, traceback_text, "ValueError", "test")

        # Retrieve traceback
        tb = backend.get_traceback(tid)
        assert tb is not None
        assert tb["tid"] == tid
        assert tb["exception_type"] == "ValueError"
        assert "test.py" in tb["traceback"]

        backend.close()

    def test_sqlite_wal_mode(self, tmp_path: Path):
        """Test WAL mode is enabled."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path, wal_mode=True)

        # Check journal mode
        cursor = backend.conn.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]
        assert journal_mode == "wal"

        backend.close()

    def test_sqlite_backend_circular(self, tmp_path: Path):
        """Test circular write mode with retention."""
        from datetime import datetime, timezone
        db_path = tmp_path / "test.sqlite"
        # Small retention for testing (1 hour)
        backend = SQLiteBackend(db_path, circular=True, max_size_mb=1, retention_hours=1)

        # Write many entries with current timestamps
        now = datetime.now(timezone.utc)
        for i in range(100):
            entry = {
                "ts": now.isoformat(),
                "level": "INFO",
                "msg": f"Message {i}",
                "rid": "rid1",
                "pid": "12345",
                "seq": i,
            }
            backend.write(entry)

        # All should be present (within retention)
        results = backend.query()
        assert len(results) == 100

        backend.close()

    def test_agent_logger_sqlite_backend(self, tmp_path: Path):
        """Test AgentLogger with SQLite backend."""
        logger = AgentLogger(
            program="test_program",
            command="test_command",
            log_dir=tmp_path,
            storage="sqlite",
        )

        logger.info("Test message")
        logger.error("Error message", error_code=ErrorCode.IO_NOT_FOUND)
        logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)

        # Verify file was created with .sqlite extension
        log_files = list(tmp_path.glob("*.sqlite"))
        assert len(log_files) == 1

        # Query using backend
        results = logger._backend.query()
        assert len(results) == 3  # info, error, tool_call

    def test_sqlite_backend_pagination(self, tmp_path: Path):
        """Test pagination with limit and offset."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)

        # Write 20 entries
        for i in range(20):
            entry = {
                "ts": f"2026-01-01T00:00:{i:02d}Z",
                "level": "INFO",
                "msg": f"Message {i}",
                "rid": "rid1",
                "pid": "12345",
                "seq": i,
            }
            backend.write(entry)

        # Query with limit
        results = backend.query(limit=5)
        assert len(results) == 5

        # Query with offset
        results = backend.query(limit=5, offset=10)
        assert len(results) == 5

        backend.close()

    def test_sqlite_backend_order_by(self, tmp_path: Path):
        """Test ordering results."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)

        entries = [
            {"ts": "2026-01-01T00:00:00Z", "level": "INFO", "msg": "First", "rid": "r1", "pid": "12345", "seq": 1, "dur": 100},
            {"ts": "2026-01-01T00:00:02Z", "level": "INFO", "msg": "Third", "rid": "r1", "pid": "12345", "seq": 2, "dur": 300},
            {"ts": "2026-01-01T00:00:01Z", "level": "INFO", "msg": "Second", "rid": "r1", "pid": "12345", "seq": 3, "dur": 200},
        ]
        for entry in entries:
            backend.write(entry)

        # Order by timestamp ascending
        results = backend.query(order_by="ts_asc")
        assert results[0]["msg"] == "First"
        assert results[2]["msg"] == "Third"

        # Order by duration descending
        results = backend.query(order_by="dur_desc")
        assert results[0]["msg"] == "Third"
        assert results[2]["msg"] == "First"

        backend.close()

    def test_sqlite_filter_by_exit_code(self, tmp_path: Path):
        """exit_code filter must work (regression: was silently ignored)."""
        db_path = tmp_path / "test.sqlite"
        backend = SQLiteBackend(db_path)
        backend.write({"ts": "2026-01-01T00:00:00Z", "level": "TOOL", "msg": "ok",
                       "rid": "r", "pid": "1", "seq": 1, "tool": "bash", "cmd": "ls",
                       "exit": 0, "dur": 10})
        backend.write({"ts": "2026-01-01T00:00:01Z", "level": "TOOL", "msg": "fail",
                       "rid": "r", "pid": "1", "seq": 2, "tool": "bash", "cmd": "bad",
                       "exit": 1, "dur": 10})

        # Direct exit_code filter
        assert len(backend.query(exit_code=1)) == 1
        # Alias 'exit' filter (entry field name)
        assert len(backend.query(exit=1)) == 1
        # Combined with tool filter
        res = backend.query(tool="bash", exit_code=1)
        assert len(res) == 1
        assert res[0]["msg"] == "fail"

        backend.close()


class TestSQLiteCoverage:
    """Cover query filters, batch, cleanup, row conversion edge cases."""

    def _full(self, backend):
        """Write one of each entry type for filter coverage."""
        from agentic_logger import ErrorCode
        base = {"rid": "r1", "pid": "1"}
        backend.write({**base, "ts": "2026-07-21T01:00:00.000+00:00", "level": "INFO",
                       "msg": "i", "module": "agent.parser", "seq": 1, "dur": 10})
        backend.write({**base, "ts": "2026-07-21T02:00:00.000+00:00", "level": "ERROR",
                       "msg": "e", "module": "agent.db", "seq": 2, "error_code": "IO_NOT_FOUND"})
        backend.write({**base, "ts": "2026-07-21T03:00:00.000+00:00", "level": "TOOL",
                       "msg": "t", "module": "m", "seq": 3, "tool": "bash", "cmd": "ls",
                       "exit": 0, "dur": 5, "stdout": "o", "stderr": "s"})
        backend.write({**base, "ts": "2026-07-21T04:00:00.000+00:00", "level": "FILE_OP",
                       "msg": "f", "module": "m", "seq": 4, "op": "write", "path": "/p",
                       "ok": True, "size": 9})
        backend.write({**base, "ts": "2026-07-21T05:00:00.000+00:00", "level": "DECISION",
                       "msg": "d", "module": "m", "seq": 5, "choice": "async",
                       "alts": ["sync"], "reason": "io", "confidence": 0.8})
        backend.write({**base, "ts": "2026-07-21T06:00:00.000+00:00", "level": "CODE_GEN",
                       "msg": "c", "module": "m", "seq": 6, "lang": "python", "path": "/x.py",
                       "lines": 5, "funcs": ["main"], "imports": ["os"]})
        backend.write({**base, "ts": "2026-07-21T07:00:00.000+00:00", "level": "CONTEXT",
                       "msg": "ctx", "module": "m", "seq": 7, "from_task": "a", "to_task": "b"})
        backend.write({**base, "ts": "2026-07-21T08:00:00.000+00:00", "level": "INFO",
                       "msg": "lifecycle", "module": "__lifecycle__", "seq": 8,
                       "event": "run_end", "exit_code": 0})

    def test_write_batch(self, tmp_path):
        b = SQLiteBackend(tmp_path / "b.sqlite")
        entries = [{"ts": f"2026-01-01T00:00:0{i}Z", "level": "INFO", "msg": f"m{i}",
                    "rid": "r", "pid": "1", "seq": i} for i in range(5)]
        b.write_batch(entries)
        assert b.count() == 5
        b.close()

    def test_query_all_filters(self, tmp_path):
        b = SQLiteBackend(tmp_path / "b.sqlite")
        self._full(b)
        assert len(b.query(module="agent.*")) >= 1          # module glob
        assert len(b.query(op="write")) == 1                 # op
        assert len(b.query(path="/p")) == 1                  # path
        assert len(b.query(choice="async")) == 1             # choice
        assert len(b.query(since="2026-07-21T05:00:00.000+00:00")) >= 4  # since
        assert len(b.query(until="2026-07-21T03:00:00.000+00:00")) >= 3  # until
        assert len(b.query(keyword="lifecycle")) >= 1        # keyword (matches msg)
        assert len(b.query(min_dur=5)) >= 1                  # min_dur
        assert len(b.query(max_dur=5)) >= 1                  # max_dur
        assert len(b.query(pid="1")) == 8                    # pid
        b.close()

    def test_get_traceback_none_and_count(self, tmp_path):
        b = SQLiteBackend(tmp_path / "b.sqlite")
        assert b.get_traceback("missing") is None
        self._full(b)
        assert b.count() == 8
        assert b.get_time_range() is not None
        b.close()

    def test_cleanup_time_and_size_and_orphans(self, tmp_path):
        # Force time-based + size-based + orphan cleanup via tiny limits.
        # max_size_mb=0 guarantees the size-based delete branch; retention_hours=0
        # makes every old-ts entry time-expired; an orphan traceback exercises the
        # orphan-cleanup DELETE. Cleanup auto-runs every 100 writes (write=100).
        b = SQLiteBackend(tmp_path / "c.sqlite", circular=True, max_size_mb=0,
                          retention_hours=0)
        b.save_traceback("tb_orphan", "x", "Err", "m")  # orphan (no matching log)
        for i in range(150):  # passes the 100-write cleanup trigger
            b.write({"ts": "2020-01-01T00:00:00.000+00:00", "level": "INFO",
                     "msg": f"m{i}", "rid": "r", "pid": "1", "seq": i})
        b.close()

    def test_row_to_dict_malformed_json(self, tmp_path):
        """Malformed ctx/alts/funcs/imports must not crash _row_to_dict."""
        b = SQLiteBackend(tmp_path / "r.sqlite")
        b.conn.execute(
            "INSERT INTO logs (ts,level,msg,module,rid,pid,seq,ctx,alts,funcs,imports,exit_code) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2026-01-01T00:00:00Z", "TOOL", "t", "m", "r", "1", 1,
             "{bad", "{bad", "{bad", "{bad", 0),
        )
        b.conn.commit()
        rows = b.query(level="TOOL")
        assert len(rows) == 1
        b.close()
