# 06 - 实施计划

## 1. 策略变更

**原计划**: Python + Node.js + Bash 并行 → MCP → CLI → REST API

**新计划**: **Python MVP 优先** → 验证核心设计 → 再扩展

```
Phase 1 (2周)  ──→  Python SDK + 存储后端 (JSONL + SQLite WAL) [MVP]
Phase 2 (1周)  ──→  MCP Server (丰富查询参数)
Phase 3 (1周)  ──→  CLI (辅助调试)
Phase 4 (1周)  ──→  循环写入 + 堆栈跟踪 + 完善
Phase 5 (1周)  ──→  文档 + 测试 + 发布
```

**总计**: 6 周

---

## 2. Phase 1: Python MVP (2周)

### 2.1 Week 1: SDK 核心 + JSONL

**目标**: 可用的 Python SDK，支持 JSONL 存储

**任务清单**:

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| 项目初始化 (pyproject.toml) | P0 | 2h | `pyproject.toml` |
| `AgentLogger` 类框架 | P0 | 3h | `core/logger.py` |
| 新字段自动填充 (ts/pid/rid) | P0 | 2h | `core/fields.py` |
| 日志文件名生成 (program_cmd_date_time) | P0 | 2h | `core/filename.py` |
| JSONL 后端 | P0 | 4h | `storage/jsonl.py` |
| 全局上下文写入 | P0 | 2h | `storage/jsonl.py` |
| `info/warn/error` 方法 | P0 | 3h | `api/basic.py` |
| `tool_call` 方法 | P0 | 2h | `api/tool.py` |
| `file_op` 方法 | P0 | 2h | `api/file.py` |
| `decision/code_gen/context_switch` | P1 | 3h | `api/special.py` |
| `save_traceback` 方法 | P1 | 2h | `api/traceback.py` |
| `set_global_context` 方法 | P1 | 2h | `api/context.py` |
| `run_start/run_end` 生命周期 | P1 | 2h | `api/lifecycle.py` |
| 单元测试 | P0 | 6h | `tests/` |

**Week 1 交付标准**:
```python
from agentic_logger import AgentLogger

logger = AgentLogger(program="test", command="unit")
logger.info("Hello", module="test")
logger.tool_call(tool="bash", cmd="ls", exit=0, dur=50)
logger.error("Failed", module="test", error_code="TEST_FAIL")
# 输出: logs/test_unit_2026-07-21_HHMMSS.jsonl
```

---

### 2.2 Week 2: SQLite + 查询

**目标**: SQLite WAL 后端 + 查询能力

**任务清单**:

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| SQLite 后端 | P0 | 6h | `storage/sqlite.py` |
| WAL 模式配置 | P0 | 2h | `storage/sqlite.py` |
| 自动后端选择 (auto) | P0 | 3h | `storage/auto.py` |
| 堆栈跟踪分离存储 | P1 | 3h | `storage/traceback.py` |
| `LogQueryEngine` 框架 | P0 | 3h | `query/engine.py` |
| JSONL 查询 (流式) | P0 | 4h | `query/jsonl_reader.py` |
| SQLite 查询 (索引) | P0 | 4h | `query/sqlite_reader.py` |
| 多条件查询 (所有字段) | P0 | 4h | `query/filters.py` |
| 集成测试 | P0 | 6h | `tests/integration/` |
| 性能测试 | P1 | 3h | `tests/performance/` |

**Week 2 交付标准**:
```python
# 写入 (自动选择后端)
logger = AgentLogger(program="test", storage="auto")

# 查询
from agentic_logger import LogQueryEngine
engine = LogQueryEngine(log_dir="./logs")
results = engine.query(rid="xxx", level="ERROR", min_dur=1000)
trace = engine.trace(rid="xxx")
```

---

## 3. Phase 2: MCP Server (1周)

### 3.1 MCP Tools 实现

**任务清单**:

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| MCP Server 框架 | P0 | 4h | `mcp/server.py` |
| `agentic_log_query` (丰富参数) | P0 | 6h | `mcp/query.py` |
| `agentic_log_trace` | P0 | 4h | `mcp/trace.py` |
| `agentic_log_analyze` | P1 | 4h | `mcp/analyze.py` |
| `agentic_log_stats` | P1 | 3h | `mcp/stats.py` |
| `agentic_log_stream` | P2 | 3h | `mcp/stream.py` |
| `agentic_log_traceback` | P1 | 2h | `mcp/traceback.py` |
| Claude Code 集成测试 | P0 | 4h | 测试报告 |
| MCP 文档 | P0 | 3h | `docs/mcp.md` |

**交付标准**:
```
Claude: Call MCP agentic_log_query(rid="550e8400", level="ERROR", min_dur=1000)
=> 返回结构化结果
```

---

## 4. Phase 3: CLI (1周)

### 4.1 CLI 实现

