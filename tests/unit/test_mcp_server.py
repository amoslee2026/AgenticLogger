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

    def test_sqlite_logs_visible_to_query(self, tmp_path):
        """SQLite-written logs must be readable via the MCP read layer (regression)."""
        log_dir = tmp_path / "logs"
        logger = AgentLogger(
            program="sql_agent", command="run", log_dir=log_dir, storage="sqlite"
        )
        logger.info("sqlite entry", module="m")
        logger.tool_call(tool="bash", cmd="ls", exit=0, dur=5)
        logger.error("boom", error_code=ErrorCode.IO_NOT_FOUND)
        result = handle_query(log_dir)
        assert result["count"] >= 3, f"sqlite logs invisible: {result}"


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


class TestDispatchTool:
    """P1: MCP tool dispatch must isolate exceptions (no 500 on bad args)."""

    def test_unknown_tool_returns_error(self, tmp_path):
        from agentic_logger.mcp_server import dispatch_tool
        result = dispatch_tool(tmp_path, "nonexistent_tool", {})
        assert "error" in result

    def test_bad_args_return_error_not_raise(self, tmp_path):
        from agentic_logger.mcp_server import dispatch_tool
        # Unknown kwarg would normally raise TypeError — must be caught.
        result = dispatch_tool(tmp_path, "agentic_log_query", {"bogus_kwarg": 1})
        assert "error" in result


class TestHandleQueryFilters:
    """Cover every handle_query filter branch + merge time-pruning."""

    def test_all_filter_branches(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        # exercise op / path / choice / keyword / min_dur / max_dur / pid / tid branches
        for kwargs in (
            dict(op="write"), dict(path="/tmp/output.txt"), dict(choice="async"),
            dict(keyword="Processing"), dict(min_dur=100), dict(max_dur=100000),
            dict(pid=str(__import__("os").getpid())), dict(tid=tid),
            dict(since="2000-01-01T00:00:00+00:00", until="2099-01-01T00:00:00+00:00"),
        ):
            res = handle_query(log_dir, **kwargs)
            assert "logs" in res

    def test_merge_time_pruning_skips_out_of_range(self, tmp_path):
        # Two backends; one entirely before the since window must be pruned.
        log_dir = tmp_path / "logs"
        old = AgentLogger(program="old", command="r", log_dir=log_dir, storage="jsonl")
        old.info("ancient", module="m")
        new = AgentLogger(program="new", command="r", log_dir=log_dir, storage="jsonl")
        new.info("recent", module="m")
        # Query a far-future window -> prunes by max_ts < since
        res = handle_query(log_dir, since="2099-01-01T00:00:00+00:00")
        assert res["count"] == 0


class TestHandleTraceFilters:
    def test_trace_level_and_module_filters(self, populated_log_dir):
        log_dir, rid, tid = populated_log_dir
        r1 = handle_trace(log_dir, rid=rid, level="ERROR")
        assert all(e["level"] == "ERROR" for e in r1["trace"])
        r2 = handle_trace(log_dir, rid=rid, module="agent.parser")
        assert r2["entry_count"] >= 1


class TestLoadBackendsRobustness:
    def test_corrupt_sqlite_is_skipped(self, tmp_path):
        """A non-SQLite .sqlite file must be skipped, not crash the loader."""
        from agentic_logger.mcp_server import _load_all_backends
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "bad.sqlite").write_text("not a sqlite db")
        (log_dir / "good.jsonl").write_text(
            '{"ts":"2026-01-01T00:00:00+00:00","level":"INFO","msg":"ok",'
            '"module":"m","rid":"r","pid":"1","seq":1}\n'
        )
        backends = _load_all_backends(log_dir)
        # good.jsonl loaded; bad.sqlite skipped
        assert any(b.file_path.name == "good.jsonl" for b in backends)


class TestDispatchAllBranches:
    """Cover every dispatch_tool branch (trace / stats / traceback found+miss / generic exc)."""

    def test_dispatch_trace(self, populated_log_dir):
        from agentic_logger.mcp_server import dispatch_tool
        log_dir, rid, tid = populated_log_dir
        r = dispatch_tool(log_dir, "agentic_log_trace", {"rid": rid})
        assert "trace" in r

    def test_dispatch_stats(self, populated_log_dir):
        from agentic_logger.mcp_server import dispatch_tool
        r = dispatch_tool(populated_log_dir[0], "agentic_log_stats", {"group_by": "level"})
        assert "groups" in r

    def test_dispatch_traceback_found(self, populated_log_dir):
        from agentic_logger.mcp_server import dispatch_tool
        _, _, tid = populated_log_dir
        r = dispatch_tool(populated_log_dir[0], "agentic_log_traceback", {"tid": tid})
        assert "traceback" in r

    def test_dispatch_traceback_not_found(self, populated_log_dir):
        from agentic_logger.mcp_server import dispatch_tool
        r = dispatch_tool(populated_log_dir[0], "agentic_log_traceback", {"tid": "nope"})
        assert "error" in r

    def test_dispatch_generic_exception(self, tmp_path, monkeypatch):
        """A non-TypeError backend error must hit the generic except branch."""
        import agentic_logger.mcp_server as m
        from agentic_logger.mcp_server import dispatch_tool

        def boom(*a, **k):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(m, "handle_query", boom)
        r = dispatch_tool(tmp_path, "agentic_log_query", {})
        assert "error" in r and "RuntimeError" in r["error"]


class TestHandleStatsEdge:
    def test_stats_unknown_group_key(self, populated_log_dir):
        """group_by on a field most entries lack still returns a valid result."""
        r = handle_stats(populated_log_dir[0], group_by="nonexistent_field")
        assert r["total"] >= 1
        assert any(g["key"] == "unknown" for g in r["groups"])


class TestMainRuntime:
    def test_main_with_mocked_stdio(self, tmp_path, monkeypatch):
        """main() must drive create_server + run() without actually serving."""
        import sys
        import mcp.server.stdio as stdio_mod
        import mcp.server as srv_mod
        import agentic_logger.mcp_server as m

        monkeypatch.setattr(sys, "argv", ["mcp", "--log-dir", str(tmp_path)])

        class _Ctx:
            async def __aenter__(self):
                return (object(), object())
            async def __aexit__(self, *a):
                return False

        def fake_stdio():
            return _Ctx()
        monkeypatch.setattr(stdio_mod, "stdio_server", fake_stdio)

        async def fake_run(self, *a, **k):
            return None
        monkeypatch.setattr(srv_mod.Server, "run", fake_run)

        m.main()  # completes without hanging


class TestServerHandlers:
    """Invoke the registered async MCP handlers directly (cover the closures)."""

    def test_list_tools_and_call_tool(self, tmp_path):
        import asyncio
        from agentic_logger.mcp_server import create_server

        server = create_server(log_dir=tmp_path)
        tools = asyncio.run(server.list_tools())
        names = [t.name for t in tools]
        assert "agentic_log_query" in names and len(names) == 4

        # call_tool dispatches via dispatch_tool and returns TextContent list
        result = asyncio.run(server.call_tool("agentic_log_query", {}))
        assert result and result[0].type == "text"
