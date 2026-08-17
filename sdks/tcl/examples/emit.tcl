# emit.tcl — emit a canonical sample log for cross-language interop testing.
#
# Run: `tclsh examples/emit.tcl <outDir>`
# Emits the same 9-entry / rid=cafebabe sample as the TS and SystemVerilog
# probes, so tests/cross_lang/validate.py can assert byte-compatibility.
source [file join [file dirname [info script]] .. agentic_logger.tcl]

if {[info exists ::env(COMPACT)] && $::env(COMPACT) eq "1"} {
    set ::agentic_compact 1
}

set dir [lindex $argv 0]
if {$dir eq ""} { set dir "/tmp/xlang_tcl" }

agentic_init "tcl_probe" "demo" $dir "cafebabe"
agentic_info "Processing started" "parser" 12 "" [agentic_kv file data.json size 1024]
agentic_warn "slow op" "db" 5000
agentic_tool_call "bash" "npm install" 0 1234 "" "" "added 50 pkgs"
agentic_error "Build failed" "build" "EXEC_NON_ZERO" "tb_abcd1234"
agentic_file_op "write" "/p/f.tcl" 1 2048
agentic_file_op "read" "/missing.tcl" 0 "" "IO_NOT_FOUND"
agentic_decision "use_redis" "redis memcached" "perf" 0.85 "arch"
agentic_code_gen "tcl" "tb.tcl" 50 "main helper"
agentic_context_switch "test" "build" "done"
agentic_close
puts [agentic_log_path]
