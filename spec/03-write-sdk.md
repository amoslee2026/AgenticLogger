# 03 - 写入 SDK API 设计

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **独立命名空间** | 独立库，不与标准 `logging` 混淆 |
| **语义化方法** | 方法名清晰表达意图 |
| **一致字段** | 所有语言使用一致的字段命名 |
| **Agent 友好** | 文档针对 Coding Agent 优化 |
| **零依赖** | 核心功能无外部依赖 |

---

## 2. Python SDK

### 2.1 安装

```bash
pip install agentic-logger
```

### 2.2 导入

```python
from agentic_logger import agent_log
```

### 2.3 初始化 (可选)

```python
from agentic_logger import agent_log, configure

# 配置日志目录
configure(
    log_dir="./logs",
    log_level="INFO",
    session_id="abc123",
    module="my_agent"
)
```

### 2.4 基础日志方法

#### `agent_log.info(message, **context)`

记录一般信息

**参数**:
- `message` (str, 必填): 日志消息
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.info("Processing started", module="parser", file="data.json")
agent_log.info("User logged in", user_id="u123", ip="192.168.1.1")
```

---

#### `agent_log.warn(message, **context)`

记录警告

**参数**: 同 `info`

**示例**:
```python
agent_log.warn("Slow operation", duration_ms=5000, threshold_ms=1000)
agent_log.warn("Deprecated API used", api="v1", replacement="v2")
```

---

#### `agent_log.error(message, error=None, **context)`

记录错误

**参数**:
- `message` (str, 必填): 日志消息
- `error` (str/Exception, 可选): 错误信息
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.error("Failed to parse", error="JSONDecodeError", file="data.json", line=42)

# 自动捕获异常
try:
    risky_operation()
except Exception as e:
    agent_log.error("Operation failed", error=e, context="parsing")
```

---

### 2.5 Coding Agent 专用方法

#### `agent_log.tool_call(tool, command, exit_code=None, duration_ms=None, stdout_summary=None, stderr_summary=None, **context)`

记录工具调用

**参数**:
- `tool` (str, 必填): 工具名称 (bash, read, write, ...)
- `command` (str, 必填): 命令/操作
- `exit_code` (int, 可选): 退出码 (0=成功)
- `duration_ms` (int, 可选): 执行时长 (毫秒)
- `stdout_summary` (str, 可选): 标准输出摘要
- `stderr_summary` (str, 可选): 标准错误摘要
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.tool_call(
    tool="bash",
    command="npm install express",
    exit_code=0,
    duration_ms=1234,
    stdout_summary="added 50 packages",
    stderr_summary=""
)

agent_log.tool_call(
    tool="read",
    command="/path/to/file.py",
    exit_code=0,
    duration_ms=10
)
```

---

#### `agent_log.file_op(operation, path, success, size_bytes=None, error=None, **context)`

记录文件操作

**参数**:
- `operation` (str, 必填): 操作类型 (`read`, `write`, `delete`, `move`, `copy`)
- `path` (str, 必填): 文件路径
- `success` (bool, 必填): 是否成功
- `size_bytes` (int, 可选): 文件大小 (字节)
- `error` (str, 可选): 错误信息 (失败时)
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.file_op(
    operation="write",
    path="/path/to/file.py",
    success=True,
    size_bytes=1024
)

agent_log.file_op(
    operation="read",
    path="/path/to/missing.txt",
    success=False,
    error="FileNotFoundError"
)
```

---

#### `agent_log.decision(choice, alternatives=None, reason=None, confidence=None, **context)`

记录决策点

**参数**:
- `choice` (str, 必填): 最终选择
- `alternatives` (list[str], 可选): 其他选项
- `reason` (str, 可选): 选择原因
- `confidence` (float, 可选): 置信度 (0-1)
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.decision(
    choice="use_async",
    alternatives=["sync", "threading"],
    reason="IO-bound workload",
    confidence=0.85
)
```

---

#### `agent_log.code_gen(language, file_path, lines=None, functions=None, imports=None, **context)`

记录代码生成

**参数**:
- `language` (str, 必填): 编程语言
- `file_path` (str, 必填): 文件路径
- `lines` (int, 可选): 代码行数
- `functions` (list[str], 可选): 函数列表
- `imports` (list[str], 可选): 导入列表
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.code_gen(
    language="python",
    file_path="src/main.py",
    lines=50,
    functions=["main", "process_data"],
    imports=["os", "sys"]
)
```

---

#### `agent_log.context_switch(from_task=None, to_task, reason=None, **context)`

记录上下文切换

**参数**:
- `from_task` (str, 可选): 原任务
- `to_task` (str, 必填): 新任务
- `reason` (str, 可选): 切换原因
- `**context` (dict, 可选): 附加上下文

**示例**:
```python
agent_log.context_switch(
    from_task="fix_bug",
    to_task="add_feature",
    reason="User requested new feature"
)
```

---

### 2.6 批量日志

```python
with agent_log.batch() as batch:
    batch.info("Step 1 completed")
    batch.info("Step 2 completed")
    batch.tool_call(tool="bash", command="npm install")
```

