# agentic_logger.tcl — AgenticLogger Tcl SDK
#
# Emits byte-compatible JSONL readable by the Python query layer, so Tcl-driven
# EDA flows (Synopsys / Cadence / Siemens scripts, chip-design automation) log
# into the same queryable dataset as the software SDKs.
# @contract: sdks/INTERCHANGE.md
#
# Usage (source this file, then call the procs):
#   source /path/to/agentic_logger.tcl
#   agentic_init "my_flow" "place" "./logs"
#   agentic_info "placement started" "place.main"
#   agentic_tool_call "icc2" "place_opt" 0 1234
#   agentic_error "DRC violations" "drc" $::agentic_ec(EXEC_NON_ZERO)
#   agentic_close
#
# Design notes:
#   - Pure Tcl 8.5+, zero runtime deps (no JSON package). Needs /dev/urandom
#     for rid generation (falls back to a time+pid hash).
#   - JSON escaping handles the common cases: backslash, double-quote, tab, CR,
#     LF. Callers must pre-sanitize binary / other control chars (< 0x20).
#   - pid is a STRING, seq/dur/exit/size/lines/confidence are unquoted numbers
#     (contract §3).
#   - `alts`/`funcs` are Tcl lists (space-separated); `ctx` is a JSON object
#     string — build one with `agentic_kv`.

# ---------------------------------------------------------------------------
# Error-code constants (contract §6). Use $::agentic_ec(<NAME>).
# ---------------------------------------------------------------------------
array set ::agentic_ec {
    PARSE_JSON PARSE_JSON        PARSE_YAML PARSE_YAML
    PARSE_XML PARSE_XML          PARSE_CSV PARSE_CSV
    PARSE_REGEX PARSE_REGEX      PARSE_ENCODING PARSE_ENCODING
    IO_NOT_FOUND IO_NOT_FOUND    IO_PERMISSION IO_PERMISSION
    IO_DISK_FULL IO_DISK_FULL    IO_READ_FAIL IO_READ_FAIL
    IO_WRITE_FAIL IO_WRITE_FAIL  IO_LOCK_FAIL IO_LOCK_FAIL
    EXEC_NON_ZERO EXEC_NON_ZERO  EXEC_TIMEOUT EXEC_TIMEOUT
    EXEC_NOT_FOUND EXEC_NOT_FOUND EXEC_KILLED EXEC_KILLED
    EXEC_CRASH EXEC_CRASH
    NET_TIMEOUT NET_TIMEOUT      NET_DNS_FAIL NET_DNS_FAIL
    NET_CONN_REFUSED NET_CONN_REFUSED NET_SSL_ERROR NET_SSL_ERROR
    NET_HTTP_ERROR NET_HTTP_ERROR
    AUTH_LOGIN_FAIL AUTH_LOGIN_FAIL  AUTH_TOKEN_EXPIRED AUTH_TOKEN_EXPIRED
    AUTH_FORBIDDEN AUTH_FORBIDDEN    AUTH_UNAUTHORIZED AUTH_UNAUTHORIZED
    CONFIG_MISSING CONFIG_MISSING    CONFIG_INVALID CONFIG_INVALID
    CONFIG_RANGE CONFIG_RANGE
    RES_MEMORY RES_MEMORY        RES_DISK RES_DISK
    RES_CPU RES_CPU              RES_FD RES_FD
    TIMEOUT_API TIMEOUT_API      TIMEOUT_DB TIMEOUT_DB
    TIMEOUT_LOCK TIMEOUT_LOCK
    CONFLICT_VERSION CONFLICT_VERSION CONFLICT_LOCK CONFLICT_LOCK
    CONFLICT_DUPLICATE CONFLICT_DUPLICATE
    INTERNAL_UNEXPECTED INTERNAL_UNEXPECTED INTERNAL_ASSERT INTERNAL_ASSERT
    INTERNAL_TYPE INTERNAL_TYPE INTERNAL_KEY INTERNAL_KEY
    INTERNAL_INDEX INTERNAL_INDEX
    UNKNOWN UNKNOWN
}

# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

# Escape a string for a JSON double-quoted value (single-pass, backslash first).
proc _agentic_je {s} {
    return [string map {"\\" "\\\\" "\"" "\\\"" "\t" "\\t" "\r" "\\r" "\n" "\\n"} $s]
}

# ISO 8601 UTC timestamp, ms precision, +00:00 offset (contract §3.1).
proc _agentic_ts {} {
    set ms [clock milliseconds]
    set sec [expr {$ms / 1000}]
    set frac [format %03d [expr {$ms % 1000}]]
    set base [clock format $sec -gmt 1 -format "%Y-%m-%dT%H:%M:%S"]
    return "$base.${frac}+00:00"
}

# Sanitise a filename component: keep [A-Za-z0-9_-], else '_', truncate 50.
proc _agentic_sanitize {s} {
    set s [regsub -all {[^A-Za-z0-9_-]} $s _]
    return [string range $s 0 49]
}

# Generate an 8-hex-char run id (uuid4 hex[:8] equivalent).
proc _agentic_gen_rid {} {
    if {![catch {set f [open /dev/urandom r]}]} {
        binary scan [read $f 4] H8 h
        close $f
        return $h
    }
    set v [expr {([clock microseconds] ^ ([pid] << 8)) & 0xffffffff}]
    return [format %08x $v]
}

# Compact-key translation (contract §4). Returns the single-char key when
# $agentic_compact is set, else the original. Top-level entry keys only.
proc _agentic_ck {key} {
    global agentic_compact
    if {![info exists agentic_compact] || !$agentic_compact} { return $key }
    set map {
        ts t  level l  module n  msg m  pid p  rid r  seq q  error_code e
        dur d  tool o   cmd c     exit x  op w   path h  ctx z  tid i
        lines s  funcs f  lang g  choice k  alts a  reason u  stdout v  stderr b
        ok y  size j
    }
    if {[dict exists $map $key]} { return [dict get $map $key] }
    return $key
}

# Serialize a Tcl list of strings into a JSON array of strings.
proc _agentic_json_arr {lst} {
    set out "\["
    set first 1
    foreach item $lst {
        if {!$first} { append out ", " }
        set first 0
        append out "\"[_agentic_je $item]\""
    }
    append out "\]"
    return $out
}

# Append one pre-built line (no trailing newline) to the open log file.
proc _agentic_append {line} {
    global agentic_fh
    puts $agentic_fh $line
}

