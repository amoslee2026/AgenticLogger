# Installation Guide (for Coding Agents)

Audience: coding agents installing and verifying AgenticLogger. Execute steps in order; check each expected result before continuing. Human-facing overview: [README](../README.md).

## Hard constraints

- NEVER `sudo pip` — PEP 668 blocks it and it pollutes system Python. Use an isolated env (venv / uv) or the host project's existing env.
- Python >= 3.10.
- The MCP server speaks **stdio only** — no ports, no network config needed.

## 1. Install

Default (PyPI):

```bash
pip install agentic-logger
```

With MCP server (log query tools for agents):

```bash
pip install "agentic-logger[mcp]"
```

uv equivalent:

```bash
uv pip install agentic-logger        # into the active env
uvx agentic-logger --version         # run without installing
```

From source (development of AgenticLogger itself):

```bash
git clone https://github.com/amoslee2026/AgenticLogger.git
cd AgenticLogger
uv sync --extra dev --extra mcp      # editable install + pytest/ruff + mcp extra
```

## 2. Verify

| Check | Command | Expected |
|---|---|---|
| CLI entry point | `agentic-logger --version` | prints `agentic-logger 0.1.x`, exit 0 |
| Python import | `python -c "from agentic_logger import AgentLogger, ErrorCode"` | silent, exit 0 |
| MCP binary | `agentic-logger-mcp --log-dir ./logs < /dev/null` | exits 0, no traceback |

## 3. Smoke test (write + read back)

```python
from agentic_logger import AgentLogger

logger = AgentLogger(program="smoke", command="verify")
logger.info("installation verified")
```

Read back via CLI:

```bash
agentic-logger list-files                    # expect logs/smoke_verify_*.jsonl
agentic-logger query --depth summary         # expect one INFO entry: "installation verified"
```

## 4. Wire up the MCP server (agent log access)

Add to the MCP config of the agent host (e.g. Claude Code `mcp.json`):

```json
{
  "mcpServers": {
    "agentic-logger": {
      "command": "agentic-logger-mcp",
      "args": ["--log-dir", "/absolute/path/to/logs"]
    }
  }
}
```

Tools exposed: `agentic_log_query` (filtered search), `agentic_log_trace` (full chain by `rid`), `agentic_log_stats` (aggregations), `agentic_log_traceback` (stack trace by `tid`).

## 5. Configuration

Environment variables (all optional):

| Variable | Values | Effect |
|---|---|---|
| `AGENTIC_LOG_DIR` | path | Default log directory (default `./logs`) |
| `AGENTIC_STORAGE` | `jsonl` / `sqlite` / `auto` | Force storage backend (default `auto`: sqlite for build/test/ci, else jsonl) |
| `AGENTIC_SELF_LOG` | `0` disables | AgenticLogger's own CLI/MCP calls logged into the same dir (`program=agentic_logger`) |

Programmatic:

```python
from agentic_logger import AgentLogger

logger = AgentLogger(
    program="my_app",
    command="run",
    log_dir="/var/log/myapp",
    storage="jsonl",   # or "sqlite" / "auto"
    circular=True,     # rotate instead of growing unbounded
    max_size_mb=100,
    max_files=10,
)
```

## 6. Error signatures → fixes

| Signature | Cause | Fix |
|---|---|---|
| `externally-managed-environment` | PEP 668 system Python | Create a venv or use `uv pip`. Do NOT use `--break-system-packages`. |
| `ModuleNotFoundError: agentic_logger` | Installed into a different env | `which python` + `pip show agentic-logger` must agree; install into the active env. |
| `command not found: agentic-logger` | venv not activated / scripts dir off PATH | Activate the venv, or invoke `.venv/bin/agentic-logger` directly. |
| `ImportError: mcp` on `agentic-logger-mcp` | MCP extra missing | `pip install "agentic-logger[mcp]"`. |
| No log files created | `log_dir` unwritable | Check `os.access(log_dir, os.W_OK)`; pass `log_dir=` explicitly. |
| `agentic-logger: error: the following arguments are required: command` | Called without a subcommand | Use a subcommand: `query` / `trace` / `stats` / `tail` / `traceback` / `list-files`; `--version` and `--help` work standalone. |
| `unrecognized arguments: --log-dir ...` | `--log-dir` is a global option, must precede the subcommand | `agentic-logger --log-dir ./logs query ...` |

## 7. Python project integration

```toml
[project]
dependencies = [
    "agentic-logger>=0.1.0",
]
```

```python
from agentic_logger import AgentLogger, ErrorCode

logger = AgentLogger(program="my_app", command="main")
logger.info("started", module="app.main")
logger.tool_call("bash", "pytest -q", exit=0, dur=5200)
try:
    ...
except Exception:
    logger.exception("pipeline failed", ErrorCode.UNKNOWN)
    raise
```

## 8. Uninstall

```bash
pip uninstall agentic-logger
rm -rf ./logs   # optional
```

## Support

Issues: <https://github.com/amoslee2026/AgenticLogger/issues>
