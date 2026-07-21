# 04 - 读取接口设计

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **Agent 优先** | MCP Tool 和 Python SDK 优先，人类可读性放低 |
| **丰富查询参数** | 支持按所有字段精确检索 (rid/level/module/error_code/tool/...) |
| **无 REST API** | 不提供 HTTP REST 接口 |
| **结构化返回** | 所有接口返回结构化数据，便于 Agent 解析 |

---

## 2. MCP Tool (Agent 优先)

### 2.1 概述

MCP (Model Context Protocol) 是 Agent 访问日志的主要接口。

### 2.2 MCP Tools 定义

---

#### `agentic_log_query` - 精确查询

**描述**: 按多条件组合查询日志，支持所有字段

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `rid` | string | ⚠️ | 运行 ID，串联一次完整流程 |
| `level` | string | ⚠️ | 日志级别 |
| `module` | string | ⚠️ | 模块名 (支持前缀匹配 `agent.*`) |
| `error_code` | string | ⚠️ | 错误码 |
| `tool` | string | ⚠️ | 工具名称 |
| `exit_code` | integer | ⚠️ | 退出码 |
| `op` | string | ⚠️ | 文件操作类型 |
| `path` | string | ⚠️ | 文件路径 (支持通配符) |
| `choice` | string | ⚠️ | 决策选择 |
| `keyword` | string | ⚠️ | 全文搜索 (msg + ctx) |
| `since` | string | ⚠️ | 起始时间 (ISO 8601 或 `1h`, `24h`) |
| `until` | string | ⚠️ | 截止时间 |
| `min_dur` | integer | ⚠️ | 最小耗时 (ms) |
| `max_dur` | integer | ⚠️ | 最大耗时 (ms) |
| `pid` | string | ⚠️ | 进程 ID |
| `tid` | string | ⚠️ | 堆栈跟踪 ID |
| `limit` | integer | ⚠️ | 返回条数 (默认 100) |
| `offset` | integer | ⚠️ | 分页偏移 |
| `order_by` | string | ⚠️ | 排序: `ts_asc`, `ts_desc`, `dur_desc` (默认 `ts_desc`) |
| `file_pattern` | string | ⚠️ | 日志文件名匹配 (如 `*main*2026-07-21*`) |

**示例调用**:
```json
{
  "tool": "agentic_log_query",
  "arguments": {
    "rid": "550e8400",
    "level": "ERROR",
    "min_dur": 1000,
    "order_by": "dur_desc",
    "limit": 20
  }
}
```

**返回**:
```json
{
  "count": 15,
  "total": 15,
  "logs": [
    {
      "ts": "2026-07-21T11:30:05.678+08:00",
      "level": "ERROR",
      "msg": "Build failed",
      "module": "agent.bash",
      "rid": "550e8400",
      "pid": "12345",
      "error_code": "BUILD_FAIL",
      "dur": 5000,
      "ctx": {"cmd": "npm run build"}
    }
  ],
  "query_info": {
    "backend": "sqlite",
    "scan_time_ms": 12,
    "files_scanned": 3
  }
}
```

---

#### `agentic_log_trace` - 链路追踪

**描述**: 按 rid 查询一次完整运行的所有日志，自动按时间排序

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `rid` | string | ✅ | 运行 ID |
| `level` | string | ⚠️ | 过滤级别 |
| `module` | string | ⚠️ | 过滤模块 |
| `include_traceback` | boolean | ⚠️ | 是否包含完整堆栈 (默认 false) |

**示例调用**:
```json
{
  "tool": "agentic_log_trace",
  "arguments": {
    "rid": "550e8400",
    "include_traceback": true
  }
}
```

**返回**:
```json
{
  "rid": "550e8400",
  "program": "my_agent",
  "command": "main",
  "start_time": "2026-07-21T10:30:00.000+08:00",
  "end_time": "2026-07-21T10:35:00.000+08:00",
  "total_duration_ms": 300000,
  "entry_count": 42,
  "trace": [
    {"ts": "...", "level": "INFO", "msg": "Agent started", "module": "__lifecycle__", ...},
    {"ts": "...", "level": "TOOL", "msg": "...", "module": "agent.bash", ...},
    ...
  ],
  "summary": {
    "info_count": 30,
    "warn_count": 5,
    "error_count": 7,
    "tool_calls": 10,
    "file_ops": 15,
    "decisions": 2
  }
}
```

