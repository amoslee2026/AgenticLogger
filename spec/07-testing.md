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

### 2.1 SDK 核心测试

**测试文件结构**:
```
tests/
├── unit/
│   ├── test_logger.py          # AgentLogger 核心
│   ├── test_fields.py          # 字段自动填充 (ts/pid/rid)
│   ├── test_filename.py        # 文件命名
│   ├── test_api_basic.py       # info/warn/error
│   ├── test_api_tool.py        # tool_call
│   ├── test_api_file.py        # file_op
│   ├── test_api_decision.py    # decision/code_gen/context_switch
│   ├── test_api_traceback.py   # save_traceback
│   ├── test_api_context.py     # set_global_context
│   └── test_api_lifecycle.py   # run_start/run_end
```

**示例测试**:

```python
# tests/unit/test_fields.py
import pytest
from agentic_logger.core.fields import AutoFields

def test_auto_fill_ts():
    """ts 自动填充"""
    fields = AutoFields()
    entry = fields.fill({})
    assert 'ts' in entry
    assert 'T' in entry['ts']  # ISO 8601

def test_auto_fill_pid():
    """pid 自动填充"""
    import os
    fields = AutoFields()
    entry = fields.fill({})
    assert entry['pid'] == str(os.getpid())

def test_auto_fill_rid():
    """rid 初始化时生成，不覆盖"""
    fields = AutoFields(rid="test_rid_001")
    entry = fields.fill({})
    assert entry['rid'] == "test_rid_001"

def test_error_code_required_for_error():
    """error 方法必须提供 error_code"""
    from agentic_logger import AgentLogger
    logger = AgentLogger(program="test")
    with pytest.raises(ValueError, match="error_code is required"):
        logger.error("Failed", module="test")  # 缺少 error_code
```

---

```python
# tests/unit/test_filename.py
import pytest
from agentic_logger.core.filename import generate_filename
from pathlib import Path

def test_filename_format(tmp_path):
    """文件命名格式"""
    filename = generate_filename(
        program="my_agent",
        command="main",
        log_dir=tmp_path,
        storage="jsonl"
    )
    # 格式: {program}_{command}_{date}_{time}.jsonl
    assert "my_agent_main_" in filename.name
    assert filename.suffix == ".jsonl"
    assert len(filename.name.split("_")) >= 4  # program, command, date, time

def test_filename_with_pid(tmp_path):
    """command 未设置时使用 pid"""
    filename = generate_filename(
        program="my_agent",
        command=None,
        log_dir=tmp_path,
        storage="jsonl"
    )
    assert "pid" in filename.name

def test_filename_special_chars(tmp_path):
    """特殊字符替换"""
    filename = generate_filename(
        program="my agent!",
        command="npm install",
        log_dir=tmp_path,
        storage="jsonl"
    )
    assert " " not in filename.name
    assert "!" not in filename.name
```

---

```python
# tests/unit/test_api_tool.py
import pytest
from agentic_logger import AgentLogger

def test_tool_call_all_fields(tmp_path):
    """tool_call 所有字段"""
    logger = AgentLogger(program="test", command="tool", log_dir=tmp_path)
    logger.tool_call(
        tool="bash",
        cmd="npm install",
        exit=0,
        dur=1234,
        stdout="added 50 packages",
        stderr=""
    )
    
    # 读取验证
    from agentic_logger import LogQueryEngine
    engine = LogQueryEngine(log_dir=tmp_path)
    logs = engine.query(tool="bash")
    assert len(logs) == 1
    log = logs[0]
    assert log['level'] == 'TOOL'
    assert log['tool'] == 'bash'
    assert log['cmd'] == 'npm install'
    assert log['exit_code'] == 0
    assert log['dur'] == 1234
    assert log['rid'] is not None
    assert log['pid'] is not None

def test_tool_call_with_error_code(tmp_path):
    """tool_call 失败时带 error_code"""
    logger = AgentLogger(program="test", command="tool", log_dir=tmp_path)
    logger.tool_call(
        tool="bash",
        cmd="npm run build",
        exit=1,
        dur=5000,
        error_code="BUILD_FAIL",
        stderr="Error: Module not found"
    )
    
    from agentic_logger import LogQueryEngine
    engine = LogQueryEngine(log_dir=tmp_path)
    logs = engine.query(error_code="BUILD_FAIL")
    assert len(logs) == 1
```

