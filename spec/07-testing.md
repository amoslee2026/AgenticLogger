# 07 - 测试策略

## 1. 测试金字塔

```
           ┌─────────┐
           │  E2E    │  ← 少量 (MCP/CLI 集成)
           ├─────────┤
           │Integration│  ← 中量 (SDK + Storage)
           ├─────────┤
           │   Unit  │  ← 大量 (单函数)
           └─────────┘
```

| 层级 | 数量 | 覆盖率目标 | 工具 |
|------|------|-----------|------|
| Unit | 多 | 90% | pytest |
| Integration | 中 | 80% | pytest |
| E2E | 少 | 关键路径 | pytest + subprocess |

---

## 2. 单元测试

### 2.1 Python SDK 测试

**测试文件结构**:
```
tests/
├── unit/
│   ├── test_logger.py        # 核心日志方法
│   ├── test_jsonl_backend.py # JSONL 存储
│   ├── test_reader.py        # 读取器
│   └── test_analyzer.py      # 分析器
```

**示例测试**:
```python
# tests/unit/test_logger.py
import pytest
from agentic_logger import agent_log
from agentic_logger.storage import JSONLBackend

def test_info_basic(tmp_path):
    """测试 info 基本功能"""
    backend = JSONLBackend(log_dir=tmp_path)
    agent_log.configure(backend=backend)
    
    agent_log.info("Hello world", module="test")
    
    # 验证写入
    logs = backend.query()
    assert len(logs) == 1
    assert logs[0]['level'] == 'INFO'
    assert logs[0]['msg'] == 'Hello world'
    assert logs[0]['module'] == 'test'

def test_tool_call_all_fields(tmp_path):
    """测试 tool_call 所有字段"""
    backend = JSONLBackend(log_dir=tmp_path)
    agent_log.configure(backend=backend)
    
    agent_log.tool_call(
        tool="bash",
        command="npm install",
        exit_code=0,
        duration_ms=1234,
        stdout_summary="added 50 packages"
    )
    
    logs = backend.query()
    assert len(logs) == 1
    log = logs[0]
    assert log['level'] == 'TOOL'
    assert log['tool'] == 'bash'
    assert log['cmd'] == 'npm install'
    assert log['exit'] == 0
    assert log['dur_ms'] == 1234

def test_error_with_exception(tmp_path):
    """测试 error 捕获异常"""
    backend = JSONLBackend(log_dir=tmp_path)
    agent_log.configure(backend=backend)
    
    try:
        raise ValueError("test error")
    except Exception as e:
        agent_log.error("Operation failed", error=e)
    
    logs = backend.query()
    assert len(logs) == 1
    assert logs[0]['level'] == 'ERROR'
    assert 'ValueError' in logs[0]['error']

def test_timestamp_format(tmp_path):
    """测试时间戳格式"""
    backend = JSONLBackend(log_dir=tmp_path)
    agent_log.configure(backend=backend)
    
    agent_log.info("Test")
    
    logs = backend.query()
    ts = logs[0]['ts']
    
    # ISO 8601 格式
    assert 'T' in ts
    assert '+' in ts or 'Z' in ts

def test_context_fields(tmp_path):
    """测试上下文字段"""
    backend = JSONLBackend(log_dir=tmp_path)
    agent_log.configure(backend=backend)
    
    agent_log.info("Test", file="data.json", line=42, custom="value")
    
    logs = backend.query()
    log = logs[0]
    assert log['file'] == 'data.json'
    assert log['line'] == 42
    assert log['custom'] == 'value'
```

---

### 2.2 JSONL 后端测试

```python
# tests/unit/test_jsonl_backend.py
import pytest
from pathlib import Path
from agentic_logger.storage import JSONLBackend

def test_write_single_entry(tmp_path):
    """测试写入单条日志"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    entry = {"ts": "2026-07-21T11:30:00Z", "level": "INFO", "msg": "Test"}
    backend.write(entry)
    
    # 验证文件存在
    files = list(tmp_path.glob("agentic-*.jsonl"))
    assert len(files) == 1
    
    # 验证内容
    with open(files[0]) as f:
        line = f.readline()
        assert '"level": "INFO"' in line

def test_write_multiple_entries(tmp_path):
    """测试写入多条日志"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    for i in range(10):
        backend.write({"ts": f"2026-07-21T11:30:{i:02d}Z", "level": "INFO", "msg": f"Test {i}"})
    
    logs = backend.query()
    assert len(logs) == 10

def test_date_rotation(tmp_path):
    """测试日期轮转"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    # 模拟昨天
    backend.current_date = date(2026, 7, 20)
    backend.write({"ts": "2026-07-20T23:59:59Z", "level": "INFO", "msg": "Yesterday"})
    
    # 今天
    backend.write({"ts": "2026-07-21T00:00:00Z", "level": "INFO", "msg": "Today"})
    
    # 验证两个文件
    files = list(tmp_path.glob("agentic-*.jsonl"))
    assert len(files) == 2

def test_query_with_filter(tmp_path):
    """测试带过滤的查询"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    backend.write({"ts": "2026-07-21T11:30:00Z", "level": "INFO", "msg": "Info"})
    backend.write({"ts": "2026-07-21T11:30:01Z", "level": "ERROR", "msg": "Error"})
    backend.write({"ts": "2026-07-21T11:30:02Z", "level": "INFO", "msg": "Info 2"})
    
    logs = backend.query(level="ERROR")
    assert len(logs) == 1
    assert logs[0]['msg'] == 'Error'

def test_query_with_since(tmp_path):
    """测试时间过滤"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    backend.write({"ts": "2026-07-21T10:00:00Z", "level": "INFO", "msg": "Old"})
    backend.write({"ts": "2026-07-21T11:00:00Z", "level": "INFO", "msg": "New"})
    
    logs = backend.query(since="2026-07-21T10:30:00Z")
    assert len(logs) == 1
    assert logs[0]['msg'] == 'New'

def test_query_with_limit(tmp_path):
    """测试限制返回数量"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    for i in range(100):
        backend.write({"ts": f"2026-07-21T11:30:{i:02d}Z", "level": "INFO", "msg": f"Test {i}"})
    
    logs = backend.query(limit=10)
    assert len(logs) == 10
```

