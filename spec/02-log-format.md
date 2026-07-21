# 02 - 日志格式规范

## 1. 格式概述

**默认格式**: JSONL (JSON Lines)

**优点**:
- 每行独立 JSON，流式友好
- 支持 `tail -f` 实时监控
- 可用 `grep`/`jq` 快速过滤
- 易于压缩归档

**文件命名**: `agentic-{YYYY-MM-DD}.jsonl`

**示例文件**: `agentic-2026-07-21.jsonl`

---

## 2. JSONL Schema

### 2.1 通用字段 (所有日志必需)

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `ts` | string (ISO 8601) | ✅ | 时间戳，含时区 |
| `level` | string | ✅ | 日志级别: `DEBUG`, `INFO`, `WARN`, `ERROR`, `TOOL`, `FILE_OP`, `DECISION`, `CODE_GEN`, `CONTEXT` |
| `msg` | string | ✅ | 日志消息 |
| `module` | string | ⚠️ | 模块名 (可选，自动推断) |

### 2.2 上下文字段 (可选)

任意键值对，用于附加上下文信息。

**常见字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | string | 文件路径 |
| `line` | integer | 行号 |
| `function` | string | 函数名 |
| `session_id` | string | 会话 ID |
| `user_id` | string | 用户 ID |

---

## 3. 日志类型详细定义

### 3.1 基础日志 (INFO / WARN / ERROR)

**INFO 示例**:
```json
{
  "ts": "2026-07-21T11:30:00.123+08:00",
  "level": "INFO",
  "msg": "Processing started",
  "module": "parser",
  "file": "data.json",
  "size_bytes": 1024
}
```

**WARN 示例**:
```json
{
  "ts": "2026-07-21T11:30:01.456+08:00",
  "level": "WARN",
  "msg": "Slow operation",
  "module": "database",
  "duration_ms": 5000,
  "threshold_ms": 1000
}
```

**ERROR 示例**:
```json
{
  "ts": "2026-07-21T11:30:02.789+08:00",
  "level": "ERROR",
  "msg": "Failed to parse",
  "module": "parser",
  "error": "JSONDecodeError",
  "file": "data.json",
  "line": 42,
  "stack_trace": "..."
}
```

---

### 3.2 工具调用 (TOOL)

**字段定义**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `tool` | string | ✅ | 工具名称 |
| `cmd` | string | ✅ | 命令/操作 |
| `exit` | integer | ⚠️ | 退出码 (0=成功) |
| `dur_ms` | integer | ⚠️ | 执行时长 (毫秒) |
| `stdout` | string | ⚠️ | 标准输出摘要 |
| `stderr` | string | ⚠️ | 标准错误摘要 |

**示例**:
```json
{
  "ts": "2026-07-21T11:30:03.012+08:00",
  "level": "TOOL",
  "msg": "Tool executed successfully",
  "module": "agent.bash",
  "tool": "bash",
  "cmd": "npm install express",
  "exit": 0,
  "dur_ms": 1234,
  "stdout": "added 50 packages in 1.2s",
  "stderr": ""
}
```

---

### 3.3 文件操作 (FILE_OP)

**字段定义**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `op` | string | ✅ | 操作类型: `read`, `write`, `delete`, `move`, `copy` |
| `path` | string | ✅ | 文件路径 |
| `ok` | boolean | ✅ | 是否成功 |
| `size` | integer | ⚠️ | 文件大小 (字节) |
| `err` | string | ⚠️ | 错误信息 (失败时) |

**示例**:
```json
{
  "ts": "2026-07-21T11:30:04.345+08:00",
  "level": "FILE_OP",
  "msg": "File written",
  "module": "agent.file",
  "op": "write",
  "path": "/path/to/file.py",
  "ok": true,
  "size": 1024
}
```

**失败示例**:
```json
{
  "ts": "2026-07-21T11:30:05.678+08:00",
  "level": "FILE_OP",
  "msg": "File read failed",
  "module": "agent.file",
  "op": "read",
  "path": "/path/to/missing.txt",
  "ok": false,
  "err": "FileNotFoundError: [Errno 2] No such file or directory"
}
```

---

### 3.4 决策点 (DECISION)

**字段定义**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `choice` | string | ✅ | 最终选择 |
| `alts` | array[string] | ⚠️ | 其他选项 |
| `reason` | string | ⚠️ | 选择原因 |
| `confidence` | float | ⚠️ | 置信度 (0-1) |

**示例**:
```json
{
  "ts": "2026-07-21T11:30:06.901+08:00",
  "level": "DECISION",
  "msg": "Architecture decision",
  "module": "agent.architect",
  "choice": "use_async",
  "alts": ["sync", "threading"],
  "reason": "IO-bound workload, async provides better concurrency",
  "confidence": 0.85
}
```

---

### 3.5 代码生成 (CODE_GEN)

**字段定义**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `lang` | string | ✅ | 编程语言 |
| `path` | string | ✅ | 文件路径 |
| `lines` | integer | ⚠️ | 代码行数 |
| `funcs` | array[string] | ⚠️ | 函数列表 |
| `imports` | array[string] | ⚠️ | 导入列表 |