---

### 2.2 JSONL 后端测试

```python
# tests/unit/test_jsonl_backend.py
import pytest
from agentic_logger.storage.jsonl import JSONLBackend

def test_write_and_read(tmp_path):
    """写入并读取"""
    backend = JSONLBackend(file_path=tmp_path / "test.jsonl")
    backend.write({"ts": "...", "level": "INFO", "msg": "Test", "module": "test", "rid": "r1", "pid": "1"})
    
    logs = backend.query()
    assert len(logs) == 1

def test_global_context_written(tmp_path):
    """全局上下文写入文件头部"""
    backend = JSONLBackend(file_path=tmp_path / "test.jsonl", program="test", command="main")
    backend.write({"ts": "...", "level": "INFO", "msg": "Test", "module": "test", "rid": "r1", "pid": "1"})
    
    # 第一行应该是全局上下文
    with open(tmp_path / "test.jsonl") as f:
        first_line = f.readline()
        entry = json.loads(first_line)
        assert entry['level'] == '__GLOBAL_CTX__'
        assert entry['program'] == 'test'

def test_traceback_separate_storage(tmp_path):
    """堆栈跟踪分离存储"""
    backend = JSONLBackend(file_path=tmp_path / "test.jsonl")
    backend.save_traceback("trace_001", "Traceback...", "ValueError", "msg")
    
    tb = backend.get_traceback("trace_001")
    assert tb is not None
    assert tb['exception_type'] == 'ValueError'
```

---

### 2.3 SQLite 后端测试

```python
# tests/unit/test_sqlite_backend.py
import pytest
from agentic_logger.storage.sqlite import SQLiteBackend

def test_wal_mode_enabled(tmp_path):
    """WAL 模式开启"""
    backend = SQLiteBackend(file_path=tmp_path / "test.sqlite", wal_mode=True)
    result = backend.conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == 'wal'

def test_indexes_created(tmp_path):
    """索引已创建"""
    backend = SQLiteBackend(file_path=tmp_path / "test.sqlite")
    indexes = backend.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    index_names = [i[0] for i in indexes]
    assert 'idx_logs_rid' in index_names
    assert 'idx_logs_level' in index_names
    assert 'idx_logs_error_code' in index_names

def test_query_by_rid(tmp_path):
    """按 rid 查询"""
    backend = SQLiteBackend(file_path=tmp_path / "test.sqlite")
    backend.write({"ts": "...", "level": "INFO", "msg": "Test1", "module": "m", "rid": "r1", "pid": "1"})
    backend.write({"ts": "...", "level": "ERROR", "msg": "Test2", "module": "m", "rid": "r2", "pid": "1"})
    
    logs = backend.query(rid="r1")
    assert len(logs) == 1
    assert logs[0]['msg'] == 'Test1'

def test_query_by_error_code(tmp_path):
    """按 error_code 查询"""
    backend = SQLiteBackend(file_path=tmp_path / "test.sqlite")
    backend.write({"ts": "...", "level": "ERROR", "msg": "E1", "module": "m", "rid": "r1", "pid": "1", "error_code": "BUILD_FAIL"})
    backend.write({"ts": "...", "level": "ERROR", "msg": "E2", "module": "m", "rid": "r1", "pid": "1", "error_code": "PARSE_JSON"})
    
    logs = backend.query(error_code="BUILD_FAIL")
    assert len(logs) == 1

def test_query_by_dur_range(tmp_path):
    """按耗时范围查询"""
    backend = SQLiteBackend(file_path=tmp_path / "test.sqlite")
    backend.write({"ts": "...", "level": "INFO", "msg": "Fast", "module": "m", "rid": "r1", "pid": "1", "dur": 100})
    backend.write({"ts": "...", "level": "INFO", "msg": "Slow", "module": "m", "rid": "r1", "pid": "1", "dur": 5000})
    
    logs = backend.query(min_dur=1000)
    assert len(logs) == 1
    assert logs[0]['msg'] == 'Slow'

def test_multiprocess_concurrent(tmp_path):
    """多进程并发写入"""
    import multiprocessing
    
    def writer(file_path, worker_id):
        backend = SQLiteBackend(file_path=file_path, wal_mode=True)
        for i in range(100):
            backend.write({"ts": "...", "level": "INFO", "msg": f"W{worker_id}_{i}", "module": "m", "rid": "r1", "pid": str(worker_id)})
    
    file_path = tmp_path / "concurrent.sqlite"
    processes = [multiprocessing.Process(target=writer, args=(file_path, i)) for i in range(4)]
    for p in processes: p.start()
    for p in processes: p.join()
    
    backend = SQLiteBackend(file_path=file_path)
    logs = backend.query()
    assert len(logs) == 400  # 4 workers x 100 entries
```

