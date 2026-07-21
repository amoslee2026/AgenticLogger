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

| 字段                        | 类型              | 必需                        | 说明                                                                                                                                |
| --------------------------- | ----------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `ts`                      | string (ISO 8601) | ✅                          | 毫秒级时间戳，含时区                                                                                                                |
| `level`                   | string            | ✅                          | 日志级别:`DEBUG`, `INFO`, `WARN`, `ERROR`, `TOOL`, `FILE_OP`, `DECISION`, `CODE_GEN`, `CONTEXT`                   |
| module                      | string            | ✅                          | 模块/class/函数名<br />定位"哪个代码区域出的问题"，配合Serena做代码级关联                                                           |
| `msg`                     | string            | ✅                          | 简短描述(一句话)人类/agent快速扫描判断是否相关                                                                                      |
| tid                         | string            | ✅                          | 堆栈跟踪引用ID(可为null)需要深挖时才关联查询完整堆栈，主表保持轻量                                                                  |
| `rid` (request_id/run_id) | string            | ✅                          | 一次完整流程/请求的唯一标识<br />agent能用它把一次任务里分散的多条日志串起来看完整链路，不用靠时间相邻猜测                          |
| `pid`/`seq`             | string            | ✅                          | 进程ID或全局序列号,多进程/多线程交织时，区分是否同一执行流                                                                          |
| dur                         |                   | ✅                          | 该操作耗时(ms，仅当适用)排查性能问题(超时、卡顿)时不需要额外算时间差                                                                |
| ErrorCode                   | string            | ✅                          | 结构化错误码(而非只有文本msg)<br />系统有明确的错误分类体系，能让 log 分析脚本 按错误码精确聚合而不是靠文本正则猜测                |
| ctx                         |                   | 可选(大多用于debug级别日志) | 少量关键上下文的键值对(如`{"user_id":123,"retry":2}`)排查时需要具体参数值，但别把整个请求体塞进去——只放能帮助复现问题的最小信息 |

### 2.2 上下文字段 

对于特定日志文件只输出一次的全局信息, 不是每条日志消息都包含

**常见字段**:

| 字段     | 类型   | 说明                   |
| -------- | ------ | ---------------------- |
| `file` | string | 输入日志的程序文件路径 |
|          |        |                        |

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

| 字段       | 类型    | 必需 | 说明            |
| ---------- | ------- | ---- | --------------- |
| `tool`   | string  | ✅   | 工具名称        |
| `cmd`    | string  | ✅   | 命令/操作       |
| `exit`   | integer | ⚠️ | 退出码 (0=成功) |
| `dur_ms` | integer | ⚠️ | 执行时长 (毫秒) |
| `stdout` | string  | ⚠️ | 标准输出摘要    |
| `stderr` | string  | ⚠️ | 标准错误摘要    |

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

| 字段     | 类型    | 必需 | 说明                                                         |
| -------- | ------- | ---- | ------------------------------------------------------------ |
| `op`   | string  | ✅   | 操作类型:`read`, `write`, `delete`, `move`, `copy` |
| `path` | string  | ✅   | 文件路径                                                     |
| `ok`   | boolean | ✅   | 是否成功                                                     |
| `size` | integer | ⚠️ | 文件大小 (字节)                                              |
| `err`  | string  | ⚠️ | 错误信息 (失败时)                                            |

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

| 字段           | 类型          | 必需 | 说明         |
| -------------- | ------------- | ---- | ------------ |
| `choice`     | string        | ✅   | 最终选择     |
| `alts`       | array[string] | ⚠️ | 其他选项     |
| `reason`     | string        | ⚠️ | 选择原因     |
| `confidence` | float         | ⚠️ | 置信度 (0-1) |

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

| 字段        | 类型          | 必需 | 说明     |
| ----------- | ------------- | ---- | -------- |
| `lang`    | string        | ✅   | 编程语言 |
| `path`    | string        | ✅   | 文件路径 |
| `lines`   | integer       | ⚠️ | 代码行数 |
| `funcs`   | array[string] | ⚠️ | 函数列表 |
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

| 字段       | 类型   | 必需 | 说明     |
| ---------- | ------ | ---- | -------- |
| `from`   | string | ⚠️ | 原任务   |
| `to`     | string | ✅   | 新任务   |
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

