# agentic-logger (Bash)

Zero-dependency Bash SDK — a sourceable function library for CI, scripts, and
agent `bash` tool calls.

## Install

```bash
source /path/to/agentic_logger.sh
```

## Usage

```bash
source agentic_logger.sh
agentic_init "my_agent" "build" "./logs"      # program command logdir [rid]
agentic_info  "Processing started" "parser" 12 "" "$(agentic_kv 'file=data.json' 'size=1024')"
agentic_tool_call "bash" "npm install" 0 1234
agentic_error "Build failed" "build" "$AGENTIC_EC_EXEC_NON_ZERO" "tb_abcd1234"
agentic_file_op "write" "/p/f.sh" 1 2048
agentic_decision "redis" "redis|memcached" "perf" 0.85 "arch"
agentic_code_gen "bash" "s.sh" 50 "main|helper"
agentic_context_switch "test" "build" "done"
echo "log: $(agentic_log_path)"
```

## Notes

- Requires GNU `date` (`%N`) and `/dev/urandom`.
- JSON escaping handles `\`, `"`, tab, CR, LF. Pre-sanitize other control chars.
- `pid` is a string; `dur`/`exit`/`size`/`seq` are unquoted numbers (contract).
- Self-test: `bash agentic_logger.sh --self-test [dir]`.
