# 01 - 系统架构

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        写入层 (多语言 SDK)                       │
│  ┌─────────┐  ┌──────────┐  ┌─────┐  ┌────┐  ┌─────┐  ┌─────┐ │
│  │ Python  │  │ Node.js  │  │Bash │  │ Go │  │Rust │  │ ...  │ │
│  │  SDK    │  │  SDK     │  │ SDK │  │SDK │  │SDK  │  │      │ │
│  └────┬────┘  └────┬─────┘  └──┬──┘  └─┬──┘  └──┬──┘  └──┬──┘ │
│       └────────────┴────────────┴───────┴────────┴────────┘     │
│                              ↓                                   │
│                    统一 JSONL 写入协议                            │
└──────────────────────────────┬───────────────────────────────────┘
                               ↓
                ┌──────────────────────────┐
                │      存储层 (后端)        │
                │  ┌──────────────────┐    │
                │  │ JSONL (默认)     │    │
                │  │ - 流式追加       │    │
                │  │ - 可 grep/jq     │    │
                │  │ - 可压缩归档     │    │
                │  └──────────────────┘    │
                │  ┌──────────────────┐    │
                │  │ SQLite (可选)    │    │
                │  │ - 索引查询       │    │
                │  │ - 单文件部署     │    │
                │  └──────────────────┘    │
                │  ┌──────────────────┐    │
                │  │ PostgreSQL (未来)│    │
                │  │ - 大规模         │    │
                │  │ - 多用户         │    │
                │  └──────────────────┘    │
                └────────────┬─────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                        读取层 (多接口)                           │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ MCP Tool │  │   CLI    │  │ REST API  │  │  Python SDK  │  │
│  │(AI Agent)│  │ (人类)   │  │(系统集成) │  │  (程序调用)  │  │
│  └──────────┘  └──────────┘  └───────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心组件

### 2.1 写入 SDK (Write SDK)

**职责**: 提供多语言的结构化日志写入接口

**组件清单**:

| 组件 | 语言 | 包名 | 优先级 |
|------|------|------|--------|
| `agentic-logger-py` | Python | `agentic-logger` | P0 |
| `agentic-logger-js` | Node.js | `@agentic/logger` | P0 |
| `agentic-logger-sh` | Bash | `agentic_logger.sh` | P1 |
| `agentic-logger-go` | Go | `agenticlogger` | P2 |
| `agentic-logger-rs` | Rust | `agentic-logger` | P2 |

**统一 API 语义**:

所有 SDK 提供相同的语义接口，确保日志格式一致。

核心方法:
- `info(message, **context)` - 一般信息
- `warn(message, **context)` - 警告
- `error(message, error=None, **context)` - 错误
- `tool_call(tool, command, exit_code, duration_ms, ...)` - 工具调用
- `file_op(operation, path, success, size_bytes, ...)` - 文件操作
- `decision(choice, alternatives, reason, ...)` - 决策点

---

### 2.2 存储后端 (Storage Backend)

**职责**: 持久化结构化日志

**后端选择**:

| 后端 | 用途 | 优点 | 缺点 | 优先级 |
|------|------|------|------|--------|
| **JSONL** | 默认 | 流式、简单、可 grep | 查询慢 | P0 |
| **SQLite** | 可选 | 索引快、单文件 | 写入并发受限 | P1 |
| **PostgreSQL** | 未来 | 大规模、多用户 | 部署复杂 | P2 |

**默认配置**:
- 日志文件路径: `./logs/agentic-{date}.jsonl`
- 自动轮转: 每天 00:00 轮转
- 保留策略: 默认 30 天

---

### 2.3 读取接口 (Read Interface)

**职责**: 提供多方式的日志查询和分析

#### 2.3.1 MCP Tool

**目标用户**: AI Agent (Claude, Cursor 等)

**MCP Tools**:

