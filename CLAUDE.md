

## Project Overview

AgenticLogger 是一个为 Coding Agent 设计的高效日志管理系统。核心目标是通过专门的工具进行日志生成和 Agentic Reading，只提取有效信息送给 LLM，从而节省推理时间和 token 消耗。
## High-Level Architecture


### 核心组件（待实现）

1. **Log Generation Tools** - 专门的日志生成工具
   - 为 Coding Agent 的结构化日志输出提供接口
   - 捕获关键执行路径和决策点

2. **Agentic Reading Tools** - 智能日志读取工具
   - 提取对 LLM 有价值的信息
   - 过滤噪音和冗余数据

3. **Information Extraction Layer** - 信息提取层
   - 识别和提取有效信息
   - 优化 token 使用效率

### 设计原则

- **output README.md in english**
- **Token Efficiency**: 最小化送入 LLM 的 token 数量
- **Information Density**: 最大化每条信息的信息密度
- **Structured Output**: 日志输出应该是结构化的，便于解析
- **Selective Reading**: 不是读取所有日志，而是智能选择关键信息
- **Don't push apikey/token into remote**: it's a pubulic repo in remote, be security
## Development Guidelines

- 遵循全局 CLAUDE.md 中的所有规则
- 使用 uv 管理 Python 依赖
- 测试覆盖率要求 99%
- 代码提交前必须通过代码审查

## Log Analysis Scripts (utils/)

位于 `utils/` 目录，遵循 Token Saving Rules：

- `utils/log_triage.py` — 错误类型摘要（计数 + 首次出现行）
- `utils/log_extract.sh` — 提取匹配模式周围 ±10 行上下文
- `utils/agentic_logger.py` — Python 脚本的共享日志工具
- `utils/CLAUDE.md` — 脚本索引（编写新脚本前先查看此文件）

**工作流**：先运行 `log_triage.py` 识别错误类型，然后用 `log_extract.sh` 提取特定模式的上下文。避免读取完整日志文件。

## Inline Spec Annotations

源代码使用内联规范标签进行漂移检测和 grep 发现：

- `@spec-ref` — 指向架构规范章节 (file#section)
- `@spec-why` — 非显而易见的决策原因
- `@spec-invariant` — 函数刻意不做的事情
- `@spec-caution` — 跨文件/跨仓库依赖
- `@agent-tag` — grep 发现的功能类别（仅用于关键/高风险路径）
- `@agent-caution` — 未来编辑的风险警告
- `@agent-todo` — 面向代理的操作提醒
- `@last-changed` — 最近实质性更改的时间戳（ISO 8601，覆盖式）
- `@log-module` — 链接到日志条目的检索元数据

**密度原则**：每行标签/注释必须简洁 — 无填充词，不复述显而易见的內容。如果內容超过 ~2 行，质疑它是否应该内联或在架构规范中。

**漂移检测**：编辑带有 `@spec-*` 标签的代码前，先读取它们作为约束。编辑后，验证新行为是否仍满足 `@spec-invariant` 并匹配 `@spec-ref` 引用的章节。如果不匹配，遵循冲突解决流程（向用户展示，不要静默重写规范）。
