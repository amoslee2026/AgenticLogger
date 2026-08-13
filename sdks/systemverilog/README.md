# agentic-logger (SystemVerilog / Verilog)

Emit byte-compatible JSONL from SystemVerilog testbenches and verification
agents, so simulation activity is queryable by the same Python tooling as
software-side logs.

## SystemVerilog (recommended)

`agentic_logger_pkg.sv` provides an `AgentLogger` class. SystemVerilog has no
portable wall-clock / UUID / `getpid`, so three tiny functions live in a DPI-C
bridge (`agentic_logger_dpi.c`).

### VCS / Xcelium / Questa

```sh
# Compile the DPI C with your simulator's C compiler, then:
vcs    -sverilog agentic_logger_dpi.c agentic_logger_pkg.sv tb.sv   # + your sources
xrun   -sv      agentic_logger_dpi.c agentic_logger_pkg.sv tb.sv
qrun   -sv      agentic_logger_dpi.c agentic_logger_pkg.sv tb.sv
```

### Verilator (Linux)

```sh
./build.sh /tmp/xlang_sv        # builds + runs tb_agentic, writes to the dir
```

### Usage

```systemverilog
module tb;
  import agentic_logger_pkg::*;
  AgentLogger lg;
  string alts[$];
  initial begin
    lg = new("tb_top", "smoke", "./logs");
    lg.info("Simulation started", "tb");
    lg.tool_call("run_test", "make sim", 0, 1234);
    lg.error("assert failed", "checker", "INTERNAL_ASSERT");
    alts.push_back("a"); alts.push_back("b");
    lg.decision("a", alts, "cheapest", 0.9, "arch");
    lg.code_gen("sv", "gen/dfifo.sv", 80, alts);
    lg.close();
    $finish;
  end
endmodule
```

### API notes

- `program` and `module` are **reserved words** in SystemVerilog — the API
  renames them to `prog` (constructor 1st arg) and `mod_name`.
- `error()` is the method name (not `err`).
- Queue params (`alts`, `funcs`) are **required** (no default `{}`); pass an
  empty queue when unused: `string empty[$]; lg.decision("x", empty);`.
- Timestamps are real wall-clock via the DPI bridge (ISO 8601 UTC ms + offset),
  so `since`/`until` queries work identically to the software SDKs.

## Verilog-2001 subset (IEEE 1364)

`agentic_logger_v2001.v` is a `\`include`-able subset for legacy Verilog
testbenches. Pure Verilog-2001 has no `string` type, classes, packages, or
portable wall-clock, so it is limited:

- Caller supplies the ISO timestamp via `al_set_ts(...)` (reused for all entries).
- Core levels only: `al_info`, `al_warn`, `al_error`, `al_tool_call`, `al_file_op`.
- No array fields. `pid` defaults to `"0"`.

```verilog
module tb;
  `include "agentic_logger_v2001.v"
  initial begin
    al_set_ts("2026-08-13T06:00:00.000+00:00");
    al_init("my_agent", "sim", "./logs", "abcd1234");
    al_info("started", "tb");
    al_error("assert", "chk", "INTERNAL_ASSERT");
    al_close();
  end
endmodule
```

For anything beyond simple logging, prefer the SystemVerilog package — every
major simulator supports SV today.
