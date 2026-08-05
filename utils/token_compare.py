#!/usr/bin/env python3
"""Token comparison: stdlib logging vs AgenticLogger for a daily health-check.

@spec-ref: docs/case-studies/agenticlogger-vs-stdlib-logging.md
@spec-ref: TokenSavingRules.md §Log & Debug File Handling
@spec-why: Quantify the case-study claim that AgenticLogger saves ~80-95% tokens
  for agent-driven daily health-checks. Generates a controlled dual-format corpus
  (same events -> stdlib .log + AgenticLogger compact .jsonl), then runs the SAME
  3-step health-check against each and reports per-step token cost. The shared
  event source makes the comparison apples-to-apples (same information, two
  representations).
@spec-invariant: Does NOT mutate measured files; generation writes only to the
  explicit --out dir. Uses one AgentLogger instance with per-entry rid override
  so the whole corpus lands in a single queryable JSONL (the per-instance rid is
  "one rid per run" by design; benchmark corpus needs many rids in one file).

Three diagnostic steps (identical goal on both sides):
  1. Error distribution    stdlib: read ALL ERROR lines (no error_code field,
                                   so the agent must eyeball-cluster them)
                          agentic: `stats --group-by error_code` (fixed-size table)
  2. Drill top error       stdlib: grep <code> + +/-N context lines
                          agentic: `query --error-code <code>` (tsv, token-efficient)
  3. Trace one request     stdlib: grep req_id=<rid>
                          agentic: `trace --rid <rid>`

Usage::

    uv run python utils/token_compare.py run --n 50000 --out ./temp/token_compare
    uv run python utils/token_compare.py generate --n 100000 --out ./temp/tc_corpus
    uv run python utils/token_compare.py measure --stdlib <file> --agentic <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure 'agentic_logger' resolves to the src/ PACKAGE, not the utils/agentic_logger.py
# helper that shadows it when this script runs from inside utils/. Must run before the
# deferred `from agentic_logger import AgentLogger` in generate_corpus().
# NOTE: insert unconditionally — src may already be on sys.path (editable install)
# but AFTER the script dir, so a "not in sys.path" guard would wrongly skip this.
_PKG_SRC = Path(__file__).resolve().parent.parent / "src"
if _PKG_SRC.is_dir():
    sys.path.insert(0, str(_PKG_SRC))

# ------------------------------------------------------------------
# Token counting — tiktoken (accurate) if importable, else heuristic.
# ------------------------------------------------------------------
_TIKTOKEN = None
try:
    import tiktoken  # type: ignore[import-not-found]

    _TIKTOKEN = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN = None


def count_tokens(text: str) -> int:
    """Token count for *text*. tiktoken cl100k_base if available, else len/4.

    @spec-why: char/4 is the standard approximation when no tokenizer is installed.
    """
    if _TIKTOKEN is not None:
        return len(_TIKTOKEN.encode(text))
    return max(1, len(text) // 4)


def tokenizer_name() -> str:
    """Human-readable name of the active token counter."""
    return "tiktoken/cl100k_base" if _TIKTOKEN is not None else "char-heuristic (len/4)"


# ------------------------------------------------------------------
# Synthetic event generation — shared source-of-truth for both formats.
# ------------------------------------------------------------------
MODULES = [
    "scraper.rss", "scraper.render", "scraper.search", "scraper.parse",
    "http.client", "http.retry", "llm.extract", "llm.embed",
    "storage.graph", "storage.kv", "queue.dispatch", "scheduler.tick",
    "cache.warm", "ratelimit", "auth.token", "config.reload",
]
# (error_code, weight, message template). FRONTMATTER_TOO_DEEP dominates -> the
# real bug pattern from the case study.
ERROR_CODES = [
    ("FRONTMATTER_TOO_DEEP", 70, "metadata nesting depth {d} exceeds limit 3"),
    ("IO_NOT_FOUND", 8, "source file missing: {url}"),
    ("NET_TIMEOUT", 7, "request timed out after {d}ms: {url}"),
    ("PARSE_JSON", 6, "LLM returned malformed JSON for {url}"),
    ("AUTH_FORBIDDEN", 5, "source denied access: {url}"),
    ("RES_MEMORY", 4, "batch exceeded memory budget"),
]
_URL_KINDS = ["feed", "blog", "news", "wiki", "api"]


def _gen_events(n: int, rng: random.Random, error_rate: float, warn_rate: float) -> list[dict]:
    """Generate *n* log events spread across ~24h, grouped into multi-entry requests.

    Each request shares an rid/pid and has 5-20 entries — so `trace --rid` returns
    a real chain. Levels: ~error_rate ERROR, ~warn_rate WARN, ~10% TOOL, ~5% FILE_OP,
    rest INFO — mirroring the aggregation pipeline in the case study.
    """
    pids = [str(10000 + i) for i in range(8)]
    base = datetime(2026, 7, 28, tzinfo=timezone.utc)
    span_ms = 24 * 3600 * 1000
    err_w = [w for _, w, _ in ERROR_CODES]

    events: list[dict] = []
    produced = 0
    while produced < n:
        rid = f"{rng.randrange(16 ** 8):08x}"
        pid = rng.choice(pids)
        start_ms = rng.randrange(span_ms)
        n_evts = min(rng.randint(5, 20), n - produced)
        for _ in range(n_evts):
            ts = (base + timedelta(milliseconds=start_ms + rng.randint(0, 4000))).isoformat(timespec="milliseconds")
            module = rng.choice(MODULES)
            url = f"https://src{rng.randint(0, 200)}.example.com/{rng.choice(_URL_KINDS)}/{rng.randint(1, 10000)}"
            r = rng.random()
            if r < error_rate:
                code, _, tmpl = rng.choices(ERROR_CODES, weights=err_w)[0]
                d = rng.randint(4, 7)
                ev = {"level": "ERROR", "module": module,
                      "msg": f"{tmpl.format(d=d, url=url)} [{code}]",
                      "error_code": code}
            elif r < error_rate + warn_rate:
                d = rng.randint(2000, 8000)
                ev = {"level": "WARN", "module": module, "msg": f"slow source {url} ({d}ms)"}
            elif r < error_rate + warn_rate + 0.10:
                tool = rng.choice(["bash", "http", "read"])
                cmd = {"bash": f"curl {url}", "http": f"GET {url}", "read": url}[tool]
                ev = {"level": "TOOL", "module": module, "msg": f"Tool {tool} succeeded",
                      "tool": tool, "cmd": cmd, "exit": 0, "dur": rng.randint(50, 1500)}
            elif r < error_rate + warn_rate + 0.15:
                op = rng.choice(["read", "write"])
                ev = {"level": "FILE_OP", "module": module, "msg": f"File {op} succeeded: {url}",
                      "op": op, "path": url, "ok": True, "size": rng.randint(100, 50000)}
            else:
                d = rng.randint(20, 800)
                ev = {"level": "INFO", "module": module,
                      "msg": rng.choice([
                          f"fetched {url} ({d}ms)",
                          f"extracted {rng.randint(1, 12)} fields from {url}",
                          f"stored entity from {url}",
                          f"queued {url} for processing",
                      ])}
            ev.update({"ts": ts, "rid": rid, "pid": pid})
            events.append(ev)
            produced += 1

    # Time-order, then assign global monotonic seq (so each rid's chain is sequential).
    events.sort(key=lambda e: e["ts"])
    for seq, ev in enumerate(events, 1):
        ev["seq"] = seq
    return events


def _render_stdlib_line(ev: dict) -> str:
    """Render one event as a verbose stdlib ``logging.Formatter``-style line.

    Mimics a real deployment's formatter that carries equivalent observability
    (process/thread/level/logger/request_id) — the redundant field names are what
    AgenticLogger's compact keys eliminate. ERROR codes appear only inside the
    message text (e.g. ``[FRONTMATTER_TOO_DEEP]``); stdlib has no structured
    error_code field, which is the whole point of the comparison.

    @spec-why: stdlib per-entry size is format-dependent; this verbose formatter
      reproduces the case study's ~150-300 B/entry range. A terser formatter would
      shrink the storage saving (and the case study observed ~40-50% with their format).
    """
    line = (f"{ev['ts']} processName=MainProcess process={ev['pid']} "
            f"levelname={ev['level']} logger={ev['module']} "
            f"request_id={ev['rid']} seq={ev['seq']} — {ev['msg']}")
    if ev["level"] == "TOOL":
        line += (f" tool={ev['tool']} command=\"{ev['cmd']}\" "
                 f"exit_code={ev['exit']} duration_ms={ev['dur']}")
    elif ev["level"] == "FILE_OP":
        line += (f" operation={ev['op']} path={ev['path']} "
                 f"ok={ev['ok']} size_bytes={ev['size']}")
    return line


def _write_agentic(ev: dict, logger) -> None:
    """Write one event via the AgentLogger SDK write path (compact JSONL).

    @spec-why: Uses the real ``_write_entry`` path so on-disk bytes match production
      compact output; per-entry rid is pre-set so many request rids coexist in one file.
    """
    entry = {"level": ev["level"], "msg": ev["msg"], "module": ev["module"],
             "ts": ev["ts"], "rid": ev["rid"], "pid": ev["pid"], "seq": ev["seq"]}
    if ev["level"] == "TOOL":
        entry.update({"tool": ev["tool"], "cmd": ev["cmd"], "exit": ev["exit"], "dur": ev["dur"]})
    elif ev["level"] == "FILE_OP":
        entry.update({"op": ev["op"], "path": ev["path"], "ok": ev["ok"], "size": ev["size"]})
    logger._write_entry(entry, error_code=ev.get("error_code"))


def generate_corpus(out_dir: str | Path, n: int, seed: int,
                    error_rate: float, warn_rate: float) -> tuple[Path, Path, int]:
    """Generate dual-format corpus. Returns (stdlib_path, agentic_dir, n_events).

    Clears only the OWNED artifacts (``app.log`` and the ``agentic/`` subdir) so
    repeat runs to the same --out don't accumulate timestamped JSONL files (which
    would double-count in queries). Stale files are moved to ``./temp/deleted/``
    (recoverability rule: mv, never rm).

    @spec-invariant: Does NOT touch files it did not create.
    """
    from agentic_logger import AgentLogger

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    deleted = Path("./temp/deleted")
    deleted.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    stdlib_path = out / "app.log"
    agentic_dir = out / "agentic"
    if stdlib_path.exists():
        shutil.move(str(stdlib_path), str(deleted / f"app_{stamp}.log"))
    if agentic_dir.exists():
        shutil.move(str(agentic_dir), str(deleted / f"agentic_{stamp}"))
    agentic_dir.mkdir(exist_ok=True)

    rng = random.Random(seed)
    events = _gen_events(n, rng, error_rate, warn_rate)

    with stdlib_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(_render_stdlib_line(ev) + "\n")

    logger = AgentLogger(program="bench", command="run", log_dir=agentic_dir,
                         storage="jsonl", compact=True)
    for ev in events:
        _write_agentic(ev, logger)
    logger.close()

    return stdlib_path, agentic_dir, len(events)


# ------------------------------------------------------------------
# AgenticLogger CLI runner + output parsers.
# ------------------------------------------------------------------
def _agentic_prefix() -> list[str]:
    """Resolve the agentic-logger CLI invocation prefix."""
    which = shutil.which("agentic-logger")
    if which:
        return [which]
    return [sys.executable, "-m", "agentic_logger.cli"]


def _run_agentic(log_dir: Path, args: list[str]) -> str:
    """Run `agentic-logger --log-dir <log_dir> <args>`, return stdout text.

    @spec-why: Captures the exact CLI output an agent would feed to an LLM.
      AGENTIC_SELF_LOG=0 keeps the measured corpus clean (no self-log pollution).
    """
    env = {**os.environ, "AGENTIC_SELF_LOG": "0"}
    proc = subprocess.run(
        _agentic_prefix() + ["--log-dir", str(log_dir)] + args,
        capture_output=True, text=True, env=env, check=False,
    )
    return proc.stdout


def _parse_top_error_code(stats_text: str) -> str | None:
    """Extract the highest-count error_code from a `stats` table."""
    best, best_n = None, -1
    for line in stats_text.splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s+(\d+)\s+([\d.]+)%\s*$", line)
        if m and int(m.group(2)) > best_n:
            best, best_n = m.group(1), int(m.group(2))
    return best


def _parse_first_rid(jsonl_text: str) -> str | None:
    """First rid from JSONL query output (bookkeeping for trace step)."""
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = obj.get("rid") or obj.get("r")
        if rid:
            return rid
    return None


# ------------------------------------------------------------------
# Stdlib workflow — in-process grep/triage equivalents.
# ------------------------------------------------------------------
def _stdlib_error_lines(lines: list[str]) -> str:
    """All ERROR lines — what an agent must read to cluster by type (no error_code field).

    Matches the verbose formatter's ``levelname=ERROR`` token (trailing space avoids
    matching the substring inside a longer level name).
    """
    return "\n".join(ln for ln in lines if "levelname=ERROR " in ln)


def _stdlib_grep(lines: list[str], needle: str, context: int) -> str:
    """Lines matching *needle* with +/-context windows (deduped by line index)."""
    idx: set[int] = set()
    for i, ln in enumerate(lines):
        if needle in ln:
            idx.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    return "\n".join(lines[j] for j in sorted(idx))


# ------------------------------------------------------------------
# Disk + token reporting.
# ------------------------------------------------------------------
def _file_bytes(p: Path) -> int:
    return p.stat().st_size if p.exists() else 0


def _dir_bytes(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.exists() else 0


def _fmt_tok(n: int) -> str:
    return f"{n:,}"


def _savings(a: int, b: int) -> str:
    """Agentic-vs-stdlib savings percentage (higher = agentic cheaper)."""
    if a == 0:
        return "n/a"
    return f"{(a - b) * 100.0 / a:.1f}%"


def print_disk_summary(stdlib_path: Path, agentic_dir: Path, n_events: int) -> None:
    sb = _file_bytes(stdlib_path)
    ab = _dir_bytes(agentic_dir)
    print("=== Corpus ===")
    print(f"events: {n_events:,}  | tokenizer: {tokenizer_name()}")
    print(f"stdlib:  {sb / 1e6:.2f} MB ({sb / max(1, n_events):.0f} B/entry)")
    print(f"agentic: {ab / 1e6:.2f} MB ({ab / max(1, n_events):.0f} B/entry)")
    print(f"storage saving: {_savings(sb, ab)}")
    print()


def measure(stdlib_path: Path, agentic_dir: Path, context: int = 5) -> int:
    """Run the 3-step health-check on both corpora; print token comparison."""
    # --- AgenticLogger side ---
    a_stats = _run_agentic(agentic_dir, ["stats", "--group-by", "error_code"])
    top = _parse_top_error_code(a_stats)
    if top is None:
        print("No error codes found in agentic corpus; cannot measure.", file=sys.stderr)
        return 1
    # rid bookkeeping (uncounted): an agent would lift this from its step-2 read.
    det = _run_agentic(agentic_dir, ["query", "--error-code", top, "--level", "ERROR",
                                     "--format", "jsonl", "--limit", "1"])
    rid = _parse_first_rid(det)
    if rid is None:
        print("Could not resolve a trace rid; cannot measure.", file=sys.stderr)
        return 1
    a_query = _run_agentic(agentic_dir, ["query", "--error-code", top, "--limit", "100"])
    a_trace = _run_agentic(agentic_dir, ["trace", "--rid", rid])

    # --- stdlib side ---
    lines = Path(stdlib_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    s_stats = _stdlib_error_lines(lines)
    s_query = _stdlib_grep(lines, top, context)
    s_trace = _stdlib_grep(lines, f"request_id={rid}", 0)

    rows = [
        (f"1. error distribution", count_tokens(s_stats), count_tokens(a_stats)),
        (f"2. drill top error ({top})", count_tokens(s_query), count_tokens(a_query)),
        (f"3. trace one request (rid {rid[:8]})", count_tokens(s_trace), count_tokens(a_trace)),
    ]
    tot_s = sum(r[1] for r in rows)
    tot_a = sum(r[2] for r in rows)

    print("=== Daily Health-Check Token Cost ===")
    print(f"{'Step':<38} {'stdlib':>10} {'agentic':>10} {'saving':>9}")
    print("-" * 70)
    for name, s, a in rows:
        print(f"{name:<38} {_fmt_tok(s):>10} {_fmt_tok(a):>10} {_savings(s, a):>9}")
    print("-" * 70)
    print(f"{'TOTAL':<38} {_fmt_tok(tot_s):>10} {_fmt_tok(tot_a):>10} {_savings(tot_s, tot_a):>9}")
    print()
    print(f"top error: {top}  | trace rid: {rid}  | stdlib context: +/-{context} lines")
    return 0


# ------------------------------------------------------------------
# Wall-clock timing — tool-execution latency per step.
# ------------------------------------------------------------------
def _time_ms(cmd: list[str], env: dict | None = None, runs: int = 5) -> float:
    """Median wall-clock (ms) over *runs* subprocess invocations.

    @spec-why: median filters system jitter; subprocess time is what an agent
      actually pays per tool call (process spawn + work + output).
    """
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    return times[len(times) // 2]


def _speedup(stdlib_ms: float, agentic_ms: float) -> str:
    """Wall-clock ratio. >1 = agentic faster, <1 = agentic slower."""
    if agentic_ms <= 0:
        return "n/a"
    r = stdlib_ms / agentic_ms
    return f"{r:.2f}x" if r >= 1 else f"{1 / r:.2f}x slower"


def time_workflow(stdlib_path: Path, agentic_dir: Path, context: int = 5, runs: int = 5) -> int:
    """Time the 3-step health-check on both corpora (tool-execution wall-clock).

    AgenticLogger side: real CLI subprocess (what an agent invokes).
    Stdlib side: real ``grep`` subprocess (best-case stdlib tooling) producing the
      same text the token measurement counts.

    @spec-invariant: Does NOT count LLM ingestion time — that is token-bound and
      already reported by measure(); it scales with the token ratio (~96% lower).
    """
    a_stats = _run_agentic(agentic_dir, ["stats", "--group-by", "error_code"])
    top = _parse_top_error_code(a_stats)
    if top is None:
        print("No error codes found in agentic corpus; cannot time.", file=sys.stderr)
        return 1
    det = _run_agentic(agentic_dir, ["query", "--error-code", top, "--level", "ERROR",
                                     "--format", "jsonl", "--limit", "1"])
    rid = _parse_first_rid(det)
    if rid is None:
        print("Could not resolve a trace rid; cannot time.", file=sys.stderr)
        return 1

    env = {**os.environ, "AGENTIC_SELF_LOG": "0"}
    prefix = _agentic_prefix() + ["--log-dir", str(agentic_dir)]
    sf = str(stdlib_path)

    rows = [
        ("1. error distribution",
         _time_ms(["grep", "levelname=ERROR ", sf], None, runs),
         _time_ms(prefix + ["stats", "--group-by", "error_code"], env, runs)),
        (f"2. drill top error ({top})",
         _time_ms(["grep", f"-B{context}", f"-A{context}", top, sf], None, runs),
         _time_ms(prefix + ["query", "--error-code", top, "--limit", "100"], env, runs)),
        (f"3. trace one request (rid {rid[:8]})",
         _time_ms(["grep", f"request_id={rid}", sf], None, runs),
         _time_ms(prefix + ["trace", "--rid", rid], env, runs)),
    ]
    tot_s = sum(r[1] for r in rows)
    tot_a = sum(r[2] for r in rows)

    print(f"=== Tool-Execution Wall-Clock (median of {runs} runs) ===")
    print(f"{'Step':<38} {'stdlib ms':>10} {'agentic ms':>11} {'ratio':>14}")
    print("-" * 76)
    for name, s, a in rows:
        print(f"{name:<38} {s:>10.1f} {a:>11.1f} {_speedup(s, a):>14}")
    print("-" * 76)
    print(f"{'TOTAL':<38} {tot_s:>10.1f} {tot_a:>11.1f} {_speedup(tot_s, tot_a):>14}")
    print()
    print("NOTE: this is tool-execution time only (process spawn + scan).")
    print("      LLM ingestion time is token-bound -> ~same ratio as token saving (~96% lower).")
    return 0


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def cmd_generate(args: argparse.Namespace) -> int:
    stdlib_path, agentic_dir, n = generate_corpus(
        args.out, args.n, args.seed, args.error_rate, args.warn_rate)
    print_disk_summary(stdlib_path, agentic_dir, n)
    print(f"stdlib:  {stdlib_path}")
    print(f"agentic: {agentic_dir}")
    return 0


def cmd_measure(args: argparse.Namespace) -> int:
    print_disk_summary(Path(args.stdlib), Path(args.agentic), _approx_events(args.stdlib))
    return measure(Path(args.stdlib), Path(args.agentic), context=args.context)


def _approx_events(stdlib_path: str) -> int:
    """Rough event count from a stdlib file (line count) for the disk summary."""
    try:
        with open(stdlib_path, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def cmd_run(args: argparse.Namespace) -> int:
    stdlib_path, agentic_dir, n = generate_corpus(
        args.out, args.n, args.seed, args.error_rate, args.warn_rate)
    print_disk_summary(stdlib_path, agentic_dir, n)
    return measure(stdlib_path, agentic_dir, context=args.context)


def cmd_timeit(args: argparse.Namespace) -> int:
    """Generate (if --n) or reuse a corpus, then time the workflow per step."""
    if args.n is not None:
        stdlib_path, agentic_dir, _ = generate_corpus(
            args.out, args.n, args.seed, args.error_rate, args.warn_rate)
    else:
        if not args.stdlib or not args.agentic:
            print("error: provide --n (generate fresh) or both --stdlib and --agentic",
                  file=sys.stderr)
            return 2
        stdlib_path, agentic_dir = Path(args.stdlib), Path(args.agentic)
    return time_workflow(stdlib_path, agentic_dir, context=args.context, runs=args.runs)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="token_compare",
        description="Measure token savings: stdlib logging vs AgenticLogger (daily health-check).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_corpus_opts(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--n", type=int, default=50000, help="Event count (default 50000)")
        sp.add_argument("--out", default="./temp/token_compare", help="Output dir")
        sp.add_argument("--seed", type=int, default=20260728, help="RNG seed (deterministic)")
        sp.add_argument("--error-rate", type=float, default=0.001, help="ERROR fraction (default 0.001)")
        sp.add_argument("--warn-rate", type=float, default=0.001, help="WARN fraction (default 0.001)")

    g = sub.add_parser("generate", help="Generate a dual-format corpus")
    add_corpus_opts(g)
    g.set_defaults(func=cmd_generate)

    m = sub.add_parser("measure", help="Measure token cost on existing files")
    m.add_argument("--stdlib", required=True, help="Path to stdlib .log file")
    m.add_argument("--agentic", required=True, help="AgenticLogger log dir")
    m.add_argument("--context", type=int, default=5, help="Stdlib drill context lines (default 5)")
    m.set_defaults(func=cmd_measure)

    r = sub.add_parser("run", help="Generate corpus then measure (default workflow)")
    add_corpus_opts(r)
    r.add_argument("--context", type=int, default=5, help="Stdlib drill context lines (default 5)")
    r.set_defaults(func=cmd_run)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
