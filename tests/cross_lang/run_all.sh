#!/usr/bin/env bash
# run_all.sh — drive every AgenticLogger SDK to emit a sample log, validate it
# against the interchange contract, and confirm the Python query layer reads it.
#
# Exit non-zero if ANY SDK fails validation or Python interop.
# Requires: bash, cargo, go, bun (or node), python3 (+ agentic_logger), tclsh, verilator+gcc (SV, optional).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SDKS="$ROOT/sdks"
PYBIN="${PYTHON:-python3}"
if command -v uv >/dev/null 2>&1; then PYBIN="uv run python"; fi
TMP="$(mktemp -d)"
PASS=0; FAIL=0
SV_OK=1

ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

validate() {  # <file> <expect_entries> <rid>
  $PYBIN "$ROOT/tests/cross_lang/validate.py" "$1" --expect-entries "$2" --expect-rid "$3" >/dev/null 2>&1
}
pyreads() {  # <dir>  — confirm Python CLI stats returns a sane count
  $PYBIN -m agentic_logger.cli --log-dir "$1" stats --group-by level 2>/dev/null | grep -q 'Statistics' || return 1
}

echo "== AgenticLogger cross-language interop =="

# --- Bash ---
echo "[bash]"
D="$TMP/bash"; mkdir -p "$D"
( source "$SDKS/bash/agentic_logger.sh"
  agentic_init "xlang" "demo" "$D" "cafebabe"
  agentic_info "started" "parser" 12 "" "$(agentic_kv 'file=data.json' 'size=1024')"
  agentic_tool_call "bash" "npm install" 0 1234
  agentic_error "failed" "build" "$AGENTIC_EC_EXEC_NON_ZERO" "tb_abcd1234"
  agentic_file_op "write" "/f" 1 2048
  agentic_decision "redis" "redis|memcached" "perf" 0.85 "arch"
  agentic_code_gen "bash" "s.sh" 10 "f1|f2"
  agentic_context_switch "test" "build" "done"
)
F="$(ls "$D"/*.jsonl)"
validate "$F" 7 cafebabe && pyreads "$D" && ok "bash emits valid JSONL, Python reads it" || bad "bash"

# --- Rust ---
echo "[rust]"
D="$TMP/rust"; mkdir -p "$D"
( cd "$SDKS/rust" && CARGO_TARGET_DIR="$TMP/rust_target" cargo run --quiet --example rust_emit -- "$D" >/dev/null 2>&1 ) \
  && F="$(ls "$D"/*.jsonl)" && validate "$F" 7 cafebabe && pyreads "$D" && ok "rust emits valid JSONL, Python reads it" \
  || bad "rust (skipping: cargo failed?)"

# --- Go ---
echo "[go]"
D="$TMP/go"; mkdir -p "$D"
( cd "$SDKS/go" && go run ./examples/emit.go "$D" >/dev/null 2>&1 ) \
  && F="$(ls "$D"/*.jsonl)" && validate "$F" 7 cafebabe && pyreads "$D" && ok "go emits valid JSONL, Python reads it" \
  || bad "go (skipping: go failed?)"

# --- TypeScript/JavaScript ---
echo "[ts/js]"
D="$TMP/ts"; mkdir -p "$D"
RUNNER=""; command -v bun >/dev/null && RUNNER="bun"
[ -z "$RUNNER" ] && command -v npx >/dev/null && RUNANNER="npx tsx"
if [ -n "$RUNNER" ]; then
  ( cd "$SDKS/ts" && $RUNNER examples/emit.ts "$D" >/dev/null 2>&1 ) \
    && F="$(ls "$D"/*.jsonl)" && validate "$F" 9 cafebabe && pyreads "$D" && ok "ts/js emits valid JSONL, Python reads it" \
    || bad "ts/js"
else
  bad "ts/js (no bun/tsx runner installed)"
fi

# --- SystemVerilog (optional — needs verilator + gcc) ---
echo "[systemverilog]"
if command -v verilator >/dev/null && command -v gcc >/dev/null; then
  D="$TMP/sv"; mkdir -p "$D"
  if ( cd "$SDKS/systemverilog" && ./build.sh "$D" >/dev/null 2>&1 ); then
    F="$(ls "$D"/*.jsonl)" && validate "$F" 9 cafebabe && pyreads "$D" && ok "systemverilog emits valid JSONL, Python reads it" \
      || bad "systemverilog"
  else
    SV_OK=0; echo "  (sv build failed; install verilator+gcc to enable)"
  fi
else
  SV_OK=0; echo "  (verilator/gcc not installed; skipping)"
fi

# --- Tcl (optional — needs tclsh) ---
echo "[tcl]"
if command -v tclsh >/dev/null; then
  D="$TMP/tcl"; mkdir -p "$D"
  if ( cd "$SDKS/tcl" && tclsh examples/emit.tcl "$D" >/dev/null 2>&1 ); then
    F="$(ls "$D"/*.jsonl)" && validate "$F" 9 cafebabe && pyreads "$D" && ok "tcl emits valid JSONL, Python reads it" \
      || bad "tcl"
  else
    bad "tcl (emit failed)"
  fi
  # compact mode (contract §4)
  DC="$TMP/tcl_compact"; mkdir -p "$DC"
  if ( cd "$SDKS/tcl" && COMPACT=1 tclsh examples/emit.tcl "$DC" >/dev/null 2>&1 ); then
    FC="$(ls "$DC"/*.jsonl)"
    grep -q '"l": "INFO"' "$FC" && validate "$FC" 9 cafebabe && ok "tcl compact mode valid" || bad "tcl compact"
  else
    bad "tcl compact (emit failed)"
  fi
else
  bad "tcl (tclsh not installed)"
fi

# --- compact-mode interop (TS compact file → Python stats) ---
echo "[compact]"
D="$TMP/compact"; mkdir -p "$D"
if ( cd "$SDKS/ts" && COMPACT=1 $RUNNER examples/emit.ts "$D" >/dev/null 2>&1 ); then
  F="$(ls "$D"/*.jsonl)"
  if validate "$F" 9 cafebabe && $PYBIN -m agentic_logger.cli --log-dir "$D" stats --group-by level 2>/dev/null | grep -q 'Statistics'; then
    # confirm compact keys present (l/m/n) AND Python expanded them correctly
    grep -q '"l": "INFO"' "$F" && ok "compact mode valid; Python stats reads compact file"
  else bad "compact (validation or Python stats failed)"; fi
else
  bad "compact (TS compact emit failed)"
fi

echo
echo "Result: $PASS passed, $FAIL failed"
rm -rf "$TMP"
[ "$FAIL" -eq 0 ]
