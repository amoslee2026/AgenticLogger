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
        db_path = tmp_path / "test.sqlite"
        # Small retention for testing (1 hour)
        backend = SQLiteBackend(db_path, circular=True, max_size_mb=1, retention_hours=1)

        # Write many entries
        for i in range(100):
            entry = {
                "ts": "2026-01-01T00:00:00Z",
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
            {"ts": "2026-01-01T00:00:00Z", "level": "INFO", "msg": "First", "rid": "r1", "dur": 100},
            {"ts": "2026-01-01T00:00:02Z", "level": "INFO", "msg": "Third", "rid": "r1", "dur": 300},
            {"ts": "2026-01-01T00:00:01Z", "level": "INFO", "msg": "Second", "rid": "r1", "dur": 200},
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
