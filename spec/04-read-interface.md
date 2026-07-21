# 04 - 读取接口设计

## 1. 概述

AgenticLogger 提供四种读取接口：

| 接口 | 目标用户 | 使用场景 |
|------|---------|---------|
| **MCP Tool** | AI Agent (Claude/Cursor) | Agent 查询分析日志 |
| **CLI** | 人类开发者 | 终端查看、调试 |
| **REST API** | 系统集成 | HTTP 接口调用 |
| **Python SDK** | 程序调用 | 代码中查询分析 |

---

## 2. MCP Tool

### 2.1 概述

MCP (Model Context Protocol) 让 AI Agent 直接查询和分析日志。

### 2.2 MCP Tools 定义

#### `agentic_log_query` - 查询日志

**描述**: 按条件查询结构化日志

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `level` | string | ⚠️ | 日志级别: `INFO`, `WARN`, `ERROR`, `TOOL`, `FILE_OP`, `DECISION`, `CODE_GEN`, `CONTEXT` |
| `tool` | string | ⚠️ | 工具名称 (如 `bash`, `read`) |
| `exit_code` | integer | ⚠️ | 退出码 (配合 `tool` 使用) |
| `since` | string | ⚠️ | 起始时间 (ISO 8601 或相对时间 `1h`, `24h`) |
| `until` | string | ⚠️ | 截止时间 |
| `limit` | integer | ⚠️ | 返回条数 (默认 100) |
| `keyword` | string | ⚠️ | 关键词搜索 |

**示例调用**:
```json
{
  "tool": "agentic_log_query",
  "arguments": {
    "level": "ERROR",
    "since": "2026-07-21T00:00:00Z",
    "limit": 50
  }
}
```

**返回**:
```json
{
  "count": 50,
  "logs": [
    {"ts": "2026-07-21T11:30:05.678+08:00", "level": "ERROR", "msg": "Build failed", "error": "Exit code 1"},
    ...
  ]
}
```

---

#### `agentic_log_analyze` - 分析日志

**描述**: 深度分析日志模式和趋势

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `time_range` | string | ⚠️ | 时间范围 (如 `1h`, `24h`, `7d`) |
| `focus` | string | ⚠️ | 分析焦点: `errors`, `tool_calls`, `decisions`, `performance` |
| `top_n` | integer | ⚠️ | 返回 Top N 结果 (默认 10) |

**示例调用**:
```json
{
  "tool": "agentic_log_analyze",
  "arguments": {
    "time_range": "24h",
    "focus": "errors",
    "top_n": 5
  }
}
```

**返回**:
```json
{
  "summary": "过去24小时共发现15个错误，主要集中在bash工具调用",
  "top_errors": [
    {"error": "Exit code 1", "count": 8, "last_seen": "2026-07-21T11:30:05Z"},
    {"error": "FileNotFoundError", "count": 5, "last_seen": "2026-07-21T10:15:00Z"}
  ],
  "pattern": "bash命令失败率较高，建议检查依赖安装"
}
```

---

#### `agentic_log_stats` - 统计分析

**描述**: 获取日志统计信息

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `since` | string | ⚠️ | 起始时间 |
| `group_by` | string | ⚠️ | 分组方式: `level`, `tool`, `hour`, `module` |

**示例调用**:
```json
{
  "tool": "agentic_log_stats",
  "arguments": {
    "since": "24h",
    "group_by": "level"
  }
}
```

**返回**:
```json
{
  "total": 1234,
  "groups": [
    {"key": "INFO", "count": 800, "percentage": 64.8},
    {"key": "TOOL", "count": 250, "percentage": 20.3},
    {"key": "ERROR", "count": 100, "percentage": 8.1},
    {"key": "FILE_OP", "count": 84, "percentage": 6.8}
  ]
}
```

---

#### `agentic_log_stream` - 实时流

**描述**: 实时订阅日志流

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `level` | string | ⚠️ | 过滤级别 |
| `tool` | string | ⚠️ | 过滤工具 |
| `duration` | string | ⚠️ | 持续时间 (如 `5m`, `1h`) |

**返回**: 流式返回新日志

---

### 2.3 MCP Server 实现

