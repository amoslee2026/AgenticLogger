# AgenticLogger

**Structured logging for Coding Agents** — write once, read efficiently.

AgenticLogger lets Coding Agents (Claude Code, Cursor, Copilot, etc.) emit structured logs that AI tools can query with minimal token overhead. Instead of parsing free-form text, agents read pre-structured JSON entries with indexed fields.

## Quick Start

```python
from agentic_logger import AgentLogger, ErrorCode

logger = AgentLogger(program="my_agent", command="build")

logger.info("Starting build", module="build.main")
logger.tool_call(tool="bash", cmd="npm install", exit=0, dur=5000)
logger.error("Build failed", module="build.compile", error_code=ErrorCode.EXEC_NON_ZERO)
```

Log file: `./logs/my_agent_build_20260721_133834090719.jsonl`

## Installation

```bash
pip install agentic-logger

# With MCP server support
pip install "agentic-logger[mcp]"
```

## Core Concepts

### Structured Log Entries

Each log entry is a single JSON line with auto-filled fields:

| Field | Auto-filled | Description |
|-------|------------|-------------|
| `ts` | ✅ | ISO 8601 timestamp (millisecond precision) |
| `level` | | `INFO`, `WARN`, `ERROR`, `TOOL`, `FILE_OP`, `DECISION`, `CODE_GEN`, `CONTEXT` |
| `msg` | | One-line summary (≤ 4KB) |
| `module` | ✅ | Caller's module path (auto-extracted from stack) |
| `rid` | ✅ | Run ID (UUID4 hex[:8]) — chains all entries from one execution |
| `pid` | ✅ | Process ID |
| `seq` | ✅ | Monotonic sequence number within a run |
| `dur` | | Operation duration (ms) |
| `error_code` | | Standardized error code (see `ErrorCode` enum) |
| `ctx` | | Small key-value context dict |

### Log Methods

| Method | Use Case |
|--------|----------|
| `info(msg, ...)` | General information |
| `warn(msg, ...)` | Warnings |
| `error(msg, error_code, ...)` | Errors (error_code recommended) |
| `exception(msg, error_code)` | Auto-capture traceback in except block |
| `tool_call(tool, cmd, exit, dur, ...)` | External command invocations |
| `file_op(op, path, ok, ...)` | File system operations |
| `decision(choice, alts, reason)` | Architectural decisions |
| `code_gen(lang, path, ...)` | Code generation events |
| `context_switch(to_task, from_task)` | Task switches |

### Error Code Taxonomy

```python
from agentic_logger import ErrorCode

# Standard categories
ErrorCode.PARSE_JSON      # Parse failures
ErrorCode.IO_NOT_FOUND    # File system errors
ErrorCode.EXEC_NON_ZERO   # Command execution failures
ErrorCode.NET_TIMEOUT     # Network timeouts
ErrorCode.AUTH_FORBIDDEN  # Authentication/authorization
ErrorCode.CONFIG_MISSING  # Configuration errors
ErrorCode.RES_MEMORY      # Resource exhaustion
ErrorCode.UNKNOWN         # Fallback
```

See `spec/02-log-format.md §9` for the complete error code list.

## Storage Backends

### JSONL (Default)

```python
logger = AgentLogger(program="my_agent", storage="jsonl")
# Output: logs/my_agent_pid12345_20260721_133834.jsonl
```

- Streaming append (safe for `tail -f`)
- Circular rotation with configurable retention
- Compatible with `grep`/`jq`

### SQLite + WAL

```python
logger = AgentLogger(program="my_agent", storage="sqlite")
# Output: logs/my_agent_pid12345_20260721_133834.sqlite
```

- WAL mode for concurrent reads during writes
- Indexed queries on `rid`, `level`, `module`, `error_code`, `tool`
- Thread-safe via `threading.Lock`
- Auto-selected for `build`/`test`/`ci` commands

### Auto Selection

```python
logger = AgentLogger(program="my_agent", storage="auto")  # default
```

Rules (first match wins):
1. Env var `AGENTIC_STORAGE` overrides all
2. Multi-process environment → SQLite
3. Existing `.sqlite` files for same program → SQLite
4. Command keywords (`build`, `test`, `ci`, ...) → SQLite
5. Default → JSONL

## Reading Logs

### MCP Server (for AI Agents)

```bash
# Start MCP server (stdio transport)
agentic-logger-mcp --log-dir ./logs
```

Available tools:

| Tool | Description |
|------|-------------|
| `agentic_log_query` | Multi-field filtered search (20+ params) |
| `agentic_log_trace` | Full trace by `rid` |
| `agentic_log_stats` | Aggregated statistics |
| `agentic_log_traceback` | Stack trace by `tid` |

### CLI (for Humans)