# Core writer: <body> is the inner JSON (without braces, without auto-fields).
proc _agentic_write {body} {
    global agentic_seq agentic_rid agentic_pid
    incr agentic_seq
    set ts [_agentic_ts]
    set line "{${body}"
    append line ", \"[_agentic_ck ts]\": \"$ts\""
    append line ", \"[_agentic_ck pid]\": \"$agentic_pid\""
    append line ", \"[_agentic_ck rid]\": \"$agentic_rid\""
    append line ", \"[_agentic_ck seq]\": $agentic_seq}"
    _agentic_append $line
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# agentic_init <program> [command] [log_dir] [rid]
proc agentic_init {program {command ""} {log_dir "./logs"} {rid ""}} {
    global agentic_program agentic_command agentic_rid agentic_pid
    global agentic_seq agentic_file agentic_fh agentic_log_dir agentic_compact
    set agentic_program [_agentic_sanitize $program]
    set agentic_pid [pid]
    if {$rid eq ""} { set agentic_rid [_agentic_gen_rid] } else { set agentic_rid $rid }
    if {$command eq ""} { set agentic_command "pid$agentic_pid" } else { set agentic_command [_agentic_sanitize $command] }
    set agentic_log_dir $log_dir
    set agentic_seq 0
    if {![info exists agentic_compact]} { set agentic_compact 0 }

    file mkdir $agentic_log_dir
    # Filename stamp: local date + time + 6-digit microseconds (contract §1.1).
    set us [clock microseconds]
    set sec [expr {$us / 1000000}]
    set stamp [clock format $sec -format "%Y%m%d_%H%M%S"]
    append stamp [format %06d [expr {$us % 1000000}]]
    set agentic_file "${agentic_log_dir}/${agentic_program}_${agentic_command}_${stamp}.jsonl"
    set agentic_fh [open $agentic_file a]

    # Global-context header (contract §1.2).
    set ts [_agentic_ts]
    set line "{"
    append line "\"[_agentic_ck ts]\": \"$ts\""
    append line ", \"[_agentic_ck level]\": \"__GLOBAL_CTX__\""
    append line ", \"[_agentic_ck msg]\": \"Global context\""
    append line ", \"[_agentic_ck module]\": \"__system__\""
    append line ", \"[_agentic_ck rid]\": \"$agentic_rid\""
    append line ", \"[_agentic_ck pid]\": \"$agentic_pid\""
    append line ", \"[_agentic_ck seq]\": 0"
    append line ", \"program\": \"$agentic_program\""
    append line ", \"command\": \"$agentic_command\"}"
    puts $agentic_fh $line
}

proc agentic_log_path {} {
    global agentic_file
    return $agentic_file
}

proc agentic_close {} {
    global agentic_fh
    if {[info exists agentic_fh]} {
        catch {close $agentic_fh}
        unset agentic_fh
    }
}

# agentic_info <msg> [module] [dur] [error_code] [ctx]
proc agentic_info {msg {module ""} {dur ""} {error_code ""} {ctx ""}} {
    if {$module eq ""} { set module "unknown" }
    set body "\"[_agentic_ck level]\": \"INFO\""
    append body ", \"[_agentic_ck msg]\": \"[_agentic_je $msg]\""
    append body ", \"[_agentic_ck module]\": \"[_agentic_je $module]\""
    if {$dur ne ""} { append body ", \"[_agentic_ck dur]\": $dur" }
    if {$error_code ne ""} { append body ", \"[_agentic_ck error_code]\": \"$error_code\"" }
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_warn <msg> [module] [dur] [error_code] [ctx]
proc agentic_warn {msg {module ""} {dur ""} {error_code ""} {ctx ""}} {
    if {$module eq ""} { set module "unknown" }
    set body "\"[_agentic_ck level]\": \"WARN\""
    append body ", \"[_agentic_ck msg]\": \"[_agentic_je $msg]\""
    append body ", \"[_agentic_ck module]\": \"[_agentic_je $module]\""
    if {$dur ne ""} { append body ", \"[_agentic_ck dur]\": $dur" }
    if {$error_code ne ""} { append body ", \"[_agentic_ck error_code]\": \"$error_code\"" }
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_error <msg> [module] [error_code] [tid] [dur] [ctx]
# (error_code defaults to UNKNOWN when omitted — matches Python.)
proc agentic_error {msg {module ""} {error_code "UNKNOWN"} {tid ""} {dur ""} {ctx ""}} {
    if {$module eq ""} { set module "unknown" }
    set body "\"[_agentic_ck level]\": \"ERROR\""
    append body ", \"[_agentic_ck msg]\": \"[_agentic_je $msg]\""
    append body ", \"[_agentic_ck module]\": \"[_agentic_je $module]\""
    if {$error_code ne ""} { append body ", \"[_agentic_ck error_code]\": \"$error_code\"" }
    if {$tid ne ""} { append body ", \"[_agentic_ck tid]\": \"$tid\"" }
    if {$dur ne ""} { append body ", \"[_agentic_ck dur]\": $dur" }
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_tool_call <tool> <cmd> <exit> <dur> [error_code] [tid] [stdout] [stderr] [ctx]
proc agentic_tool_call {tool cmd exit dur {error_code ""} {tid ""} {stdout ""} {stderr ""} {ctx ""}} {
    if {$exit eq "0"} { set msg "Tool $tool succeeded" } else { set msg "Tool $tool failed" }
    set body "\"[_agentic_ck level]\": \"TOOL\""
    append body ", \"[_agentic_ck msg]\": \"[_agentic_je $msg]\""
    append body ", \"[_agentic_ck tool]\": \"[_agentic_je $tool]\""
    append body ", \"[_agentic_ck cmd]\": \"[_agentic_je $cmd]\""
    append body ", \"[_agentic_ck exit]\": $exit"
    append body ", \"[_agentic_ck dur]\": $dur"
    if {$error_code ne ""} { append body ", \"[_agentic_ck error_code]\": \"$error_code\"" }
    if {$tid ne ""} { append body ", \"[_agentic_ck tid]\": \"$tid\"" }
    if {$stdout ne ""} { append body ", \"[_agentic_ck stdout]\": \"[_agentic_je $stdout]\"" }
    if {$stderr ne ""} { append body ", \"[_agentic_ck stderr]\": \"[_agentic_je $stderr]\"" }
    append body ", \"[_agentic_ck module]\": \"unknown\""
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_file_op <op> <path> <ok> [size] [error_code] [tid] [dur] [ctx]
proc agentic_file_op {op path ok {size ""} {error_code ""} {tid ""} {dur ""} {ctx ""}} {
    set okj "false"
    if {$ok eq "1" || $ok eq "true"} { set okj "true" }
    if {$okj eq "true"} { set msg "File $op succeeded: $path" } else { set msg "File $op failed: $path" }
    set body "\"[_agentic_ck level]\": \"FILE_OP\""
    append body ", \"[_agentic_ck msg]\": \"[_agentic_je $msg]\""
    append body ", \"[_agentic_ck op]\": \"$op\""
    append body ", \"[_agentic_ck path]\": \"[_agentic_je $path]\""
    append body ", \"[_agentic_ck ok]\": $okj"
    if {$size ne ""} { append body ", \"[_agentic_ck size]\": $size" }
    if {$error_code ne ""} { append body ", \"[_agentic_ck error_code]\": \"$error_code\"" }
    if {$tid ne ""} { append body ", \"[_agentic_ck tid]\": \"$tid\"" }
    if {$dur ne ""} { append body ", \"[_agentic_ck dur]\": $dur" }
    append body ", \"[_agentic_ck module]\": \"unknown\""
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_decision <choice> [alts_list] [reason] [confidence] [module] [ctx]
proc agentic_decision {choice {alts ""} {reason ""} {confidence ""} {module ""} {ctx ""}} {
    if {$module eq ""} { set module "unknown" }
    set body "\"[_agentic_ck level]\": \"DECISION\""
    append body ", \"[_agentic_ck msg]\": \"Decision: [_agentic_je $choice]\""
    append body ", \"[_agentic_ck choice]\": \"[_agentic_je $choice]\""
    if {$alts ne ""} { append body ", \"[_agentic_ck alts]\": [_agentic_json_arr $alts]" }
    if {$reason ne ""} { append body ", \"[_agentic_ck reason]\": \"[_agentic_je $reason]\"" }
    if {$confidence ne ""} { append body ", \"confidence\": $confidence" }
    append body ", \"[_agentic_ck module]\": \"[_agentic_je $module]\""
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_code_gen <lang> <path> [lines] [funcs_list] [module] [ctx]
proc agentic_code_gen {lang path {lines ""} {funcs ""} {module ""} {ctx ""}} {
    if {$module eq ""} { set module "unknown" }
    set body "\"[_agentic_ck level]\": \"CODE_GEN\""
    append body ", \"[_agentic_ck msg]\": \"Generated $lang code: [_agentic_je $path]\""
    append body ", \"[_agentic_ck lang]\": \"$lang\""
    append body ", \"[_agentic_ck path]\": \"[_agentic_je $path]\""
    if {$lines ne ""} { append body ", \"[_agentic_ck lines]\": $lines" }
    if {$funcs ne ""} { append body ", \"[_agentic_ck funcs]\": [_agentic_json_arr $funcs]" }
    append body ", \"[_agentic_ck module]\": \"[_agentic_je $module]\""
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_context_switch <to_task> [from_task] [reason] [module] [ctx]
proc agentic_context_switch {to_task {from_task ""} {reason ""} {module ""} {ctx ""}} {
    if {$module eq ""} { set module "unknown" }
    set body "\"[_agentic_ck level]\": \"CONTEXT\""
    append body ", \"[_agentic_ck msg]\": \"Switching to: [_agentic_je $to_task]\""
    append body ", \"to_task\": \"[_agentic_je $to_task]\""
    if {$from_task ne ""} { append body ", \"from_task\": \"[_agentic_je $from_task]\"" }
    if {$reason ne ""} { append body ", \"[_agentic_ck reason]\": \"[_agentic_je $reason]\"" }
    append body ", \"[_agentic_ck module]\": \"[_agentic_je $module]\""
    if {$ctx ne ""} { append body ", \"[_agentic_ck ctx]\": $ctx" }
    _agentic_write $body
}

# agentic_save_traceback <tid> <exc_type> <exc_msg> <traceback>
# Sidecar always uses FULL keys (contract §5). Newlines are JSON-escaped.
proc agentic_save_traceback {tid exc_type exc_msg traceback} {
    global agentic_file
    set tb_path [string map {.jsonl .tracebacks} $agentic_file]
    set fh [open $tb_path a]
    puts $fh "{\"tid\": \"$tid\", \"exception_type\": \"[_agentic_je $exc_type]\", \"exception_msg\": \"[_agentic_je $exc_msg]\", \"traceback\": \"[_agentic_je $traceback]\"}"
    close $fh
}

# agentic_save_traceback_new <exc_type> <exc_msg> <traceback>  -> returns tid (tb_+8hex)
proc agentic_save_traceback_new {exc_type exc_msg traceback} {
    set tid "tb_[_agentic_gen_rid]"
    agentic_save_traceback $tid $exc_type $exc_msg $traceback
    return $tid
}

# Helper: build a ctx JSON object from key/value args (numeric values are
# written unquoted).  e.g.  agentic_kv file data.json size 1024
proc agentic_kv {args} {
    set out "{"
    set first 1
    foreach {k v} $args {
        if {!$first} { append out ", " }
        set first 0
        append out "\"[_agentic_je $k]\": "
        if {[string is integer -strict $v]} {
            append out $v
        } elseif {[string is double -strict $v]} {
            append out $v
        } else {
            append out "\"[_agentic_je $v]\""
        }
    }
    append out "}"
    return $out
}

# ---------------------------------------------------------------------------
# Self-test: `tclsh agentic_logger.tcl --self-test [dir]`
# ---------------------------------------------------------------------------
if {[llength $argv] > 0 && [lindex $argv 0] eq "--self-test"} {
    set _dir [lindex $argv 1]
    if {$_dir eq ""} { set _dir "/tmp/agentic_tcl_selftest" }
    agentic_init "selftest" "demo" $_dir "deadbeef"
    agentic_info "Processing started" "parser" 12 "UNKNOWN" [agentic_kv file data.json size 1024]
    agentic_warn "slow op" "db" 5000
    agentic_error "Build failed" "build" "EXEC_NON_ZERO" "tb_abcd1234"
    agentic_tool_call "bash" "npm install" 0 1234 "" "" "added 50 pkgs"
    agentic_tool_call "bash" "make fail" 1 5000 "EXEC_NON_ZERO"
    agentic_file_op "write" "/p/f.tcl" 1 2048
    agentic_file_op "read" "/missing.tcl" 0 "" "IO_NOT_FOUND"
    agentic_decision "use_redis" "redis memcached" "perf" 0.85 "arch"
    agentic_code_gen "tcl" "src/main.tcl" 50 "main helper"
    agentic_context_switch "test" "build" "done"
    agentic_save_traceback_new "ValueError" "bad input" "Traceback (most recent call last):\n  File \"x\""
    agentic_close
    puts "file: [agentic_log_path]"
}
