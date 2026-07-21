# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgenticLogger 是一个为 Coding Agent 设计的高效日志管理系统。核心目标是通过专门的工具进行日志生成和 Agentic Reading，只提取有效信息送给 LLM，从而节省推理时间和 token 消耗。

## Common Development Commands

由于项目尚未初始化，以下命令待项目搭建后补充：

```bash
# 项目初始化（待确定技术栈后补充）
# 构建命令
# 测试命令
# 代码检查命令
```

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

- **Token Efficiency**: 最小化送入 LLM 的 token 数量
- **Information Density**: 最大化每条信息的信息密度
- **Structured Output**: 日志输出应该是结构化的，便于解析
- **Selective Reading**: 不是读取所有日志，而是智能选择关键信息

## Technology Stack

待确定。建议考虑：
- Python (with uv) - 基于现有环境配置
- 结构化日志格式 (JSON/Protocol Buffers)
- 轻量级嵌入模型用于信息筛选

## Development Guidelines

- 遵循全局 CLAUDE.md 中的所有规则
- 使用 uv 管理 Python 依赖
- 测试覆盖率要求 99%
- 代码提交前必须通过代码审查