| 完整名           | 缩写       | 说明          |
| ---------------- | ---------- | ------------- |
| `timestamp`    | `ts`     | 时间戳        |
| `message`      | `msg`    | 消息          |
| `module`       | `module` | 模块 (不缩写) |
| `level`        | `level`  | 级别 (不缩写) |
| `command`      | `cmd`    | 命令          |
| `exit_code`    | `exit`   | 退出码        |
| `duration_ms`  | `dur_ms` | 时长          |
| `operation`    | `op`     | 操作          |
| `success`      | `ok`     | 成功标志      |
| `error`        | `err`    | 错误          |
| `alternatives` | `alts`   | 选项          |
| `language`     | `lang`   | 语言          |
| `functions`    | `funcs`  | 函数          |
| `size_bytes`   | `size`   | 大小          |

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

| 级别         | 用途       | 示例场景                |
| ------------ | ---------- | ----------------------- |
| `DEBUG`    | 调试信息   | 变量值、中间状态        |
| `INFO`     | 一般信息   | 流程开始/结束、状态变更 |
| `WARN`     | 警告       | 慢操作、资源不足        |
| `ERROR`    | 错误       | 异常、失败              |
| `TOOL`     | 工具调用   | 执行命令、调用 API      |
| `FILE_OP`  | 文件操作   | 读写删除文件            |
| `DECISION` | 决策点     | 架构选择、方案决定      |
| `CODE_GEN` | 代码生成   | 生成代码文件            |
| `CONTEXT`  | 上下文切换 | 任务切换、状态变更      |

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

## 9. 标准错误码字典 (ErrorCode)

> 评审修复 (AGG-002): 定义标准错误码分类体系，确保跨 Agent 一致性。

### 9.1 错误码命名规范

**格式**: `{CATEGORY}_{SPECIFIC}` (全大写 + 下划线)

**分类前缀**:

| 前缀 | 类别 | 说明 |
|------|------|------|
| `PARSE_*` | 解析错误 | JSON/YAML/XML/CSV 等格式解析失败 |
| `IO_*` | 文件系统 | 读写删除权限等文件操作错误 |
| `EXEC_*` | 执行错误 | 命令执行失败、超时、非零退出码 |
| `NETWORK_*` | 网络错误 | 连接超时、DNS 失败、SSL 错误 |
| `AUTH_*` | 认证授权 | 登录失败、token 过期、权限不足 |
| `CONFIG_*` | 配置错误 | 缺失配置、格式错误、值不合法 |
| `RESOURCE_*` | 资源不足 | 内存不足、磁盘满、CPU 超限 |
| `VALIDATION_*` | 输入校验 | 参数非法、类型错误、范围越界 |
| `TIMEOUT_*` | 超时 | 各类超时场景 |
| `CONFLICT_*` | 冲突 | 并发冲突、版本冲突、锁竞争 |
| `INTERNAL_*` | 内部错误 | 程序 bug、未预期的异常 |
| `UNKNOWN` | 未知 | 无法分类的错误 (兜底) |

### 9.2 完整错误码列表

#### PARSE_* (解析错误)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `PARSE_JSON` | JSON 解析失败 | `json.loads()` 抛出异常 |
| `PARSE_YAML` | YAML 解析失败 | `yaml.safe_load()` 格式错误 |
| `PARSE_XML` | XML 解析失败 | XML 格式不合法 |
| `PARSE_CSV` | CSV 解析失败 | 列数不匹配 |
| `PARSE_REGEX` | 正则匹配失败 | 模式不匹配或语法错误 |
| `PARSE_ENCODING` | 编码错误 | UTF-8 解码失败 |

#### IO_* (文件系统)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `IO_NOT_FOUND` | 文件/目录不存在 | `FileNotFoundError` |
| `IO_PERMISSION` | 权限不足 | `PermissionError` |
| `IO_DISK_FULL` | 磁盘空间不足 | `NoSpaceLeftOnDevice` |
| `IO_READ_FAIL` | 读取失败 | 通用读取错误 |
| `IO_WRITE_FAIL` | 写入失败 | 通用写入错误 |
| `IO_LOCK_FAIL` | 文件锁获取失败 | 并发写入冲突 |