---

### 2.4 查询引擎测试

```python
# tests/unit/test_query_engine.py
import pytest
from agentic_logger import LogQueryEngine

def test_query_all_fields(tmp_path):
    """查询支持所有字段"""
    engine = LogQueryEngine(log_dir=tmp_path)
    # 准备数据
    _setup_test_data(tmp_path)
    
    # 按各字段查询
    assert len(engine.query(rid="r1")) > 0
    assert len(engine.query(level="ERROR")) > 0
    assert len(engine.query(module="agent.bash")) > 0
    assert len(engine.query(error_code="BUILD_FAIL")) > 0
    assert len(engine.query(tool="bash")) > 0
    assert len(engine.query(exit_code=1)) > 0
    assert len(engine.query(min_dur=1000)) > 0
    assert len(engine.query(pid="12345")) > 0

def test_query_wildcard_module(tmp_path):
    """模块通配符查询"""
    engine = LogQueryEngine(log_dir=tmp_path)
    _setup_test_data(tmp_path)
    
    logs = engine.query(module="agent.*")
    assert all(log['module'].startswith('agent.') for log in logs)

def test_query_order_by(tmp_path):
    """排序"""
    engine = LogQueryEngine(log_dir=tmp_path)
    _setup_test_data(tmp_path)
    
    logs_desc = engine.query(order_by="dur_desc")
    for i in range(len(logs_desc) - 1):
        assert (logs_desc[i].get('dur') or 0) >= (logs_desc[i+1].get('dur') or 0)

def test_query_pagination(tmp_path):
    """分页"""
    engine = LogQueryEngine(log_dir=tmp_path)
    _setup_test_data(tmp_path, count=100)
    
    page1 = engine.query(limit=20, offset=0)
    page2 = engine.query(limit=20, offset=20)
    assert len(page1) == 20
    assert len(page2) == 20
    assert page1[0]['ts'] != page2[0]['ts']

def test_trace_by_rid(tmp_path):
    """链路追踪"""
    engine = LogQueryEngine(log_dir=tmp_path)
    _setup_test_data(tmp_path)
    
    trace = engine.trace(rid="r1")
    assert trace['rid'] == "r1"
    assert len(trace['trace']) > 0
    # 按时间排序
    for i in range(len(trace['trace']) - 1):
        assert trace['trace'][i]['ts'] <= trace['trace'][i+1]['ts']

def test_stats_group_by(tmp_path):
    """统计分析"""
    engine = LogQueryEngine(log_dir=tmp_path)
    _setup_test_data(tmp_path)
    
    stats = engine.stats(group_by="level")
    assert 'groups' in stats
    assert stats['total'] > 0

def test_analyze_errors(tmp_path):
    """错误分析"""
    engine = LogQueryEngine(log_dir=tmp_path)
    _setup_test_data(tmp_path)
    
    analysis = engine.analyze(focus="errors")
    assert 'error_code_distribution' in analysis
    assert 'recommendations' in analysis
```