---

#### `agentic_log_analyze` - 深度分析

**描述**: 分析日志模式和趋势

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `rid` | string | ⚠️ | 运行 ID (限定分析范围) |
| `time_range` | string | ⚠️ | 时间范围 (如 `1h`, `24h`, `7d`) |
| `focus` | string | ⚠️ | 分析焦点: `errors`, `tool_calls`, `decisions`, `performance`, `all` |
| `error_code` | string | ⚠️ | 按错误码过滤 |
| `module` | string | ⚠️ | 按模块过滤 |
| `min_dur` | integer | ⚠️ | 最小耗时 (ms) |
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
  "error_code_distribution": [
    {"error_code": "BUILD_FAIL", "count": 8, "last_seen": "...", "avg_dur_ms": 5000},
    {"error_code": "FILE_NOT_FOUND", "count": 5, "last_seen": "...", "avg_dur_ms": 10}
  ],
  "module_distribution": [
    {"module": "agent.bash", "error_count": 10},
    {"module": "agent.file", "error_count": 5}
  ],
  "performance_hotspots": [
    {"module": "agent.bash", "avg_dur_ms": 3000, "p99_dur_ms": 15000},
    {"module": "agent.coder", "avg_dur_ms": 1500, "p99_dur_ms": 8000}
  ],
  "recommendations": [
    "bash 命令失败率较高 (40%)，建议检查依赖安装",
    "coder 模块 P99 延迟 8s，建议优化代码生成逻辑"
  ]
}
```

---

#### `agentic_log_stats` - 统计分析

**描述**: 获取日志统计信息

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `rid` | string | ⚠️ | 运行 ID |
| `since` | string | ⚠️ | 起始时间 |
| `until` | string | ⚠️ | 截止时间 |
| `group_by` | string | ⚠️ | 分组: `level`, `tool`, `module`, `error_code`, `hour`, `pid` |
| `file_pattern` | string | ⚠️ | 文件名匹配 |

**示例调用**:
```json
{
  "tool": "agentic_log_stats",
  "arguments": {
    "since": "24h",
    "group_by": "error_code"
  }
}
```

**返回**:
```json
{
  "total_entries": 1234,
  "time_range": {"since": "2026-07-20T11:00:00Z", "until": "2026-07-21T11:00:00Z"},
  "groups": [
    {"key": "BUILD_FAIL", "count": 8, "percentage": 40.0},
    {"key": "FILE_NOT_FOUND", "count": 5, "percentage": 25.0},
    {"key": "PARSE_JSON", "count": 4, "percentage": 20.0},
    {"key": "EXEC_RUNTIME", "count": 3, "percentage": 15.0}
  ],
  "files_scanned": 5,
  "scan_time_ms": 23
}
```

---

#### `agentic_log_stream` - 实时流

**描述**: 实时订阅日志流

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `level` | string | ⚠️ | 过滤级别 |
| `module` | string | ⚠️ | 过滤模块 |
| `error_code` | string | ⚠️ | 过滤错误码 |
| `rid` | string | ⚠️ | 过滤运行 ID |
| `file_pattern` | string | ⚠️ | 文件名匹配 |
| `duration` | string | ⚠️ | 持续时间 (如 `5m`, `1h`) |

---

#### `agentic_log_traceback` - 获取堆栈跟踪

**描述**: 按 tid 获取完整堆栈跟踪

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `tid` | string | ✅ | 堆栈跟踪引用 ID |

**返回**:
```json
{
  "tid": "trace_001",
  "traceback": "Traceback (most recent call last):\n  File \"main.py\", line 42, ...\nValueError: ...",
  "exception_type": "ValueError",
  "exception_msg": "..."
}
```

---

### 2.3 MCP Server 实现

```python
from mcp.server import Server
from agentic_logger import LogQueryEngine

server = Server("agentic-logger")

