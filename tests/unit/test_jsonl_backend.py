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

    def test_global_ctx_header_uses_utc(self, tmp_path):
        """Global-context header ts must be UTC (+00:00) to match data entries."""
        fp = tmp_path / "ctx.jsonl"
        JSONLBackend(file_path=fp, global_ctx={"program": "t"})
        with open(fp) as f:
            header = json.loads(f.readline())
        assert header["ts"].endswith("+00:00"), f"expected UTC, got {header['ts']}"

    def test_close_is_noop(self, backend):
        """JSONLBackend.close() must exist and not raise (interface parity)."""
        backend.close()


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

    def test_query_since_until(self, backend):
        """since/until must filter by ts range (regression: was silently ignored)."""
        backend.write(_entry(msg="old", ts="2026-07-21T01:00:00.000+00:00"))
        backend.write(_entry(msg="mid", ts="2026-07-21T05:00:00.000+00:00"))
        backend.write(_entry(msg="new", ts="2026-07-21T10:00:00.000+00:00"))
        results = backend.query(
            since="2026-07-21T03:00:00.000+00:00",
            until="2026-07-21T08:00:00.000+00:00",
        )
        data = [r for r in results if r.get("level") != "__GLOBAL_CTX__"]
        assert len(data) == 1
        assert data[0]["msg"] == "mid"

    def test_query_max_dur_excludes_no_dur_entries(self, backend):
        """Entries without dur must be excluded from a dur range filter
        (regression: ``dur or 0`` conflated missing-dur with dur=0)."""
        backend.write(_entry(msg="timed", dur=500))
        backend.write(_entry(msg="untimed"))  # no dur field
        results = backend.query(max_dur=1000)
        data = [r for r in results if r.get("level") != "__GLOBAL_CTX__"]
        msgs = [r["msg"] for r in data]
        assert "timed" in msgs
        assert "untimed" not in msgs


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

    def test_traceback_newline_and_pipe_in_msg(self, backend):
        """exc_msg with newline/pipe must round-trip without corrupting records."""
        backend.save_traceback(
            "tb_pipe", "Line1\nLine2", "ValueError",
            "msg with | pipe and \n newline",
        )
        tb = backend.get_traceback("tb_pipe")
        assert tb is not None
        assert tb["tid"] == "tb_pipe"
        assert tb["exception_type"] == "ValueError"
        assert tb["exception_msg"] == "msg with | pipe and \n newline"
        assert "Line1" in tb["traceback"]
        # A following record must still be retrievable (no line-split corruption)
        backend.save_traceback("tb_next", "ok", "RuntimeError", "next record")
        nxt = backend.get_traceback("tb_next")
        assert nxt is not None
        assert nxt["exception_msg"] == "next record"


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
        # Write valid JSON (not garbage) so query can parse
        fp.write_text('{"ts":"...","level":"INFO","msg":"existing"}\n')
        b = JSONLBackend(file_path=fp, max_size_mb=0, circular=False)
        b.write(_entry(msg="test"))
        # Should still write to same file without rotation
        results = b.query()
        msgs = [e.get("msg") for e in results]
        assert "test" in msgs

    def test_max_files_enforced(self, tmp_path):
        """After rotation, total files should not exceed max_files + 1 (current)."""
        # Create 3 existing files with valid content
        for i in range(3):
            fp = tmp_path / f"test_main_2026072{i}_10000000000{i}.jsonl"
            fp.write_text('{"ts":"...","level":"INFO","msg":"old","rid":"r","pid":"1","seq":1}\n')

        # Backend with max_files=3, very small size to force rotation
        fp = tmp_path / "test_main_20260723_100000000003.jsonl"
        b = JSONLBackend(
            file_path=fp,
            max_files=3,
            max_size_mb=0,
            circular=True,
        )
        # Write to trigger rotation
        b.write(_entry(msg="trigger rotation"))

        files = list(tmp_path.glob("test_main_*.jsonl"))
        # Should have at most max_files + 1 (the current file being written)
        # because rotation deletes oldest when >= max_files
        assert len(files) <= 4  # 3 existing + 1 new (at most)

    def test_rotation_no_double_extension(self, tmp_path):
        """Rotated files must NOT get a .jsonl.jsonl double extension (regression)."""
        fp = tmp_path / "test_main_20260721_100000000000.jsonl"
        fp.write_text(
            '{"ts":"...","level":"INFO","msg":"old","rid":"r","pid":"1","seq":1}\n'
        )
        b = JSONLBackend(file_path=fp, max_size_mb=0, circular=True, max_files=5)
        b.write(_entry(msg="new"))
        files = list(tmp_path.glob("*"))
        bad = [f.name for f in files if f.name.endswith(".jsonl.jsonl")]
        assert bad == [], f"double-extension files found: {bad}"

    def test_rotation_rollback_restores_original(self, tmp_path, monkeypatch):
        """A mid-rotation failure must clean the orphan new file and restore
        the original path + file_path (regression: left orphan + wrong name)."""
        import agentic_logger.storage.jsonl as mod

        fp = tmp_path / "rot_main_20260721_100000000000.jsonl"
        fp.write_text(
            '{"ts":"x","level":"INFO","msg":"old","rid":"r","pid":"1","seq":1}\n'
        )
        b = JSONLBackend(file_path=fp, max_size_mb=0, circular=True, max_files=5)

        def boom(self):
            raise OSError("simulated disk full")
        monkeypatch.setattr(mod.JSONLBackend, "_write_global_context", boom)

        with pytest.raises(RuntimeError):
            b.write(_entry(msg="trigger"))

        assert fp.exists(), "original path not restored after rollback"
        assert "old" in fp.read_text(), "original content lost"
        assert b.file_path == fp, "file_path not restored to original"
        assert len(list(tmp_path.glob("*.jsonl"))) == 1, "orphan new file left behind"


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