---

## 3. 集成测试

```python
# tests/integration/test_full_workflow.py
import pytest
from agentic_logger import AgentLogger, LogQueryEngine

def test_full_workflow(tmp_path):
    """完整工作流: 写入 → 查询 → 分析"""
    # 1. 写入
    logger = AgentLogger(program="test", command="integration", log_dir=tmp_path)
    logger.run_start(msg="Test started")
    
    logger.info("Processing", module="parser", ctx={"file": "data.json"})
    logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
    logger.file_op("write", "/test.txt", ok=True, size=100)
    logger.decision(choice="async", alts=["sync"], reason="IO-bound", module="arch")
    
    try:
        raise ValueError("test error")
    except Exception as e:
        tid = logger.save_traceback(e)
        logger.error("Failed", module="executor", error_code="EXEC_TEST", tid=tid)
    
    logger.run_end(msg="Test finished", exit_code=1, dur=1000)
    
    # 2. 查询
    engine = LogQueryEngine(log_dir=tmp_path)
    
    all_logs = engine.query()
    assert len(all_logs) >= 7  # run_start + 5 + run_end
    
    errors = engine.query(level="ERROR")
    assert len(errors) == 1
    assert errors[0]['error_code'] == 'EXEC_TEST'
    
    # 3. 链路追踪
    trace = engine.trace(rid=logger.rid)
    assert trace['entry_count'] >= 7
    
    # 4. 堆栈跟踪
    tb = engine.traceback(tid=tid)
    assert tb is not None
    assert 'ValueError' in tb['traceback']
    
    # 5. 统计
    stats = engine.stats(group_by="level")
    assert stats['total'] >= 7
```

---

## 4. 性能测试

```python
# tests/performance/test_write_performance.py
import time
import pytest

def test_jsonl_write_throughput(tmp_path):
    """JSONL 写入吞吐量"""
    from agentic_logger import AgentLogger
    logger = AgentLogger(program="perf", command="jsonl", log_dir=tmp_path, storage="jsonl")
    
    start = time.time()
    count = 10000
    for i in range(count):
        logger.info(f"Test {i}", module="perf")
    elapsed = time.time() - start
    
    throughput = count / elapsed
    assert throughput > 1000  # > 1000 QPS

def test_sqlite_write_throughput(tmp_path):
    """SQLite WAL 写入吞吐量"""
    from agentic_logger import AgentLogger
    logger = AgentLogger(program="perf", command="sqlite", log_dir=tmp_path, storage="sqlite")
    
    start = time.time()
    count = 10000
    for i in range(count):
        logger.info(f"Test {i}", module="perf")
    elapsed = time.time() - start
    
    throughput = count / elapsed
    assert throughput > 500  # > 500 QPS

def test_query_performance(tmp_path):
    """查询性能"""
    from agentic_logger import AgentLogger, LogQueryEngine
    logger = AgentLogger(program="perf", command="query", log_dir=tmp_path, storage="sqlite")
    
    # 准备 10000 条数据
    for i in range(10000):
        level = "ERROR" if i % 10 == 0 else "INFO"
        logger.info(f"Test {i}", module="perf", level=level, dur=i*10)
    
    engine = LogQueryEngine(log_dir=tmp_path)
    
    start = time.time()
    logs = engine.query(level="ERROR", min_dur=50000, limit=100)
    elapsed = time.time() - start
    
    assert elapsed < 1.0  # < 1s
```

---

## 5. 测试检查清单

### 5.1 提交前

- [ ] 单元测试全部通过
- [ ] 集成测试全部通过
- [ ] 覆盖率 > 90%
- [ ] 无 lint 错误

### 5.2 发布前

- [ ] E2E 测试通过
- [ ] 性能测试达标
- [ ] 多进程并发测试通过
- [ ] 循环写入测试通过
- [ ] 手动测试关键路径
