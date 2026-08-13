// agentic_logger_pkg.sv — AgenticLogger SystemVerilog SDK.
//
// Emits byte-compatible JSONL (readable by the Python query layer) from
// SystemVerilog testbenches / verification agents. Platform bits (wall-clock,
// rid, pid) come from a tiny DPI-C bridge (agentic_logger_dpi.c). Supports
// compact-key mode (contract §4) and a traceback sidecar (contract §5).
//
// @contract: sdks/INTERCHANGE.md
//
// NOTE: `program` and `module` are SystemVerilog reserved words → renamed to
// `prog` / `mod_name` on the API surface.

`ifndef AGENTIC_LOGGER_PKG_SV
`define AGENTIC_LOGGER_PKG_SV

package agentic_logger_pkg;

  import "DPI-C" function string agentic_get_ts();
  import "DPI-C" function string agentic_gen_rid();
  import "DPI-C" function string agentic_get_pid();

  // ---- JSON string escape -------------------------------------------------
  function automatic string agentic_esc(string s);
    string out; integer i; byte c;
    out = "";
    for (i = 0; i < s.len(); i++) begin
      c = s[i];
      if (c == 8'h5C) out = {out, "\\\\"};
      else if (c == 8'h22) out = {out, "\\\""};
      else out = {out, string'(c)};
    end
    return out;
  endfunction

  function automatic string agentic_sanitize(string s);
    string out; integer i, n; byte c;
    out = ""; n = s.len(); if (n > 50) n = 50;
    for (i = 0; i < n; i++) begin
      c = s[i];
      if ((c >= 8'h30 && c <= 8'h39) || (c >= 8'h41 && c <= 8'h5A) ||
          (c >= 8'h61 && c <= 8'h7A) || c == 8'h5F || c == 8'h2D)
        out = {out, string'(c)};
      else out = {out, "_"};
    end
    return out;
  endfunction

  function automatic string agentic_real_str(real r);
    return $sformatf("%0.2f", r);
  endfunction

  // Full JSON-string escape (for sidecar values): \\ \" \n \r \t.
  function automatic string agentic_esc_json(string s);
    string out; integer i; byte c;
    out = "";
    for (i = 0; i < s.len(); i++) begin
      c = s[i];
      if (c == 8'h5C) out = {out, "\\\\"};
      else if (c == 8'h22) out = {out, "\\\""};
      else if (c == 8'h0A) out = {out, "\\n"};
      else if (c == 8'h0D) out = {out, "\\r"};
      else if (c == 8'h09) out = {out, "\\t"};
      else out = {out, string'(c)};
    end
    return out;
  endfunction

  // ---- AgentLogger class --------------------------------------------------
  class AgentLogger;
    string  prog_name;
    string  command_name;
    string  rid;
    string  pid;
    integer fd;
    integer seq;
    bit     compact;
    string  file_path;

    function new(string prog, string command = "",
                 string log_dir = "./logs", string rid_in = "",
                 bit compact = 0);
      string safe_p, safe_c, ts, stamp;
      this.prog_name = agentic_sanitize(prog);
      if (command == "") this.command_name = {"pid", agentic_get_pid()};
      else               this.command_name = agentic_sanitize(command);
      this.rid = (rid_in != "") ? rid_in : agentic_gen_rid();
      this.pid = agentic_get_pid();
      this.seq = 0;
      this.compact = compact;

      ts = agentic_get_ts();
      stamp = {ts.substr(0,3), ts.substr(5,6), ts.substr(8,9), "_",
               ts.substr(11,12), ts.substr(14,15), ts.substr(17,18),
               ts.substr(20,22), "000"};
      this.file_path = {log_dir, "/", this.prog_name, "_",
                        this.command_name, "_", stamp, ".jsonl"};
      this.fd = $fopen(this.file_path, "a");
      if (this.fd == 0) $display("[agentic_logger] cannot open %0s", this.file_path);
      this.write_header(ts);
    endfunction

    // Compact-key translation (contract §4); top-level keys only.
    function string ck(string key);
      if (!this.compact) return key;
      case (key)
        "ts": return "t"; "level": return "l"; "module": return "n"; "msg": return "m";
        "pid": return "p"; "rid": return "r"; "seq": return "q"; "error_code": return "e";
        "dur": return "d"; "tool": return "o"; "cmd": return "c"; "exit": return "x";
        "op": return "w"; "path": return "h"; "ctx": return "z"; "tid": return "i";
        "lines": return "s"; "funcs": return "f"; "lang": return "g"; "choice": return "k";
        "alts": return "a"; "reason": return "u"; "stdout": return "v"; "stderr": return "b";
        "ok": return "y"; "size": return "j"; default: return key;
      endcase
    endfunction

    // emit a `"key": ` prefix fragment honoring compact mode.
    function string kf(string key);
      return {"\"", this.ck(key), "\": "};
    endfunction

    function void write_header(string ts);
      string line;
      line = {"{", this.kf("ts"), "\"", ts, "\"", ", ",
              this.kf("level"), "\"__GLOBAL_CTX__\"", ", ",
              this.kf("msg"), "\"Global context\"", ", ",
              this.kf("module"), "\"__system__\"", ", ",
              this.kf("rid"), "\"", this.rid, "\"", ", ",
              this.kf("pid"), "\"", this.pid, "\"", ", ",
              this.kf("seq"), "0", ", ",
              "\"program\": \"", this.prog_name, "\", \"command\": \"", this.command_name, "\"}\n"};
      if (this.fd != 0) $fwrite(this.fd, line);
    endfunction

    function void write_entry(string body);
      string ts, line;
      if (this.fd == 0) return;
      this.seq = this.seq + 1;
      ts = agentic_get_ts();
      line = {"{", body, ", ",
              this.kf("ts"), "\"", ts, "\"", ", ",
              this.kf("pid"), "\"", this.pid, "\"", ", ",
              this.kf("rid"), "\"", this.rid, "\"", ", ",
              this.kf("seq"), $sformatf("%0d", this.seq), "}\n"};
      $fwrite(this.fd, line);
    endfunction

    function void close();
      if (this.fd != 0) $fclose(this.fd);
      this.fd = 0;
    endfunction

    // Traceback sidecar (contract §5; sidecar always uses FULL keys).
    function string save_traceback(string exc_type, string exc_msg, string traceback);
      string tid, tb_path, line; integer tbfd;
      tid = {"tb_", agentic_gen_rid()};
      tb_path = {this.file_path.substr(0, this.file_path.len()-6), "tracebacks"};
      tbfd = $fopen(tb_path, "a");
      if (tbfd != 0) begin
        line = {"{\"tid\": \"", tid, "\", \"exception_type\": \"", agentic_esc_json(exc_type),
                "\", \"exception_msg\": \"", agentic_esc_json(exc_msg),
                "\", \"traceback\": \"", agentic_esc_json(traceback), "\"}\n"};
        $fwrite(tbfd, line);
        $fclose(tbfd);
      end
      return tid;
    endfunction

    // ---- basic levels -----------------------------------------------------
    function void info(string msg, string mod_name = "unknown",
                       integer dur = -1, string error_code = "",
                       string tid = "", string ctx_json = "");
      this.basic("INFO", msg, mod_name, dur, error_code, tid, ctx_json);
    endfunction
    function void warn(string msg, string mod_name = "unknown",
                       integer dur = -1, string error_code = "",
                       string tid = "", string ctx_json = "");
      this.basic("WARN", msg, mod_name, dur, error_code, tid, ctx_json);
    endfunction
    function void error(string msg, string mod_name = "unknown",
                        string error_code = "UNKNOWN",
                        string tid = "", integer dur = -1, string ctx_json = "");
      string body;
      body = {this.kf("level"), "\"ERROR\"", ", ", this.kf("msg"), "\"", agentic_esc(msg), "\"",
              ", ", this.kf("module"), "\"", agentic_esc(mod_name), "\"",
              ", ", this.kf("error_code"), "\"", error_code, "\""};
      if (tid != "")      body = {body, ", ", this.kf("tid"), "\"", tid, "\""};
      if (dur >= 0)       body = {body, ", ", this.kf("dur"), $sformatf("%0d", dur)};
      if (ctx_json != "") body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    function void basic(string level, string msg, string mod_name,
                        integer dur, string error_code, string tid, string ctx_json);
      string body;
      body = {this.kf("level"), "\"", level, "\"", ", ",
              this.kf("msg"), "\"", agentic_esc(msg), "\"", ", ",
              this.kf("module"), "\"", agentic_esc(mod_name), "\""};
      if (dur >= 0)       body = {body, ", ", this.kf("dur"), $sformatf("%0d", dur)};
      if (error_code != "") body = {body, ", ", this.kf("error_code"), "\"", error_code, "\""};
      if (tid != "")      body = {body, ", ", this.kf("tid"), "\"", tid, "\""};
      if (ctx_json != "") body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    // ---- specialised ------------------------------------------------------
    function void tool_call(string tool, string cmd, integer exit_code, integer dur,
                            string error_code = "", string tid = "",
                            string stdout_s = "", string stderr_s = "",
                            string ctx_json = "");
      string body, msg;
      if (exit_code == 0) msg = {"Tool ", tool, " succeeded"};
      else                msg = {"Tool ", tool, " failed"};
      body = {this.kf("level"), "\"TOOL\"", ", ", this.kf("msg"), "\"", agentic_esc(msg), "\"",
              ", ", this.kf("tool"), "\"", agentic_esc(tool), "\"",
              ", ", this.kf("cmd"), "\"", agentic_esc(cmd), "\"",
              ", ", this.kf("exit"), $sformatf("%0d", exit_code),
              ", ", this.kf("dur"), $sformatf("%0d", dur)};
      if (error_code != "") body = {body, ", ", this.kf("error_code"), "\"", error_code, "\""};
      if (tid != "")        body = {body, ", ", this.kf("tid"), "\"", tid, "\""};
      if (stdout_s != "")   body = {body, ", ", this.kf("stdout"), "\"", agentic_esc(stdout_s), "\""};
      if (stderr_s != "")   body = {body, ", ", this.kf("stderr"), "\"", agentic_esc(stderr_s), "\""};
      body = {body, ", ", this.kf("module"), "\"unknown\""};
      if (ctx_json != "")   body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    function void file_op(string op, string path, bit ok,
                          integer sz = -1, string error_code = "",
                          string tid = "", integer dur = -1, string ctx_json = "");
      string body, msg, ok_s;
      ok_s = ok ? "true" : "false";
      if (ok) msg = {"File ", op, " succeeded: ", path};
      else    msg = {"File ", op, " failed: ", path};
      body = {this.kf("level"), "\"FILE_OP\"", ", ", this.kf("msg"), "\"", agentic_esc(msg), "\"",
              ", ", this.kf("op"), "\"", op, "\"",
              ", ", this.kf("path"), "\"", agentic_esc(path), "\"",
              ", ", this.kf("ok"), ok_s};
      if (sz >= 0)          body = {body, ", ", this.kf("size"), $sformatf("%0d", sz)};
      if (error_code != "") body = {body, ", ", this.kf("error_code"), "\"", error_code, "\""};
      if (tid != "")        body = {body, ", ", this.kf("tid"), "\"", tid, "\""};
      if (dur >= 0)         body = {body, ", ", this.kf("dur"), $sformatf("%0d", dur)};
      body = {body, ", ", this.kf("module"), "\"unknown\""};
      if (ctx_json != "")   body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    function void decision(string choice, string alts[$],
                           string reason = "", real confidence = -1.0,
                           string mod_name = "unknown", string ctx_json = "");
      string body;
      body = {this.kf("level"), "\"DECISION\"", ", ", this.kf("msg"), "\"Decision: ", agentic_esc(choice), "\"",
              ", ", this.kf("choice"), "\"", agentic_esc(choice), "\""};
      if (alts.size() > 0)   body = {body, ", ", this.kf("alts"), str_arr(alts)};
      if (reason != "")      body = {body, ", ", this.kf("reason"), "\"", agentic_esc(reason), "\""};
      if (confidence >= 0.0) body = {body, ", \"confidence\": ", agentic_real_str(confidence)};
      body = {body, ", ", this.kf("module"), "\"", agentic_esc(mod_name), "\""};
      if (ctx_json != "")    body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    function void code_gen(string lang, string path,
                           string funcs[$], integer lines = -1,
                           string mod_name = "unknown", string ctx_json = "");
      string body;
      body = {this.kf("level"), "\"CODE_GEN\"", ", ", this.kf("msg"), "\"Generated ", lang, " code: ", agentic_esc(path), "\"",
              ", ", this.kf("lang"), "\"", lang, "\"",
              ", ", this.kf("path"), "\"", agentic_esc(path), "\""};
      if (funcs.size() > 0)  body = {body, ", ", this.kf("funcs"), str_arr(funcs)};
      if (lines >= 0)        body = {body, ", ", this.kf("lines"), $sformatf("%0d", lines)};
      body = {body, ", ", this.kf("module"), "\"", agentic_esc(mod_name), "\""};
      if (ctx_json != "")    body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    function void context_switch(string to_task, string from_task = "",
                                 string reason = "", string mod_name = "unknown",
                                 string ctx_json = "");
      string body;
      body = {this.kf("level"), "\"CONTEXT\"", ", ", this.kf("msg"), "\"Switching to: ", agentic_esc(to_task), "\"",
              ", \"to_task\": \"", agentic_esc(to_task), "\""};
      if (from_task != "") body = {body, ", \"from_task\": \"", agentic_esc(from_task), "\""};
      if (reason != "")    body = {body, ", ", this.kf("reason"), "\"", agentic_esc(reason), "\""};
      body = {body, ", ", this.kf("module"), "\"", agentic_esc(mod_name), "\""};
      if (ctx_json != "")  body = {body, ", ", this.kf("ctx"), ctx_json};
      this.write_entry(body);
    endfunction

    function string str_arr(string arr[$]);
      string out; int i;
      out = "[";
      for (i = 0; i < arr.size(); i++) begin
        if (i > 0) out = {out, ", "};
        out = {out, "\"", agentic_esc(arr[i]), "\""};
      end
      out = {out, "]"};
      return out;
    endfunction

  endclass

endpackage

`endif
