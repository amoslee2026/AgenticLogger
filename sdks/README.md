# AgenticLogger — Language SDKs

Every SDK in this directory emits the **same byte-compatible JSONL**, so a log
written by any one of them is read by the **Python query layer** (`cli` /
`mcp_server` / `JSONLBackend`) with zero conversion. The Python SDK remains the
read/query authority; these SDKs are write-side clients.

**Single source of truth**: [`INTERCHANGE.md`](./INTERCHANGE.md) — the
canonical byte-level format contract. If an SDK and that document disagree, the
document wins.

| SDK | Directory | Package / artifact | Status |
|-----|-----------|--------------------|--------|
| Python (reference) | `../src/agentic_logger` | `agentic-logger` (PyPI) | full (read + write) |
| Bash | [`bash/`](./bash) | `agentic_logger.sh` (sourceable) | write |
| Rust | [`rust/`](./rust) | `agentic-logger` crate | write |
| Go | [`go/`](./go) | `github.com/agenticlogger/agentic-logger-go` | write |
| TypeScript / JavaScript | [`ts/`](./ts) | `agentic-logger` (npm, ESM + types) | write |
| SystemVerilog | [`systemverilog/`](./systemverilog) | `agentic_logger_pkg.sv` + DPI-C | write |
| Verilog-2001 | [`systemverilog/agentic_logger_v2001.v`](./systemverilog/agentic_logger_v2001.v) | `\`include` subset | write (limited) |

## Why byte-compatibility is non-trivial

The Python `stats` command counts fields by **byte substring** (e.g.
`"level": "INFO"`) rather than parsing every line. That fast path only works if
every SDK emits the exact same separators (`": "`, `", "`) and does not escape
non-ASCII to `\uXXXX`. Compact separators (`":"`, `,`) would make **every entry
bucket as `unknown`** — a correctness bug, not just a slowdown. Each SDK
therefore builds JSON with these separators explicitly (see INTERCHANGE.md §2).

## Cross-language verification

```bash
./tests/cross_lang/run_all.sh
```

Drives every SDK to emit a sample, validates each file against INTERCHANGE.md,
and confirms the Python CLI reads it. Run `python3 tests/cross_lang/validate.py
<file.jsonl>` to validate any single file.

## Quick API map (all SDKs)

| Concept | Python | Bash | Rust | Go | TS/JS | SystemVerilog |
|---|---|---|---|---|---|---|
| Create | `AgentLogger(...)` | `agentic_init ...` | `AgentLogger::new(...)` | `New(...)` | `new AgentLogger({...})` | `new(...)` |
| Info | `.info(...)` | `agentic_info` | `.info` | `.Info` | `.info` | `.info` |
| Error | `.error(...)` | `agentic_error` | `.error` | `.Error` | `.error` | `.error` |
| Tool call | `.tool_call(...)` | `agentic_tool_call` | `.tool_call` | `.ToolCall` | `.toolCall` | `.tool_call` |
| File op | `.file_op(...)` | `agentic_file_op` | `.file_op` | `.FileOp` | `.fileOp` | `.file_op` |
| Error codes | `ErrorCode.X` | `$AGENTIC_EC_X` | `ErrorCode::X` | `ErrX` | `ErrorCode.X` | string literal |

See each SDK's README for idiomatic usage, install, and limitations.
