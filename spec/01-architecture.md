# 01 - 系统架构

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│              写入层 (Python SDK 为 MVP)                         │
│  ┌─────────┐  ┌──────────┐  ┌─────┐                           │
│  │ Python  │  │ Node.js  │  │Bash │  ...后续扩展              │
│  │  SDK    │  │  SDK     │  │ SDK │                           │
│  └────┬────┘  └────┬─────┘  └──┬──┘                           │
│       └────────────┴────────────┘                               │
│              ↓ 统一写入协议 (新字段: rid/tid/pid/dur/ErrorCode) │
└──────────────────────────────┬───────────────────────────────────┘
                               ↓
                ┌──────────────────────────┐
                │      存储层 (双后端)      │
                │                          │
                │  ┌──────────────────┐    │
                │  │ JSONL            │    │
                │  │ (小文件场景)     │    │
                │  │ - 流式追加       │    │
                │  │ - 可 grep/jq     │    │
                │  └──────────────────┘    │
                │  ┌──────────────────┐    │
                │  │ SQLite + WAL     │    │
                │  │ (大文件/多进程)  │    │
                │  │ - 索引查询       │    │
                │  │ - 并发读写       │    │
                │  └──────────────────┘    │
                └────────────┬─────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                    读取层 (Agent 优先)                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ MCP Tool         │  │ CLI              │  │ Python SDK   │  │
│  │ (Agent高效访问)  │  │ (人类辅助调试)   │  │ (程序调用)   │  │
│  │ 优先保证         │  │ 可读性放低       │  │              │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 设计原则变更

| 原则 | 说明 |
|------|------|
| **Agent 优先** | 优先保证 Agent 高效访问，人类可读性优先级放低 |
| **结构化优先** | 日志写入时即为结构化，所有字段面向程序解析 |
| **信息丰富** | 包含 rid/tid/pid/dur/ErrorCode 等丰富字段，便于 Agent 精确检索 |
| **MVP 优先** | Python SDK 作为 MVP，验证核心设计后再扩展多语言 |

---

## 2. 核心组件

### 2.1 写入 SDK

**MVP**: Python SDK，后续扩展到 Node.js / Bash / Go / Rust

**核心方法** (所有方法均需支持新字段 rid/tid/pid/dur/ErrorCode/ctx)：

| 方法 | 说明 |
|------|------|
| `info(msg, module, rid, ...)` | 一般信息 |
| `warn(msg, module, rid, ...)` | 警告 |
| `error(msg, module, rid, error_code, ...)` | 错误 |
| `tool_call(tool, cmd, exit, dur, rid, ...)` | 工具调用 |
| `file_op(op, path, ok, rid, ...)` | 文件操作 |
| `decision(choice, alts, reason, rid, ...)` | 决策点 |
| `code_gen(lang, path, rid, ...)` | 代码生成 |
| `context_switch(from_task, to_task, rid, ...)` | 上下文切换 |

---

### 2.2 存储后端

**双后端策略**：

| 后端 | 适用场景 | 优先级 |
|------|---------|--------|
| **JSONL** | 日志文件较小 (< 阈值) | P0 |
| **SQLite + WAL** | 日志文件较大 / 多进程并发读写 | P0 |

**不再考虑 PostgreSQL**。

**存储后端自动选择逻辑**:
```python
if file_size < THRESHOLD and not multi_process:
    use JSONLBackend()
else:
    use SQLiteBackend(wal_mode=True)
```

---

### 2.3 日志文件命名

**每次运行生成独立文件**，文件名包含程序/命令标识和运行日期：

**格式**: `{program_name}_{command_or_pid}_{YYYY-MM-DD}_{HHmmss}.jsonl`

**示例**:
```
logs/
├── my_agent_main_2026-07-21_103000.jsonl
├── my_agent_worker_2026-07-21_103005.jsonl
├── build_script_npm_install_2026-07-21_110000.jsonl
└── coder_agent_pid12345_2026-07-21_113000.jsonl
```

