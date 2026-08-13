import { describe, test, expect } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentLogger, ErrorCode } from "../src/index.ts";

function newDir(): string {
  return mkdtempSync(join(tmpdir(), "agentic-ts-"));
}

function readJsonl(path: string): Record<string, unknown>[] {
  return readFileSync(path, "utf8")
    .trimEnd()
    .split("\n")
    .map((l) => JSON.parse(l));
}

describe("byte-compatible JSONL", () => {
  test("writes header + all entry types with correct field types", () => {
    const dir = newDir();
    const lg = new AgentLogger({ program: "ts_probe", command: "demo", logDir: dir, rid: "cafebabe" });

    lg.info("Processing started", { module: "parser", dur: 12, ctx: { file: "data.json", size: 1024 } });
    lg.toolCall({ tool: "bash", cmd: "npm install", exit: 0, dur: 1234, stdout: "added 50 pkgs" });
    lg.error("Build failed", { module: "build", errorCode: ErrorCode.EXEC_NON_ZERO, tid: "tb_abcd1234" });
    lg.fileOp({ op: "write", path: "/p/f.ts", ok: true, size: 2048, dur: 5 });
    lg.decision({ choice: "use_redis", alts: ["redis", "memcached"], reason: "perf", confidence: 0.85, module: "arch" });
    lg.codeGen({ lang: "ts", path: "src/main.ts", lines: 50, funcs: ["main", "helper"] });
    lg.contextSwitch({ toTask: "test", fromTask: "build", reason: "done" });

    const entries = readJsonl(lg.filePath);
    expect(entries.length).toBe(8); // header + 7

    expect(entries[0].level).toBe("__GLOBAL_CTX__");
    expect(entries[0].seq).toBe(0);

    for (const e of entries) {
      expect(typeof e.pid).toBe("string"); // pid is STRING
      expect(typeof e.seq).toBe("number"); // seq is NUMBER
      expect(e.rid).toBe("cafebabe");
      expect(typeof e.ts).toBe("string");
      expect(String(e.ts)).toMatch(/\+00:00$/);
    }

    const tool = entries.find((e) => e.level === "TOOL")!;
    expect(tool.exit).toBe(0);
    expect(typeof tool.exit).toBe("number");
    const dec = entries.find((e) => e.level === "DECISION")!;
    expect(dec.confidence).toBe(0.85);
    rmSync(dir, { recursive: true, force: true });
  });

  test("separators match Python (spaces after : and ,)", () => {
    const dir = newDir();
    const lg = new AgentLogger({ program: "sep", command: "d", logDir: dir });
    lg.info("hi 中文 <b>", { module: "m" });
    const raw = readFileSync(lg.filePath, "utf8");
    // critical for Python stats byte-count
    expect(raw).toContain('"level": "INFO"');
    // no HTML escaping
    expect(raw).not.toContain("\\u003c");
    // raw UTF-8 (ensure_ascii=false equivalent)
    expect(raw).toContain("中文");
    rmSync(dir, { recursive: true, force: true });
  });

  test("omits null/undefined fields", () => {
    const dir = newDir();
    const lg = new AgentLogger({ program: "nulls", command: "d", logDir: dir });
    lg.info("plain");
    const raw = readFileSync(lg.filePath, "utf8");
    const line = raw.trimEnd().split("\n").pop()!;
    expect(line).not.toContain('"dur"');
    expect(line).not.toContain('"error_code"');
    rmSync(dir, { recursive: true, force: true });
  });

  test("compact mode matches Python single-char keys", () => {
    const dir = newDir();
    const lg = new AgentLogger({ program: "cp", command: "d", logDir: dir, rid: "cafe0000", compact: true });
    lg.info("hi 中文", { module: "parser", dur: 12, ctx: { f: "d.json" } });
    lg.toolCall({ tool: "bash", cmd: "npm i", exit: 0, dur: 5, stdout: "ok" });
    lg.decision({ choice: "x", alts: ["a", "b"], reason: "r", confidence: 0.5, module: "m" });
    const raw = readFileSync(lg.filePath, "utf8");
    expect(raw).toContain('"l": "INFO"');      // level→l
    expect(raw).toContain('"n": "parser"');    // module→n
    expect(raw).toContain('"d": 12');          // dur→d
    expect(raw).toContain('"z": {"f":"d.json"}'); // ctx→z; nested ctx keys NOT compacted
    expect(raw).toContain('"confidence": 0.5'); // unmapped key passes through
    expect(raw).toContain('"x": 0');           // exit→x
    rmSync(dir, { recursive: true, force: true });
  });

  test("traceback sidecar uses full keys + tb_ tid", () => {
    const dir = newDir();
    const lg = new AgentLogger({ program: "tb", command: "d", logDir: dir });
    const tid = lg.saveTraceback("ValueError", "bad", "Traceback:\n  boom");
    expect(tid).toMatch(/^tb_[0-9a-f]{8}$/);
    const tb = readFileSync(lg.tracebackPath, "utf8").trim();
    expect(tb).toContain('"tid":');
    expect(tb).toContain('"exception_type": "ValueError"');
    expect(tb).toContain('"traceback": "Traceback:\\n  boom"');
    rmSync(dir, { recursive: true, force: true });
  });
});