**任务清单**:

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| click 框架 | P0 | 2h | `cli/main.py` |
| `query` 命令 (丰富参数) | P0 | 6h | `cli/query.py` |
| `trace` 命令 | P0 | 4h | `cli/trace.py` |
| `stats` 命令 | P1 | 3h | `cli/stats.py` |
| `tail` 命令 | P1 | 3h | `cli/tail.py` |
| `traceback` 命令 | P1 | 2h | `cli/traceback_cmd.py` |
| `list-files` 命令 | P2 | 2h | `cli/list_files.py` |
| 输出格式 (table/json/jsonl/csv) | P1 | 4h | `cli/formatter.py` |
| CLI 测试 | P0 | 4h | `tests/cli/` |

**交付标准**:
```bash
agentic-logger query --rid 550e8400 --level ERROR --min-dur 1000 --order-by dur_desc
agentic-logger trace --rid 550e8400 --include-traceback
agentic-logger stats --group-by error_code --since 24h
```

---

## 5. Phase 4: 循环写入 + 完善 (1周)

### 5.1 循环写入

**任务清单**:

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| JSONL 循环写入 | P0 | 4h | `storage/circular_jsonl.py` |
| SQLite 循环写入 | P0 | 4h | `storage/circular_sqlite.py` |
| 文件大小监控 | P0 | 2h | `storage/monitor.py` |
| 旧数据清理 | P1 | 2h | `storage/cleanup.py` |
| 循环写入测试 | P0 | 4h | `tests/circular/` |

---

### 5.2 完善

**任务清单**:

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| 错误处理 (静默失败 + 降级) | P0 | 3h | `core/error_handler.py` |
| 批量写入 | P1 | 3h | `core/batch.py` |
| 性能优化 (缓冲写入) | P1 | 3h | `core/buffer.py` |
| 日志文件发现 (自动扫描目录) | P1 | 3h | `query/discovery.py` |
| 多进程安全测试 | P0 | 4h | `tests/multiprocess/` |

---

## 6. Phase 5: 文档 + 测试 + 发布 (1周)

### 6.1 文档

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| README.md | P0 | 3h | `README.md` |
| API 文档 (Agent 友好) | P0 | 4h | `docs/api.md` |
| 使用示例 | P0 | 3h | `examples/` |
| 字段参考 | P0 | 2h | `docs/fields.md` |
| MCP 使用指南 | P0 | 2h | `docs/mcp.md` |

---

### 6.2 测试

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| 补充单元测试 | P0 | 4h | `tests/unit/` |
| 补充集成测试 | P0 | 4h | `tests/integration/` |
| 性能基准测试 | P1 | 3h | `tests/benchmark/` |
| 覆盖率报告 (>90%) | P0 | 2h | `htmlcov/` |

---

### 6.3 发布

| 任务 | 优先级 | 工时 | 交付物 |
|------|--------|------|--------|
| PyPI 发布 | P0 | 2h | PyPI package |
| GitHub Actions CI | P1 | 4h | `.github/workflows/` |
| CHANGELOG | P0 | 1h | `CHANGELOG.md` |

---

## 7. 里程碑

| 里程碑 | 时间 | 交付内容 |
|--------|------|---------|
| **M1**: SDK 可用 | Week 1 | Python SDK + JSONL 存储 |
| **M2**: MVP 完整 | Week 2 | + SQLite WAL + 查询引擎 |
| **M3**: Agent 接入 | Week 3 | MCP Server |
| **M4**: 人类可用 | Week 4 | CLI |
| **M5**: 生产就绪 | Week 5 | 循环写入 + 完善 |
| **M6**: 正式发布 | Week 6 | 文档 + 测试 + PyPI |

---

## 8. MVP 后的扩展计划

Python MVP 验证后，按需扩展：

| 阶段 | 内容 | 触发条件 |
|------|------|---------|
| **Ext-1** | Node.js SDK | 需要 JS/TS 项目集成 |
| **Ext-2** | Bash SDK | 需要 Shell 脚本集成 |
| **Ext-3** | Go/Rust SDK | 需要高性能场景 |
| **Ext-4** | GLiNER 集成 | 需要处理外部非结构化日志 |
| **Ext-5** | NuExtract 集成 | 需要深度语义抽取 |

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| SQLite WAL 多进程冲突 | 中 | 高 | 充分测试 + busy_timeout |
| 循环写入数据丢失 | 中 | 高 | 先写新文件再删旧文件 |
| 查询性能不足 | 低 | 中 | SQLite 索引 + JSONL 流式 |
| 字段设计不合理 | 中 | 高 | MVP 阶段快速迭代调整 |

---

## 10. 成功标准

### MVP 标准 (Week 2)

- [ ] Python SDK 所有方法可用
- [ ] JSONL + SQLite 双后端
- [ ] 新字段 (rid/tid/pid/dur/error_code/ctx) 正确填充
- [ ] 文件名格式正确 (program_cmd_date_time)
- [ ] 查询引擎支持所有字段
- [ ] 测试覆盖率 > 90%

### 完整产品标准 (Week 6)

- [ ] MCP Server 所有 Tool 可用
- [ ] CLI 所有命令可用
- [ ] 循环写入稳定
- [ ] 多进程并发安全
- [ ] 文档完整
- [ ] PyPI 发布
