"""Tests for AgentLogger core functionality."""

import json
import os
import tempfile
import warnings
from pathlib import Path

import pytest

from agentic_logger import AgentLogger, ErrorCode


@pytest.fixture
def log_dir(tmp_path):
    return tmp_path / "logs"


@pytest.fixture
def logger(log_dir):
    return AgentLogger(program="test_agent", command="test", log_dir=log_dir, storage="jsonl")


def _read_logs(file_path: Path) -> list[dict]:
    """Read all JSON entries from a log file, skipping global ctx."""
    with open(file_path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _read_entries(file_path: Path) -> list[dict]:
    """Read log entries excluding __GLOBAL_CTX__."""
    return [e for e in _read_logs(file_path) if e["level"] != "__GLOBAL_CTX__"]


# === Test: Initialization ===


class TestInit:
    def test_creates_log_dir(self, tmp_path):
        log_dir = tmp_path / "new_dir"
        logger = AgentLogger(program="test", log_dir=log_dir)
        assert log_dir.exists()
        assert logger.file_path.parent == log_dir

    def test_filename_format(self, log_dir):
        logger = AgentLogger(program="test_agent", command="test", log_dir=log_dir, storage="jsonl")
        name = logger.file_path.name
        assert name.startswith("test_agent_test_")
        assert name.endswith(".jsonl")
        # Format: {program}_{cmd}_{YYYYMMDD}_{HHmmssffffff}.jsonl
        parts = name.replace(".jsonl", "").split("_")
        assert len(parts) >= 4  # test, agent, test, date, time

    def test_rid_auto_generated(self, logger):
        assert logger.rid is not None
        assert len(logger.rid) == 8

    def test_rid_custom(self, log_dir):
        logger = AgentLogger(program="test", log_dir=log_dir, rid="custom_rid")
        assert logger.rid == "custom_rid"

    def test_global_context_written(self, logger):
        entries = _read_logs(logger.file_path)
        ctx = entries[0]
        assert ctx["level"] == "__GLOBAL_CTX__"
        assert ctx["program"] == "test_agent"
        assert ctx["command"] == "test"


# === Test: Auto Fields ===


class TestAutoFields:
    def test_ts_present(self, logger):
        logger.info("test")
        entries = _read_entries(logger.file_path)
        assert "ts" in entries[0]
        assert "T" in entries[0]["ts"]  # ISO 8601

    def test_pid_present(self, logger):
        logger.info("test")
        entries = _read_entries(logger.file_path)
        assert entries[0]["pid"] == str(os.getpid())

    def test_rid_present(self, logger):
        logger.info("test")
        entries = _read_entries(logger.file_path)
        assert entries[0]["rid"] == logger.rid

    def test_seq_increments(self, logger):
        logger.info("first")
        logger.info("second")
        logger.info("third")
        entries = _read_entries(logger.file_path)
        seqs = [e["seq"] for e in entries]
        assert seqs == [1, 2, 3]

    def test_none_values_omitted(self, logger):
        """评审修复 R06: None values should be omitted to save tokens."""
        logger.info("test")
        entries = _read_entries(logger.file_path)
        assert "tid" not in entries[0]  # tid=None → omitted
        assert "dur" not in entries[0]  # dur=None → omitted
        assert "error_code" not in entries[0]


# === Test: Basic Log Methods ===


class TestBasicLogs:
    def test_info(self, logger):
        logger.info("Hello world")
        entries = _read_entries(logger.file_path)
        assert len(entries) == 1
        assert entries[0]["level"] == "INFO"
        assert entries[0]["msg"] == "Hello world"

    def test_info_with_ctx(self, logger):
        logger.info("test", ctx={"key": "value", "num": 42})
        entries = _read_entries(logger.file_path)
        assert entries[0]["ctx"] == {"key": "value", "num": 42}

    def test_info_with_module(self, logger):
        logger.info("test", module="custom.module")
        entries = _read_entries(logger.file_path)
        assert entries[0]["module"] == "custom.module"

    def test_info_auto_module(self, logger):
        logger.info("test")
        entries = _read_entries(logger.file_path)
        # Should auto-detect module name
        assert "module" in entries[0]
        assert entries[0]["module"] != "unknown"

    def test_warn(self, logger):
        logger.warn("Slow op", dur=5000)
        entries = _read_entries(logger.file_path)
        assert entries[0]["level"] == "WARN"
        assert entries[0]["dur"] == 5000

    def test_error_with_code(self, logger):
        logger.error("Failed", error_code=ErrorCode.IO_NOT_FOUND)
        entries = _read_entries(logger.file_path)
        assert entries[0]["level"] == "ERROR"
        assert entries[0]["error_code"] == "IO_NOT_FOUND"

    def test_error_without_code_warns(self, logger):
        """评审修复 AGG-002: missing error_code should warn."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            logger.error("Oops")
            assert len(w) == 1
            assert "error_code not provided" in str(w[0].message)

    def test_error_default_code(self, logger):
        """Without error_code, defaults to UNKNOWN."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            logger.error("Oops")
        entries = _read_entries(logger.file_path)
        assert entries[0]["error_code"] == "UNKNOWN"

    def test_msg_truncated(self, logger):
        """评审修复 B01: msg should be truncated to 4KB."""
        long_msg = "x" * 10000
        logger.info(long_msg)
        entries = _read_entries(logger.file_path)
        assert len(entries[0]["msg"]) <= 4096


# === Test: Specialized Methods ===


class TestSpecialized:
    def test_tool_call_success(self, logger):
        logger.tool_call(tool="bash", cmd="ls -la", exit=0, dur=50, stdout="file1.txt")
        entries = _read_entries(logger.file_path)
        e = entries[0]
        assert e["level"] == "TOOL"
        assert e["tool"] == "bash"
        assert e["cmd"] == "ls -la"
        assert e["exit"] == 0
        assert e["dur"] == 50
        assert e["stdout"] == "file1.txt"

    def test_tool_call_failure_requires_error_code(self, logger):
        """评审修复 AGG-016: exit != 0 requires error_code."""
        with pytest.raises(ValueError, match="error_code is required"):
            logger.tool_call(tool="bash", cmd="rm -rf /", exit=1, dur=100)

    def test_tool_call_failure_with_code(self, logger):
        logger.tool_call(
            tool="bash", cmd="rm -rf /", exit=1, dur=100,
            error_code=ErrorCode.EXEC_NON_ZERO, stderr="Permission denied"
        )
        entries = _read_entries(logger.file_path)
        assert entries[0]["error_code"] == "EXEC_NON_ZERO"

    def test_file_op_success(self, logger):
        logger.file_op("write", "/tmp/test.txt", ok=True, size=1024)
        entries = _read_entries(logger.file_path)
        e = entries[0]
        assert e["level"] == "FILE_OP"
        assert e["op"] == "write"
        assert e["path"] == "/tmp/test.txt"
        assert e["ok"] is True
        assert e["size"] == 1024

    def test_file_op_failure_requires_error_code(self, logger):
        """评审修复 AGG-016: ok=False requires error_code."""
        with pytest.raises(ValueError, match="error_code is required"):
            logger.file_op("read", "/missing.txt", ok=False)

    def test_file_op_failure_with_code(self, logger):
        logger.file_op("read", "/missing.txt", ok=False, error_code=ErrorCode.IO_NOT_FOUND)
        entries = _read_entries(logger.file_path)
        assert entries[0]["error_code"] == "IO_NOT_FOUND"

    def test_decision(self, logger):
        logger.decision(choice="async", alts=["sync", "threading"], reason="IO-bound", confidence=0.85)
        entries = _read_entries(logger.file_path)
        e = entries[0]
        assert e["level"] == "DECISION"
        assert e["choice"] == "async"
        assert e["alts"] == ["sync", "threading"]
        assert e["reason"] == "IO-bound"
        assert e["confidence"] == 0.85

    def test_code_gen(self, logger):
        logger.code_gen(lang="python", path="main.py", lines=50, funcs=["main"])
        entries = _read_entries(logger.file_path)
        e = entries[0]
        assert e["level"] == "CODE_GEN"
        assert e["lang"] == "python"
        assert e["path"] == "main.py"
        assert e["lines"] == 50
        assert e["funcs"] == ["main"]

    def test_context_switch(self, logger):
        logger.context_switch(to_task="deploy", from_task="test", reason="CI passed")
        entries = _read_entries(logger.file_path)
        e = entries[0]
        assert e["level"] == "CONTEXT"
        assert e["to_task"] == "deploy"
        assert e["from_task"] == "test"
        assert e["reason"] == "CI passed"


# === Test: Exception & Traceback ===


class TestException:
    def test_exception_captures_traceback(self, logger):
        try:
            raise ValueError("test error")
        except Exception:
            logger.exception("Operation failed", error_code=ErrorCode.INTERNAL_UNEXPECTED)

        entries = _read_entries(logger.file_path)
        e = entries[0]
        assert e["level"] == "ERROR"
        assert "tid" in e
        assert e["error_code"] == "INTERNAL_UNEXPECTED"

        # Verify traceback saved
        tb = logger._backend.get_traceback(e["tid"])
        assert tb is not None
        assert tb["exception_type"] == "ValueError"
        assert "test error" in tb["exception_msg"]
        assert "ValueError" in tb["traceback"]

    def test_exception_outside_except_raises(self, logger):
        with pytest.raises(ValueError, match="must be called inside an except block"):
            logger.exception("Not in except")

    def test_save_traceback_returns_tid(self, logger):
        try:
            raise RuntimeError("boom")
        except Exception as e:
            tid = logger.save_traceback(e)

        assert tid.startswith("tb_")
        tb = logger._backend.get_traceback(tid)
        assert tb is not None
        assert "boom" in tb["traceback"]


# === Test: Lifecycle ===


class TestLifecycle:
    def test_run_start_end(self, logger):
        logger.run_start()
        logger.info("working")
        logger.run_end(exit_code=0, dur=1000)

        entries = _read_entries(logger.file_path)
        assert entries[0]["event"] == "run_start"
        assert entries[-1]["event"] == "run_end"
        assert entries[-1]["exit_code"] == 0
        assert entries[-1]["dur"] == 1000

    def test_auto_run_end_on_exit(self, log_dir):
        """atexit hook should auto-close unclosed runs."""
        logger = AgentLogger(program="test", log_dir=log_dir)
        logger.run_start()
        logger.info("working")
        # Don't call run_end — simulate crash

        # Trigger atexit manually
        logger._auto_run_end()

        entries = _read_entries(logger.file_path)
        last = entries[-1]
        assert last["event"] == "run_end"
        assert last["exit_code"] == 1
        assert "unexpectedly" in last["msg"]


# === Test: Query ===


class TestQuery:
    def test_query_by_level(self, logger):
        logger.info("info1")
        logger.warn("warn1")
        logger.error("error1", error_code=ErrorCode.UNKNOWN)
        logger.info("info2")

        errors = logger._backend.query(level="ERROR")
        assert len(errors) == 1
        assert errors[0]["msg"] == "error1"

    def test_query_by_error_code(self, logger):
        logger.error("e1", error_code=ErrorCode.IO_NOT_FOUND)
        logger.error("e2", error_code=ErrorCode.EXEC_NON_ZERO)

        results = logger._backend.query(error_code="IO_NOT_FOUND")
        assert len(results) == 1
        assert results[0]["msg"] == "e1"

    def test_query_by_module_wildcard(self, logger):
        logger.info("a", module="agent.bash")
        logger.info("b", module="agent.file")
        logger.info("c", module="parser.json")

        results = logger._backend.query(module="agent.*")
        assert len(results) == 2

    def test_query_by_rid(self, logger):
        logger.info("test")
        rid = logger.rid
        results = logger._backend.query(rid=rid)
        # GLOBAL_CTX + INFO both have rid
        entries = [e for e in results if e["level"] != "__GLOBAL_CTX__"]
        assert len(entries) == 1

    def test_query_by_dur_range(self, logger):
        logger.info("fast", dur=50)
        logger.info("medium", dur=500)
        logger.info("slow", dur=5000)

        results = logger._backend.query(min_dur=100, max_dur=1000)
        assert len(results) == 1
        assert results[0]["msg"] == "medium"

    def test_query_limit(self, logger):
        for i in range(20):
            logger.info(f"msg {i}")
        results = logger._backend.query(limit=5)
        assert len(results) == 5

    def test_query_keyword(self, logger):
        logger.info("Processing user request", ctx={"user": "alice"})
        logger.info("Building project")

        results = logger._backend.query(keyword="alice")
        assert len(results) == 1


# === Test: JSONL Validity ===


class TestJSONLValidity:
    def test_each_line_valid_json(self, logger):
        logger.info("test1")
        logger.warn("test2")
        logger.error("test3", error_code=ErrorCode.UNKNOWN)

        with open(logger.file_path) as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    assert isinstance(entry, dict)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Line {i} is not valid JSON: {e}\n{line}")

    def test_no_newlines_in_msg(self, logger):
        """评审修复 S01: newlines in msg should be escaped."""
        logger.info("line1\nline2\rline3")
        entries = _read_entries(logger.file_path)
        # Should be parseable as single JSON line
        assert "\n" not in json.dumps(entries[0])


# === Test: ErrorCode Enum ===


class TestErrorCode:
    def test_enum_values(self):
        assert str(ErrorCode.PARSE_JSON) == "PARSE_JSON"
        assert str(ErrorCode.IO_NOT_FOUND) == "IO_NOT_FOUND"
        assert str(ErrorCode.UNKNOWN) == "UNKNOWN"

    def test_all_categories(self):
        """Verify all categories exist."""
        codes = [e.value for e in ErrorCode]
        assert any(c.startswith("PARSE_") for c in codes)
        assert any(c.startswith("IO_") for c in codes)
        assert any(c.startswith("EXEC_") for c in codes)
        assert any(c.startswith("NET_") for c in codes)
        assert any(c.startswith("AUTH_") for c in codes)
        assert any(c.startswith("CONFIG_") for c in codes)
        assert any(c.startswith("RES_") for c in codes)
        assert any(c.startswith("TIMEOUT_") for c in codes)
        assert any(c.startswith("CONFLICT_") for c in codes)
        assert any(c.startswith("INTERNAL_") for c in codes)
        assert "UNKNOWN" in codes


# === P1: Rotation-aware file_path, close(), thread safety ===


class TestFilePathAndClose:
    def test_file_path_updates_after_rotation(self, tmp_path):
        """logger.file_path must reflect the active file after rotation."""
        log_dir = tmp_path / "logs"
        logger = AgentLogger(
            program="rot", command="main", log_dir=log_dir,
            storage="jsonl", circular=True, max_size_mb=0, max_files=5,
        )
        original = logger.file_path
        logger.info("trigger rotation")  # max_size_mb=0 forces rotation
        assert logger.file_path != original, "file_path stale after rotation"

    def test_logger_close_closes_sqlite_backend(self, tmp_path):
        """AgentLogger.close() must release the SQLite connection."""
        log_dir = tmp_path / "logs"
        logger = AgentLogger(
            program="cl", command="main", log_dir=log_dir, storage="sqlite"
        )
        logger.info("x")
        logger.close()
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            logger._backend.query()


class TestThreadSafety:
    def test_seq_unique_under_concurrency(self):
        """seq must stay unique when many threads fill concurrently."""
        import threading
        from agentic_logger.fields import AutoFields

        af = AutoFields()
        collected: list[int] = []
        guard = threading.Lock()

        def worker():
            local = []
            for _ in range(200):
                e = {}
                af.fill(e)
                local.append(e["seq"])
            with guard:
                collected.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(collected) == len(set(collected)), "duplicate seq under concurrency"
