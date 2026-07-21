# AgenticLogger 设计规范

**版本**: v1.0.0  
**创建时间**: 2026-07-21  
**状态**: Draft

---

## 文档索引

| 文档 | 描述 | 状态 |
|------|------|------|
| [01-architecture.md](./01-architecture.md) | 系统架构概览 | ✅ |
| [02-log-format.md](./02-log-format.md) | 日志格式规范 (JSONL Schema) | ✅ |
| [03-write-sdk.md](./03-write-sdk.md) | 写入 SDK API 设计 | ✅ |
| [04-read-interface.md](./04-read-interface.md) | 读取接口设计 (MCP/CLI/REST) | ✅ |
| [05-storage.md](./05-storage.md) | 存储后端设计 | ✅ |
| [06-implementation.md](./06-implementation.md) | 实施计划 | ✅ |
| [07-testing.md](./07-testing.md) | 测试策略 | ✅ |

---

## 项目概述

**AgenticLogger** 是专为 Coding Agent 设计的结构化日志管理系统。

**核心价值**:
- 让 Coding Agent 生成的代码能够输出**结构化日志**
- 通过专门的工具进行**高效的信息提取和分析**
- 只提取有效信息送给 LLM，**节省推理时间和 token 消耗**

**目标用户**:
- **写入端**: Coding Agent (Claude, Cursor, Copilot 等) 生成的程序/脚本
- **读取端**: AI Agent (通过 MCP)、人类开发者 (通过 CLI)、其他系统 (通过 REST API)

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **结构化优先** | 日志写入时即为结构化，避免后续解析 |
| **独立命名空间** | 独立库，不与标准 `logging` 混淆 |
| **语义化 API** | 方法名清晰表达意图 (`tool_call`, `file_op`, `decision`) |
| **多语言支持** | 写入 SDK 支持 Python/Node.js/Bash 等 |
| **多接口读取** | MCP (AI Agent) + CLI (人类) + REST (系统集成) |
| **流式友好** | 默认 JSONL 格式，支持 `tail -f` 实时监控 |

---

## 快速开始

### 写入日志 (Python SDK)

```python
from agentic_logger import agent_log

# 基础日志
agent_log.info("Processing started", module="parser")

# 工具调用
agent_log.tool_call(
    tool="bash",
    command="npm install express",
    exit_code=0,
    duration_ms=1234,
    stdout_summary="added 50 packages"
)

# 文件操作
agent_log.file_op(
    operation="write",
    path="/path/to/file.py",
    success=True,
    size_bytes=1024
)

# 决策点
agent_log.decision(
    choice="use_async",
    alternatives=["sync", "async"],
    reason="IO-bound workload"
)
```

### 读取日志 (CLI)

```bash
# 实时查看错误
agentic-logger tail --level ERROR --follow

# 查询工具调用
agentic-logger query --tool bash --exit-code 1 --since 1h

# 统计分析
agentic-logger stats --group-by tool --since 24h
```

### 读取日志 (MCP Tool)

```
Call MCP: agentic_log_query(level="ERROR", since="2026-07-21T00:00:00Z", limit=100)
Call MCP: agentic_log_analyze(focus="errors", time_range="24h")
Call MCP: agentic_log_stats(group_by="tool", since="24h")
```

---

## 相关文档

- **技术调研**: `research_reports/agentic-log-management/report.md`
- **执行摘要**: `research_reports/agentic-log-management/executive_summary.md`
- **项目想法**: `idea/` (待生成)

---

## 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-07-21 | v1.0.0 | 初始版本 |
