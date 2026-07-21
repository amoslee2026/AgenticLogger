# 03 - 写入 SDK API 设计

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **Agent 优先** | API 设计面向 Coding Agent 调用，非人类手动编写 |
| **信息丰富** | 每条日志包含 rid/tid/pid/dur/ErrorCode 等丰富字段 |
| **独立命名空间** | `agentic_logger`，不与标准 `logging` 混淆 |
| **语义化方法** | 方法名清晰表达意图 (`tool_call`, `file_op`, `decision`) |
| **MVP Python** | Python SDK 先行，API 设计考虑后续多语言一致性 |

---

## 2. Python SDK

### 2.1 安装

```bash
pip install agentic-logger
```

### 2.2 导入与初始化

```python
from agentic_logger import AgentLogger

# 每次运行创建独立的 logger 实例
logger = AgentLogger(
    program="my_agent",           # 程序名 (用于文件名)
    command="main",               # 子命令 (用于文件名)
    log_dir="./logs",             # 日志目录
    storage="auto",               # "jsonl" | "sqlite" | "auto"
    max_size_mb=500,              # 大文件循环写入阈值
    circular=True,                # 启用循环写入
    retention_count=100000,       # 循环写入保留条数
)
```

**初始化时自动生成**:
- `rid`: 本次运行的唯一 ID (UUID4)
- `pid`: 进程 ID
- 日志文件名: `{program}_{command}_{YYYY-MM-DD}_{HHmmss}.jsonl`

---

### 2.3 核心方法

所有方法共享以下**自动填充字段**（开发者无需手动传递）：

| 字段 | 自动填充 | 说明 |
|------|---------|------|
| `ts` | ✅ | 当前时间戳 (毫秒精度) |
| `pid` | ✅ | 进程 ID |
| `rid` | ✅ | 本次运行的 run_id (初始化时生成) |

---

#### `logger.info(msg, module=None, dur=None, error_code=None, ctx=None)`

> 评审修复 (AGG-007): `module` 改为可选，默认从调用栈自动提取。

**参数**:
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `msg` | str | ✅ | 简短描述 (一句话) |
| `module` | str | ⚠️ | 模块/class/函数名 (**不传则自动提取**) |
| `tid` | str | ⚠️ | 堆栈跟踪引用 ID (可为 null) |
| `dur` | int | ⚠️ | 操作耗时 (ms) |
| `error_code` | str | ⚠️ | 结构化错误码 (建议使用 ErrorCode 枚举，见 02-log-format.md §9) |
| `ctx` | dict | ⚠️ | 少量关键上下文键值对 |

**示例**:
```python
# module 自动提取 (推荐 — Agent 生成代码最简形式)
logger.info("Processing started", ctx={"file": "data.json", "size": 1024})
logger.info("Request completed", dur=234, ctx={"endpoint": "/users"})

# 显式指定 module
logger.info("Processing started", module="parser", ctx={"file": "data.json"})

# 使用 ErrorCode 枚举
from agentic_logger import ErrorCode
logger.error("Parse failed", error_code=ErrorCode.PARSE_JSON, ctx={"file": "data.json"})
```

**输出**:
```json
{"ts":"2026-07-21T11:30:00.123+08:00","level":"INFO","msg":"Processing started","module":"parser","tid":null,"rid":"550e8400","pid":"12345","dur":null,"error_code":null,"ctx":{"file":"data.json","size":1024}}
```

---

#### `logger.warn(msg, module, dur=None, error_code=None, ctx=None)`

参数同 `info`。

```python
logger.warn("Slow operation", module="database", dur=5000, error_code="PERF_SLOW", ctx={"threshold": 1000})
```

---

#### `logger.error(msg, module, error_code, tid=None, dur=None, ctx=None)`

**参数**:
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `msg` | str | ✅ | 简短描述 |
| `module` | str | ✅ | 模块名 |
| `error_code` | str | ✅ | **结构化错误码 (必填)** |
| `tid` | str | ⚠️ | 堆栈跟踪引用 ID |
| `dur` | int | ⚠️ | 操作耗时 (ms) |
| `ctx` | dict | ⚠️ | 上下文 |

