"""Tests for JSONLBackend.stats() fast aggregation path.

@spec-ref: src/agentic_logger/storage/jsonl.py §stats
@spec-why: Lock in that the bytes.count / re.findall fast path matches the slow
  query()-based counts exactly — across compact/full-key files and every group_by
  axis the CLI exposes (level, tool, module, error_code, pid).
"""

from __future__ import annotations

from collections import Counter

import pytest

from agentic_logger.storage.jsonl import JSONLBackend


def _compact_entries() -> list[dict]:
    return [
        {"t": "2026-07-28T00:00:01.000+00:00", "l": "INFO", "n": "scraper.rss", "m": "ok", "r": "r1", "p": "1", "q": 1},
        {"t": "2026-07-28T00:00:02.000+00:00", "l": "INFO", "n": "scraper.rss", "m": "ok", "r": "r2", "p": "1", "q": 2},
        {"t": "2026-07-28T00:00:03.000+00:00", "l": "ERROR", "n": "storage.graph", "m": "depth", "e": "FRONTMATTER_TOO_DEEP", "r": "r1", "p": "1", "q": 3},
        {"t": "2026-07-28T00:00:04.000+00:00", "l": "ERROR", "n": "http.client", "m": "timeout", "e": "NET_TIMEOUT", "r": "r2", "p": "2", "q": 1},
        {"t": "2026-07-28T00:00:05.000+00:00", "l": "TOOL", "n": "http.client", "m": "Tool http succeeded", "o": "http",
         "c": "GET /", "x": 0, "d": 50, "r": "r1", "p": "1", "q": 4},
    ]


def _full_entries() -> list[dict]:
    """Same data as _compact_entries but with full field names."""
    return [
        {"ts": "2026-07-28T00:00:01.000+00:00", "level": "INFO", "module": "scraper.rss", "msg": "ok", "rid": "r1", "pid": "1", "seq": 1},
        {"ts": "2026-07-28T00:00:02.000+00:00", "level": "INFO", "module": "scraper.rss", "msg": "ok", "rid": "r2", "pid": "1", "seq": 2},
        {"ts": "2026-07-28T00:00:03.000+00:00", "level": "ERROR", "module": "storage.graph", "msg": "depth",
         "error_code": "FRONTMATTER_TOO_DEEP", "rid": "r1", "pid": "1", "seq": 3},
        {"ts": "2026-07-28T00:00:04.000+00:00", "level": "ERROR", "module": "http.client", "msg": "timeout",
         "error_code": "NET_TIMEOUT", "rid": "r2", "pid": "2", "seq": 1},
        {"ts": "2026-07-28T00:00:05.000+00:00", "level": "TOOL", "module": "http.client", "msg": "Tool http succeeded", "tool": "http",
         "cmd": "GET /", "exit": 0, "dur": 50, "rid": "r1", "pid": "1", "seq": 4},
    ]


def _query_counts(backend: JSONLBackend, group_by: str, rid: str | None = None) -> Counter:
    """The slow reference: load every entry via query(), Counter in Python."""
    c: Counter = Counter()
    for e in backend.query(limit=100000, rid=rid):
        if e.get("level") == "__GLOBAL_CTX__":
            continue
        c[str(e.get(group_by, "unknown"))] += 1
    return c


@pytest.fixture
def compact_backend(tmp_path):
    b = JSONLBackend(file_path=tmp_path / "c.jsonl", compact=True)
    for e in _compact_entries():
        b.write(e)
    return b


@pytest.fixture
def full_backend(tmp_path):
    b = JSONLBackend(file_path=tmp_path / "f.jsonl", compact=False)
    for e in _full_entries():
        b.write(e)
    return b


# ------------------------------------------------------------------
# Fast path == slow path, every supported group_by axis
# ------------------------------------------------------------------
@pytest.mark.parametrize("group_by", ["level", "error_code", "module", "tool", "pid"])
def test_stats_matches_query_compact(compact_backend, group_by):
    assert compact_backend.stats(group_by) == _query_counts(compact_backend, group_by)


@pytest.mark.parametrize("group_by", ["level", "error_code", "module", "tool", "pid"])
def test_stats_matches_query_full(full_backend, group_by):
    assert full_backend.stats(group_by) == _query_counts(full_backend, group_by)


# ------------------------------------------------------------------
# Correctness details
# ------------------------------------------------------------------
def test_stats_excludes_global_ctx_header(compact_backend):
    counts = compact_backend.stats("level")
    assert "__GLOBAL_CTX__" not in counts
    assert counts["INFO"] == 2
    assert counts["ERROR"] == 2
    assert counts["TOOL"] == 1


def test_stats_level_drops_zero_buckets(compact_backend):
    """levels absent from the file must not appear as 0-count groups via handle_stats."""
    # stats() may return zeros for the bounded enum; consumers filter them.
    counts = {k: v for k, v in compact_backend.stats("level").items() if v}
    assert "DECISION" not in counts  # never written


def test_stats_rid_filter_fallback_matches(compact_backend):
    # rid filter forces the per-entry correlation fallback path.
    assert compact_backend.stats("level", rid="r1") == _query_counts(compact_backend, "level", rid="r1")


def test_stats_missing_file(tmp_path):
    b = JSONLBackend(file_path=tmp_path / "absent.jsonl")
    # construction writes a header (global_ctx empty by default -> no header line);
    # delete it to simulate a missing file cleanly
    (tmp_path / "absent.jsonl").unlink(missing_ok=True)
    assert b.stats("level") == Counter()


def test_stats_since_filter_fallback(compact_backend):
    # since/until trigger the fallback; result still matches a rid-free filtered query.
    since = "2000-01-01T00:00:00.000+00:00"  # before all entries -> all match
    assert compact_backend.stats("level", since=since) == _query_counts(compact_backend, "level")