```python
from mcp.server import Server
from agentic_logger import LogReader

server = Server("agentic-logger")

@server.tool("agentic_log_query")
def query_logs(level=None, tool=None, since=None, limit=100):
    reader = LogReader()
    logs = reader.query(level=level, tool=tool, since=since, limit=limit)
    return {"count": len(logs), "logs": logs}

@server.tool("agentic_log_analyze")
def analyze_logs(time_range="24h", focus="errors", top_n=10):
    reader = LogReader()
    analysis = reader.analyze(time_range=time_range, focus=focus, top_n=top_n)
    return analysis

@server.tool("agentic_log_stats")
def get_stats(since="24h", group_by="level"):
    reader = LogReader()
    stats = reader.stats(since=since, group_by=group_by)
    return stats
```

---

## 3. CLI

### 3.1 安装

```bash
pip install agentic-logger[cli]
```

### 3.2 命令概览

```bash
agentic-logger <command> [options]
```

| 命令 | 功能 |
|------|------|
| `tail` | 实时查看日志 |
| `query` | 查询过滤日志 |
| `stats` | 统计分析 |
| `export` | 导出日志 |
| `config` | 配置管理 |

---

### 3.3 `tail` - 实时查看

**用法**:
```bash
agentic-logger tail [options]
```

**选项**:

| 选项 | 说明 | 默认 |
|------|------|------|
| `-f, --follow` | 持续跟踪新日志 | false |
| `-n, --lines N` | 显示最后 N 行 | 20 |
| `-l, --level LEVEL` | 过滤级别 | all |
| `-t, --tool TOOL` | 过滤工具 | all |
| `--format FORMAT` | 输出格式: `json`, `table`, `pretty` | `pretty` |
| `--color` | 彩色输出 | true |

**示例**:
```bash
# 实时查看所有日志
agentic-logger tail -f

# 只看错误
agentic-logger tail -f -l ERROR

# 只看工具调用
agentic-logger tail -f -t bash

# JSON 输出 (便于 jq 处理)
agentic-logger tail -f --format json | jq .

# 最后 100 行
agentic-logger tail -n 100
```

**输出示例 (pretty)**:
```
2026-07-21 11:30:05 [ERROR] agent.bash: Build failed
  error: Exit code 1
  cmd: npm run build
  stderr: Error: Module not found

2026-07-21 11:30:06 [TOOL] agent.bash: Tool executed successfully
  tool: bash
  cmd: ls -la
  exit: 0
  duration: 50ms
```

---

### 3.4 `query` - 查询过滤

**用法**:
```bash
agentic-logger query [options]
```

**选项**:

| 选项 | 说明 |
|------|------|
| `-l, --level LEVEL` | 过滤级别 |
| `-t, --tool TOOL` | 过滤工具 |
| `-e, --exit-code CODE` | 过滤退出码 |
| `-s, --since TIME` | 起始时间 (ISO 8601 或 `1h`, `24h`) |
| `-u, --until TIME` | 截止时间 |
| `-k, --keyword TEXT` | 关键词搜索 |
| `--limit N` | 返回条数 (默认 100) |
| `--format FORMAT` | 输出格式 |

**示例**:
```bash
# 查询最近 1 小时的错误
agentic-logger query -l ERROR -s 1h

# 查询失败的 bash 命令
agentic-logger query -t bash -e 1

# 关键词搜索
agentic-logger query -k "npm install"

# 时间范围
agentic-logger query -s "2026-07-21T10:00:00Z" -u "2026-07-21T11:00:00Z"

# JSON 输出
agentic-logger query -l ERROR --format json
```

---

### 3.5 `stats` - 统计分析

**用法**:
```bash
agentic-logger stats [options]
```

**选项**:

| 选项 | 说明 | 默认 |
|------|------|------|
| `-s, --since TIME` | 起始时间 | `24h` |
| `-g, --group-by FIELD` | 分组: `level`, `tool`, `hour`, `module` | `level` |
| `--top N` | Top N 结果 | 10 |
| `--format FORMAT` | 输出格式 | `table` |

**示例**:
```bash
# 按级别统计
agentic-logger stats -g level

# 按工具统计
agentic-logger stats -g tool -s 7d

# 按小时统计
agentic-logger stats -g hour -s 24h
```