---

### 2.3 Node.js SDK 测试

```javascript
// tests/unit/logger.test.js
import { describe, it, expect } from 'vitest';
import { agentLog } from '../src/logger';
import { JSONLBackend } from '../src/storage';

describe('agentLog', () => {
  it('should write info log', async () => {
    const backend = new JSONLBackend({ logDir: './test-logs' });
    agentLog.configure({ backend });
    
    await agentLog.info('Hello world', { module: 'test' });
    
    const logs = await backend.query();
    expect(logs).toHaveLength(1);
    expect(logs[0].level).toBe('INFO');
    expect(logs[0].msg).toBe('Hello world');
  });
  
  it('should write tool_call log', async () => {
    const backend = new JSONLBackend({ logDir: './test-logs' });
    agentLog.configure({ backend });
    
    await agentLog.toolCall({
      tool: 'bash',
      command: 'ls',
      exitCode: 0,
      durationMs: 50
    });
    
    const logs = await backend.query();
    expect(logs[0].level).toBe('TOOL');
    expect(logs[0].tool).toBe('bash');
  });
});
```

---

## 3. 集成测试

### 3.1 SDK + Storage 集成

```python
# tests/integration/test_sdk_storage.py
import pytest
from agentic_logger import agent_log, configure
from agentic_logger.storage import JSONLBackend, SQLiteBackend

@pytest.fixture
def jsonl_backend(tmp_path):
    return JSONLBackend(log_dir=tmp_path)

@pytest.fixture
def sqlite_backend(tmp_path):
    return SQLiteBackend(db_path=tmp_path / "test.db")

def test_full_workflow_jsonl(jsonl_backend):
    """测试完整工作流 (JSONL)"""
    configure(backend=jsonl_backend)
    
    # 写入
    agent_log.info("Start")
    agent_log.tool_call(tool="bash", command="ls", exit_code=0)
    agent_log.error("Failed", error="Test error")
    
    # 查询
    all_logs = jsonl_backend.query()
    assert len(all_logs) == 3
    
    error_logs = jsonl_backend.query(level="ERROR")
    assert len(error_logs) == 1
    
    tool_logs = jsonl_backend.query(level="TOOL")
    assert len(tool_logs) == 1

def test_full_workflow_sqlite(sqlite_backend):
    """测试完整工作流 (SQLite)"""
    configure(backend=sqlite_backend)
    
    # 写入
    agent_log.info("Start")
    agent_log.tool_call(tool="bash", command="ls", exit_code=0)
    
    # 查询
    all_logs = sqlite_backend.query()
    assert len(all_logs) == 2
```

---

### 3.2 MCP Server 集成

```python
# tests/integration/test_mcp.py
import pytest
from mcp.testing import TestServer
from agentic_logger.mcp import create_server

@pytest.fixture
def mcp_server(tmp_path):
    server = create_server(log_dir=tmp_path)
    return TestServer(server)

def test_query_tool(mcp_server):
    """测试 query tool"""
    # 写入测试数据
    with open(mcp_server.log_dir / "agentic-2026-07-21.jsonl", 'w') as f:
        f.write('{"ts":"2026-07-21T11:30:00Z","level":"ERROR","msg":"Test"}\n')
    
    # 调用 tool
    result = mcp_server.call_tool("agentic_log_query", {"level": "ERROR"})
    
    assert result['count'] == 1
    assert result['logs'][0]['msg'] == 'Test'

def test_stats_tool(mcp_server):
    """测试 stats tool"""
    # 写入测试数据
    ...
    
    result = mcp_server.call_tool("agentic_log_stats", {"group_by": "level"})
    assert 'groups' in result
```

---

## 4. E2E 测试

### 4.1 CLI E2E