**示例**:
```json
{
  "ts": "2026-07-21T11:30:07.234+08:00",
  "level": "CODE_GEN",
  "msg": "Generated Python module",
  "module": "agent.coder",
  "lang": "python",
  "path": "src/main.py",
  "lines": 50,
  "funcs": ["main", "process_data", "helper"],
  "imports": ["os", "sys", "json"]
}
```

---

### 3.6 上下文切换 (CONTEXT)

**字段定义**:

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `from` | string | ⚠️ | 原任务 |
| `to` | string | ✅ | 新任务 |
| `reason` | string | ⚠️ | 切换原因 |

**示例**:
```json
{
  "ts": "2026-07-21T11:30:08.567+08:00",
  "level": "CONTEXT",
  "msg": "Switching task",
  "module": "agent.coordinator",
  "from": "fix_bug",
  "to": "add_feature",
  "reason": "User requested new feature"
}
```

---

## 4. 字段命名规范

### 4.1 通用规则

- **短名称**: 使用缩写减少 token (如 `ts` 而非 `timestamp`, `msg` 而非 `message`)
- **下划线分隔**: 多词字段使用下划线 (如 `exit_code`, `duration_ms`)
- **小写**: 所有字段名小写
- **单位后缀**: 带单位的字段添加后缀 (如 `_ms` 毫秒, `_bytes` 字节)

### 4.2 字段缩写表

| 完整名 | 缩写 | 说明 |
|--------|------|------|
| `timestamp` | `ts` | 时间戳 |
| `message` | `msg` | 消息 |
| `module` | `module` | 模块 (不缩写) |
| `level` | `level` | 级别 (不缩写) |
| `command` | `cmd` | 命令 |
| `exit_code` | `exit` | 退出码 |
| `duration_ms` | `dur_ms` | 时长 |
| `operation` | `op` | 操作 |
| `success` | `ok` | 成功标志 |
| `error` | `err` | 错误 |
| `alternatives` | `alts` | 选项 |
| `language` | `lang` | 语言 |
| `functions` | `funcs` | 函数 |
| `size_bytes` | `size` | 大小 |

---

## 5. 时间戳格式

**格式**: ISO 8601，含时区

**示例**:
- `2026-07-21T11:30:00.123+08:00` (北京时间)
- `2026-07-21T03:30:00.123Z` (UTC)

**精度**: 毫秒 (3 位小数)

**时区**: 建议使用本地时区或 UTC

---

## 6. 日志级别

| 级别 | 用途 | 示例场景 |
|------|------|---------|
| `DEBUG` | 调试信息 | 变量值、中间状态 |
| `INFO` | 一般信息 | 流程开始/结束、状态变更 |
| `WARN` | 警告 | 慢操作、资源不足 |
| `ERROR` | 错误 | 异常、失败 |
| `TOOL` | 工具调用 | 执行命令、调用 API |
| `FILE_OP` | 文件操作 | 读写删除文件 |
| `DECISION` | 决策点 | 架构选择、方案决定 |
| `CODE_GEN` | 代码生成 | 生成代码文件 |
| `CONTEXT` | 上下文切换 | 任务切换、状态变更 |

---

## 7. 示例日志文件

**文件**: `agentic-2026-07-21.jsonl`

```jsonl
{"ts":"2026-07-21T11:30:00.123+08:00","level":"INFO","msg":"Agent started","module":"main","session_id":"abc123"}
{"ts":"2026-07-21T11:30:01.456+08:00","level":"TOOL","msg":"Executing command","module":"agent.bash","tool":"bash","cmd":"ls -la","exit":0,"dur_ms":50}
{"ts":"2026-07-21T11:30:02.789+08:00","level":"FILE_OP","msg":"Reading file","module":"agent.file","op":"read","path":"config.json","ok":true,"size":256}
{"ts":"2026-07-21T11:30:03.012+08:00","level":"DECISION","msg":"Choosing framework","module":"agent.architect","choice":"FastAPI","alts":["Flask","Django"],"reason":"Modern async support","confidence":0.9}
{"ts":"2026-07-21T11:30:04.345+08:00","level":"CODE_GEN","msg":"Generated module","module":"agent.coder","lang":"python","path":"src/main.py","lines":100,"funcs":["main","handler"]}
{"ts":"2026-07-21T11:30:05.678+08:00","level":"ERROR","msg":"Build failed","module":"agent.bash","error":"Exit code 1","cmd":"npm run build","stderr":"Error: Module not found"}
```

---

## 8. 压缩与归档

**压缩**: `gzip agentic-2026-07-21.jsonl` → `agentic-2026-07-21.jsonl.gz`

**归档策略**:
- 当天日志: 不压缩 (便于实时查看)
- 昨天日志: 压缩 (`gzip`)
- 30 天前: 移动到归档目录或删除

---

## 9. 兼容性

### 9.1 向后兼容

- 新增字段不影响旧版本解析
- 删除字段需标记为 `deprecated` 并保留至少 1 个版本

### 9.2 外部日志支持

对于非 AgenticLogger 格式的外部日志 (CI 日志、应用日志等):
- 读取时提供适配层
- 可选使用 GLiNER/NuExtract 进行结构化抽取
- 转换为本格式后存储