**输出示例**:
```
Level Statistics (last 24h)
┌──────────┬───────┬────────────┐
│ Level    │ Count │ Percentage │
├──────────┼───────┼────────────┤
│ INFO     │   800 │     64.8%  │
│ TOOL     │   250 │     20.3%  │
│ ERROR    │   100 │      8.1%  │
│ FILE_OP  │    84 │      6.8%  │
└──────────┴───────┴────────────┘
Total: 1234 entries
```

---

### 3.6 `export` - 导出日志

**用法**:
```bash
agentic-logger export [options]
```

**选项**:

| 选项 | 说明 |
|------|------|
| `-s, --since TIME` | 起始时间 |
| `-f, --format FORMAT` | 格式: `json`, `csv`, `jsonl` |
| `-o, --output FILE` | 输出文件 |

**示例**:
```bash
# 导出为 JSON
agentic-logger export -s 7d -f json -o logs.json

# 导出为 CSV
agentic-logger export -s 24h -f csv -o logs.csv

# 导出为 JSONL (保持原格式)
agentic-logger export -s 24h -f jsonl -o logs.jsonl
```

---

## 4. REST API

### 4.1 概述

HTTP REST API 用于系统集成。

**Base URL**: `http://localhost:8080/api/v1`

### 4.2 Endpoints

#### `GET /api/v1/logs` - 查询日志

**参数** (Query String):

| 参数 | 类型 | 说明 |
|------|------|------|
| `level` | string | 日志级别 |
| `tool` | string | 工具名称 |
| `exit_code` | integer | 退出码 |
| `since` | string | 起始时间 (ISO 8601) |
| `until` | string | 截止时间 |
| `keyword` | string | 关键词 |
| `limit` | integer | 返回条数 (默认 100) |

**示例**:
```bash
curl "http://localhost:8080/api/v1/logs?level=ERROR&since=2026-07-21T00:00:00Z&limit=50"
```

**响应**:
```json
{
  "count": 50,
  "logs": [
    {"ts": "...", "level": "ERROR", "msg": "..."},
    ...
  ]
}
```

---

#### `GET /api/v1/stats` - 统计分析

**参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `since` | string | 起始时间 |
| `group_by` | string | 分组方式 |

**示例**:
```bash
curl "http://localhost:8080/api/v1/stats?since=24h&group_by=level"
```

---

#### `POST /api/v1/analyze` - 深度分析

**请求体**:
```json
{
  "time_range": "24h",
  "focus": "errors",
  "top_n": 10
}
```

**示例**:
```bash
curl -X POST "http://localhost:8080/api/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{"time_range": "24h", "focus": "errors"}'
```

---

#### `GET /api/v1/stream` - 实时流 (WebSocket)

**连接**:
```bash
wscat -c "ws://localhost:8080/api/v1/stream?level=ERROR"
```

---

### 4.3 认证 (可选)

```bash
# API Key
curl -H "Authorization: Bearer YOUR_API_KEY" "http://localhost:8080/api/v1/logs"
```

---

## 5. Python SDK (读取端)

### 5.1 导入

```python
from agentic_logger import LogReader, LogAnalyzer
```

### 5.2 LogReader

```python
reader = LogReader(log_dir="./logs")

# 查询日志
logs = reader.query(level="ERROR", since="1h", limit=100)
for log in logs:
    print(log)

# 实时流
for log in reader.stream(level="ERROR"):
    print(log)
```

### 5.3 LogAnalyzer

```python
analyzer = LogAnalyzer(log_dir="./logs")

# 统计分析
stats = analyzer.stats(since="24h", group_by="level")
print(stats)

# 深度分析
analysis = analyzer.analyze(time_range="24h", focus="errors")
print(analysis.summary)
```

---

## 6. 高级功能

### 6.1 GLiNER 增强 (外部日志)

对于非 AgenticLogger 格式的外部日志，可使用 GLiNER 进行实体识别：

```python
from agentic_logger import ExternalLogParser

parser = ExternalLogParser(use_gliner=True)
result = parser.parse("2026-07-21 ERROR [module] Failed to connect")
# => {"ts": "...", "level": "ERROR", "module": "module", "msg": "Failed to connect"}
```

### 6.2 NuExtract 增强 (深度抽取)

```python
from agentic_logger import DeepExtractor

extractor = DeepExtractor(use_nuextract=True)
result = extractor.extract(error_logs)
# => {"root_cause": "...", "suggested_action": "..."}
```
