"""Tests for JSONL storage backend."""

import json
import tempfile
from pathlib import Path

import pytest

from agentic_logger.storage.jsonl import JSONLBackend


@pytest.fixture
def jsonl_file(tmp_path):
    return tmp_path / "test.jsonl"


@pytest.fixture
def backend(jsonl_file):
    return JSONLBackend(file_path=jsonl_file)


def _entry(level="INFO", msg="test", **kwargs):
    """Helper to create a log entry."""
    return {
        "ts": "2026-07-21T11:30:00.000+08:00",
        "level": level,
        "msg": msg,
        "module": "test",
        "rid": "test_rid",
        "pid": "12345",
        "seq": 1,
        **kwargs,
    }


class TestWriteRead:
    def test_write_single(self, backend, jsonl_file):
        backend.write(_entry(msg="hello"))
        with open(jsonl_file) as f:
            lines = [l for l in f if l.strip()]
        # First line is GLOBAL_CTX (empty since no global_ctx), second is entry
        entries = [json.loads(l) for l in lines]
        data_entries = [e for e in entries if e["level"] != "__GLOBAL_CTX__"]
        assert len(data_entries) == 1
        assert data_entries[0]["msg"] == "hello"

    def test_write_batch(self, backend):
        entries = [_entry(msg=f"msg {i}") for i in range(5)]
        backend.write_batch(entries)
        results = backend.query()
        assert len(results) == 5

    def test_write_append(self, backend):
        backend.write(_entry(msg="first"))
        backend.write(_entry(msg="second"))
        results = backend.query()
        assert len(results) == 2
        assert results[0]["msg"] == "first"
        assert results[1]["msg"] == "second"

    def test_global_context_header(self, tmp_path):
        fp = tmp_path / "ctx.jsonl"
        b = JSONLBackend(file_path=fp, global_ctx={"program": "test", "user": "alice"})
        with open(fp) as f:
            first = json.loads(f.readline())
        assert first["level"] == "__GLOBAL_CTX__"
        assert first["program"] == "test"
        assert first["user"] == "alice"


class TestQuery:
    def test_query_all(self, backend):
        for i in range(10):
            backend.write(_entry(msg=f"msg {i}"))
        results = backend.query()
        assert len(results) == 10

    def test_query_by_level(self, backend):
        backend.write(_entry(level="INFO", msg="info"))
        backend.write(_entry(level="ERROR", msg="error"))
        results = backend.query(level="ERROR")
        assert len(results) == 1
        assert results[0]["msg"] == "error"

    def test_query_by_module(self, backend):
        backend.write(_entry(msg="a", module="agent.bash"))
        backend.write(_entry(msg="b", module="agent.file"))
        backend.write(_entry(msg="c", module="parser"))
        results = backend.query(module="agent.bash")
        assert len(results) == 1

    def test_query_module_wildcard(self, backend):
        backend.write(_entry(msg="a", module="agent.bash"))
        backend.write(_entry(msg="b", module="agent.file"))
        backend.write(_entry(msg="c", module="parser"))
        results = backend.query(module="agent.*")
        assert len(results) == 2

    def test_query_by_error_code(self, backend):
        backend.write(_entry(level="ERROR", msg="e1", error_code="IO_NOT_FOUND"))
        backend.write(_entry(level="ERROR", msg="e2", error_code="EXEC_NON_ZERO"))
        results = backend.query(error_code="IO_NOT_FOUND")
        assert len(results) == 1

    def test_query_by_rid(self, backend):
        backend.write(_entry(msg="a", rid="rid1"))
        backend.write(_entry(msg="b", rid="rid2"))
        results = backend.query(rid="rid1")
        assert len(results) == 1

    def test_query_by_tool(self, backend):
        backend.write(_entry(level="TOOL", msg="t1", tool="bash"))
        backend.write(_entry(level="TOOL", msg="t2", tool="read"))
        results = backend.query(tool="bash")
        assert len(results) == 1

    def test_query_min_max_dur(self, backend):
        backend.write(_entry(msg="fast", dur=50))
        backend.write(_entry(msg="medium", dur=500))
        backend.write(_entry(msg="slow", dur=5000))
        results = backend.query(min_dur=100, max_dur=1000)
        assert len(results) == 1
        assert results[0]["msg"] == "medium"

    def test_query_limit(self, backend):
        for i in range(20):
            backend.write(_entry(msg=f"msg {i}"))
        results = backend.query(limit=5)
        assert len(results) == 5

    def test_query_offset(self, backend):
        for i in range(10):
            backend.write(_entry(msg=f"msg {i}"))
        results = backend.query(limit=5, offset=5)
        assert len(results) == 5

    def test_query_order_ts_asc(self, backend):
        backend.write(_entry(msg="a", ts="2026-07-21T11:30:01.000+08:00"))
        backend.write(_entry(msg="b", ts="2026-07-21T11:30:00.000+08:00"))
        results = backend.query(order_by="ts_asc")
        assert results[0]["msg"] == "b"

    def test_query_order_dur_desc(self, backend):
        backend.write(_entry(msg="fast", dur=50))
        backend.write(_entry(msg="slow", dur=5000))
        results = backend.query(order_by="dur_desc")
        assert results[0]["msg"] == "slow"

    def test_query_keyword(self, backend):
        backend.write(_entry(msg="Processing user request"))
        backend.write(_entry(msg="Building project"))
        results = backend.query(keyword="user request")
        assert len(results) == 1

    def test_query_empty_file(self, tmp_path):
        fp = tmp_path / "empty.jsonl"
        fp.touch()
        b = JSONLBackend(file_path=fp)
        results = b.query()
        assert results == []

    def test_query_nonexistent_file(self, tmp_path):
        fp = tmp_path / "nonexistent.jsonl"
        b = JSONLBackend(file_path=fp)
        results = b.query()
        assert results == []