---

### 2.7 装饰器 (自动记录)

```python
from agentic_logger import instrument

@instrument
def my_function(x, y):
    """自动记录函数调用"""
    return x + y

# 输出:
# INFO: Entering my_function(x=1, y=2)
# INFO: Exiting my_function, duration=10ms, result=3
```

---

## 3. Node.js SDK

### 3.1 安装

```bash
npm install @agentic/logger
```

### 3.2 导入

```javascript
import { agentLog } from '@agentic/logger';
// 或
const { agentLog } = require('@agentic/logger');
```

### 3.3 初始化 (可选)

```javascript
import { agentLog, configure } from '@agentic/logger';

configure({
  logDir: './logs',
  logLevel: 'INFO',
  sessionId: 'abc123',
  module: 'my_agent'
});
```

### 3.4 API (与 Python 一致)

```javascript
// 基础日志
agentLog.info('Processing started', { module: 'parser', file: 'data.json' });
agentLog.warn('Slow operation', { durationMs: 5000 });
agentLog.error('Failed to parse', { error: 'JSONDecodeError', file: 'data.json' });

// 工具调用
agentLog.toolCall({
  tool: 'bash',
  command: 'npm install express',
  exitCode: 0,
  durationMs: 1234,
  stdoutSummary: 'added 50 packages'
});

// 文件操作
agentLog.fileOp({
  operation: 'write',
  path: '/path/to/file.py',
  success: true,
  sizeBytes: 1024
});

// 决策点
agentLog.decision({
  choice: 'use_async',
  alternatives: ['sync', 'threading'],
  reason: 'IO-bound workload',
  confidence: 0.85
});
```

---

## 4. Bash SDK

### 4.1 安装

```bash
# 下载脚本
curl -o agentic_logger.sh https://raw.githubusercontent.com/.../agentic_logger.sh

# 或添加到项目
source ./agentic_logger.sh
```

### 4.2 初始化 (可选)

```bash
export AGENTIC_LOG_DIR="./logs"
export AGENTIC_LOG_LEVEL="INFO"
export AGENTIC_SESSION_ID="abc123"
export AGENTIC_MODULE="my_script"
```

### 4.3 API

```bash
# 基础日志
agent_log_info "Processing started" "module=parser" "file=data.json"
agent_log_warn "Slow operation" "duration_ms=5000"
agent_log_error "Failed to parse" "error=SyntaxError" "file=main.sh"

# 工具调用
agent_log_tool_call "bash" "npm install" 0 1234 "added 50 packages" ""

# 文件操作
agent_log_file_op "write" "/path/to/file.sh" true 1024 ""

# 决策点
agent_log_decision "use_bash" "python,perl" "Simpler syntax" 0.8
```

---

## 5. 多语言一致性

### 5.1 字段命名映射

| 概念 | Python | Node.js | Bash |
|------|--------|---------|------|
| 时间戳 | `ts` | `ts` | `ts` |
| 消息 | `msg` | `msg` | `msg` |
| 模块 | `module` | `module` | `module` |
| 命令 | `command` | `command` | `command` |
| 退出码 | `exit_code` | `exitCode` | `exit_code` |
| 时长(毫秒) | `duration_ms` | `durationMs` | `duration_ms` |
| 成功 | `success` | `success` | `success` |

### 5.2 输出格式一致性

所有 SDK 输出相同的 JSONL 格式：

```jsonl
{"ts":"2026-07-21T11:30:00.123+08:00","level":"INFO","msg":"Hello","module":"test"}
```

---

## 6. 错误处理

### 6.1 日志写入失败

SDK 应该:
- 静默失败 (不抛出异常)
- 写入 stderr (可选)
- 继续执行

```python
try:
    _write_to_file(log_entry)
except Exception as e:
    print(f"Failed to write log: {e}", file=sys.stderr)
```

### 6.2 参数验证

SDK 应该:
- 验证必填字段
- 提供清晰的错误信息
- 不阻塞主程序

```python
if not message:
    raise ValueError("message is required")
```

---

## 7. 性能优化

### 7.1 批量写入

```python
# 推荐：批量写入
with agent_log.batch() as batch:
    for i in range(100):
        batch.info(f"Step {i}")

# 不推荐：逐条写入
for i in range(100):
    agent_log.info(f"Step {i}")  # 100 次文件 IO
```

### 7.2 异步写入 (未来)

```python
# 异步模式 (未来版本)
agent_log.configure(async_mode=True)
```

---

## 8. 文档编写指南 (针对 Agent)

### 8.1 文档结构

```markdown
# agentic_logger 使用指南

## 安装
pip install agentic-logger

## 快速开始
from agentic_logger import agent_log
agent_log.info("Hello!")

## API 参考

### agent_log.info(message, **context)
**参数**:
- message (str, 必填): 日志消息
- **context (dict, 可选): 附加上下文

**示例**:
agent_log.info("Processing file", file="data.json")
```

### 8.2 示例驱动

提供丰富的示例，覆盖常见场景：
- 执行 bash 命令
- 读写文件
- 错误处理
- 决策记录