**字段说明**:
- `program_name`: 程序名 (如 `my_agent`, `build_script`)
- `command_or_pid`: 子命令名或进程ID
- `YYYY-MM-DD`: 运行日期
- `HHmmss`: 启动时间 (时/分/秒)

---

### 2.4 循环写入模式

**对于较大的日志文件**，采用循环写入 (circular/ring buffer)：

```
文件达到大小上限 → 从头部覆盖旧数据 → 始终保持最近 N 条日志
```

**配置**:
```python
configure(
    storage="sqlite",
    max_size_mb=500,      # 文件最大 500MB
    circular=True,        # 启用循环写入
    retention_count=100000  # 保留最近 10 万条
)
```

---

### 2.5 读取接口

**Agent 优先**，人类可读性放低。

| 接口 | 目标用户 | 优先级 | 说明 |
|------|---------|--------|------|
| **MCP Tool** | AI Agent | P0 | 丰富的查询参数，结构化返回 |
| **CLI** | 人类 | P1 | 辅助调试，可读性次要 |
| **Python SDK** | 程序 | P0 | 直接 API 调用 |

**不再提供 REST API**。

---

## 3. 数据流

### 3.1 写入流程

```
Coding Agent 生成代码
    ↓
导入 SDK (from agentic_logger import agent_log)
    ↓
初始化 (设置 program_name, rid, 存储后端)
    ↓
调用 API (agent_log.tool_call(...))
    ↓
SDK 内部处理
    ├─→ 自动填充 ts, pid/seq, module
    ├─→ 序列化 (含 rid/tid/dur/ErrorCode)
    └─→ 选择存储后端 (JSONL or SQLite+WAL)
    ↓
写入 {program}_{cmd}_{date}_{time}.jsonl
```

### 3.2 读取流程 (MCP)

```
AI Agent 调用 MCP Tool
    ↓
MCP Server 接收请求 (丰富参数: rid/level/module/error_code/tool/...)
    ↓
根据文件大小选择读取路径
    ├─→ JSONL: 流式解析 + 过滤
    └─→ SQLite: SQL 查询 (WAL 模式)
    ↓
返回结构化结果 (Agent 可直接解析)
```

---

## 4. 技术栈

### 4.1 MVP (Python)

| 组件 | 技术栈 |
|------|--------|
| SDK | 纯 Python (无外部依赖) |
| JSONL 存储 | 纯文件 IO |
| SQLite 存储 | `sqlite3` (stdlib) + WAL |
| MCP | `mcp` SDK |
| CLI | `click` |

### 4.2 后续扩展

| 组件 | 技术栈 |
|------|--------|
| Node.js SDK | TypeScript + ESM |
| Bash SDK | Bash 4.0+ |

---

## 5. 性能目标

| 指标 | 目标 |
|------|------|
| 写入延迟 | < 1ms (JSONL), < 5ms (SQLite WAL) |
| 读取延迟 (MCP) | < 500ms (10000 行) |
| 多进程并发写入 | SQLite WAL 模式支持 |
| 循环写入 | 文件大小可控，旧数据自动覆盖 |

---

## 6. 与旧版差异

| 方面 | 旧版 | 新版 |
|------|------|------|
| 首要目标 | 人类可读 | Agent 高效访问 |
| 存储后端 | JSONL → SQLite → PostgreSQL | JSONL + SQLite (WAL), 无 PostgreSQL |
| 读取接口 | MCP + CLI + REST API + SDK | MCP + CLI + SDK, 无 REST API |
| SDK 优先级 | Python + Node.js + Bash 并行 | Python MVP 优先 |
| 日志字段 | 基础字段 | 丰富字段 (rid/tid/pid/dur/ErrorCode/ctx) |
| 文件命名 | `agentic-{date}.jsonl` | `{program}_{cmd}_{date}_{time}.jsonl` |
| 大文件策略 | 按日轮转 | 循环写入 |