class TestTimeRange:
    def test_get_time_range(self, backend):
        backend.write(_entry(ts="2026-07-21T10:00:00.000+08:00"))
        backend.write(_entry(ts="2026-07-21T12:00:00.000+08:00"))
        tr = backend.get_time_range()
        assert tr["min_ts"] == "2026-07-21T10:00:00.000+08:00"
        assert tr["max_ts"] == "2026-07-21T12:00:00.000+08:00"

    def test_get_time_range_empty(self, tmp_path):
        fp = tmp_path / "empty.jsonl"
        fp.touch()
        b = JSONLBackend(file_path=fp)
        assert b.get_time_range() is None


class TestTraceback:
    def test_save_and_get_traceback(self, backend):
        backend.save_traceback("tb_001", "Traceback...\n  File...", "ValueError", "bad value")
        tb = backend.get_traceback("tb_001")
        assert tb is not None
        assert tb["tid"] == "tb_001"
        assert tb["exception_type"] == "ValueError"
        assert tb["exception_msg"] == "bad value"
        assert "Traceback..." in tb["traceback"]

    def test_get_traceback_not_found(self, backend):
        tb = backend.get_traceback("nonexistent")
        assert tb is None

    def test_traceback_file_separate(self, backend, jsonl_file):
        backend.save_traceback("tb_002", "trace", "Err", "msg")
        tb_path = jsonl_file.with_suffix(".tracebacks")
        assert tb_path.exists()
        assert tb_path != jsonl_file


class TestCircularRotation:
    def test_rotation_creates_new_file(self, tmp_path):
        fp = tmp_path / "test_agent_main_20260721_100000000000.jsonl"
        # Write a tiny file first
        fp.write_text('{"ts":"...","level":"INFO","msg":"old"}\n')
        # Create backend with very small max_size to force rotation
        b = JSONLBackend(
            file_path=fp,
            max_size_mb=0,  # 0 MB = always rotate
            circular=True,
        )
        b.write(_entry(msg="new"))
        # After rotation, old file should be renamed, new file should exist
        files = sorted(tmp_path.glob("test_agent_main_*.jsonl"))
        assert len(files) >= 1

    def test_no_rotation_when_disabled(self, tmp_path):
        fp = tmp_path / "test.jsonl"
        fp.write_text("x" * 2000)
        b = JSONLBackend(file_path=fp, max_size_mb=0, circular=False)
        b.write(_entry(msg="test"))
        # Should still write to same file without rotation
        results = b.query()
        assert any(e.get("msg") == "test" for e in results)

    def test_max_files_enforced(self, tmp_path):
        # Create 3 existing files
        for i in range(3):
            fp = tmp_path / f"test_main_2026072{i}_10000000000{i}.jsonl"
            fp.write_text('{"ts":"...","level":"INFO","msg":"old"}\n')

        # Backend with max_files=3, very small size to force rotation
        fp = tmp_path / "test_main_20260723_100000000003.jsonl"
        b = JSONLBackend(
            file_path=fp,
            max_files=3,
            max_size_mb=0,
            circular=True,
        )
        b.write(_entry(msg="trigger rotation"))

        files = list(tmp_path.glob("test_main_*.jsonl"))
        # Should have at most 3 files (max_files)
        assert len(files) <= 3


class TestRecovery:
    def test_recover_from_interrupted_rotation(self, tmp_path):
        """If a .rotating file exists, it should be recovered."""
        rotating = tmp_path / "test_main_20260721_100000000000.jsonl.rotating"
        rotating.write_text('{"ts":"...","level":"INFO","msg":"interrupted"}\n')

        fp = tmp_path / "test_main_20260721_100000000001.jsonl"
        b = JSONLBackend(file_path=fp)

        # .rotating should be recovered to .jsonl
        assert not rotating.exists()
        recovered = tmp_path / "test_main_20260721_100000000000.jsonl"
        assert recovered.exists()
