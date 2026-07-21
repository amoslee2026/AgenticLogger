# AgenticLogger

> 为 Coding Agent 设计的高效日志管理系统

## 目标

通过专门的工具进行日志生成与 **Agentic Reading**，只提取有效信息送给 LLM，从而节省推理时间与 token 消耗。

## 核心组件（规划中）

| 组件 | 职责 |
|------|------|
| **Log Generation Tools** | 为 Coding Agent 的结构化日志输出提供接口，捕获关键执行路径与决策点 |
| **Agentic Reading Tools** | 智能日志读取，提取对 LLM 有价值的信息，过滤噪音与冗余 |
| **Information Extraction Layer** | 识别并提取有效信息，优化 token 使用效率 |

## 设计原则

- **Token Efficiency** — 最小化送入 LLM 的 token 数量
- **Information Density** — 最大化每条信息的信息密度
- **Structured Output** — 日志输出结构化，便于解析
- **Selective Reading** — 智能选择关键信息，而非读取所有日志

## 技术栈（待定）

- Python（使用 `uv` 管理依赖）
- 结构化日志格式（JSON / Protocol Buffers）
- 轻量级嵌入模型用于信息筛选

## 开发

```bash
# 依赖安装（待项目初始化后补充）
uv sync

# 测试
uv run pytest

# 代码检查
uv run ruff check .
```

> 测试覆盖率要求：**99%**

## 状态

🚧 **项目规划阶段** — 核心组件尚未实现，正在确定技术栈与架构。

## License

MIT