@server.tool("agentic_log_query")
def query_logs(
    rid=None, level=None, module=None, error_code=None,
    tool=None, exit_code=None, op=None, path=None,
    choice=None, keyword=None, since=None, until=None,
    min_dur=None, max_dur=None, pid=None, tid=None,
    limit=100, offset=0, order_by="ts_desc",
    file_pattern=None
):
    engine = LogQueryEngine()
    results = engine.query(
        rid=rid, level=level, module=module, error_code=error_code,
        tool=tool, exit_code=exit_code, op=op, path=path,
        choice=choice, keyword=keyword, since=since, until=until,
        min_dur=min_dur, max_dur=max_dur, pid=pid, tid=tid,
        limit=limit, offset=offset, order_by=order_by,
        file_pattern=file_pattern
    )
    return results
```

---

## 3. CLI (人类辅助调试)

### 3.1 安装

```bash
pip install agentic-logger[cli]
```

### 3.2 命令概览

| 命令 | 功能 | 人类可读性 |
|------|------|-----------|
| `query` | 多条件查询 | 中 (支持表格/JSON) |
| `trace` | 链路追踪 | 中 |
| `stats` | 统计分析 | 中 |
| `tail` | 实时查看 | 低 (原始 JSONL) |
| `traceback` | 获取堆栈 | 低 |
| `list-files` | 列出日志文件 | 高 |

### 3.3 `query` 命令

**支持所有查询参数**：

```bash
# 按运行 ID 查询
agentic-logger query --rid 550e8400

# 按错误码查询
agentic-logger query --error-code BUILD_FAIL

# 按模块查询 (支持前缀)
agentic-logger query --module "agent.*"

# 按耗时范围查询
agentic-logger query --min-dur 1000 --max-dur 10000

# 按工具查询
agentic-logger query --tool bash --exit-code 1

# 按文件路径查询 (支持通配符)
agentic-logger query --path "*.py"

# 按决策查询
agentic-logger query --level DECISION --choice "use_async"

# 组合查询
agentic-logger query --rid 550e8400 --level ERROR --min-dur 1000 --order-by dur_desc --limit 20

# 按文件名模式查询
agentic-logger query --file-pattern "*main*2026-07-21*"

# JSON 输出 (便于 jq 处理)
agentic-logger query --error-code BUILD_FAIL --format json | jq .
```

**完整选项**：

| 选项 | 说明 |
|------|------|
| `--rid RID` | 运行 ID |
| `--level LEVEL` | 日志级别 |
| `--module MODULE` | 模块名 (支持 `*` 通配) |
| `--error-code CODE` | 错误码 |
| `--tool TOOL` | 工具名称 |
| `--exit-code CODE` | 退出码 |
| `--op OP` | 文件操作类型 |
| `--path PATH` | 文件路径 (支持通配) |
| `--choice CHOICE` | 决策选择 |
| `--keyword TEXT` | 全文搜索 |
| `--since TIME` | 起始时间 |
| `--until TIME` | 截止时间 |
| `--min-dur MS` | 最小耗时 (ms) |
| `--max-dur MS` | 最大耗时 (ms) |
| `--pid PID` | 进程 ID |
| `--tid TID` | 堆栈跟踪 ID |
| `--limit N` | 返回条数 (默认 100) |
| `--offset N` | 分页偏移 |
| `--order-by FIELD` | 排序: `ts_asc`, `ts_desc`, `dur_desc` |
| `--file-pattern PATTERN` | 文件名匹配 |
| `--format FMT` | 输出: `table`, `json`, `jsonl`, `csv` |

---

### 3.4 `trace` 命令

```bash
# 追踪一次完整运行
agentic-logger trace --rid 550e8400

# 包含堆栈跟踪
agentic-logger trace --rid 550e8400 --include-traceback

# 过滤级别
agentic-logger trace --rid 550e8400 --level ERROR
```

---

### 3.5 `stats` 命令

```bash
# 按错误码统计
agentic-logger stats --group-by error_code --since 24h

# 按模块统计
agentic-logger stats --group-by module

# 按小时统计
agentic-logger stats --group-by hour --since 7d

# 按进程统计
agentic-logger stats --group-by pid

# 按文件名统计
agentic-logger stats --group-by file
```

---

### 3.6 `tail` 命令

```bash
# 实时查看 (原始 JSONL)
agentic-logger tail --follow