#### EXEC_* (执行错误)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `EXEC_NON_ZERO` | 命令非零退出 | `exit_code != 0` |
| `EXEC_TIMEOUT` | 命令执行超时 | 超过设定时间限制 |
| `EXEC_NOT_FOUND` | 命令不存在 | `command not found` |
| `EXEC_KILLED` | 进程被杀死 | OOM killer 或信号 |
| `EXEC_CRASH` | 进程崩溃 | segfault 或 panic |

#### NETWORK_* (网络错误)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `NET_TIMEOUT` | 网络超时 | 连接/读取超时 |
| `NET_DNS_FAIL` | DNS 解析失败 | 域名无法解析 |
| `NET_CONN_REFUSED` | 连接被拒绝 | 端口未监听 |
| `NET_SSL_ERROR` | SSL/TLS 错误 | 证书无效 |
| `NET_HTTP_ERROR` | HTTP 错误 | 4xx/5xx 状态码 |

#### AUTH_* (认证授权)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `AUTH_LOGIN_FAIL` | 登录失败 | 用户名/密码错误 |
| `AUTH_TOKEN_EXPIRED` | Token 过期 | JWT 过期 |
| `AUTH_FORBIDDEN` | 权限不足 | 403 Forbidden |
| `AUTH_UNAUTHORIZED` | 未认证 | 401 Unauthorized |

#### CONFIG_* (配置错误)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `CONFIG_MISSING` | 配置缺失 | 必填项未设置 |
| `CONFIG_INVALID` | 配置格式错误 | 类型不匹配 |
| `CONFIG_RANGE` | 配置值越界 | 超出允许范围 |

#### RESOURCE_* (资源不足)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `RES_MEMORY` | 内存不足 | OOM |
| `RES_DISK` | 磁盘不足 | 存储空间耗尽 |
| `RES_CPU` | CPU 超限 | 超出配额 |
| `RES_FD` | 文件描述符耗尽 | `Too many open files` |

#### TIMEOUT_* (超时)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `TIMEOUT_API` | API 调用超时 | 远程服务无响应 |
| `TIMEOUT_DB` | 数据库查询超时 | 慢查询 |
| `TIMEOUT_LOCK` | 锁等待超时 | 数据库行锁/表锁 |

#### CONFLICT_* (冲突)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `CONFLICT_VERSION` | 版本冲突 | Git merge conflict |
| `CONFLICT_LOCK` | 锁竞争 | 多线程/多进程争抢 |
| `CONFLICT_DUPLICATE` | 重复冲突 | 唯一约束违反 |

#### INTERNAL_* (内部错误)

| 错误码 | 说明 | 示例场景 |
|--------|------|---------|
| `INTERNAL_UNEXPECTED` | 未预期异常 | 通用兜底 |
| `INTERNAL_ASSERT` | 断言失败 | `assert` 触发 |
| `INTERNAL_TYPE` | 类型错误 | `TypeError` |
| `INTERNAL_KEY` | 键不存在 | `KeyError` |
| `INTERNAL_INDEX` | 索引越界 | `IndexError` |

#### UNKNOWN

| 错误码 | 说明 |
|--------|------|
| `UNKNOWN` | 无法分类的错误 (兜底默认值) |

### 9.3 SDK 使用示例

```python
from agentic_logger import AgentLogger, ErrorCode

logger = AgentLogger(program="my_agent")

# 使用枚举常量
logger.error("Failed to parse config", module="config", error_code=ErrorCode.PARSE_JSON)
logger.tool_call(tool="bash", cmd="npm build", exit=1, dur=5000, error_code=ErrorCode.EXEC_NON_ZERO)
logger.file_op("read", "/missing.txt", ok=False, error_code=ErrorCode.IO_NOT_FOUND)

# 允许自定义扩展 (保持 PREFIX_SPECIFIC 格式)
logger.error("Custom error", module="custom", error_code="CUSTOM_BUSINESS_RULE")
```

---

## 10. 兼容性

### 10.1 向后兼容

- 新增字段不影响旧版本解析
- 删除字段需标记为 `deprecated` 并保留至少 1 个版本

### 9.2 外部日志支持

对于非 AgenticLogger 格式的外部日志 (CI 日志、应用日志等):

- 读取时提供适配层
- 可选使用 GLiNER/NuExtract 进行结构化抽取
- 转换为本格式后存储