| Tool | 功能 | 参数 |
|------|------|------|
| `agentic_log_query` | 查询日志 | `level`, `tool`, `since`, `limit` |
| `agentic_log_analyze` | 分析模式 | `time_range`, `focus` |
| `agentic_log_stats` | 统计分析 | `since`, `group_by` |
| `agentic_log_stream` | 实时流 | `level`, `tool` |

#### 2.3.2 CLI

**目标用户**: 人类开发者

**命令**:

| 命令 | 功能 | 示例 |
|------|------|------|
| `tail` | 实时查看 | `agentic-logger tail --level ERROR --follow` |
| `query` | 查询过滤 | `agentic-logger query --tool bash --since 1h` |
| `stats` | 统计分析 | `agentic-logger stats --group-by tool` |
| `export` | 导出日志 | `agentic-logger export --format json` |

#### 2.3.3 REST API

**目标用户**: 其他系统集成

**Endpoints**:

| Endpoint | Method | 功能 |
|----------|--------|------|
| `/api/v1/logs` | GET | 查询日志 |
| `/api/v1/stats` | GET | 统计分析 |
| `/api/v1/analyze` | POST | 深度分析 |
| `/api/v1/stream` | WebSocket | 实时流 |

---

## 3. 数据流

### 3.1 写入流程

```
Coding Agent 生成代码
    ↓
导入 SDK (from agentic_logger import agent_log)
    ↓
调用 API (agent_log.tool_call(...))
    ↓
SDK 内部处理
    ├─→ 添加 timestamp
    ├─→ 添加模块信息
    └─→ 序列化为 JSON
    ↓
写入 JSONL 文件 (追加模式)
```

### 3.2 读取流程 (CLI)

```
用户执行命令 (agentic-logger query --tool bash)
    ↓
CLI 解析参数
    ↓
读取 JSONL 文件 (流式)
    ↓
逐行解析 + 过滤
    ↓
格式化输出 (表格/JSON)
```

### 3.3 读取流程 (MCP)

```
AI Agent 调用 MCP Tool
    ↓
MCP Server 接收请求
    ↓
读取 JSONL/SQLite
    ↓
查询/分析
    ↓
返回结构化结果
```

---

## 4. 技术栈

### 4.1 写入 SDK

| 语言 | 技术栈 | 依赖 |
|------|--------|------|
| Python | 纯 Python (无外部依赖) | `orjson` (可选，加速 JSON) |
| Node.js | TypeScript + ESM | 无外部依赖 |
| Bash | Bash 4.0+ | `jq` (可选) |

### 4.2 存储后端

| 后端 | 技术栈 |
|------|--------|
| JSONL | 纯文件 IO |
| SQLite | `sqlite3` (Python stdlib) |

### 4.3 读取接口

| 接口 | 技术栈 |
|------|--------|
| MCP | Python + `mcp` SDK |
| CLI | Python + `click` |
| REST | Python + `fastapi` |

---

## 5. 部署架构

### 5.1 单机部署 (默认)

```
单进程
├─ SDK 写入 → JSONL 文件
└─ CLI/MCP 读取 → JSONL 文件
```

### 5.2 分布式部署 (未来)

```
多进程/多机
├─ SDK 写入 → 消息队列 (Kafka/Redis)
├─ Worker → 消费队列 → JSONL/PostgreSQL
└─ CLI/MCP/REST → 查询数据库
```

---

## 6. 性能目标

| 指标 | 目标 |
|------|------|
| 写入延迟 | < 1ms (追加到文件) |
| 读取延迟 (CLI query) | < 1s (1000 行) |
| 读取延迟 (MCP query) | < 2s (10000 行) |
| 并发写入 | 1000 QPS (单机) |
| 日志大小 | 单文件 < 1GB (自动轮转) |

---

## 7. 扩展性

### 7.1 未来扩展方向

- **更多 SDK**: Go, Rust, Java
- **更多后端**: Elasticsearch, ClickHouse
- **更多接口**: gRPC, GraphQL
- **高级功能**: 实时告警、可视化仪表板

### 7.2 插件机制

- **写入插件**: 自定义日志处理器
- **读取插件**: 自定义分析器
- **存储插件**: 自定义存储后端
