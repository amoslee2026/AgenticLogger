"""MCP Server for AgenticLogger — AI Agent log query interface.

@spec-ref: spec/04-read-interface.md §2 — MCP Tool
@spec-ref: spec/01-architecture.md §2.3 — 读取接口

Provides these MCP Tools to AI Agents (Claude Code, Cursor, etc.):

- ``agentic_log_query``    — Multi-field filtered log search
- ``agentic_log_trace``    — Full trace of one run by ``rid``
- ``agentic_log_stats``    — Aggregated statistics by group key
- ``agentic_log_traceback`` — Retrieve full stack trace by ``tid``

Usage::

    # As a CLI entry point (stdio transport)
    agentic-logger-mcp --log-dir ./logs

    # Programmatically
    from agentic_logger.mcp_server import create_server
    server = create_server(log_dir="./logs")
    server.run()
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agentic_logger.storage.jsonl import JSONLBackend


def _load_all_backends(log_dir: Path) -> list[JSONLBackend]:
    """Discover all ``.jsonl`` files in *log_dir* and wrap them."""
    backends = []
    for f in sorted(log_dir.glob("*.jsonl")):
        if f.name.endswith(".rotating"):
            continue
        try:
            backends.append(JSONLBackend(file_path=f))
        except Exception:
            continue
    return backends


def _merge_query(
    backends: list[JSONLBackend],
    since: str | None = None,
    until: str | None = None,
    **filters: Any,
) -> list[dict]:
    """Query across all backends with time-range pruning + merge sort.

    @spec-ref: spec/04-read-interface.md §5.1 — 跨后端归并排序
    """
    # Extract pagination from filters (with safe defaults)
    limit = filters.pop("limit", 100)
    offset = filters.pop("offset", 0)
    order_by = filters.pop("order_by", "ts_desc")

    candidates = []
    for b in backends:
        tr = b.get_time_range()
        if tr and since and tr.get("max_ts") and tr["max_ts"] < since:
            continue
        if tr and until and tr.get("min_ts") and tr["min_ts"] > until:
            continue
        candidates.append(b)

    # Fetch all matching entries from each candidate (generous limit per backend)
    all_results = []
    for b in candidates:
        all_results.extend(b.query(since=since, until=until, limit=100000, **filters))

    # Sort
    reverse = order_by != "ts_asc"
    if order_by == "dur_desc":
        all_results.sort(key=lambda x: x.get("dur") or 0, reverse=True)
    else:
        all_results.sort(key=lambda x: x.get("ts", ""), reverse=reverse)

    return all_results[offset : offset + limit]


# ------------------------------------------------------------------
# Tool handlers
# ------------------------------------------------------------------


def handle_query(
    log_dir: Path,
    rid: str | None = None,
    level: str | None = None,
    module: str | None = None,
    error_code: str | None = None,
    tool: str | None = None,
    exit_code: int | None = None,
    op: str | None = None,
    path: str | None = None,
    choice: str | None = None,
    keyword: str | None = None,
    since: str | None = None,
    until: str | None = None,
    min_dur: int | None = None,
    max_dur: int | None = None,
    pid: str | None = None,
    tid: str | None = None,
    limit: int = 100,
    offset: int = 0,
    order_by: str = "ts_desc",
    file_pattern: str | None = None,
) -> dict:
    """``agentic_log_query`` — multi-field filtered log search.

    @spec-ref: spec/04-read-interface.md §2.2 — agentic_log_query
    """
    backends = _load_all_backends(log_dir)
    if not backends:
        return {"count": 0, "total": 0, "logs": [], "message": "No log files found"}

    filters: dict[str, Any] = {}
    if rid is not None:
        filters["rid"] = rid
    if level is not None:
        filters["level"] = level
    if module is not None:
        filters["module"] = module
    if error_code is not None:
        filters["error_code"] = error_code
    if tool is not None:
        filters["tool"] = tool
    if exit_code is not None:
        # MCP API uses "exit_code", JSONL entry uses "exit"
        filters["exit"] = exit_code
    if op is not None:
        filters["op"] = op
    if path is not None:
        filters["path"] = path
    if choice is not None:
        filters["choice"] = choice
    if keyword is not None:
        filters["keyword"] = keyword
    if min_dur is not None:
        filters["min_dur"] = min_dur
    if max_dur is not None:
        filters["max_dur"] = max_dur
    if pid is not None:
        filters["pid"] = pid
    if tid is not None:
        filters["tid"] = tid
    filters["limit"] = limit
    filters["offset"] = offset
    filters["order_by"] = order_by

    logs = _merge_query(backends, since=since, until=until, **filters)

    # Filter out __GLOBAL_CTX__ entries from results
    data_logs = [e for e in logs if e.get("level") != "__GLOBAL_CTX__"]

    return {
        "count": len(data_logs),
        "logs": data_logs,
        "query_info": {
            "backends_scanned": len(backends),
            "log_dir": str(log_dir),
        },
    }


def handle_trace(
    log_dir: Path,
    rid: str,
    level: str | None = None,
    module: str | None = None,
    include_traceback: bool = False,
) -> dict:
    """``agentic_log_trace`` — full trace of one run by ``rid``.

    @spec-ref: spec/04-read-interface.md §2.2 — agentic_log_trace
    """
    backends = _load_all_backends(log_dir)

    all_entries = []
    for b in backends:
        entries = b.query(rid=rid, limit=10000)
        all_entries.extend(entries)

    # Filter out __GLOBAL_CTX__
    data_entries = [e for e in all_entries if e.get("level") != "__GLOBAL_CTX__"]

    # Additional filters
    if level:
        data_entries = [e for e in data_entries if e.get("level") == level]
    if module:
        data_entries = [e for e in data_entries if e.get("module") == module]

    # Sort by ts ascending
    data_entries.sort(key=lambda x: x.get("ts", ""))

    # Build summary
    level_counts: dict[str, int] = {}
    for e in data_entries:
        lvl = e.get("level", "UNKNOWN")
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    # Optionally fetch tracebacks
    if include_traceback:
        for entry in data_entries:
            tid = entry.get("tid")
            if tid:
                for b in backends:
                    tb = b.get_traceback(tid)
                    if tb:
                        entry["traceback_detail"] = tb
                        break

    # Find time range
    timestamps = [e.get("ts", "") for e in data_entries if e.get("ts")]
    start_time = min(timestamps) if timestamps else None
    end_time = max(timestamps) if timestamps else None

    return {
        "rid": rid,
        "entry_count": len(data_entries),
        "start_time": start_time,
        "end_time": end_time,
        "summary": level_counts,
        "trace": data_entries,
    }


def handle_stats(
    log_dir: Path,
    since: str | None = None,
    until: str | None = None,
    group_by: str = "level",
    rid: str | None = None,
    file_pattern: str | None = None,
) -> dict:
    """``agentic_log_stats`` — aggregated statistics by group key.

    @spec-ref: spec/04-read-interface.md §2.2 — agentic_log_stats
    """
    backends = _load_all_backends(log_dir)

    filters: dict[str, Any] = {"limit": 100000}
    if rid:
        filters["rid"] = rid

    all_entries = _merge_query(backends, since=since, until=until, **filters)
    data_entries = [e for e in all_entries if e.get("level") != "__GLOBAL_CTX__"]

    # Group
    groups: dict[str, int] = {}
    for entry in data_entries:
        key = str(entry.get(group_by, "unknown"))
        groups[key] = groups.get(key, 0) + 1

    total = len(data_entries)
    sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)

    return {
        "total": total,
        "group_by": group_by,
        "groups": [
            {"key": k, "count": v, "percentage": round(v / total * 100, 1) if total else 0}
            for k, v in sorted_groups
        ],
        "backends_scanned": len(backends),
    }


def handle_traceback(log_dir: Path, tid: str) -> dict | None:
    """``agentic_log_traceback`` — retrieve full stack trace by ``tid``.

    @spec-ref: spec/04-read-interface.md §2.2 — agentic_log_traceback
    """
    backends = _load_all_backends(log_dir)
    for b in backends:
        tb = b.get_traceback(tid)
        if tb:
            return tb
    return None


# ------------------------------------------------------------------
# MCP Server Factory
# ------------------------------------------------------------------


def create_server(log_dir: str | Path = "./logs"):
    """Create and configure the MCP server.

    @spec-ref: spec/04-read-interface.md §2.3 — MCP Server 实现

    Returns an ``mcp.Server`` ready to be run via ``server.run()``.
    """
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    log_path = Path(log_dir)
    server = Server("agentic-logger")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="agentic_log_query",
                description=(
                    "Query structured logs with multi-field filters. "
                    "Supports: rid, level, module (with * glob), error_code, "
                    "tool, exit_code, op, path, choice, keyword, "
                    "min_dur, max_dur, pid, tid, since, until, "
                    "order_by (ts_asc/ts_desc/dur_desc), limit, offset."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "rid": {"type": "string", "description": "Run ID"},
                        "level": {"type": "string", "enum": [
                            "DEBUG", "INFO", "WARN", "ERROR",
                            "TOOL", "FILE_OP", "DECISION", "CODE_GEN", "CONTEXT",
                        ]},
                        "module": {"type": "string", "description": "Module name, supports * glob"},
                        "error_code": {"type": "string"},
                        "tool": {"type": "string"},
                        "exit_code": {"type": "integer"},
                        "op": {"type": "string", "enum": ["read", "write", "delete", "move", "copy"]},
                        "path": {"type": "string"},
                        "choice": {"type": "string"},
                        "keyword": {"type": "string", "description": "Full-text search"},
                        "since": {"type": "string", "description": "ISO 8601 or relative (1h, 24h)"},
                        "until": {"type": "string"},
                        "min_dur": {"type": "integer", "description": "Min duration (ms)"},
                        "max_dur": {"type": "integer", "description": "Max duration (ms)"},
                        "pid": {"type": "string"},
                        "tid": {"type": "string"},
                        "limit": {"type": "integer", "default": 100},
                        "offset": {"type": "integer", "default": 0},
                        "order_by": {"type": "string", "enum": ["ts_asc", "ts_desc", "dur_desc"], "default": "ts_desc"},
                        "file_pattern": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="agentic_log_trace",
                description=(
                    "Get the full trace of one run by its rid. "
                    "Returns all entries in chronological order with summary."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "rid": {"type": "string", "description": "Run ID (required)"},
                        "level": {"type": "string", "description": "Optional level filter"},
                        "module": {"type": "string", "description": "Optional module filter"},
                        "include_traceback": {"type": "boolean", "default": False},
                    },
                    "required": ["rid"],
                },
            ),
            Tool(
                name="agentic_log_stats",
                description=(
                    "Get aggregated statistics grouped by a field. "
                    "Useful for error distribution, tool usage, etc."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "since": {"type": "string"},
                        "until": {"type": "string"},
                        "group_by": {
                            "type": "string",
                            "enum": ["level", "tool", "module", "error_code", "pid"],
                            "default": "level",
                        },
                        "rid": {"type": "string"},
                        "file_pattern": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="agentic_log_traceback",
                description="Retrieve full stack trace text by its tid reference.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tid": {"type": "string", "description": "Traceback ID (required)"},
                    },
                    "required": ["tid"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "agentic_log_query":
            result = handle_query(log_path, **arguments)
        elif name == "agentic_log_trace":
            result = handle_trace(log_path, **arguments)
        elif name == "agentic_log_stats":
            result = handle_stats(log_path, **arguments)
        elif name == "agentic_log_traceback":
            result = handle_traceback(log_path, **arguments)
            if result is None:
                result = {"error": f"Traceback not found: {arguments.get('tid')}"}
        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2, default=str),
        )]

    return server


def main():
    """CLI entry point — run the MCP server over stdio."""
    parser = argparse.ArgumentParser(description="AgenticLogger MCP Server")
    parser.add_argument("--log-dir", default="./logs", help="Log directory")
    args = parser.parse_args()

    server = create_server(log_dir=args.log_dir)

    from mcp.server.stdio import stdio_server
    import asyncio

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
