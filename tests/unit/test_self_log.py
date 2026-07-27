"""Tests for self-observability — AgenticLogger logging its own read layer.

@spec-ref: /home/lxx/.claude/plans/misty-foraging-turtle.md

Covers: env switch, lazy cached logger, MCP dispatch logging (success +
error), CLI main logging (success + ValueError), the closed-loop guarantee
(self-log queryable by ``handle_query`` via ``--module agentic_logger.*``),
and argument summarisation.
"""

import json
import sys
from pathlib import Path

import pytest

from agentic_logger import AgentLogger
from agentic_logger.cli import main as cli_main
from agentic_logger.mcp_server import dispatch_tool, handle_query
from agentic_logger.self_log import (
    _summarize_args,
    get_self_logger,
    is_enabled,
    log_cli_call,
    log_mcp_call,
    reset_cache,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def self_log_on(monkeypatch):
    """Explicitly enable self-log; clear the cache before and after."""
    monkeypatch.setenv("AGENTIC_SELF_LOG", "1")
    reset_cache()
    yield
    reset_cache()


def _self_files(log_dir: Path) -> list[Path]:
    return sorted(Path(log_dir).glob("agentic_logger_*.jsonl"))


def _entries(log_dir: Path) -> list[dict]:
    out: list[dict] = []
    for f in _self_files(log_dir):
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _data_entries(log_dir: Path) -> list[dict]:
    return [e for e in _entries(log_dir) if e.get("level") != "__GLOBAL_CTX__"]


# ------------------------------------------------------------------
# Env switch
# ------------------------------------------------------------------


class TestEnvSwitch:
    def test_default_off_via_conftest(self):
        # The autouse conftest fixture sets AGENTIC_SELF_LOG=0.
        assert is_enabled() is False

    def test_explicit_on(self, self_log_on):
        assert is_enabled() is True


# ------------------------------------------------------------------
# Disabled = no-op (covers early-return branches)
# ------------------------------------------------------------------


class TestDisabledNoOp:
    def test_get_self_logger_returns_none(self, tmp_path):
        reset_cache()
        assert get_self_logger(tmp_path / "logs", "mcp") is None

    def test_log_mcp_call_no_file(self, tmp_path):
        reset_cache()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_mcp_call(log_dir, "agentic_log_query", {}, {"count": 0, "logs": []}, 5)
        assert _self_files(log_dir) == []

    def test_log_cli_call_no_file(self, tmp_path):
        reset_cache()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_cli_call(log_dir, "query", 0, 5)
        assert _self_files(log_dir) == []

    def test_dispatch_no_file_when_disabled(self, tmp_path):
        reset_cache()
        log_dir = tmp_path / "logs"
        AgentLogger(program="user", command="c", log_dir=log_dir, storage="jsonl").info("hi")
        dispatch_tool(log_dir, "agentic_log_query", {})
        assert _self_files(log_dir) == []


# ------------------------------------------------------------------
# MCP dispatch self-log
# ------------------------------------------------------------------


class TestMcpSelfLog:
    def test_dispatch_logs_success(self, tmp_path, self_log_on):
        log_dir = tmp_path / "logs"
        AgentLogger(program="user", command="c", log_dir=log_dir, storage="jsonl").info("hi", module="m")
        dispatch_tool(log_dir, "agentic_log_query", {"limit": 5})

        hits = [e for e in _data_entries(log_dir) if "agentic_log_query" in e.get("msg", "")]
        assert len(hits) == 1
        hit = hits[0]
        assert hit["level"] == "INFO"
        assert hit["module"] == "agentic_logger.mcp_server"
        assert hit["ctx"]["tool"] == "agentic_log_query"
        assert hit["ctx"]["exit"] == 0
        assert hit["ctx"]["args"] == {"limit": 5}
        # query result carries count + query_info.backends_scanned
        assert "results" in hit["ctx"]
        assert "backends" in hit["ctx"]

    def test_dispatch_logs_error(self, tmp_path, self_log_on):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # Unknown tool -> result has "error"
        dispatch_tool(log_dir, "nonexistent_tool", {})

        errs = [e for e in _data_entries(log_dir) if e.get("level") == "ERROR"]
        assert len(errs) == 1
        assert errs[0]["error_code"] == "INTERNAL_UNEXPECTED"
        assert errs[0]["ctx"]["exit"] == 1
        assert "error" in errs[0]["ctx"]


# ------------------------------------------------------------------
# CLI main self-log
# ------------------------------------------------------------------


class TestCliSelfLog:
    def test_main_logs_success(self, tmp_path, self_log_on, monkeypatch):
        log_dir = tmp_path / "logs"
        AgentLogger(program="user", command="c", log_dir=log_dir, storage="jsonl").info("hi", module="m")
        monkeypatch.setattr(sys, "argv", ["agentic-logger", "--log-dir", str(log_dir), "query"])

        with pytest.raises(SystemExit) as ei:
            cli_main()
        assert ei.value.code == 0

        hits = [e for e in _data_entries(log_dir) if e.get("module") == "agentic_logger.cli"]
        assert len(hits) == 1
        assert hits[0]["level"] == "INFO"
        assert hits[0]["ctx"]["command"] == "query"
        assert hits[0]["ctx"]["exit_code"] == 0

    def test_main_logs_value_error(self, tmp_path, self_log_on, monkeypatch):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        monkeypatch.setattr(
            sys, "argv", ["agentic-logger", "--log-dir", str(log_dir), "query", "--since", "100"]
        )

        with pytest.raises(SystemExit) as ei:
            cli_main()
        assert ei.value.code == 2

        hits = [e for e in _data_entries(log_dir) if e.get("module") == "agentic_logger.cli"]
        assert len(hits) == 1
        assert hits[0]["level"] == "ERROR"
        assert hits[0]["ctx"]["exit_code"] == 2
        assert "error" in hits[0]["ctx"]

    def test_log_cli_call_error_without_msg(self, tmp_path, self_log_on):
        log_dir = tmp_path / "logs"
        log_cli_call(log_dir, "query", 1, 7)
        errs = [e for e in _data_entries(log_dir) if e.get("level") == "ERROR"]
        assert len(errs) == 1
        assert errs[0]["ctx"]["exit_code"] == 1
        assert "error" not in errs[0]["ctx"]


# ------------------------------------------------------------------
# Closed loop — self-log queryable by AgenticLogger itself
# ------------------------------------------------------------------


class TestClosedLoop:
    def test_self_log_queryable_via_module_glob(self, tmp_path, self_log_on):
        """Dogfooding闭环: 自身日志可被 handle_query(module=agentic_logger.*) 命中。"""
        log_dir = tmp_path / "logs"
        AgentLogger(program="user", command="c", log_dir=log_dir, storage="jsonl").info("user", module="user.mod")
        dispatch_tool(log_dir, "agentic_log_query", {"limit": 5})

        result = handle_query(log_dir, module="agentic_logger.*")
        assert result["count"] >= 1
        for log in result["logs"]:
            assert log["module"].startswith("agentic_logger.")


# ------------------------------------------------------------------
# Cache + summariser
# ------------------------------------------------------------------


class TestCache:
    def test_logger_cached_per_key(self, tmp_path, self_log_on):
        log_dir = tmp_path / "logs"
        a = get_self_logger(log_dir, "mcp")
        b = get_self_logger(log_dir, "mcp")
        assert a is b  # same instance — no per-call file churn

    def test_distinct_keys_distinct_loggers(self, tmp_path, self_log_on):
        log_dir = tmp_path / "logs"
        a = get_self_logger(log_dir, "mcp")
        b = get_self_logger(log_dir, "query")
        assert a is not b


class TestSummarizeArgs:
    def test_scalar_passthrough(self):
        assert _summarize_args({"a": "s", "b": 1, "c": True, "d": None, "e": 4.5}) == {
            "a": "s", "b": 1, "c": True, "d": None, "e": 4.5,
        }

    def test_long_string_truncated(self):
        s = _summarize_args({"k": "x" * 100})
        assert len(s["k"]) == 40 and s["k"].endswith("...")

    def test_non_scalar_degrades_to_type_name(self):
        s = _summarize_args({"k": [1, 2], "m": {"n": 1}})
        assert s["k"] == "list" and s["m"] == "dict"

    def test_none_args(self):
        assert _summarize_args(None) == {}
