# agentic-logger (Rust)

`AgentLogger` for Rust. Emits byte-compatible JSONL via a custom `serde_json`
formatter (`": "` / `", "` separators, no `\u` escaping) so the Python query
layer reads it unchanged.

## Install

```toml
[dependencies]
agentic-logger = "0.1"
```

(Local build: `cargo build`. Depends only on `serde`, `serde_json`, `uuid`.)

## Usage

```rust
use agentic_logger::{AgentLogger, ErrorCode};
use serde_json::json;

let lg = AgentLogger::new("my_agent", Some("build"), "./logs", None)?;
lg.info("Processing started", Some("parser"))?;
lg.info_full("with ctx", Some("net"), None, None, None,
             Some(json!({"endpoint": "/x"})))?;
lg.tool_call("bash", "npm install", 0, 1234, None, None, Some("added 50 pkgs"), None, None)?;
lg.error("Build failed", Some("build"), ErrorCode::ExecNonZero, Some("tb_abcd1234"))?;
lg.file_op("write", "/p/f.rs", true, Some(2048), None, None, Some(5), None)?;
lg.decision("use_redis", Some(&["redis","memcached"]), Some("perf"), Some(0.85), Some("arch"), None)?;
```

## Notes

- `pid` stored as a string; `seq`/`dur`/`exit`/`size` as unquoted numbers.
- ISO 8601 timestamps computed dependency-free (no `chrono`), UTC `+00:00`.
- `module` is a required parameter (no stack introspection in stable Rust);
  defaults to `"unknown"` when `None`.
- Run tests: `cargo test`. Run the sample emitter: `cargo run --example rust_emit -- <dir>`.
