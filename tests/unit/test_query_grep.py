"""Tests for JSONLBackend.query() byte-narrowed (grep) fast path.

@spec-ref: src/agentic_logger/storage/jsonl.py §query/_query_narrowed
@spec-why: Lock in that the grep fast path returns results identical to the full
  scan, across compact/full files, single/multi exact filters, and exact+complex
  combinations. Result equivalence is the correctness invariant.
"""

from __future__ import annotations

import pytest

from agentic_logger.storage.jsonl import JSONLBackend


def _compact_entries() -> list[dict]:
    return [
        {"t": "2026-07-28T00:00:01.000+00:00", "l": "INFO", "n": "scraper.rss", "m": "ok", "r": "r1", "p": "1", "q": 1},
        {"t": "2026-07-28T00:00:02.000+00:00", "l": "INFO", "n": "scraper.rss", "m": "fail", "r": "r2", "p": "1", "q": 2},
        {"t": "2026-07-28T00:00:03.000+00:00", "l": "ERROR", "n": "storage.graph", "m": "depth", "e": "FRONTMATTER_TOO_DEEP", "r": "r1", "p": "1", "q": 3, "d": 200},
        {"t": "2026-07-28T00:00:04.000+00:00", "l": "ERROR", "n": "http.client", "m": "timeout", "e": "NET_TIMEOUT", "r": "r2", "p": "2", "q": 1, "d": 5000},
        {"t": "2026-07-28T00:00:05.000+00:00", "l": "TOOL", "n": "http.client", "m": "Tool http succeeded", "o": "http", "c": "GET /", "x": 0, "d": 50, "r": "r1", "p": "1", "q": 4},
    ]


def _full_entries() -> list[dict]:
    return [
        {"ts": "2026-07-28T00:00:01.000+00:00", "level": "INFO", "module": "scraper.rss", "msg": "ok", "rid": "r1", "pid": "1", "seq": 1},
        {"ts": "2026-07-28T00:00:02.000+00:00", "level": "INFO", "module": "scraper.rss", "msg": "fail", "rid": "r2", "pid": "1", "seq": 2},
        {"ts": "2026-07-28T00:00:03.000+00:00", "level": "ERROR", "module": "storage.graph", "msg": "depth", "error_code": "FRONTMATTER_TOO_DEEP", "rid": "r1", "pid": "1", "seq": 3, "dur": 200},
        {"ts": "2026-07-28T00:00:04.000+00:00", "level": "ERROR", "module": "http.client", "msg": "timeout", "error_code": "NET_TIMEOUT", "rid": "r2", "pid": "2", "seq": 1, "dur": 5000},
        {"ts": "2026-07-28T00:00:05.000+00:00", "level": "TOOL", "module": "http.client", "msg": "Tool http succeeded", "tool": "http", "cmd": "GET /", "exit": 0, "dur": 50, "rid": "r1", "pid": "1", "seq": 4},
    ]


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


def _ids(entries):
    return sorted((e["seq"], e.get("rid")) for e in entries)


# Each case: a filter dict that triggers the grep path (has an exact-match key).
@pytest.mark.parametrize("filt", [
    {"level": "ERROR"},
    {"level": "INFO"},
    {"error_code": "FRONTMATTER_TOO_DEEP"},
    {"rid": "r1"},
    {"rid": "r2"},
    {"tool": "http"},
    {"pid": "2"},
    {"module": "http.client"},            # exact module (no glob) -> narrowable
    {"level": "ERROR", "rid": "r1"},      # multiple exact filters (AND)
    {"level": "ERROR", "min_dur": 1000},  # exact + complex
    {"rid": "r1", "keyword": "depth"},    # exact + keyword
])
def test_query_grep_matches_full_scan_compact(compact_backend, filt):
    got = compact_backend.query(limit=100000, **filt)
    ref = compact_backend._query_full_scan({k: v for k, v in filt.items()})
    assert _ids(got) == _ids(ref)


@pytest.mark.parametrize("filt", [
    {"level": "ERROR"},
    {"error_code": "NET_TIMEOUT"},
    {"rid": "r1"},
    {"tool": "http"},
    {"module": "scraper.rss"},
    {"level": "ERROR", "rid": "r2"},
    {"level": "ERROR", "min_dur": 1000},
])
def test_query_grep_matches_full_scan_full(full_backend, filt):
    got = full_backend.query(limit=100000, **filt)
    ref = full_backend._query_full_scan({k: v for k, v in filt.items()})
    assert _ids(got) == _ids(ref)


def test_module_glob_uses_full_scan(compact_backend):
    # glob -> NOT narrowable -> full scan path; results still correct.
    got = compact_backend.query(limit=100000, module="scraper.*")
    assert len(got) == 2
    assert all(e["module"] == "scraper.rss" for e in got)


def test_query_no_match_returns_empty(compact_backend):
    assert compact_backend.query(rid="nonexistent") == []


def test_query_narrowed_respects_limit_and_order(compact_backend):
    # all INFO entries (2), ordered ts_desc, limit 1 -> newest INFO only
    out = compact_backend.query(level="INFO", limit=1, order_by="ts_desc")
    assert len(out) == 1
    assert out[0]["seq"] == 2  # the second INFO (newer ts)


def test_query_narrowed_offset(compact_backend):
    out = compact_backend.query(level="ERROR", order_by="ts_asc")
    # both ERROR entries, ts_asc -> storage.graph (00:03) then http.client (00:04)
    assert [e["module"] for e in out] == ["storage.graph", "http.client"]
