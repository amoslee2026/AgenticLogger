"""Tests for CLI commands."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_logger import AgentLogger, ErrorCode


@pytest.fixture
def cli_env(tmp_path):
    """Set up a log directory with test data and return CLI base args."""
    log_dir = tmp_path / "logs"
    logger = AgentLogger(program="cli_test", command="demo", log_dir=log_dir, storage="jsonl")
    logger.run_start()
    logger.info("Processing", module="agent.parser", ctx={"file": "data.json"})
    logger.warn("Slow op", dur=5000)
    logger.error("Failed", error_code=ErrorCode.IO_NOT_FOUND)
    logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
    logger.tool_call(tool="bash", cmd="rm", exit=1, dur=100, error_code=ErrorCode.EXEC_NON_ZERO)
    logger.decision(choice="async", alts=["sync"])
    logger.run_end(exit_code=0, dur=10000)

    # Save a traceback
    try:
        raise ValueError("test error")
    except Exception as e:
        tid = logger.save_traceback(e)
        logger.error("Exception caught", error_code=ErrorCode.INTERNAL_UNEXPECTED, tid=tid)

    base = [sys.executable, "-m", "agentic_logger.cli", "--log-dir", str(log_dir)]
    return base, logger.rid, tid


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


class TestQuery:
    def test_query_all(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query"])
        assert r.returncode == 0
        assert "Found" in r.stdout

    def test_query_by_level(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query", "--level", "ERROR"])
        assert r.returncode == 0
        assert "Failed" in r.stdout or "Exception" in r.stdout

    def test_query_json_format(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query", "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "count" in data
        assert "logs" in data

    def test_query_by_error_code(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["query", "--error-code", "IO_NOT_FOUND"])
        assert r.returncode == 0
        assert "IO_NOT_FOUND" in r.stdout


class TestTrace:
    def test_trace_by_rid(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["trace", "--rid", rid])
        assert r.returncode == 0
        assert f"rid={rid}" in r.stdout

    def test_trace_json(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["trace", "--rid", rid, "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["rid"] == rid

    def test_trace_with_traceback(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["trace", "--rid", rid, "--include-traceback", "--format", "json"])
        assert r.returncode == 0


class TestStats:
    def test_stats_by_level(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["stats", "--group-by", "level"])
        assert r.returncode == 0
        assert "INFO" in r.stdout
        assert "ERROR" in r.stdout

    def test_stats_json(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["stats", "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "total" in data
        assert "groups" in data


class TestTail:
    def test_tail_no_follow(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["tail"])
        assert r.returncode == 0
        assert "Tailing:" in r.stderr


class TestTraceback:
    def test_traceback_found(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["traceback", "--tid", tid])
        assert r.returncode == 0
        assert "ValueError" in r.stdout

    def test_traceback_not_found(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["traceback", "--tid", "nonexistent"])
        assert r.returncode == 1


class TestListFiles:
    def test_list_files(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["list-files"])
        assert r.returncode == 0
        assert "cli_test_demo_" in r.stdout

    def test_list_files_json(self, cli_env):
        base, rid, tid = cli_env
        r = _run(base + ["list-files", "--format", "json"])
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data) >= 1
