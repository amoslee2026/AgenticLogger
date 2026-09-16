# Installation Guide

This guide covers all ways to install AgenticLogger, from quick pip install to full development setup.

- [Quick Start](#quick-start)
- [Installation Methods](#installation-methods)
- [Optional Dependencies](#optional-dependencies)
- [Verify Installation](#verify-installation)
- [Configuration](#configuration)
- [Integration Guide](#integration-guide)
  - [Claude Code Integration](#claude-code-integration)
  - [MCP Server Setup](#mcp-server-setup)
  - [Python Project Integration](#python-project-integration)
- [Troubleshooting](#troubleshooting)
- [Uninstallation](#uninstallation)

---

## Quick Start

For most users, a single command is enough:

```bash
pip install agentic-logger
```

Then start logging:

```python
from agentic_logger import AgentLogger

logger = AgentLogger(program="my_app", command="run")
logger.info("Hello, AgenticLogger!")
```

---

## Installation Methods

### PyPI (Recommended)

Install from PyPI for stable releases:

```bash
# Basic installation
pip install agentic-logger

# With MCP server support
pip install "agentic-logger[mcp]"
```

Prefer an isolated environment (PEP 668 blocks system-wide installs on most modern distros):

```bash
python -m venv .venv && source .venv/bin/activate
pip install agentic-logger
```

### From Source

Clone the repository and install in editable mode:

```bash
git clone https://github.com/amoslee2026/AgenticLogger.git
cd AgenticLogger

# Install with uv (recommended)
uv sync --extra dev --extra mcp

# Or with pip
pip install -e ".[dev,mcp]"
```

**Verify the installation:**

```bash
# CLI should be available
agentic-logger --version

# Python import should work
python -c "from agentic_logger import AgentLogger; print('OK')"
```

### uv (Fast Python Package Manager)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install AgenticLogger
uv pip install agentic-logger

# Or use uvx to run without installing
uvx agentic-logger --help
```

---

## Optional Dependencies

AgenticLogger has minimal core dependencies. Optional features require additional packages:

| Feature | Installation | Description |
|---------|-------------|-------------|
| MCP Server | `pip install "agentic-logger[mcp]"` | Enables MCP protocol support for AI agent integration |
| Development | `pip install "agentic-logger[dev]"` | pytest, ruff, and other dev tools |

**Note:** The MCP extra is required if you want to use AgenticLogger as an MCP server for Claude Code or other AI agents.

---

## Verify Installation

After installation, verify everything works:

### 1. Check CLI Availability

```bash
# Should print help message
agentic-logger --help

# Check version
agentic-logger --version
```

### 2. Check Python Import

```bash
python -c "from agentic_logger import AgentLogger, ErrorCode; print('Import OK')"
```

### 3. Test Basic Logging

```python
from agentic_logger import AgentLogger

logger = AgentLogger(program="test", command="verify")
logger.info("Installation verified successfully")
```

Expected output: A JSONL log file created in `./logs/test_verify_*.jsonl`

### 4. Test MCP Server (if installed with MCP extra)

```bash
# Should start MCP server (press Ctrl+C to exit)
agentic-logger-mcp --help
```

### 5. Run Self-Test (development installation)

```bash
# If installed from source with dev dependencies
pytest tests/ -v
```

---

## Configuration

AgenticLogger works out of the box with sensible defaults. Configuration is optional.

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `AGENTIC_LOG_DIR` | Default log directory | `./logs` | `/var/log/myapp` |
| `AGENTIC_STORAGE` | Force storage backend | `auto` | `jsonl`, `sqlite`, `auto` |
| `AGENTIC_SELF_LOG` | Enable self-observability | `1` | `0` to disable |

**Example:**

```bash
export AGENTIC_LOG_DIR=/var/log/myapp
export AGENTIC_STORAGE=sqlite
```

### Programmatic Configuration

```python
from agentic_logger import AgentLogger

logger = AgentLogger(
    program="my_app",
    command="run",
    log_dir="/var/log/myapp",
    storage="jsonl",   # or "sqlite" / "auto"
    circular=True,
    max_size_mb=100,
    max_files=10,
)
```

---

## Integration Guide

### Claude Code Integration

AgenticLogger integrates with Claude Code via MCP (Model Context Protocol).

#### 1. Install with MCP Support

```bash
pip install "agentic-logger[mcp]"
```

#### 2. Configure Claude Code

Add to your Claude Code MCP configuration (e.g., `~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "agentic-logger": {
      "command": "agentic-logger-mcp",
      "args": ["--log-dir", "/path/to/your/logs"]
    }
  }
}
```

#### 3. Use in Claude Code

Claude can now query your logs:

```
# Example Claude commands
"查询最近1小时的错误日志"
"追踪 rid=abc12345 的完整执行链路"
"统计过去24小时的错误分布"
```

### MCP Server Setup

For standalone MCP server usage:

```bash
# Start MCP server (stdio transport)
agentic-logger-mcp --log-dir ./logs
```

**Available MCP Tools:**

| Tool | Description |
|------|-------------|
| `agentic_log_query` | Multi-field filtered search |
| `agentic_log_trace` | Full trace by `rid` |
| `agentic_log_stats` | Aggregated statistics |
| `agentic_log_traceback` | Stack trace by `tid` |

### Python Project Integration

#### 1. Add to Project Dependencies

**pyproject.toml:**

```toml
[project]
dependencies = [
    "agentic-logger>=0.1.0",
]
```

**requirements.txt:**

```
agentic-logger>=0.1.0
agentic-logger[mcp]>=0.1.0  # With MCP support
```

#### 2. Basic Integration

```python
from agentic_logger import AgentLogger, ErrorCode

# Initialize logger at application start
logger = AgentLogger(
    program="my_app",
    command="main",
    circular=True,  # Enable circular mode for long-running apps
    max_size_mb=500,
)

# Use throughout your application
def process_data():
    logger.info("Processing started", module="data.processor")
    try:
        # Your logic here
        logger.tool_call("bash", "curl https://api.example.com", exit=0, dur=1500)
    except Exception as e:
        logger.exception("Processing failed", ErrorCode.UNKNOWN)
        raise
```


---

## Troubleshooting

### Installation Issues

**Problem:** `Command not found: agentic-logger`

**Solution:**
```bash
# Check if installed
pip show agentic-logger

# Reinstall
pip install --force-reinstall agentic-logger

# Check PATH
echo $PATH
which agentic-logger
```

**Problem:** `ImportError: No module named 'agentic_logger'`

**Solution:**
```bash
# Check Python environment
which python
python -m pip list | grep agentic

# Reinstall in correct environment
python -m pip install agentic-logger
```

**Problem:** `Permission denied` during installation

**Solution:**
```bash
# Use --user flag
pip install --user agentic-logger

# Or use virtual environment
python -m venv .venv
source .venv/bin/activate
pip install agentic-logger
```

### Runtime Issues

**Problem:** Log files not created

**Solution:**
```python
# Check log directory permissions
import os
log_dir = "./logs"
print(f"Log dir exists: {os.path.exists(log_dir)}")
print(f"Log dir writable: {os.access(log_dir, os.W_OK)}")

# Create directory if needed
from pathlib import Path
Path(log_dir).mkdir(parents=True, exist_ok=True)
```

**Problem:** MCP server fails to start

**Solution:**
```bash
# Check if MCP extra installed
pip show agentic-logger | grep Requires

# Reinstall with MCP extra
pip install --force-reinstall "agentic-logger[mcp]"

# stdio transport — no network ports involved; verify the binary starts:
agentic-logger-mcp --log-dir ./logs < /dev/null && echo "mcp binary OK"
```

### Performance Issues

**Problem:** Slow query performance

**Solution:**
```python
# Use SQLite backend for indexed queries
from agentic_logger import AgentLogger

logger = AgentLogger(
    program="my_app",
    storage="sqlite",  # Better for large datasets
)
```

**Problem:** Log files too large

**Solution:**
```python
# Enable circular mode
logger = AgentLogger(
    program="my_app",
    circular=True,
    max_size_mb=100,  # Rotate at 100MB
    max_files=5,       # Keep last 5 files
)
```

---

## Uninstallation

```bash
# Basic uninstall
pip uninstall agentic-logger

# Clean up log files (optional)
rm -rf ./logs
```

---

## Next Steps

- [Quick Start Guide](../README.md#quick-start)
- [User Guide](../README.md#user-guide)

---

## Support

- **Documentation:** [README.md](../README.md)
- **Issues:** [GitHub Issues](https://github.com/amoslee2026/AgenticLogger/issues)
