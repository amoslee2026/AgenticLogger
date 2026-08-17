# agentic-logger (Tcl)

Emit byte-compatible JSONL from **Tcl** — the de-facto scripting language of
the EDA toolchain (Synopsys ICC2/DC, Cadence Innovus, Siemens Calibre, and the
surrounding chip-design automation). Simulation/implementation scripts log into
the same queryable dataset as the software SDKs, readable by the Python CLI /
MCP with zero conversion.

## Install

No build step. `source` the single file:

```tcl
source /path/to/agentic_logger.tcl
```

Requires Tcl 8.5+ (standard `clock`, `file`, `binary`, `pid`, `puts`). No JSON
extension or external package. Rid generation reads `/dev/urandom` when
available and falls back to a time+pid hash otherwise.

## Usage

```tcl
source /path/to/agentic_logger.tcl

agentic_init "place_flow" "place_opt" "./logs"        ;# program, command, dir, [rid]
agentic_info "placement started" "place.main" 0 "" \
    [agentic_kv corner ssg0p63v125c lib nangate45]
agentic_warn "high congestion" "place.congestion" 5000
agentic_tool_call "icc2" "place_opt -effort high" 0 1234 "" "" "placed 1.2M cells"
agentic_error "DRC violations" "drc" $::agentic_ec(EXEC_NON_ZERO) "tb_abcd1234"
agentic_file_op "write" "/net/final.v.gz" 1 204800
agentic_file_op "read" "/net/missing.v" 0 "" $::agentic_ec(IO_NOT_FOUND)
agentic_decision "use_ccd" "ccd classical" "better QoR" 0.85 "place.strategy"
agentic_code_gen "tcl" "gen/floorplan.tcl" 80 "make_rows make_sites"
agentic_context_switch "cts" "place" "placement done"
agentic_close
```

Log file: `./logs/place_flow_place_opt_YYYYMMDD_HHMMSSffffff.jsonl`.

## API

| Concept | Proc | Notes |
|---------|------|-------|
| Create | `agentic_init program ?command? ?log_dir? ?rid?` | `command` defaults to `pid<PID>` |
| Info | `agentic_info msg ?module? ?dur? ?error_code? ?ctx?` | `module` defaults to `"unknown"` |
| Warn | `agentic_warn msg ?module? ?dur? ?error_code? ?ctx?` | |
| Error | `agentic_error msg ?module? ?error_code? ?tid? ?dur? ?ctx?` | `error_code` defaults to `UNKNOWN` |
| Tool call | `agentic_tool_call tool cmd exit dur ?error_code? ?tid? ?stdout? ?stderr? ?ctx?` | |
| File op | `agentic_file_op op path ok ?size? ?error_code? ?tid? ?dur? ?ctx?` | `ok` accepts `1`/`0`/`true`/`false` |
| Decision | `agentic_decision choice ?alts? ?reason? ?confidence? ?module? ?ctx?` | `alts` is a Tcl list |
| Code gen | `agentic_code_gen lang path ?lines? ?funcs? ?module? ?ctx?` | `funcs` is a Tcl list |
| Context switch | `agentic_context_switch to_task ?from_task? ?reason? ?module? ?ctx?` | |
| Traceback | `agentic_save_traceback tid type msg tb` / `agentic_save_traceback_new type msg tb` | sidecar `.tracebacks` |
| Path | `agentic_log_path` | returns the current file path |
| Close | `agentic_close` | flush + close the file handle |

### API notes

- `ctx` is a **JSON object string**. Build one with the `agentic_kv` helper:
  `[agentic_kv file data.json size 1024]` → `{"file": "data.json", "size": 1024}`
  (numeric values are written unquoted, strings quoted).
- `alts` / `funcs` are **Tcl lists** (space-separated); they serialize to JSON
  string arrays.
- Error codes live in the global array `::agentic_ec` — e.g.
  `$::agentic_ec(EXEC_NON_ZERO)`. The full §6 taxonomy (48 codes) is defined.
- `dur` / `exit` / `size` / `lines` / `confidence` are written unquoted
  (numbers); `pid` is a string (contract §3). Callers must pass numbers as
  numeric strings.

## Compact mode

Set the global `::agentic_compact` to `1` before `agentic_init` to emit
single-char keys (contract §4):

```tcl
set ::agentic_compact 1
agentic_init "flow" "run" "./logs"
```

Off by default, identical to every other SDK.

## Limitations

- Pure Tcl 8.5+ with no C extension: timestamps are `+00:00` UTC (matching the
  other SDKs), computed via `clock milliseconds`/`clock format`.
- JSON escaping covers `\ " \t \r \n`; callers must pre-sanitize other control
  characters, same as the Bash SDK.

## Verify

```tcl
tclsh agentic_logger.tcl --self-test /tmp/tcl_selftest
```

```bash
python3 ../../tests/cross_lang/validate.py /tmp/tcl_selftest/*.jsonl
```