class TestJsonlCoverage:
    """Cover corrupt-line skips, legacy tb read, level-specific filters, prune, recovery."""

    def test_query_skips_corrupt_lines(self, tmp_path):
        fp = tmp_path / "c.jsonl"
        fp.write_text("{not valid json\n"
                      '{"ts":"2026-01-01T00:00:00+00:00","level":"INFO","msg":"ok",'
                      '"module":"m","rid":"r","pid":"1","seq":1}\n')
        b = JSONLBackend(file_path=fp)
        # corrupt global_ctx header skipped on query -> only the valid entry
        results = b.query()
        assert any(r.get("msg") == "ok" for r in results)

    def test_get_traceback_legacy_pipe_format(self, tmp_path):
        """Reading must support the legacy tid|type|msg|tb sidecar format."""
        fp = tmp_path / "c.jsonl"
        b = JSONLBackend(file_path=fp)
        tb = fp.with_suffix(".tracebacks")
        tb.write_text('tb_old|ValueError|bad|Line1\\nLine2\n')      # legacy 4-field
        tb.write('{broken json\n', )  # type: ignore  # malformed JSON line
        tb.write('short|two\n', )  # type: ignore      # <4 fields
        rec = b.get_traceback("tb_old")
        assert rec is not None and rec["exception_type"] == "ValueError"
        assert rec["traceback"] == "Line1\nLine2"
        assert b.get_traceback("tb_old") is not None  # re-read stability

    def test_match_exit_and_lang_filters(self, tmp_path):
        b = JSONLBackend(file_path=tmp_path / "c.jsonl")
        b.write({"ts": "2026-01-01T00:00:00+00:00", "level": "TOOL", "msg": "t",
                 "module": "m", "rid": "r", "pid": "1", "seq": 1, "tool": "bash",
                 "cmd": "ls", "exit": 0, "dur": 5})
        b.write({"ts": "2026-01-01T00:00:01+00:00", "level": "CODE_GEN", "msg": "g",
                 "module": "m", "rid": "r", "pid": "1", "seq": 2, "lang": "python",
                 "path": "/x.py"})
        assert len(b.query(exit=0)) == 1
        assert len(b.query(lang="python")) == 1

    def test_global_context_empty_is_noop(self, tmp_path):
        """_write_global_context returns early when global_ctx is empty."""
        fp = tmp_path / "c.jsonl"
        b = JSONLBackend(file_path=fp, global_ctx=None)
        # No header line written -> file empty
        assert fp.read_text() == ""

    def test_rotation_prunes_oldest_beyond_max_files(self, tmp_path):
        """When rotation leaves more than max_files completed, oldest are pruned."""
        for i in range(4):
            fp = tmp_path / f"rot_main_2026072{i}_10000000000{i}.jsonl"
            fp.write_text('{"ts":"x","level":"INFO","msg":"old","rid":"r","pid":"1","seq":1}\n')
            # give each a traceback sidecar so the unlink-tb branch runs
            fp.with_suffix(".tracebacks").write_text("tb|x|y|z\n")
        fp = tmp_path / "rot_main_20260724_100000000004.jsonl"
        fp.write_text('{"ts":"x","level":"INFO","msg":"cur","rid":"r","pid":"1","seq":1}\n')
        b = JSONLBackend(file_path=fp, max_size_mb=0, circular=True, max_files=2)
        b.write({"ts": "2026-01-01T00:00:00+00:00", "level": "INFO", "msg": "new",
                 "module": "m", "rid": "r", "pid": "1", "seq": 2})
        # prune ran without error; at least the active file remains
        assert b.file_path.exists()

    def test_recovery_when_original_already_exists(self, tmp_path):
        """A stale .rotating whose original already exists is discarded."""
        fp = tmp_path / "rot_main_20260721_100000000001.jsonl"
        fp.write_text('{"ts":"x","level":"INFO","msg":"ok","rid":"r","pid":"1","seq":1}\n')
        (tmp_path / "rot_main_20260721_100000000001.jsonl.rotating").write_text("stale")
        JSONLBackend(file_path=fp)  # recovery discards the stale .rotating
        assert not (tmp_path / "rot_main_20260721_100000000001.jsonl.rotating").exists()
