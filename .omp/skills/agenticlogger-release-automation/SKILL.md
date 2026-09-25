---
name: agenticlogger-release-automation
description: 回答/核实 AgenticLogger 三栈包（PyPI/npm/crates.io）发布机制与升级语义时用：push-main 自动 bump+发布链、证据判读、PUBLISH.md 过时段落、本地分叉处置
---

# AgenticLogger 自动发布机制（2026-09-16 核实）

## 结论
`~/wrk/AgenticLogger` 的 `.github/workflows/release.yml` 实现了「升级后自动发布三仓」：
- **触发**：push 到 main（commit message 以 `[skip ci]` 开头则跳过——docs-only 改动的 opt-out）；**不使用 git tag**
- **动作**：自动 bump patch 位并同步三处 manifest（`pyproject.toml`、`sdks/ts/package.json`、`sdks/rust/Cargo.toml`）→ 发布 PyPI（OIDC trusted publishing，免 token）/ npm（`NPM_TOKEN`）/ crates.io（`CARGO_REGISTRY_TOKEN`）→ bump commit 以 `[skip ci]` 推回
- **major/minor 手动**：push 前改 pyproject.toml，workflow 只加 patch
- **`workflow_dispatch`**：可对指定 registry（all/npm/pypi/crates）重发当前版本，不占版本号，用于重试失败发布
- **secret 缺失**：对应 registry 在 check job 静默跳过（PyPI 无需 token 恒可用）

## 实证方法（可复算）
1. 读 `.github/workflows/release.yml`（机制）+ `git log origin/main` 找 `chore: bump version to X [skip ci]`（CI 运行痕迹）
2. 三仓版本核对：`curl -sf https://pypi.org/pypi/agentic-logger/json | jq .info.version`、`npm view agentic-logger version`、`curl -sf -A ua https://crates.io/api/v1/crates/agentic-logger | jq .crate.max_version`——三者一致即自动链全程跑通（2026-09-16 实测均 0.1.2）

## 已知坑
- **`sdks/PUBLISH.md` §CI publishing 过时**（2026-09-16 现状）：仍写「version tag 触发、git tag 唯一真相源、需 PYPI_TOKEN」，与 release.yml 实际矛盾——以 workflow 为准，文档待修
- **本地 checkout 易落后**：CI bump commit 在远端，本地不 pull 会看到旧版本号（2026-09-16 实测 ahead 1/behind 1）；判读版本前先 `git fetch` + 看 origin/main
- 包名三栈同名 `agentic-logger`（Rust lib 名 `agentic_logger`），JSONL 三栈字节兼容（npm/Cargo description 明示）

## 规则面
TokenSavingRules.md「AgenticLogger 强制使用」已固化为包优先表述（PyPI/npm/crates.io 安装，源码仓 `~/wrk/AgenticLogger` 仅 SDK 开发时相关）。
