# AgenticLogger 设计规范

**版本**: v1.1.0  
**创建时间**: 2026-07-21  
**更新时间**: 2026-07-21  
**状态**: Draft

---

## 文档索引

| 文档 | 描述 | 状态 |
|------|------|------|
| [01-architecture.md](./01-architecture.md) | 系统架构概览 | ✅ v1.1 |
| [02-log-format.md](./02-log-format.md) | 日志格式规范 (JSONL Schema) | ✅ v1.1 |
| [03-write-sdk.md](./03-write-sdk.md) | 写入 SDK API 设计 | ✅ v1.1 |
| [04-read-interface.md](./04-read-interface.md) | 读取接口设计 (MCP/CLI) | ✅ v1.1 |
| [05-storage.md](./05-storage.md) | 存储后端设计 | ✅ v1.1 |
| [06-implementation.md](./06-implementation.md) | 实施计划 (Python MVP) | ✅ v1.1 |
| [07-testing.md](./07-testing.md) | 测试策略 | ✅ v1.1 |

---

## 项目概述

**AgenticLogger** 是专为 Coding Agent 设计的结构化日志管理系统。

**核心价值**:
- 让 Coding Agent 生成的代码能够输出**结构化日志**
- 通过专门的工具进行**高效的信息提取和分析**
- 只提取有效信息送给 LLM，**节省推理时间和 token 消耗**

**设计原则** (v1.1):
- **Agent 优先**: 优先保证 Agent 高效访问，人类可读性放低
- **信息丰富**: 包含 rid/tid/pid/dur/ErrorCode/ctx 等丰富字段
- **Python MVP**: Python SDK 先行，验证后扩展多语言
- **双后端**: JSONL (小文件) + SQLite WAL (大文件/多进程)

---

## 快速开始

### 写入日志 (Python SDK)

```python
from agentic_logger import AgentLogger

logger = AgentLogger(program="my_agent", command="main")

# 基础日志 (自动填充 ts/pid/rid)
logger.info("Processing started", module="parser", ctx={"file": "data.json"})

# 工具调用
logger.tool_call(
    tool="bash",
    cmd="npm install express",
    exit=0,
    dur=1234,
    stdout="added 50 packages"
)

# 错误 (error_code 必填)
logger.error("Build failed", module="builder", error_code="BUILD_FAIL")

# 决策记录
logger.decision(choice="use_async", alts=["sync"], reason="IO-bound")
```

### 读取日志 (MCP Tool)

```
Call MCP: agentic_log_query(rid="550e8400", level="ERROR", min_dur=1000)
Call MCP: agentic_log_trace(rid="550e8400")
Call MCP: agentic_log_analyze(focus="errors", time_range="24h")
Call MCP: agentic_log_stats(group_by="error_code", since="24h")
```

### 读取日志 (CLI)

```bash
# 多条件查询
agentic-logger query --rid 550e8400 --level ERROR --min-dur 1000 --order-by dur_desc

# 链路追踪
agentic-logger trace --rid 550e8400 --include-traceback

# 统计分析
agentic-logger stats --group-by error_code --since 24h
```

---

## v1.1 变更摘要 (相比 v1.0)

| 变更 | v1.0 | v1.1 |
|------|------|------|
| **实施策略** | 多语言并行 | Python MVP 优先 |
| **设计目标** | 人类可读优先 | Agent 高效访问优先 |
| **存储后端** | JSONL → SQLite → PostgreSQL | JSONL + SQLite WAL (无 PostgreSQL) |
| **读取接口** | MCP + CLI + REST API + SDK | MCP + CLI + SDK (无 REST API) |
| **日志字段** | 基础字段 | 丰富字段: rid/tid/pid/dur/error_code/ctx |
| **文件命名** | `agentic-{date}.jsonl` | `{program}_{cmd}_{date}_{time}.jsonl` |
| **大文件策略** | 按日轮转 | 循环写入 |
| **查询参数** | 基础过滤 | 丰富参数: 所有字段可检索 |

---

## 日志格式核心字段

| 字段 | 说明 |
|------|------|
| `ts` | 毫秒级时间戳 |
| `level` | 日志级别 |
| `module` | 模块/class/函数名 |
| `msg` | 简短描述 |
| `tid` | 堆栈跟踪引用 ID |
| `rid` | 运行 ID (串联一次完整流程) |
| `pid` | 进程 ID |
| `dur` | 操作耗时 (ms) |
| `error_code` | 结构化错误码 |
| `ctx` | 关键上下文键值对 |

---

## 相关文档

- **技术调研**: `research_reports/agentic-log-management/report.md`
- **执行摘要**: `research_reports/agentic-log-management/executive_summary.md`

---

## 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-07-21 | v1.0.0 | 初始版本 |
| 2026-07-21 | v1.1.0 | Python MVP 优先; Agent 优先设计; 丰富字段; 双后端; 新文件命名; 循环写入; 移除 REST/PostgreSQL |
