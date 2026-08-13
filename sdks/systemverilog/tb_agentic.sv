`timescale 1ns/1ps
module tb_agentic;
  import agentic_logger_pkg::*;
  AgentLogger lg;
  string alts[$];
  string funcs[$];

  initial begin
    string out_dir;
    out_dir = "/tmp/xlang_sv";
    void'($value$plusargs("OUT=%s", out_dir));
    lg = new("sv_probe", "demo", out_dir, "cafebabe");
    lg.info("Processing started", "parser", 12, "", "", "{\"file\": \"data.json\", \"size\": 1024}");
    lg.warn("slow op", "db", 5000);
    lg.tool_call("bash", "npm install", 0, 1234, "", "", "added 50 pkgs");
    lg.error("Build failed", "build", "EXEC_NON_ZERO", "tb_abcd1234");
    lg.file_op("write", "/p/f.sv", 1'b1, 2048);
    lg.file_op("read", "/missing.v", 1'b0, -1, "IO_NOT_FOUND");
    alts.push_back("redis"); alts.push_back("memcached");
    lg.decision("use_redis", alts, "perf", 0.85, "arch");
    funcs.push_back("main"); funcs.push_back("helper");
    lg.code_gen("sv", "tb.sv", funcs, 50);
    lg.context_switch("test", "build", "done");
    lg.close();
    $display("WROTE %0s", lg.file_path);
    $finish;
  end
endmodule
