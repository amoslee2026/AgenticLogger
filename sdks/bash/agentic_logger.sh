#!/usr/bin/env bash
# agentic_logger.sh — AgenticLogger Bash SDK
#
# Emits byte-compatible JSONL readable by the Python query layer.
# @contract: sdks/INTERCHANGE.md
#
# Usage:
#   source agentic_logger.sh
#   agentic_init "my_agent" "build" "./logs"
#   agentic_info "started" "parser"
#   agentic_tool_call "bash" "npm install" 0 1234
#   agentic_error "failed" "build" "$AGENTIC_EC_EXEC_NON_ZERO"
#
# Design notes:
#   - Pure bash, zero runtime deps (no jq). Needs GNU date (%N) and /dev/urandom.
#   - JSON escaping handles the common cases: backslash, double-quote, tab, CR, LF.
#     Callers must pre-sanitize binary / other control chars (< 0x20).
#   - pid is a STRING, seq/dur/exit/size are unquoted numbers (contract §3).

# ---------------------------------------------------------------------------
# Error-code constants (contract §6). Use $AGENTIC_EC_<NAME>.
# ---------------------------------------------------------------------------
readonly AGENTIC_EC_PARSE_JSON="PARSE_JSON"
readonly AGENTIC_EC_IO_NOT_FOUND="IO_NOT_FOUND"
readonly AGENTIC_EC_IO_PERMISSION="IO_PERMISSION"
readonly AGENTIC_EC_EXEC_NON_ZERO="EXEC_NON_ZERO"
readonly AGENTIC_EC_EXEC_TIMEOUT="EXEC_TIMEOUT"
readonly AGENTIC_EC_NET_TIMEOUT="NET_TIMEOUT"
readonly AGENTIC_EC_AUTH_FORBIDDEN="AUTH_FORBIDDEN"
readonly AGENTIC_EC_CONFIG_MISSING="CONFIG_MISSING"
readonly AGENTIC_EC_RES_MEMORY="RES_MEMORY"
readonly AGENTIC_EC_TIMEOUT_API="TIMEOUT_API"
readonly AGENTIC_EC_CONFLICT_VERSION="CONFLICT_VERSION"
readonly AGENTIC_EC_INTERNAL_UNEXPECTED="INTERNAL_UNEXPECTED"
readonly AGENTIC_EC_UNKNOWN="UNKNOWN"

# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Escape a string for a JSON double-quoted value.
_agentic_je() {
  local s="$1"
  s="${s//\\/\\\\}"      # backslash first
  s="${s//\"/\\\"}"      # double quote
  s="${s//$'\t'/\\t}"    # tab
  s="${s//$'\r'/\\r}"    # carriage return
  s="${s//$'\n'/\\n}"    # newline
  printf '%s' "$s"
}

# ISO 8601 UTC timestamp, ms precision, +00:00 offset (contract §3.1).
_agentic_ts() {
  # GNU date %3N => 3-digit ms. UTC => +00:00.
  printf '%s' "$(date -u +"%Y-%m-%dT%H:%M:%S.%3N+00:00")"
}

# Sanitise a filename component: keep [A-Za-z0-9_-], else '_', truncate 50.
_agentic_sanitize() {
  local s="${1//[^A-Za-z0-9_-]/_}"
  printf '%s' "${s:0:50}"
}

# Compact-key translation (contract §4). Echoes the single-char key when
# AGENTIC_COMPACT=1, else the original. Top-level entry keys only.
_agentic_ck() {
  [ "${AGENTIC_COMPACT:-0}" = "1" ] || { printf '%s' "$1"; return; }
  case "$1" in
    ts) printf t;; level) printf l;; module) printf n;; msg) printf m;;
    pid) printf p;; rid) printf r;; seq) printf q;; error_code) printf e;;
    dur) printf d;; tool) printf o;; cmd) printf c;; exit) printf x;;
    op) printf w;; path) printf h;; ctx) printf z;; tid) printf i;;
    lines) printf s;; funcs) printf f;; lang) printf g;; choice) printf k;;
    alts) printf a;; reason) printf u;; stdout) printf v;; stderr) printf b;;
    ok) printf y;; size) printf j;; *) printf '%s' "$1";;
  esac
}

# Generate an 8-hex-char run id.
_agentic_gen_rid() {
  od -An -tx1 -N4 /dev/urandom 2>/dev/null | tr -d ' \n' || printf '00000000'
}