```bash
# Query with filters
agentic-logger query --level ERROR --since 1h
agentic-logger query --module "agent.*" --error-code IO_NOT_FOUND
agentic-logger query --tool bash --exit-code 1 --min-dur 1000

# Trace a full run
agentic-logger trace --rid abc12345 --include-traceback

# Statistics
agentic-logger stats --group-by error_code --since 24h

# Real-time streaming
agentic-logger tail --follow --level ERROR

# Get stack trace
agentic-logger traceback --tid tb_053dff45

# List log files
agentic-logger list-files
```

### Python SDK (for Programs)

```python
from agentic_logger.mcp_server import handle_query, handle_trace, handle_stats
from pathlib import Path

log_dir = Path("./logs")

# Query
result = handle_query(log_dir, level="ERROR", since="1h")

# Trace
result = handle_trace(log_dir, rid="abc12345", include_traceback=True)

# Stats
result = handle_stats(log_dir, group_by="error_code")
```

## Log File Naming

Format: `{program}_{command}_{YYYYMMDD}_{HHmmssffffff}.{ext}`

Examples:
- `my_agent_main_20260721_133834090719.jsonl`
- `build_script_test_20260721_140000123456.sqlite`

Microsecond precision avoids collisions when multiple instances start within the same second.

## Circular Write Mode

For long-running agents, enable circular write to bound file size:

```python
logger = AgentLogger(
    program="my_agent",
    circular=True,
    max_size_mb=500,      # Rotate when file exceeds 500MB
    max_files=10,         # Keep last 10 files (JSONL)
    retention_hours=24,   # Keep last 24h (SQLite)
)
```

**JSONL rotation**: Safe rename → create → delete ordering (crash-safe).
**SQLite cleanup**: Time-based retention + size-based pruning with WAL checkpoint.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              写入层 (AgentLogger SDK)                        │
│  AgentLogger.info()  .tool_call()  .error()  ...            │
│              ↓  Auto-fields: ts/pid/rid/seq                 │
├─────────────────────────────────────────────────────────────┤
│              存储层 (JSONL / SQLite WAL)                     │
│  {program}_{cmd}_{date}_{time}.jsonl  |  .sqlite            │
├─────────────────────────────────────────────────────────────┤
│              读取层 (MCP / CLI / SDK)                        │
│  agentic_log_query  |  agentic-logger query  |  handle_query│
└─────────────────────────────────────────────────────────────┘
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev --extra mcp

# Run tests
uv run pytest tests/ -v

# Check coverage
uv run pytest tests/ --cov=agentic_logger

# Lint
uv run ruff check src/
```

## Log Analysis Utilities

The `utils/` directory provides scripts for efficient log analysis (per Token Saving Rules):

| Script | Purpose | Usage |
|--------|---------|-------|
| `utils/log_triage.py` | Error-type summary (count + first occurrence) | `./utils/log_triage.py <logfile>` |
| `utils/log_extract.sh` | Extract ±10-line context around patterns | `./utils/log_extract.sh <logfile> [pattern]` |
| `utils/agentic_logger.py` | Shared logging utility for Python scripts | `from utils.agentic_logger import get_logger` |
| `utils/CLAUDE.md` | Index describing each script | Read before writing new scripts |

**Workflow**: Run `log_triage.py` first to identify error types, then `log_extract.sh` to pull context around specific patterns. This avoids reading the full log file.

## Code Conventions

### Inline Spec Annotations

Source files use inline spec tags for drift detection and grep-based discovery:

| Tag | Purpose |
|-----|---------|
| `@spec-ref` | Points to arch spec section (file#section) |
| `@spec-why` | Reasoning behind non-obvious decisions |
| `@spec-invariant` | What the function deliberately does NOT do |
| `@spec-caution` | Cross-file/cross-repo dependencies |
| `@agent-tag` | Functional category for grep discovery (sparse, critical paths only) |
| `@agent-caution` | Risk warnings for future edits |
| `@agent-todo` | Agent-facing action reminders |
| `@last-changed` | Single timestamp of most recent substantive change (ISO 8601) |
| `@log-module` | Retrieval metadata linking to log entries |

**Density principle**: Every tag/comment line must be terse — no filler words, no restating the obvious. If content exceeds ~2 lines, question whether it belongs inline or in the arch spec.

**Drift detection**: Before editing code with `@spec-*` tags, read them as constraints. After editing, verify the new behavior still satisfies `@spec-invariant` and matches the section cited in `@spec-ref`. If not, follow the conflict resolution process (present to user, don't silently rewrite specs).

## Design Specifications

Full design documents in `spec/`:

| Document | Description |
|----------|-------------|
| `01-architecture.md` | System architecture |
| `02-log-format.md` | Log entry schema + ErrorCode taxonomy |
| `03-write-sdk.md` | Write SDK API design |
| `04-read-interface.md` | Read interfaces (MCP / CLI / SDK) |
| `05-storage.md` | Storage backends (JSONL / SQLite) |
| `06-implementation.md` | Implementation plan |
| `07-testing.md` | Testing strategy |

## License

MIT
