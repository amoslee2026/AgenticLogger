"""Tests for utils/token_compare.py.

@spec-ref: utils/token_compare.py
@spec-why: Lock in the parser/generator invariants that the token-comparison
  numbers depend on — format strings, needle matching, and an end-to-end
  generate+measure smoke pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make utils/ importable. token_compare's own top-level src/ insert runs on
# import and fixes the agentic_logger shadowing for these tests too.
_UTILS = Path(__file__).resolve().parent.parent / "utils"
if str(_UTILS) not in sys.path:
    sys.path.insert(0, str(_UTILS))

import token_compare as tc  # type: ignore[import-not-found]


# ------------------------------------------------------------------
# Token counter
# ------------------------------------------------------------------
def test_count_tokens_positive_and_empty():
    assert tc.count_tokens("hello world") >= 1
    # Empty string still counts as >= 1 token (max(1, len//4)).
    assert tc.count_tokens("") >= 1


def test_count_tokens_monotonic():
    a = tc.count_tokens("a")
    b = tc.count_tokens("a" * 100)
    assert b > a


# ------------------------------------------------------------------
# Stdlib rendering
# ------------------------------------------------------------------
def _err_event() -> dict:
    return {"ts": "2026-07-28T12:00:00.000+00:00", "level": "ERROR",
            "module": "storage.graph", "rid": "abc12345", "pid": "12345", "seq": 7,
            "msg": "depth 5 exceeds limit 3 [FRONTMATTER_TOO_DEEP]"}


def test_render_stdlib_error_line_carries_fields_and_code_in_msg():
    line = tc._render_stdlib_line(_err_event())
    assert "levelname=ERROR " in line
    assert "request_id=abc12345" in line
    assert "FRONTMATTER_TOO_DEEP" in line  # code lives in message text only


def test_render_stdlib_tool_extras():
    ev = {"ts": "2026-07-28T12:00:00.000+00:00", "level": "TOOL", "module": "http.client",
          "rid": "abc12345", "pid": "12345", "seq": 3, "msg": "Tool http succeeded",
          "tool": "http", "cmd": "GET /feed", "exit": 0, "dur": 120}
    line = tc._render_stdlib_line(ev)
    assert "tool=http" in line
    assert "exit_code=0" in line
    assert "duration_ms=120" in line


# ------------------------------------------------------------------
# Output parsers
# ------------------------------------------------------------------
def test_parse_top_error_code_picks_highest_count():
    stats = ("Statistics (group_by=error_code, total=100):\n"
             "key  count  percentage\n"
             "FRONTMATTER_TOO_DEEP  70  0.1%\n"
             "IO_NOT_FOUND  8  0.0%\n")
    assert tc._parse_top_error_code(stats) == "FRONTMATTER_TOO_DEEP"


def test_parse_top_error_code_none_when_empty():
    assert tc._parse_top_error_code("no rows here") is None


def test_parse_first_rid_from_jsonl():
    txt = '{"t":"x","r":"deadbeef"}\n{"t":"y","r":"cafef00d"}'
    assert tc._parse_first_rid(txt) == "deadbeef"


def test_parse_first_rid_handles_compact_key():
    txt = '{"r":"beefcafe"}'
    assert tc._parse_first_rid(txt) == "beefcafe"


# ------------------------------------------------------------------
# Stdlib grep / triage
# ------------------------------------------------------------------
def test_stdlib_grep_context_window_dedup():
    lines = ["a", "b", "NEEDLE", "d", "e"]
    out = tc._stdlib_grep(lines, "NEEDLE", context=1)
    assert "NEEDLE" in out
    assert "b" in out and "d" in out      # within window
    assert "a" not in out and "e" not in out  # outside window


def test_stdlib_error_lines_filters_level_only():
    lines = ["x levelname=ERROR y", "z levelname=INFO w", "q levelname=ERROR r"]
    out = tc._stdlib_error_lines(lines)
    assert "levelname=ERROR" in out
    assert "INFO" not in out
    assert out.count("\n") == 1  # two ERROR lines -> one newline


# ------------------------------------------------------------------
# End-to-end generate + measure
# ------------------------------------------------------------------
def test_generate_corpus_writes_both_formats(tmp_path: Path):
    stdlib, agentic, n = tc.generate_corpus(
        tmp_path, n=500, seed=42, error_rate=0.05, warn_rate=0.01)
    assert n == 500
    assert stdlib.exists() and stdlib.stat().st_size > 0
    assert agentic.is_dir() and any(agentic.glob("*.jsonl"))


def test_measure_runs_clean_on_generated_corpus(tmp_path: Path, capsys):
    stdlib, agentic, _ = tc.generate_corpus(
        tmp_path, n=500, seed=42, error_rate=0.05, warn_rate=0.01)
    rc = tc.measure(stdlib, agentic, context=3)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Daily Health-Check Token Cost" in out
    assert "TOTAL" in out
    assert "FRONTMATTER_TOO_DEEP" in out  # dominant error surfaced
