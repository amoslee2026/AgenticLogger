"""Tests for multi-file parallel read path (process-pool fan-out).

@spec-ref: src/agentic_logger/mcp_server.py §_parallel_pool
@spec-why: Lock in that the parallel path returns results identical to the
  sequential path (AGENTIC_PARALLEL_WORKERS=0), across stats and query, with
  enough files to exceed the parallelism threshold.
"""

from __future__ import annotations

import pytest

from agentic_logger.mcp_server import handle_query, handle_stats
from agentic_logger.storage.jsonl import JSONLBackend


def _entries(seed: int) -> list[dict]:
    return [
        {"t": f"2026-07-28T00:00:0{seed}.000+00:00", "l": "INFO", "n": f"mod{seed}",
         "m": "ok", "r": f"r{seed}", "p": str(seed), "q": 1},
        {"t": f"2026-07-28T00:00:0{seed}.100+00:00", "l": "ERROR", "n": f"mod{seed}",
         "m": "x", "e": "FRONTMATTER_TOO_DEEP", "r": f"r{seed}", "p": str(seed), "q": 2},
        {"t": f"2026-07-28T00:00:0{seed}.200+00:00", "l": "ERROR", "n": f"mod{seed}",
         "m": "y", "e": "NET_TIMEOUT", "r": f"r{seed}", "p": str(seed), "q": 3},
        {"t": f"2026-07-28T00:00:0{seed}.300+00:00", "l": "WARN", "n": f"mod{seed}",
         "m": "z", "r": f"r{seed}", "p": str(seed), "q": 4},
    ]


@pytest.fixture
def multifile_dir(tmp_path):
    # 4 files -> exceeds _PARALLEL_THRESHOLD (3) so the pool path activates.
    for i in range(4):
        b = JSONLBackend(file_path=tmp_path / f"f{i}.jsonl", compact=True)
        for e in _entries(i):
            b.write(e)
    return tmp_path


def _groups(result: dict) -> dict:
    return {g["key"]: g["count"] for g in result["groups"]}


def test_stats_parallel_matches_sequential(multifile_dir, monkeypatch):
    monkeypatch.delenv("AGENTIC_PARALLEL_WORKERS", raising=False)
    par = _groups(handle_stats(multifile_dir, group_by="error_code"))

    monkeypatch.setenv("AGENTIC_PARALLEL_WORKERS", "0")
    seq = _groups(handle_stats(multifile_dir, group_by="error_code"))

    assert par == seq
    # 4 files x 2 ERROR each; FRONTMATTER and NET_TIMEOUT appear once per file.
    assert par.get("FRONTMATTER_TOO_DEEP") == 4
    assert par.get("NET_TIMEOUT") == 4


def test_stats_parallel_total(multifile_dir, monkeypatch):
    monkeypatch.delenv("AGENTIC_PARALLEL_WORKERS", raising=False)
    result = handle_stats(multifile_dir, group_by="level")
    # 4 files x 4 entries each = 16 data entries.
    assert result["total"] == 16
    assert _groups(result).get("ERROR") == 8  # 2 per file x 4


def test_query_parallel_matches_sequential(multifile_dir, monkeypatch):
    def msgs():
        return sorted(e["msg"] for e in handle_query(multifile_dir, level="ERROR", limit=100000))

    monkeypatch.delenv("AGENTIC_PARALLEL_WORKERS", raising=False)
    par = msgs()
    monkeypatch.setenv("AGENTIC_PARALLEL_WORKERS", "0")
    seq = msgs()

    assert par == seq
    assert len(par) == 8  # 4 files x 2 ERROR


def test_parallel_disabled_env_falls_back(monkeypatch, multifile_dir):
    """AGENTIC_PARALLEL_WORKERS=0 forces the sequential path (smoke)."""
    monkeypatch.setenv("AGENTIC_PARALLEL_WORKERS", "0")
    result = handle_stats(multifile_dir, group_by="level")
    assert result["total"] == 16
