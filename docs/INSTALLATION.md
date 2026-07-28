# Installation Guide

This guide covers all ways to install AgenticLogger, from quick pip install to full development setup.

## Table of Contents

- [Quick Start](#quick-start)
- [Installation Methods](#installation-methods)
  - [PyPI (Recommended)](#pypi-recommended)
  - [From Source](#from-source)
  - [uv (Fast Python Package Manager)](#uv-fast-python-package-manager)
- [Optional Dependencies](#optional-dependencies)
- [Verify Installation](#verify-installation)
- [Configuration](#configuration)
- [Integration Guide](#integration-guide)
  - [Claude Code Integration](#claude-code-integration)
  - [MCP Server Setup](#mcp-server-setup)
  - [Python Project Integration](#python-project-integration)
- [Deployment Scenarios](#deployment-scenarios)
  - [Development Environment](#development-environment)
  - [Production Environment](#production-environment)
  - [CI/CD Pipeline](#cicd-pipeline)
  - [Multi-User Shared Installation](#multi-user-shared-installation)
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

# With all optional dependencies
pip install "agentic-logger[all]"
```

**System-wide vs user installation:**

```bash
# User installation (recommended, no sudo needed)
pip install --user agentic-logger

# System-wide (requires sudo)
sudo pip install agentic-logger

# Virtual environment (isolated, best practice)
python -m venv .venv
source .venv/bin/activate
pip install agentic-logger
```

### From Source

Clone the repository and install in editable mode:

```bash
git clone https://github.com/your-org/AgenticLogger.git
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
| All | `pip install "agentic-logger[all]"` | All optional dependencies |

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
from agentic_logger.storage import JSONLStorage

# Custom storage configuration
storage = JSONLStorage(
    log_dir="/var/log/myapp",
    circular=True,
    max_size_mb=100,
    max_files=10,
)

logger = AgentLogger(
    program="my_app",
    command="run",
    storage=storage,
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

# With custom port (for HTTP transport, if supported)
agentic-logger-mcp --log-dir ./logs --port 8080
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

[project.optional-dependencies]
mcp = ["agentic-logger[mcp]"]
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

#### 3. Integration with Popular Frameworks

**FastAPI:**

```python
from fastapi import FastAPI
from agentic_logger import AgentLogger

app = FastAPI()
logger = AgentLogger(program="fastapi_app", command="server")

@app.on_event("startup")
async def startup():
    logger.info("FastAPI app started", module="app.main")

@app.get("/api/users")
async def get_users():
    logger.info("Fetching users", module="api.users")
    # Your logic
    return {"users": []}
```

**Flask:**

```python
from flask import Flask
from agentic_logger import AgentLogger

app = Flask(__name__)
logger = AgentLogger(program="flask_app", command="server")

@app.before_request
def log_request():
    logger.info("Request received", module="app", ctx={"path": request.path})
```

**CLI Applications:**

```python
import click
from agentic_logger import AgentLogger

@click.command()
def main():
    logger = AgentLogger(program="cli_app", command="main")
    logger.info("CLI started", module="cli")
    # Your logic

if __name__ == "__main__":
    main()
```

---

## Deployment Scenarios

### Development Environment

**Recommended setup:**

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install "agentic-logger[dev,mcp]"

# Or with uv
uv sync --extra dev --extra mcp
```

**Configuration:**

```bash
# Use JSONL for easy debugging
export AGENTIC_STORAGE=jsonl
export AGENTIC_LOG_DIR=./logs/dev
```

### Production Environment

**Recommended setup:**

```bash
# Install specific version for reproducibility
pip install agentic-logger==0.1.0

# Use SQLite for better query performance
export AGENTIC_STORAGE=sqlite
export AGENTIC_LOG_DIR=/var/log/myapp

# Enable circular mode to bound disk usage
```

**Systemd Service (Linux):**

Create `/etc/systemd/system/myapp.service`:

```ini
[Unit]
Description=My Application with AgenticLogger
After=network.target

[Service]
Type=simple
User=myapp
WorkingDirectory=/opt/myapp
Environment=AGENTIC_LOG_DIR=/var/log/myapp
Environment=AGENTIC_STORAGE=sqlite
ExecStart=/opt/myapp/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Docker:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install AgenticLogger
RUN pip install --no-cache-dir agentic-logger[mcp]

# Copy application
COPY . .

# Set log directory
ENV AGENTIC_LOG_DIR=/var/log/app
ENV AGENTIC_STORAGE=sqlite

# Create log directory
RUN mkdir -p /var/log/app

CMD ["python", "main.py"]
```

### CI/CD Pipeline

**GitHub Actions:**

```yaml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      
      - name: Run tests
        run: pytest tests/ -v --cov=agentic_logger
      
      - name: Upload logs on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: test-logs
          path: logs/
```

**GitLab CI:**

```yaml
test:
  image: python:3.11
  script:
    - pip install -e ".[dev]"
    - pytest tests/ -v --cov=agentic_logger
  artifacts:
    when: on_failure
    paths:
      - logs/
```

### Multi-User Shared Installation

For shared systems where multiple users need access:

```bash
# System-wide installation
sudo pip install agentic-logger

# Or install to shared location
sudo pip install --prefix=/opt/agentic-logger agentic-logger

# Users can then import it
python -c "from agentic_logger import AgentLogger"
```

**Per-user log directories:**

```python
import os
from pathlib import Path
from agentic_logger import AgentLogger

# Each user gets their own log directory
user_log_dir = Path.home() / ".local" / "share" / "myapp" / "logs"
user_log_dir.mkdir(parents=True, exist_ok=True)

logger = AgentLogger(
    program="my_app",
    command="run",
    storage=JSONLStorage(log_dir=str(user_log_dir)),
)
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

# Check for port conflicts
netstat -tulpn | grep 8080
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

# Remove all optional dependencies
pip uninstall agentic-logger mcp

# Clean up log files (optional)
rm -rf ./logs
```

---

## Next Steps

- [Quick Start Guide](../README.md#quick-start)
- [User Guide](../README.md#user-guide)
- [Architecture Overview](../spec/01-architecture.md)
- [API Reference](../spec/03-write-sdk.md)

---

## Support

- **Documentation:** [README.md](../README.md)
- **Issues:** [GitHub Issues](https://github.com/your-org/AgenticLogger/issues)
- **Discussions:** [GitHub Discussions](https://github.com/your-org/AgenticLogger/discussions)
