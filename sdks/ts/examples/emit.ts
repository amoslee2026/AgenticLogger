// Run: `bun examples/emit.ts <outDir>`
import { AgentLogger, ErrorCode } from "../src/index.ts";

const dir = process.argv[2] || "/tmp/xlang_ts";
const lg = new AgentLogger({ program: "ts_probe", command: "demo", logDir: dir, rid: "cafebabe", compact: process.env.COMPACT === "1" });
lg.info("Processing started", { module: "parser", dur: 12, ctx: { file: "data.json", size: 1024 } });
lg.warn("slow op", { module: "db", dur: 5000 });
lg.toolCall({ tool: "bash", cmd: "npm install", exit: 0, dur: 1234, stdout: "added 50 pkgs" });
lg.error("Build failed", { module: "build", errorCode: ErrorCode.EXEC_NON_ZERO, tid: "tb_abcd1234" });
lg.fileOp({ op: "write", path: "/p/f.ts", ok: true, size: 2048, dur: 5 });
lg.fileOp({ op: "read", path: "/missing.ts", ok: false, errorCode: ErrorCode.IO_NOT_FOUND });
lg.decision({ choice: "use_redis", alts: ["redis", "memcached"], reason: "perf", confidence: 0.85, module: "arch" });
lg.codeGen({ lang: "ts", path: "src/main.ts", lines: 50, funcs: ["main", "helper"] });
lg.contextSwitch({ toTask: "test", fromTask: "build", reason: "done" });
console.log(lg.filePath);