**示例**:
```python
logger.error("Failed to parse", module="parser", error_code="PARSE_JSON", tid="trace_001", ctx={"file": "data.json", "line": 42})

# 自动捕获异常
try:
    risky_operation()
except Exception as e:
    logger.error("Operation failed", module="executor", error_code="EXEC_RUNTIME", tid=logger.save_traceback(e))
```

---

#### `logger.tool_call(tool, cmd, exit, dur, tid=None, error_code=None, stdout=None, stderr=None, ctx=None)`

**参数**:
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `tool` | str | ✅ | 工具名称 |
| `cmd` | str | ✅ | 命令/操作 |
| `exit` | int | ✅ | 退出码 (0=成功) |
| `dur` | int | ✅ | 执行耗时 (ms) |
| `tid` | str | ⚠️ | 堆栈跟踪引用 ID |
| `error_code` | str | ⚠️ | 错误码 (失败时) |
| `stdout` | str | ⚠️ | 标准输出摘要 |
| `stderr` | str | ⚠️ | 标准错误摘要 |
| `ctx` | dict | ⚠️ | 上下文 |

**示例**:
```python
logger.tool_call(
    tool="bash",
    cmd="npm install express",
    exit=0,
    dur=1234,
    stdout="added 50 packages in 1.2s",
    stderr=""
)

# 失败的工具调用
logger.tool_call(
    tool="bash",
    cmd="npm run build",
    exit=1,
    dur=5000,
    error_code="BUILD_FAIL",
    stderr="Error: Module not found"
)
```

---

#### `logger.file_op(op, path, ok, size=None, error_code=None, tid=None, dur=None, ctx=None)`

**参数**:
| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `op` | str | ✅ | 操作: `read`, `write`, `delete`, `move`, `copy` |
| `path` | str | ✅ | 文件路径 |
| `ok` | bool | ✅ | 是否成功 |
| `size` | int | ⚠️ | 文件大小 (字节) |
| `error_code` | str | ⚠️ | 错误码 (失败时) |
| `tid` | str | ⚠️ | 堆栈跟踪引用 ID |
| `dur` | int | ⚠️ | 操作耗时 (ms) |
| `ctx` | dict | ⚠️ | 上下文 |

**示例**:
```python
logger.file_op("write", "/path/to/file.py", ok=True, size=1024, dur=10)
logger.file_op("read", "/missing.txt", ok=False, error_code="FILE_NOT_FOUND")
```

---

#### `logger.decision(choice, alts=None, reason=None, confidence=None, module=None, ctx=None)`

**示例**:
```python
logger.decision(
    choice="use_async",
    alts=["sync", "threading"],
    reason="IO-bound workload",
    confidence=0.85,
    module="agent.architect"
)
```

---

#### `logger.code_gen(lang, path, lines=None, funcs=None, imports=None, module=None, ctx=None)`

**示例**:
```python
logger.code_gen(
    lang="python",
    path="src/main.py",
    lines=50,
    funcs=["main", "process_data"],
    imports=["os", "sys"],
    module="agent.coder"
)
```

---

#### `logger.context_switch(from_task=None, to_task=None, reason=None, module=None, ctx=None)`

**示例**:
```python
logger.context_switch(
    from_task="fix_bug",
    to_task="add_feature",
    reason="User requested",
    module="agent.coordinator"
)
```

---

### 2.4 辅助方法

#### `logger.save_traceback(exc) -> str`

保存异常的完整堆栈跟踪，返回 `tid` 引用。

```python
try:
    risky_operation()
except Exception as e:
    tid = logger.save_traceback(e)
    logger.error("Failed", module="executor", error_code="EXEC_RUNTIME", tid=tid)
```

**堆栈跟踪存储**: 存储在单独的 `.traceback` 文件中，主日志只存引用 ID，保持轻量。

---

#### `logger.set_global_context(**kwargs)`

设置全局上下文（写入日志文件头部，每条日志自动携带）。

```python
logger.set_global_context(
    user_id="u123",
    session_id="sess_abc",
    project="my_project",
    git_branch="feature-x"
)
```

**输出**: 在日志文件头部写入一条 `GLOBAL_CTX` 记录。

---

### 2.5 运行生命周期

```python
# 自动记录运行开始
logger.run_start(msg="Agent started", ctx={"args": sys.argv})

# ... 执行各种操作 ...

# 自动记录运行结束
logger.run_end(msg="Agent finished", exit_code=0, dur=total_duration)
```

