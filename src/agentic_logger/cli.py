"""CLI for AgenticLogger — query, trace, stats, tail, traceback, list-files.

@spec-ref: spec/04-read-interface.md §3 — CLI
@last-changed: 2026-07-21
@log-module: agentic_logger.cli

Usage::

    agentic-logger query --level ERROR --since 1h
    agentic-logger trace --rid abc12345
    agentic-logger stats --group-by error_code --since 24h
    agentic-logger tail --follow --level ERROR
    agentic-logger traceback --tid tb_053dff45
    agentic-logger list-files --since 7d
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentic_logger.mcp_server import (
    handle_query,
    handle_stats,
    handle_trace,
    handle_traceback,
    _load_all_backends,
)


def _parse_since(since: str | None) -> str | None:
    """Convert relative time (e.g. '1h', '24h', '7d') to ISO 8601.

    Raises ``ValueError`` on ambiguous input (bare number, unknown unit,
    fractional value) instead of silently producing a wrong time window.
    (@spec-ref: spec/04-read-interface.md §3 — 评审修复: _parse_since 静默错误)
    """
    if not since:
        return None
    # Already ISO 8601?
    if "T" in since:
        return since
    # Relative time: <integer><unit>
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if len(since) < 2 or since[-1] not in units:
        raise ValueError(
            f"invalid time value {since!r}: expected <N><unit> "
            f"(e.g. 1h, 24h, 7d; units: {sorted(units)}) or an ISO 8601 timestamp"
        )
    try:
        value = int(since[:-1])
    except ValueError as e:
        raise ValueError(
            f"invalid time value {since!r}: <N> must be an integer"
        ) from e
    seconds = value * units[since[-1]]
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.isoformat(timespec="milliseconds")


def _format_table(rows: list[dict], columns: list[str]) -> str:
    """Format rows as an aligned text table."""
    if not rows:
        return "(no results)"
    # Calculate column widths
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            val = str(row.get(col, ""))
            widths[col] = max(widths[col], min(len(val), 60))

    # Header
    header = "  ".join(col.ljust(widths[col])[:widths[col]] for col in columns)
    separator = "  ".join("-" * widths[col] for col in columns)
    lines = [header, separator]

    # Rows
    for row in rows:
        parts = []
        for col in columns:
            val = str(row.get(col, ""))
            if len(val) > 60:
                val = val[:57] + "..."
            parts.append(val.ljust(widths[col])[:widths[col]])
        lines.append("  ".join(parts))

    return "\n".join(lines)


def _format_entry_json(entry: dict) -> str:
    """Format a single entry as pretty JSON."""
    return json.dumps(entry, ensure_ascii=False, indent=2, default=str)


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------


def cmd_query(args: argparse.Namespace) -> int:
    """Handle the 'query' command."""
    log_dir = Path(args.log_dir)
    since = _parse_since(args.since)
    until = _parse_since(args.until)

    result = handle_query(
        log_dir,
        rid=args.rid,
        level=args.level,
        module=args.module,
        error_code=args.error_code,
        tool=args.tool,
        exit_code=args.exit_code,
        op=args.op,
        path=args.path,
        choice=args.choice,
        keyword=args.keyword,
        since=since,
        until=until,
        min_dur=args.min_dur,
        max_dur=args.max_dur,
        pid=args.pid,
        tid=args.tid,
        limit=args.limit,
        offset=args.offset,
        order_by=args.order_by,
        depth=args.depth,
        format=args.format,
        fields=args.fields,
        smart=args.smart,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.format == "jsonl":
        # JSONL format: one JSON object per line
        for entry in result["logs"]:
            print(json.dumps(entry, ensure_ascii=False, default=str))
        if args.smart and "smart_analysis" in result:
            print("\n# Smart Analysis")
            print(json.dumps(result["smart_analysis"], ensure_ascii=False, indent=2, default=str))
    else:
        # Table format
        columns = ["ts", "level", "module", "msg"]
        if any(e.get("dur") for e in result["logs"]):
            columns.append("dur")
        if any(e.get("error_code") for e in result["logs"]):
            columns.append("error_code")
        print(f"Found {result['count']} entries:")
        print(_format_table(result["logs"], columns))

    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """Handle the 'trace' command."""
    log_dir = Path(args.log_dir)
    result = handle_trace(
        log_dir,
        rid=args.rid,
        level=args.level,
        module=args.module,
        include_traceback=args.include_traceback,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Trace for rid={args.rid}:")
        print(f"  Entries: {result['entry_count']}")
        print(f"  Time range: {result['start_time']} → {result['end_time']}")
        print(f"  Summary: {result['summary']}")
        print()
        columns = ["ts", "level", "module", "msg"]
        if args.include_traceback:
            columns.append("tid")
        print(_format_table(result["trace"], columns))

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Handle the 'stats' command."""
    log_dir = Path(args.log_dir)
    since = _parse_since(args.since)
    until = _parse_since(args.until)

    result = handle_stats(
        log_dir,
        since=since,
        until=until,
        group_by=args.group_by,
        rid=args.rid,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Statistics (group_by={result['group_by']}, total={result['total']}):")
        rows = [
            {"key": g["key"], "count": g["count"], "percentage": f"{g['percentage']}%"}
            for g in result["groups"]
        ]
        print(_format_table(rows, ["key", "count", "percentage"]))

    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    """Handle the 'tail' command — real-time log streaming."""
    log_dir = Path(args.log_dir)
    backends = _load_all_backends(log_dir)

    if not backends:
        print(f"No log files found in {log_dir}", file=sys.stderr)
        return 1

    # Use the most recent backend for tailing
    latest = max(backends, key=lambda b: b.file_path.stat().st_mtime)
    print(f"Tailing: {latest.file_path}", file=sys.stderr)

    # Dedup by (ts, seq) — ts-only dedup dropped entries sharing a millisecond.
    # Bounded to avoid unbounded growth across long --follow sessions.
    seen: set[tuple] = set()
    try:
        while True:
            # Read new entries
            entries = latest.query(limit=100, order_by="ts_asc")
            for entry in entries:
                key = (entry.get("ts"), entry.get("seq"))
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > 100_000:
                    seen.clear()
                    seen.add(key)

                # Apply filters (module uses fnmatch glob, consistent with query)
                if args.level and entry.get("level") != args.level:
                    continue
                if args.module and not fnmatch.fnmatch(entry.get("module", ""), args.module):
                    continue
                if args.error_code and entry.get("error_code") != args.error_code:
                    continue

                if args.format == "json":
                    print(json.dumps(entry, ensure_ascii=False, default=str), flush=True)
                else:
                    ts = entry.get("ts", "")
                    ts_short = ts[11:23] if len(ts) > 23 else ts
                    level = entry.get("level", "?")
                    module = entry.get("module", "?")
                    msg = entry.get("msg", "")
                    print(f"[{ts_short}] {level:7s} {module}: {msg}", flush=True)

            if not args.follow:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)

    return 0


