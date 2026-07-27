"""Self-observability — AgenticLogger logs its own read-layer operations.

@spec-ref: /home/lxx/.claude/plans/misty-foraging-turtle.md
@last-changed: 2026-07-27
@log-module: agentic_logger.self_log

Dogfooding: the CLI and MCP read layer record their own tool / command
invocations via the :class:`AgentLogger` SDK, so AgenticLogger's runtime
behaviour becomes queryable by AgenticLogger itself — closing the loop.

Enabled by default.  Set ``AGENTIC_SELF_LOG=0`` to disable (tests do this
via an autouse conftest fixture so existing assertions stay unaffected).

Self-log files live **alongside** user logs in the same ``log_dir`` with
``program="agentic_logger"`` (e.g. ``agentic_logger_mcp_*.jsonl``).  They
are therefore part of the queryable dataset; filter them with
``--module "agentic_logger.*"``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agentic_logger.error_codes import ErrorCode
from agentic_logger.logger import AgentLogger

_PROGRAM = "agentic_logger"
_MODULE_MCP = "agentic_logger.mcp_server"
_MODULE_CLI = "agentic_logger.cli"

# One logger per (log_dir, command) — avoids per-call file churn.
# @spec-why: CLI is invoked many times in short-lived processes; reusing one
# file per command keeps the self-log dataset navigable instead of fragmenting
# into thousands of microsecond-named files.
_CACHE: dict[tuple[Path, str], AgentLogger] = {}


def is_enabled() -> bool:
    """Return *True* unless ``AGENTIC_SELF_LOG=0``.

    @spec-why: Default-on realises the dogfooding intent; the env knob gives
    tests and noise-sensitive callers a one-line opt-out.
    """
    return os.environ.get("AGENTIC_SELF_LOG", "1") != "0"


def reset_cache() -> None:
    """Clear the logger cache (test helper for isolation)."""
    _CACHE.clear()


def get_self_logger(log_dir: str | Path, command: str) -> AgentLogger | None:
    """Return a cached self-observation logger, or *None* if disabled.

    @spec-invariant: Does NOT rotate by size — only by file count (``max_files``);
    self-log growth is bounded and predictable.
    """
    if not is_enabled():
        return None
    key = (Path(log_dir), command)
    logger = _CACHE.get(key)
    if logger is None:
        logger = AgentLogger(
            program=_PROGRAM,
            command=command,
            log_dir=str(log_dir),
            storage="jsonl",
            circular=True,
            max_files=10,
        )
        _CACHE[key] = logger
    return logger


def _summarize_args(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Compact argument snapshot — keys + small scalar values only.

    @spec-why: Token efficiency + avoid persisting large or potentially
    sensitive payloads.  Non-scalar values degrade to their type name.
    @spec-invariant: Does NOT recurse into nested structures — one level only.
    """
    summary: dict[str, Any] = {}
    for k, v in (arguments or {}).items():
        if isinstance(v, bool) or v is None:
            summary[k] = v
        elif isinstance(v, (int, float)):
            summary[k] = v
        elif isinstance(v, str):
            summary[k] = v if len(v) <= 40 else v[:37] + "..."
        else:
            summary[k] = type(v).__name__
    return summary


def log_mcp_call(
    log_dir: str | Path,
    name: str,
    arguments: dict[str, Any] | None,
    result: dict[str, Any] | None,
    dur_ms: int,
) -> None:
    """Record one MCP tool dispatch.

    @spec-ref: plan §接入点 1
    @agent-tag: self-log-mcp
    @spec-invariant: Never raises — a self-log failure must not break dispatch.
    """
    logger = get_self_logger(log_dir, "mcp")
    if logger is None:
        return
    is_error = isinstance(result, dict) and "error" in result
    ctx: dict[str, Any] = {
        "tool": name,
        "exit": 1 if is_error else 0,
        "dur_ms": dur_ms,
        "args": _summarize_args(arguments),
    }
    if isinstance(result, dict):
        if "count" in result:
            ctx["results"] = result["count"]
        if "backends_scanned" in result.get("query_info", {}):
            ctx["backends"] = result["query_info"]["backends_scanned"]
        if is_error:
            err = str(result.get("error"))
            ctx["error"] = err[:200]
    msg = f"MCP {name} {'failed' if is_error else 'ok'}"
    if is_error:
        logger.error(msg, module=_MODULE_MCP, error_code=ErrorCode.INTERNAL_UNEXPECTED, ctx=ctx)
    else:
        logger.info(msg, module=_MODULE_MCP, ctx=ctx)


def log_cli_call(
    log_dir: str | Path,
    command: str,
    exit_code: int,
    dur_ms: int,
    error: str | None = None,
) -> None:
    """Record one CLI command invocation.

    @spec-ref: plan §接入点 2
    @agent-tag: self-log-cli
    @spec-invariant: Never raises — a self-log failure must not break the CLI.
    """
    logger = get_self_logger(log_dir, command)
    if logger is None:
        return
    is_error = exit_code != 0
    ctx: dict[str, Any] = {
        "command": command,
        "exit_code": exit_code,
        "dur_ms": dur_ms,
    }
    if error:
        ctx["error"] = error[:200]
    msg = f"CLI {command} {'failed' if is_error else 'ok'}"
    if is_error:
        logger.error(msg, module=_MODULE_CLI, error_code=ErrorCode.INTERNAL_UNEXPECTED, ctx=ctx)
    else:
        logger.info(msg, module=_MODULE_CLI, ctx=ctx)