**自动输出**:
```json
{"ts":"...","level":"INFO","msg":"Agent started","module":"__lifecycle__","rid":"550e8400","pid":"12345","event":"run_start",...}
{"ts":"...","level":"INFO","msg":"Agent finished","module":"__lifecycle__","rid":"550e8400","pid":"12345","event":"run_end","dur":12345,"exit_code":0,...}
```

---

## 3. 日志文件命名

### 3.1 命名规则

**格式**: `{program}_{command}_{YYYY-MM-DD}_{HHmmss}.{ext}`

**示例**:
```
logs/
├── my_agent_main_2026-07-21_103000.jsonl
├── my_agent_worker_2026-07-21_103005.sqlite
├── build_script_npm_install_2026-07-21_110000.jsonl
└── coder_agent_pid12345_2026-07-21_113000.jsonl
```

### 3.2 命名参数

| 参数 | 来源 | 说明 |
|------|------|------|
| `program` | `AgentLogger(program=...)` | 程序名 |
| `command` | `AgentLogger(command=...)` | 子命令 |
| `YYYY-MM-DD` | 当前日期 | 运行日期 |
| `HHmmss` | 启动时间 | 时分秒 |
| `ext` | 存储后端决定 | `jsonl` 或 `sqlite` |

**特殊处理**:
- 如果 `command` 未设置，使用 `pid{PID}` 替代
- 文件名中的非法字符替换为 `_`

---

## 4. 存储后端自动选择

```python
def _select_backend(log_dir, max_size_mb, circular):
    """根据配置和文件大小选择存储后端"""
    if max_size_mb is None or max_size_mb > LARGE_THRESHOLD:
        # 大文件场景: SQLite + WAL
        return SQLiteBackend(wal_mode=True, circular=circular)
    else:
        # 小文件场景: JSONL
        return JSONLBackend()
```

**默认阈值**: `LARGE_THRESHOLD = 100MB`

---

## 5. 循环写入模式

### 5.1 JSONL 循环写入

**策略**: 文件达到大小上限后，创建新文件，删除最旧的文件。

```python
class CircularJSONLBackend:
    def __init__(self, max_files=10, max_size_mb=500):
        self.max_files = max_files
        self.max_size_mb = max_size_mb
    
    def write(self, entry):
        if self._current_file_size() > self.max_size_mb * 1024 * 1024:
            self._rotate()
        self._append(entry)
    
    def _rotate(self):
        """删除最旧的文件，创建新文件"""
        files = sorted(self._get_log_files())
        if len(files) >= self.max_files:
            files[0].unlink()  # 删除最旧
        self._create_new_file()
```

### 5.2 SQLite 循环写入

**策略**: 表内记录数达到上限后，删除最旧的记录。

```python
class CircularSQLiteBackend:
    def __init__(self, retention_count=100000):
        self.retention_count = retention_count
    
    def write(self, entry):
        self._insert(entry)
        if self._count() > self.retention_count:
            self._delete_oldest(self._count() - self.retention_count)
```

---

## 6. 多语言一致性

### 6.1 接口规范 (未来 Node.js/Bash)

所有语言 SDK 必须实现相同的核心方法，输出相同的 JSONL 格式：

```
info(msg, module, dur?, error_code?, ctx?)
warn(msg, module, dur?, error_code?, ctx?)
error(msg, module, error_code, tid?, dur?, ctx?)
tool_call(tool, cmd, exit, dur, tid?, error_code?, stdout?, stderr?, ctx?)
file_op(op, path, ok, size?, error_code?, tid?, dur?, ctx?)
decision(choice, alts?, reason?, confidence?, module?, ctx?)
```

### 6.2 字段命名

所有语言输出相同的字段名（小写 + 下划线）：
`ts`, `level`, `msg`, `module`, `tid`, `rid`, `pid`, `dur`, `error_code`, `ctx`

---

## 7. 错误处理

### 7.1 日志写入失败

- **静默失败**: 不抛出异常，不影响主程序
- **写入 stderr**: 输出错误信息到 stderr
- **降级策略**: JSONL 失败时尝试 SQLite，反之亦然

### 7.2 参数验证

- `error_code` 在 `error()` 中必填
- `module` 所有方法必填
- `rid` 自动填充，不允许覆盖
