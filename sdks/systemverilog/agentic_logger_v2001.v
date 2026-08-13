// agentic_logger_v2001.v — AgenticLogger Verilog-2001 (IEEE 1364) subset.
//
// SystemVerilog (agentic_logger_pkg.sv) is the recommended, full-featured SDK.
// Pure Verilog-2001 has no `string` type, no classes, no packages, and no
// portable wall-clock ($system is SV-only). This file therefore provides a
// **minimal subset** using `task` + `reg` vector JSON building, intended for
// legacy Verilog testbenches. It emits the SAME JSONL format (contract:
// sdks/INTERCHANGE.md) so the Python query layer reads it unchanged.
//
// Limitations vs the SV package:
//   * No wall-clock: caller supplies the ISO 8601 timestamp string via
//     `al_set_ts` (e.g. captured from `$system` on SV, or a software driver,
//     or sim-time formatted). All entries reuse the last-set ts.
//   * pid defaults to "0" (no getpid in V2001); override via al_set_pid.
//   * Core levels only: info / warn / error / tool_call / file_op.
//   * No array fields (alts/funcs) — pass pre-built JSON fragments if needed.
//
// Usage (`\`include "agentic_logger_v2001.v"` inside an `initial` block scope):
//   reg [8*120-1:0] _al_ts; integer _al_fd; integer _al_seq;
//   initial begin
//     al_set_ts("2026-08-13T06:00:00.000+00:00");
//     al_init("my_agent", "sim", "./logs", "r1d00000");
//     al_info("started", "tb");
//     al_error("assert", "chk", "INTERNAL_ASSERT");
//     al_close();
//   end

`ifndef AGENTIC_LOGGER_V2001_V
`define AGENTIC_LOGGER_V2001_V

// Shared state — declare these in the same scope as the `\`include`.
// (Kept as plain identifiers so callers see them; not redeclared here to avoid
//  multi-include conflicts. See usage comment above for the declarations.)
integer _al_fd;
integer _al_seq;
reg [8*128-1:0] _al_rid;
reg [8*32-1:0]  _al_pid;
reg [8*64-1:0]  _al_ts;
reg [8*256-1:0] _al_path;

task al_set_ts;
  input [8*64-1:0] ts;
  begin _al_ts = ts; end
endtask

task al_set_pid;
  input [8*32-1:0] pid;
  begin _al_pid = pid; end
endtask

task al_init;
  input [8*64-1:0] prog;
  input [8*64-1:0] cmd;
  input [8*256-1:0] dir;
  input [8*128-1:0] rid;
  reg [8*512-1:0] fname;
  reg [8*512-1:0] hdr;
  begin
    _al_rid = rid;
    if (_al_pid == 0) _al_pid = "0";
    _al_seq = 0;
    $sformat(fname, "%0s/%0s_%0s_v2001.jsonl", dir, prog, cmd);
    _al_path = fname;
    _al_fd = $fopen(fname, "w");
    _al_seq = 0;
    $sformat(hdr,
      "{\"ts\": \"%0s\", \"level\": \"__GLOBAL_CTX__\", \"msg\": \"Global context\", \"module\": \"__system__\", \"rid\": \"%0s\", \"pid\": \"%0s\", \"seq\": 0, \"program\": \"%0s\", \"command\": \"%0s\"}\n",
      _al_ts, _al_rid, _al_pid, prog, cmd);
    $fwrite(_al_fd, hdr);
  end
endtask

// internal: append auto-fields tail to a pre-formed body and write.
task _al_emit;
  input [8*512-1:0] body;
  begin
    _al_seq = _al_seq + 1;
    $fwrite(_al_fd,
      "{%0s, \"ts\": \"%0s\", \"pid\": \"%0s\", \"rid\": \"%0s\", \"seq\": %0d}\n",
      body, _al_ts, _al_pid, _al_rid, _al_seq);
  end
endtask

task al_info;
  input [8*512-1:0] msg;
  input [8*128-1:0] mod_name;
  reg [8*512-1:0] b;
  begin
    $sformat(b, "\"level\": \"INFO\", \"msg\": \"%0s\", \"module\": \"%0s\"", msg, mod_name);
    _al_emit(b);
  end
endtask

task al_warn;
  input [8*512-1:0] msg;
  input [8*128-1:0] mod_name;
  reg [8*512-1:0] b;
  begin
    $sformat(b, "\"level\": \"WARN\", \"msg\": \"%0s\", \"module\": \"%0s\"", msg, mod_name);
    _al_emit(b);
  end
endtask

task al_error;
  input [8*512-1:0] msg;
  input [8*128-1:0] mod_name;
  input [8*64-1:0]  error_code;
  reg [8*512-1:0] b;
  begin
    $sformat(b, "\"level\": \"ERROR\", \"msg\": \"%0s\", \"module\": \"%0s\", \"error_code\": \"%0s\"",
             msg, mod_name, error_code);
    _al_emit(b);
  end
endtask

task al_tool_call;
  input [8*128-1:0] tool;
  input [8*512-1:0] cmd;
  input [31:0] exit_code;
  input [31:0] dur;
  input [8*64-1:0] error_code;   // "" for success
  reg [8*512-1:0] b;
  begin
    if (exit_code == 0)
      $sformat(b, "\"level\": \"TOOL\", \"msg\": \"Tool %0s succeeded\", \"tool\": \"%0s\", \"cmd\": \"%0s\", \"exit\": %0d, \"dur\": %0d, \"module\": \"unknown\"",
               tool, tool, cmd, exit_code, dur);
    else
      $sformat(b, "\"level\": \"TOOL\", \"msg\": \"Tool %0s failed\", \"tool\": \"%0s\", \"cmd\": \"%0s\", \"exit\": %0d, \"dur\": %0d, \"error_code\": \"%0s\", \"module\": \"unknown\"",
               tool, tool, cmd, exit_code, dur, error_code);
    _al_emit(b);
  end
endtask

task al_file_op;
  input [8*32-1:0]  op;
  input [8*512-1:0] path;
  input ok;                       // 1-bit
  input [8*64-1:0]  error_code;
  reg [8*512-1:0] b;
  begin
    if (ok)
      $sformat(b, "\"level\": \"FILE_OP\", \"msg\": \"File %0s succeeded: %0s\", \"op\": \"%0s\", \"path\": \"%0s\", \"ok\": true, \"module\": \"unknown\"",
               op, path, op, path);
    else
      $sformat(b, "\"level\": \"FILE_OP\", \"msg\": \"File %0s failed: %0s\", \"op\": \"%0s\", \"path\": \"%0s\", \"ok\": false, \"error_code\": \"%0s\", \"module\": \"unknown\"",
               op, path, op, path, error_code);
    _al_emit(b);
  end
endtask

task al_close;
  begin
  if (_al_fd != 0) $fclose(_al_fd);
  _al_fd = 0;
  end
endtask

`endif