# 过滤级别
agentic-logger tail --follow --level ERROR

# 过滤文件
agentic-logger tail --follow --file-pattern "*main*"
```

---

### 3.7 `traceback` 命令

```bash
# 获取堆栈跟踪
agentic-logger traceback --tid trace_001
```

---

### 3.8 `list-files` 命令

```bash
# 列出所有日志文件
agentic-logger list-files

# 按日期过滤
agentic-logger list-files --since 2026-07-20

# 按程序名过滤
agentic-logger list-files --program my_agent

# 显示文件大小
agentic-logger list-files --size
```

**输出示例**:
```
File                                          Size    Entries  Backend
my_agent_main_2026-07-21_103000.jsonl         2.3MB   1234     jsonl
my_agent_worker_2026-07-21_103005.sqlite      15MB    45678    sqlite
build_script_npm_2026-07-21_110000.jsonl      0.5MB   234      jsonl
```

---

## 4. Python SDK (读取端)

### 4.1 导入

```python
from agentic_logger import LogQueryEngine
```

### 4.2 查询

```python
engine = LogQueryEngine(log_dir="./logs")

# 精确查询
logs = engine.query(
    rid="550e8400",
    level="ERROR",
    min_dur=1000,
    order_by="dur_desc",
    limit=20
)

# 链路追踪
trace = engine.trace(rid="550e8400", include_traceback=True)

# 统计分析
stats = engine.stats(since="24h", group_by="error_code")

# 深度分析
analysis = engine.analyze(time_range="24h", focus="errors", top_n=5)

# 实时流
for log in engine.stream(level="ERROR", rid="550e8400"):
    print(log)
```

---

## 5. 查询引擎实现

### 5.1 统一查询接口

```python
class LogQueryEngine:
    """统一查询引擎，自动选择 JSONL 或 SQLite 后端"""
    
    def __init__(self, log_dir="./logs"):
        self.log_dir = Path(log_dir)
    
    def query(self, **filters):
        """多条件查询"""
        backends = self._detect_backends()
        results = []
        
        for backend in backends:
            results.extend(backend.query(**filters))
        
        # 排序 + 分页
        results = self._sort_and_paginate(results, **filters)
        return results
    
    def _detect_backends(self):
        """扫描日志目录，检测所有后端"""
        backends = []
        for f in self.log_dir.iterdir():
            if f.suffix == ".jsonl":
                backends.append(JSONLBackend(file_path=f))
            elif f.suffix == ".sqlite":
                backends.append(SQLiteBackend(file_path=f))
        return backends
```

### 5.2 JSONL 查询 (流式解析)

```python
class JSONLBackend:
    def query(self, **filters):
        results = []
        with open(self.file_path, 'r') as f:
            for line in f:
                entry = json.loads(line)
                if self._match(entry, filters):
                    results.append(entry)
        return results
    
    def _match(self, entry, filters):
        """多字段匹配"""
        for key, value in filters.items():
            if value is None:
                continue
            if key == "module" and "*" in value:
                # 通配符匹配
                import fnmatch
                if not fnmatch.fnmatch(entry.get("module", ""), value):
                    return False
            elif key == "min_dur":
                if (entry.get("dur") or 0) < value:
                    return False
            elif key == "max_dur":
                if (entry.get("dur") or 0) > value:
                    return False
            elif key in entry and entry[key] != value:
                return False
        return True
```

### 5.3 SQLite 查询 (索引加速)

```python
class SQLiteBackend:
    def query(self, **filters):
        query = "SELECT * FROM logs WHERE 1=1"
        params = []
        
        if filters.get("rid"):
            query += " AND rid = ?"
            params.append(filters["rid"])
        if filters.get("level"):
            query += " AND level = ?"
            params.append(filters["level"])
        if filters.get("error_code"):
            query += " AND error_code = ?"
            params.append(filters["error_code"])
        if filters.get("min_dur"):
            query += " AND dur >= ?"
            params.append(filters["min_dur"])
        # ... 其他字段
        
        query += f" ORDER BY ts DESC LIMIT {filters.get('limit', 100)}"
        
        cursor = self.conn.execute(query, params)
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
```
