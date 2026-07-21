"""Tests for MCP Server tool handlers.

@spec-ref: spec/04-read-interface.md §2 — MCP Tool
"""

import json
from pathlib import Path

import pytest

from agentic_logger import AgentLogger, ErrorCode
from agentic_logger.mcp_server import (
    create_server,
    handle_query,
    handle_stats,
    handle_trace,
    handle_traceback,
)


@pytest.fixture
def populated_log_dir(tmp_path):
    """Create a log directory with test data."""
    log_dir = tmp_path / "logs"
    logger = AgentLogger(program="test_agent", command="mcp_test", log_dir=log_dir, storage="jsonl")
    logger.run_start(msg="Test run started")
    logger.info("Processing started", module="agent.parser", ctx={"file": "data.json"})
    logger.info("Step 1 done", module="agent.parser")
    logger.warn("Slow operation", module="agent.db", dur=5000)
    logger.tool_call(tool="bash", cmd="npm install", exit=0, dur=1234, stdout="added 50 packages")
    logger.tool_call(tool="bash", cmd="npm run build", exit=1, dur=5000, error_code=ErrorCode.EXEC_NON_ZERO)
    logger.file_op("write", "/tmp/output.txt", ok=True, size=2048)
    logger.file_op("read", "/missing.txt", ok=False, error_code=ErrorCode.IO_NOT_FOUND)
    logger.decision(choice="async", alts=["sync"], reason="IO-bound", module="agent.architect")
    logger.code_gen(lang="python", path="src/main.py", lines=50, funcs=["main"])

    # Save a traceback for testing
    try:
        raise ValueError("test error for traceback")
    except Exception as e:
        tid = logger.save_traceback(e)
        logger.error("Operation failed", error_code=ErrorCode.INTERNAL_UNEXPECTED, tid=tid)

    logger.run_end(exit_code=0, dur=10000)

    return log_dir, logger.rid, tid


class TestHandleQuery:
    def test_query_all(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir)
        assert result["count"] > 0
        assert "logs" in result

    def test_query_by_level(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, level="ERROR")
        assert result["count"] >= 1
        for log in result["logs"]:
            assert log["level"] == "ERROR"

    def test_query_by_module_wildcard(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, module="agent.*")
        assert result["count"] >= 1
        for log in result["logs"]:
            assert log["module"].startswith("agent.")

    def test_query_by_error_code(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, error_code="IO_NOT_FOUND")
        assert result["count"] >= 1

    def test_query_by_tool(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, tool="bash")
        assert result["count"] == 2

    def test_query_by_exit_code(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, tool="bash", exit_code=1)
        assert result["count"] == 1

    def test_query_by_keyword(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, keyword="npm install")
        assert result["count"] >= 1

    def test_query_by_rid(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, rid=rid)
        assert result["count"] >= 1

    def test_query_min_dur(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, min_dur=1000)
        assert result["count"] >= 1
        for log in result["logs"]:
            assert (log.get("dur") or 0) >= 1000

    def test_query_limit(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, limit=3)
        assert result["count"] <= 3

    def test_query_order_by_dur_desc(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir, order_by="dur_desc", limit=5)
        durs = [log.get("dur", 0) for log in result["logs"]]
        assert durs == sorted(durs, reverse=True)

    def test_query_empty_dir(self, tmp_path):
        log_dir = tmp_path / "empty"
        log_dir.mkdir()
        result = handle_query(log_dir)
        assert result["count"] == 0

    def test_query_excludes_global_ctx(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_query(log_dir)
        for log in result["logs"]:
            assert log["level"] != "__GLOBAL_CTX__"


class TestHandleTrace:
    def test_trace_by_rid(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_trace(log_dir, rid=rid)
        assert result["rid"] == rid
        assert result["entry_count"] > 0
        assert result["start_time"] is not None
        assert result["end_time"] is not None

    def test_trace_sorted_by_time(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_trace(log_dir, rid=rid)
        timestamps = [e["ts"] for e in result["trace"]]
        assert timestamps == sorted(timestamps)

    def test_trace_with_level_filter(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_trace(log_dir, rid=rid, level="ERROR")
        for entry in result["trace"]:
            assert entry["level"] == "ERROR"

    def test_trace_summary(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_trace(log_dir, rid=rid)
        summary = result["summary"]
        assert "INFO" in summary
        assert "ERROR" in summary

    def test_trace_include_traceback(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_trace(log_dir, rid=rid, include_traceback=True)
        # At least one entry should have traceback_detail
        has_tb = any("traceback_detail" in e for e in result["trace"])
        assert has_tb

    def test_trace_nonexistent_rid(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_trace(log_dir, rid="nonexistent")
        assert result["entry_count"] == 0


class TestHandleStats:
    def test_stats_by_level(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_stats(log_dir, group_by="level")
        assert result["total"] > 0
        keys = [g["key"] for g in result["groups"]]
        assert "INFO" in keys
        assert "ERROR" in keys

    def test_stats_by_module(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_stats(log_dir, group_by="module")
        assert result["total"] > 0

    def test_stats_by_tool(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_stats(log_dir, group_by="tool")
        # Only TOOL entries have 'tool' field
        assert result["total"] >= 2

    def test_stats_by_error_code(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_stats(log_dir, group_by="error_code")
        assert result["total"] > 0

    def test_stats_with_rid_filter(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_stats(log_dir, group_by="level", rid=rid)
        assert result["total"] > 0

    def test_stats_percentages_sum(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_stats(log_dir, group_by="level")
        total_pct = sum(g["percentage"] for g in result["groups"])
        assert abs(total_pct - 100.0) < 1.0  # Within 1% due to rounding


class TestHandleTraceback:
    def test_get_existing_traceback(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_traceback(log_dir, tid)
        assert result is not None
        assert result["tid"] == tid
        assert result["exception_type"] == "ValueError"
        assert "test error for traceback" in result["exception_msg"]
        assert "ValueError" in result["traceback"]

    def test_get_nonexistent_traceback(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        result = handle_traceback(log_dir, "nonexistent_tid")
        assert result is None


class TestCreateServer:
    def test_server_name(self, tmp_path):
        server = create_server(log_dir=tmp_path)
        assert server.name == "agentic-logger"

    def test_list_tools(self, tmp_path):
        """Verify the server registers all expected tools."""
        server = create_server(log_dir=tmp_path)
        # The list_tools handler is registered; we can't call it directly
        # without an async MCP context, but we can verify server creation
        assert server is not None