```python
# tests/e2e/test_cli.py
import subprocess
import pytest

def test_cli_tail(tmp_path):
    """测试 CLI tail 命令"""
    # 准备日志文件
    log_file = tmp_path / "agentic-2026-07-21.jsonl"
    log_file.write_text('{"ts":"2026-07-21T11:30:00Z","level":"INFO","msg":"Test"}\n')
    
    # 执行 CLI
    result = subprocess.run(
        ["agentic-logger", "tail", "-n", "1", "--log-dir", str(tmp_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0
    assert "Test" in result.stdout

def test_cli_query(tmp_path):
    """测试 CLI query 命令"""
    ...
```

---

### 4.2 REST API E2E

```python
# tests/e2e/test_api.py
import pytest
from fastapi.testclient import TestClient
from agentic_logger.api import app

@pytest.fixture
def client(tmp_path):
    app.state.log_dir = tmp_path
    return TestClient(app)

def test_query_endpoint(client, tmp_path):
    """测试 query endpoint"""
    # 准备数据
    ...
    
    # 调用 API
    response = client.get("/api/v1/logs?level=ERROR")
    
    assert response.status_code == 200
    data = response.json()
    assert 'logs' in data
```

---

## 5. 性能测试

### 5.1 写入性能

```python
# tests/performance/test_write_performance.py
import time
import pytest
from agentic_logger.storage import JSONLBackend

def test_jsonl_write_throughput(tmp_path):
    """测试 JSONL 写入吞吐量"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    entry = {"ts": "2026-07-21T11:30:00Z", "level": "INFO", "msg": "Test"}
    
    # 预热
    for _ in range(100):
        backend.write(entry)
    
    # 测试
    start = time.time()
    count = 10000
    for _ in range(count):
        backend.write(entry)
    elapsed = time.time() - start
    
    throughput = count / elapsed
    print(f"Throughput: {throughput:.0f} writes/sec")
    
    # 目标: > 1000 QPS
    assert throughput > 1000

def test_jsonl_write_latency(tmp_path):
    """测试 JSONL 写入延迟"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    entry = {"ts": "2026-07-21T11:30:00Z", "level": "INFO", "msg": "Test"}
    
    latencies = []
    for _ in range(1000):
        start = time.time()
        backend.write(entry)
        latency = (time.time() - start) * 1000  # ms
        latencies.append(latency)
    
    avg_latency = sum(latencies) / len(latencies)
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]
    
    print(f"Avg latency: {avg_latency:.2f}ms, P99: {p99_latency:.2f}ms")
    
    # 目标: avg < 1ms
    assert avg_latency < 1.0
```

---

### 5.2 查询性能

```python
# tests/performance/test_query_performance.py
import time
import pytest
from agentic_logger.storage import JSONLBackend

def test_query_large_file(tmp_path):
    """测试大文件查询性能"""
    backend = JSONLBackend(log_dir=tmp_path)
    
    # 准备 10000 条日志
    for i in range(10000):
        backend.write({
            "ts": f"2026-07-21T11:30:{i%60:02d}Z",
            "level": "INFO" if i % 10 != 0 else "ERROR",
            "msg": f"Test {i}"
        })
    
    # 测试查询
    start = time.time()
    logs = backend.query(level="ERROR", limit=100)
    elapsed = time.time() - start
    
    print(f"Query time: {elapsed*1000:.2f}ms")
    
    # 目标: < 1s
    assert elapsed < 1.0
```

---

## 6. 测试覆盖率

### 6.1 覆盖率目标

| 模块 | 目标 |
|------|------|
| Python SDK | 95% |
| JSONL Backend | 95% |
| SQLite Backend | 90% |
| MCP Server | 90% |
| CLI | 85% |
| REST API | 90% |
| **总计** | **90%+** |

### 6.2 覆盖率报告

```bash
# 生成覆盖率报告
pytest --cov=agentic_logger --cov-report=html

# 查看报告
open htmlcov/index.html
```

---

## 7. CI/CD 集成

### 7.1 GitHub Actions

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      
      - name: Run tests
        run: |
          pytest --cov=agentic_logger --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

---

## 8. 测试数据生成

### 8.1 Fixture

```python
# tests/fixtures.py
import pytest
from datetime import datetime, timedelta

@pytest.fixture
def sample_logs():
    """生成示例日志"""
    base_time = datetime(2026, 7, 21, 11, 30, 0)
    
    logs = []
    for i in range(100):
        ts = base_time + timedelta(seconds=i)
        logs.append({
            "ts": ts.isoformat(),
            "level": "INFO" if i % 10 != 0 else "ERROR",
            "msg": f"Test message {i}",
            "module": "test"
        })
    
    return logs
```

---

## 9. 测试检查清单

### 9.1 提交前检查

- [ ] 单元测试全部通过
- [ ] 集成测试全部通过
- [ ] 覆盖率 > 90%
- [ ] 无 lint 错误
- [ ] 文档已更新

### 9.2 发布前检查

- [ ] E2E 测试通过
- [ ] 性能测试达标
- [ ] 手动测试关键路径
- [ ] CHANGELOG 已更新