# Core writer: <body> is the inner JSON (without braces, without auto-fields).
_agentic_write() {
  local body="$1"
  AGENTIC_SEQ=$((AGENTIC_SEQ + 1))
  local ts rid pid
  ts="$(_agentic_ts)"
  rid="$AGENTIC_RID"
  pid="$AGENTIC_PID"
  printf '{%s, "%s": "%s", "%s": "%s", "%s": "%s", "%s": %d}\n' \
    "$body" "$(_agentic_ck ts)" "$ts" "$(_agentic_ck pid)" "$pid" "$(_agentic_ck rid)" "$rid" "$(_agentic_ck seq)" "$AGENTIC_SEQ" >> "$AGENTIC_FILE"
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# agentic_init <program> [command] [log_dir] [rid]
agentic_init() {
  AGENTIC_PROGRAM="$(_agentic_sanitize "${1:-agent}")"
  AGENTIC_RAW_COMMAND="${2:-}"
  AGENTIC_LOG_DIR="${3:-./logs}"
  AGENTIC_PID="$$"
  AGENTIC_RID="${4:-$(_agentic_gen_rid)}"
  AGENTIC_SEQ=0

  local cmd
  if [ -n "$AGENTIC_RAW_COMMAND" ]; then
    cmd="$(_agentic_sanitize "$AGENTIC_RAW_COMMAND")"
  else
    cmd="pid${AGENTIC_PID}"
  fi
  local stamp; stamp="$(date +"%Y%m%d_%H%M%S%6N")"
  mkdir -p "$AGENTIC_LOG_DIR"
  AGENTIC_FILE="${AGENTIC_LOG_DIR}/${AGENTIC_PROGRAM}_${cmd}_${stamp}.jsonl"

  # Global-context header (contract §1.2).
  AGENTIC_SEQ=0
  {
    printf '{"%s": "%s", "%s": "__GLOBAL_CTX__", "%s": "Global context", ' "$(_agentic_ck ts)" "$(_agentic_ts)" "$(_agentic_ck level)" "$(_agentic_ck msg)"
    printf '"%s": "__system__", "%s": "%s", "%s": "%s", "%s": 0, ' "$(_agentic_ck module)" "$(_agentic_ck rid)" "$AGENTIC_RID" "$(_agentic_ck pid)" "$AGENTIC_PID" "$(_agentic_ck seq)"
    printf '"program": "%s", "command": "%s"}\n' "$AGENTIC_PROGRAM" "$cmd"
  } >> "$AGENTIC_FILE"
}

agentic_log_path() { printf '%s' "$AGENTIC_FILE"; }

# agentic_info <msg> [module] [dur] [error_code] [ctx_json]
agentic_info() {
  local msg="$1" module="${2:-}" dur="${3:-}" ec="${4:-}" ctx="${5:-}"
  local body; body="\"$(_agentic_ck level)\": \"INFO\", \"$(_agentic_ck msg)\": \"$(_agentic_je "$msg")\""
  body+=", \"$(_agentic_ck module)\": \"$(_agentic_je "${module:-unknown}")\""
  [ -n "$dur" ] && body+=", \"$(_agentic_ck dur)\": $dur"
  [ -n "$ec" ] && body+=", \"$(_agentic_ck error_code)\": \"$ec\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_warn <msg> [module] [dur] [error_code] [ctx_json]
agentic_warn() {
  local msg="$1" module="${2:-}" dur="${3:-}" ec="${4:-}" ctx="${5:-}"
  local body; body="\"$(_agentic_ck level)\": \"WARN\", \"$(_agentic_ck msg)\": \"$(_agentic_je "$msg")\""
  body+=", \"$(_agentic_ck module)\": \"$(_agentic_je "${module:-unknown}")\""
  [ -n "$dur" ] && body+=", \"$(_agentic_ck dur)\": $dur"
  [ -n "$ec" ] && body+=", \"$(_agentic_ck error_code)\": \"$ec\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_error <msg> [module] [error_code] [tid] [dur] [ctx_json]
# (error_code defaults to UNKNOWN when omitted — matches Python.)
agentic_error() {
  local msg="$1" module="${2:-}" ec="${3:-$AGENTIC_EC_UNKNOWN}" tid="${4:-}" dur="${5:-}" ctx="${6:-}"
  local body; body="\"$(_agentic_ck level)\": \"ERROR\", \"$(_agentic_ck msg)\": \"$(_agentic_je "$msg")\""
  body+=", \"$(_agentic_ck module)\": \"$(_agentic_je "${module:-unknown}")\""
  [ -n "$ec" ] && body+=", \"$(_agentic_ck error_code)\": \"$ec\""
  [ -n "$tid" ] && body+=", \"$(_agentic_ck tid)\": \"$tid\""
  [ -n "$dur" ] && body+=", \"$(_agentic_ck dur)\": $dur"
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_tool_call <tool> <cmd> <exit> <dur> [error_code] [tid] [stdout] [stderr] [ctx_json]
agentic_tool_call() {
  local tool="$1" cmd="$2" exit_="$3" dur="$4" ec="${5:-}" tid="${6:-}" out="${7:-}" err="${8:-}" ctx="${9:-}"
  local body
  body="\"$(_agentic_ck level)\": \"TOOL\", \"$(_agentic_ck msg)\": \"Tool $(_agentic_je "$tool") "
  if [ "$exit_" = "0" ]; then body+="succeeded"; else body+="failed"; fi
  body+="\""
  body+=", \"$(_agentic_ck tool)\": \"$(_agentic_je "$tool")\", \"$(_agentic_ck cmd)\": \"$(_agentic_je "$cmd")\""
  body+=", \"$(_agentic_ck exit)\": $exit_, \"$(_agentic_ck dur)\": $dur"
  [ -n "$ec" ] && body+=", \"$(_agentic_ck error_code)\": \"$ec\""
  [ -n "$tid" ] && body+=", \"$(_agentic_ck tid)\": \"$tid\""
  [ -n "$out" ] && body+=", \"$(_agentic_ck stdout)\": \"$(_agentic_je "$out")\""
  [ -n "$err" ] && body+=", \"$(_agentic_ck stderr)\": \"$(_agentic_je "$err")\""
  body+=", \"$(_agentic_ck module)\": \"unknown\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_file_op <op> <path> <ok> [size] [error_code] [tid] [dur] [ctx_json]
agentic_file_op() {
  local op="$1" path="$2" ok="$3" size="${4:-}" ec="${5:-}" tid="${6:-}" dur="${7:-}" ctx="${8:-}"
  local okj; if [ "$ok" = "1" ] || [ "$ok" = "true" ]; then okj="true"; else okj="false"; fi
  local body
  body="\"$(_agentic_ck level)\": \"FILE_OP\", \"$(_agentic_ck msg)\": \"File $op "
  if [ "$okj" = "true" ]; then body+="succeeded"; else body+="failed"; fi
  body+=": $(_agentic_je "$path")\""
  body+=", \"$(_agentic_ck op)\": \"$op\", \"$(_agentic_ck path)\": \"$(_agentic_je "$path")\", \"$(_agentic_ck ok)\": $okj"
  [ -n "$size" ] && body+=", \"$(_agentic_ck size)\": $size"
  [ -n "$ec" ] && body+=", \"$(_agentic_ck error_code)\": \"$ec\""
  [ -n "$tid" ] && body+=", \"$(_agentic_ck tid)\": \"$tid\""
  [ -n "$dur" ] && body+=", \"$(_agentic_ck dur)\": $dur"
  body+=", \"$(_agentic_ck module)\": \"unknown\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_decision <choice> [alts_pipe_sep] [reason] [confidence] [module] [ctx_json]
agentic_decision() {
  local choice="$1" alts="${2:-}" reason="${3:-}" conf="${4:-}" module="${5:-}" ctx="${6:-}"
  local body; body="\"$(_agentic_ck level)\": \"DECISION\", \"$(_agentic_ck msg)\": \"Decision: $(_agentic_je "$choice")\""
  body+=", \"$(_agentic_ck choice)\": \"$(_agentic_je "$choice")\""
  if [ -n "$alts" ]; then
    local arr="[" first=1 alt
    IFS='|' read -ra _alts <<< "$alts"
    for alt in "${_alts[@]}"; do
      [ $first -eq 1 ] && first=0 || arr+=", "
      arr+="\"$(_agentic_je "$alt")\""
    done
    arr+="]"
    body+=", \"$(_agentic_ck alts)\": $arr"
  fi
  [ -n "$reason" ] && body+=", \"$(_agentic_ck reason)\": \"$(_agentic_je "$reason")\""
  [ -n "$conf" ] && body+=", \"confidence\": $conf"
  body+=", \"$(_agentic_ck module)\": \"$(_agentic_je "${module:-unknown}")\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_code_gen <lang> <path> [lines] [funcs_pipe_sep] [module] [ctx_json]
agentic_code_gen() {
  local lang="$1" path="$2" lines="${3:-}" funcs="${4:-}" module="${5:-}" ctx="${6:-}"
  local body; body="\"$(_agentic_ck level)\": \"CODE_GEN\", \"$(_agentic_ck msg)\": \"Generated $lang code: $(_agentic_je "$path")\""
  body+=", \"$(_agentic_ck lang)\": \"$lang\", \"$(_agentic_ck path)\": \"$(_agentic_je "$path")\""
  [ -n "$lines" ] && body+=", \"$(_agentic_ck lines)\": $lines"
  if [ -n "$funcs" ]; then
    local arr="[" first=1 fn
    IFS='|' read -ra _fns <<< "$funcs"
    for fn in "${_fns[@]}"; do
      [ $first -eq 1 ] && first=0 || arr+=", "
      arr+="\"$(_agentic_je "$fn")\""
    done
    arr+="]"
    body+=", \"$(_agentic_ck funcs)\": $arr"
  fi
  body+=", \"$(_agentic_ck module)\": \"$(_agentic_je "${module:-unknown}")\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_context_switch <to_task> [from_task] [reason] [module] [ctx_json]
agentic_context_switch() {
  local to="$1" from="${2:-}" reason="${3:-}" module="${4:-}" ctx="${5:-}"
  local body; body="\"$(_agentic_ck level)\": \"CONTEXT\", \"$(_agentic_ck msg)\": \"Switching to: $(_agentic_je "$to")\""
  body+=", \"to_task\": \"$(_agentic_je "$to")\""
  [ -n "$from" ] && body+=", \"from_task\": \"$(_agentic_je "$from")\""
  [ -n "$reason" ] && body+=", \"$(_agentic_ck reason)\": \"$(_agentic_je "$reason")\""
  body+=", \"$(_agentic_ck module)\": \"$(_agentic_je "${module:-unknown}")\""
  [ -n "$ctx" ] && body+=", \"$(_agentic_ck ctx)\": $ctx"
  _agentic_write "$body"
}

# agentic_save_traceback <tid> <exc_type> <exc_msg> <traceback>
# Sidecar always uses FULL keys (contract §5). Newlines in traceback are JSON-escaped.
agentic_save_traceback() {
  local tid="$1" et="$2" em="$3" tb="$4"
  local tb_path="${AGENTIC_FILE%.jsonl}.tracebacks"
  printf '{"tid": "%s", "exception_type": "%s", "exception_msg": "%s", "traceback": "%s"}\n' \
    "$tid" "$(_agentic_je "$et")" "$(_agentic_je "$em")" "$(_agentic_je "$tb")" >> "$tb_path"
}

# agentic_save_traceback_new <exc_type> <exc_msg> <traceback>  -> echoes tid (tb_+8hex)
agentic_save_traceback_new() {
  local tid="tb_$(_agentic_gen_rid)"
  agentic_save_traceback "$tid" "$1" "$2" "$3"
  printf '%s' "$tid"
}

# Helper: build a ctx JSON object from key=value args.
#   ctx=$(agentic_kv "user=u123" "retry=2")
agentic_kv() {
  local out="{" first=1 kv k v
  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    [ $first -eq 1 ] && first=0 || out+=", "
    out+="\"$(_agentic_je "$k")\": \"$(_agentic_je "$v")\""
  done
  out+="}"
  printf '%s' "$out"
}

# ---------------------------------------------------------------------------
# Self-test: `bash agentic_logger.sh --self-test [dir]`
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  set -euo pipefail
  _dir="${2:-/tmp/agentic_bash_selftest}"
  rm -rf "$_dir"; mkdir -p "$_dir"
  agentic_init "selftest" "demo" "$_dir" "deadbeef"
  agentic_info "Processing started" "parser" 12 "$AGENTIC_EC_UNKNOWN" "$(agentic_kv "file=data.json" "size=1024")"
  agentic_warn "slow op" "db" 5000
  agentic_error "Build failed" "build" "$AGENTIC_EC_EXEC_NON_ZERO" "tb_abcd1234"
  agentic_tool_call "bash" 'npm install "x"' 0 1234 "" "" "added 50 pkgs"
  agentic_tool_call "bash" "make fail" 1 5000 "$AGENTIC_EC_EXEC_NON_ZERO"
  agentic_file_op "write" "/p/f.py" 1 2048
  agentic_file_op "read" "/missing.txt" 0 "" "$AGENTIC_EC_IO_NOT_FOUND"
  agentic_decision "use_redis" "redis|memcached" "perf" 0.85 "arch"
  agentic_code_gen "rust" "src/main.rs" 50 "main|helper"
  agentic_context_switch "test" "build" "done"
  # Validate every line is parseable JSON + key fields present.
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$AGENTIC_FILE" <<'PY'
import json, sys
n=0
for i,line in enumerate(open(sys.argv[1]),1):
    line=line.strip()
    if not line: continue
    d=json.loads(line)
    assert "ts" in d and "level" in d and "pid" in d and "rid" in d and "seq" in d, (i,d)
    assert isinstance(d["pid"], str) and isinstance(d["seq"], int), (i,d)
    n+=1
print(f"OK: {n} lines, all valid JSONL, field types correct")
PY
  else
    echo "OK: wrote $(wc -l < "$AGENTIC_FILE") lines (python3 not available to validate)"
  fi
  echo "file: $AGENTIC_FILE"
fi