def cmd_traceback(args: argparse.Namespace) -> int:
    """Handle the 'traceback' command."""
    log_dir = Path(args.log_dir)
    result = handle_traceback(log_dir, args.tid)

    if result is None:
        print(f"Traceback not found: {args.tid}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Traceback: {result['tid']}")
        print(f"Exception: {result['exception_type']}: {result['exception_msg']}")
        print()
        print(result["traceback"])

    return 0


def cmd_list_files(args: argparse.Namespace) -> int:
    """Handle the 'list-files' command."""
    log_dir = Path(args.log_dir)
    backends = _load_all_backends(log_dir)

    if not backends:
        print(f"No log files found in {log_dir}")
        return 0

    rows = []
    for b in backends:
        tr = b.get_time_range()
        size = b.file_path.stat().st_size
        size_str = f"{size / 1024:.1f}KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}MB"
        rows.append({
            "file": b.file_path.name,
            "size": size_str,
            "min_ts": (tr or {}).get("min_ts", "?"),
            "max_ts": (tr or {}).get("max_ts", "?"),
        })

    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(_format_table(rows, ["file", "size", "min_ts", "max_ts"]))

    return 0


# ------------------------------------------------------------------
# CLI Argument Parser
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="agentic-logger",
        description="AgenticLogger CLI — query, trace, and analyze agent logs",
    )
    parser.add_argument("--log-dir", default="./logs", help="Log directory (default: ./logs)")

    sub = parser.add_subparsers(dest="command", required=True)

    # query
    p_query = sub.add_parser("query", help="Query logs with filters")
    p_query.add_argument("--rid", help="Run ID")
    p_query.add_argument("--level", choices=["DEBUG", "INFO", "WARN", "ERROR", "TOOL", "FILE_OP", "DECISION", "CODE_GEN", "CONTEXT"])
    p_query.add_argument("--module", help="Module name (supports * glob)")
    p_query.add_argument("--error-code", help="Error code")
    p_query.add_argument("--tool", help="Tool name")
    p_query.add_argument("--exit-code", type=int, help="Exit code")
    p_query.add_argument("--op", choices=["read", "write", "delete", "move", "copy"])
    p_query.add_argument("--path", help="File path")
    p_query.add_argument("--choice", help="Decision choice")
    p_query.add_argument("--keyword", help="Full-text search")
    p_query.add_argument("--since", help="Start time (ISO 8601 or relative: 1h, 24h, 7d)")
    p_query.add_argument("--until", help="End time")
    p_query.add_argument("--min-dur", type=int, help="Min duration (ms)")
    p_query.add_argument("--max-dur", type=int, help="Max duration (ms)")
    p_query.add_argument("--pid", help="Process ID")
    p_query.add_argument("--tid", help="Traceback ID")
    p_query.add_argument("--limit", type=int, default=100)
    p_query.add_argument("--offset", type=int, default=0)
    p_query.add_argument("--order-by", choices=["ts_asc", "ts_desc", "dur_desc"], default="ts_desc")
    p_query.add_argument("--format", choices=["jsonl", "json", "table"], default="jsonl", help="Output format: jsonl (Agent-friendly, default), json (structured), table (human-readable)")
    p_query.add_argument("--depth", choices=["summary", "detail", "full"], default="summary", help="Information richness: summary (compact), detail (debugging), full (all fields)")
    p_query.add_argument("--fields", help="Comma-separated field names (e.g., 'ts,level,msg,rid,duration_ms')")
    p_query.add_argument("--smart", action="store_true", help="Enable smart analysis mode (stats + top errors + suggestions)")

    # trace
    p_trace = sub.add_parser("trace", help="Trace a full run by rid")
    p_trace.add_argument("--rid", required=True, help="Run ID")
    p_trace.add_argument("--level", help="Filter by level")
    p_trace.add_argument("--module", help="Filter by module")
    p_trace.add_argument("--include-traceback", action="store_true")
    p_trace.add_argument("--format", choices=["table", "json"], default="table")

    # stats
    p_stats = sub.add_parser("stats", help="Aggregated statistics")
    p_stats.add_argument("--group-by", choices=["level", "tool", "module", "error_code", "pid"], default="level")
    p_stats.add_argument("--since", help="Start time")
    p_stats.add_argument("--until", help="End time")
    p_stats.add_argument("--rid", help="Filter by run ID")
    p_stats.add_argument("--format", choices=["table", "json"], default="table")

    # tail
    p_tail = sub.add_parser("tail", help="Real-time log streaming")
    p_tail.add_argument("--follow", "-f", action="store_true", help="Follow new entries")
    p_tail.add_argument("--level", help="Filter by level")
    p_tail.add_argument("--module", help="Filter by module")
    p_tail.add_argument("--error-code", help="Filter by error code")
    p_tail.add_argument("--format", choices=["text", "json"], default="text")

    # traceback
    p_tb = sub.add_parser("traceback", help="Retrieve stack trace by tid")
    p_tb.add_argument("--tid", required=True, help="Traceback ID")
    p_tb.add_argument("--format", choices=["text", "json"], default="text")

    # list-files
    p_list = sub.add_parser("list-files", help="List log files")
    p_list.add_argument("--format", choices=["table", "json"], default="table")

    return parser


def main():
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "query": cmd_query,
        "trace": cmd_trace,
        "stats": cmd_stats,
        "tail": cmd_tail,
        "traceback": cmd_traceback,
        "list-files": cmd_list_files,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        sys.exit(handler(args))
    except ValueError as e:
        # e.g. invalid --since/--until value from _parse_since
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
