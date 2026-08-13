/**
 * # agentic-logger (TypeScript / JavaScript)
 *
 * Structured logging SDK for Coding Agents. Emits **byte-compatible** JSONL
 * that the AgenticLogger Python query layer reads without conversion.
 *
 * @contract: sdks/INTERCHANGE.md
 *
 * Why we build JSON by hand: `JSON.stringify` emits compact separators
 * (`","`, `":"`). The Python `stats` byte-counter searches for `'"level": "'`
 * (with the space), so compact output makes every entry bucket as "unknown".
 * We stringify each VALUE with JSON.stringify (correct escaping, raw UTF-8 =
 * ensure_ascii=false equivalent) and join `"key": <value>` parts with ", ".
 */
import { mkdirSync, appendFileSync } from "node:fs";
import { join } from "node:path";
import { ErrorCode } from "./errorCodes.js";
import { filenameStamp, genRid, nowIso, sanitize } from "./time.js";

export { ErrorCode } from "./errorCodes.js";
export type { ErrorCode as ErrorCodeType } from "./errorCodes.js";

/** Constructor options. */
export interface AgentLoggerOptions {
  /** Program name (filename component). */
  program: string;
  /** Sub-command; omitted → `pid<PID>`. */
  command?: string;
  /** Log directory (created if missing). Default "./logs". */
  logDir?: string;
  /** Run-id override; omitted → random 8 hex chars. */
  rid?: string;
  /** Compact-key mode (contract §4): single-char top-level keys. Default false. */
  compact?: boolean;
}

/** Optional fields shared by most log methods. */
export interface CommonFields {
  module?: string;
  dur?: number;
  errorCode?: string;
  tid?: string;
  ctx?: Record<string, unknown>;
}

const MSG_MAX = 4096;
const STREAM_MAX = 65536;

/** Compact-key map (contract §4). Top-level entry keys only; nested ctx keys
 * and unmapped keys pass through unchanged. */
const COMPACT_MAP: Record<string, string> = {
  ts: "t", level: "l", module: "n", msg: "m", pid: "p", rid: "r", seq: "q",
  error_code: "e", dur: "d", tool: "o", cmd: "c", exit: "x", op: "w", path: "h",
  ctx: "z", tid: "i", lines: "s", funcs: "f", lang: "g", choice: "k", alts: "a",
  reason: "u", stdout: "v", stderr: "b", ok: "y", size: "j",
};

/** One run → one JSONL file. Thread-safe via synchronous append. */
export class AgentLogger {
  readonly program: string;
  readonly command: string;
  readonly rid: string;
  readonly filePath: string;
  private readonly pid: string;
  private readonly compact: boolean;
  private seq = 0;

  constructor(opts: AgentLoggerOptions) {
    const pid = String(process.pid);
    this.pid = pid;
    this.rid = opts.rid ?? genRid();
    this.compact = opts.compact ?? false;
    this.program = sanitize(opts.program);
    const rawCmd = opts.command ?? `pid${pid}`;
    this.command = sanitize(rawCmd);
    const logDir = opts.logDir ?? "./logs";
    mkdirSync(logDir, { recursive: true });
    this.filePath = join(logDir, `${this.program}_${this.command}_${filenameStamp()}.jsonl`);

    // Global-context header (contract §1.2).
    const hdr = new Entry(this.compact);
    hdr.add("ts", nowIso());
    hdr.add("level", "__GLOBAL_CTX__");
    hdr.add("msg", "Global context");
    hdr.add("module", "__system__");
    hdr.add("rid", this.rid);
    hdr.add("pid", pid);
    hdr.add("seq", 0);
    hdr.add("program", this.program);
    hdr.add("command", this.command);
    this.appendRaw(hdr.toString());
  }

  // ---- basic levels -------------------------------------------------------

  info(msg: string, f: CommonFields = {}): void {
    this.basic("INFO", msg, f);
  }
  warn(msg: string, f: CommonFields = {}): void {
    this.basic("WARN", msg, f);
  }
  error(msg: string, f: CommonFields = {}): void {
    this.basic("ERROR", msg, { errorCode: ErrorCode.UNKNOWN, ...f });
  }

  private basic(level: string, msg: string, f: CommonFields): void {
    const e = new Entry(this.compact);
    e.add("level", level);
    e.add("msg", truncate(msg, MSG_MAX));
    e.add("module", f.module ?? "unknown");
    e.addOpt("dur", f.dur);
    e.addOpt("error_code", f.errorCode);
    e.addOpt("tid", f.tid);
    e.addOpt("ctx", f.ctx);
    this.write(e);
  }

  // ---- specialised --------------------------------------------------------

  toolCall(args: {
    tool: string;
    cmd: string;
    exit: number;
    dur: number;
    errorCode?: string;
    tid?: string;
    stdout?: string;
    stderr?: string;
    module?: string;
    ctx?: Record<string, unknown>;
  }): void {
    const ok = args.exit === 0;
    const e = new Entry(this.compact);
    e.add("level", "TOOL");
    e.add("msg", `Tool ${args.tool} ${ok ? "succeeded" : "failed"}`);
    e.add("tool", args.tool);
    e.add("cmd", args.cmd);
    e.add("exit", args.exit);
    e.add("dur", args.dur);
    e.addOpt("error_code", args.errorCode);
    e.addOpt("tid", args.tid);
    e.addOpt("stdout", args.stdout !== undefined ? truncate(args.stdout, STREAM_MAX) : undefined);
    e.addOpt("stderr", args.stderr !== undefined ? truncate(args.stderr, STREAM_MAX) : undefined);
    e.add("module", args.module ?? "unknown");
    e.addOpt("ctx", args.ctx);
    this.write(e);
  }

  fileOp(args: {
    op: "read" | "write" | "delete" | "move" | "copy";
    path: string;
    ok: boolean;
    size?: number;
    errorCode?: string;
    tid?: string;
    dur?: number;
    module?: string;
    ctx?: Record<string, unknown>;
  }): void {
    const e = new Entry(this.compact);
    e.add("level", "FILE_OP");
    e.add("msg", `File ${args.op} ${args.ok ? "succeeded" : "failed"}: ${args.path}`);
    e.add("op", args.op);
    e.add("path", args.path);
    e.add("ok", args.ok);
    e.addOpt("size", args.size);
    e.addOpt("error_code", args.errorCode);
    e.addOpt("tid", args.tid);
    e.addOpt("dur", args.dur);
    e.add("module", args.module ?? "unknown");
    e.addOpt("ctx", args.ctx);
    this.write(e);
  }

  decision(args: {
    choice: string;
    alts?: string[];
    reason?: string;
    confidence?: number;
    module?: string;
    ctx?: Record<string, unknown>;
  }): void {
    const e = new Entry(this.compact);
    e.add("level", "DECISION");
    e.add("msg", `Decision: ${args.choice}`);
    e.add("choice", args.choice);
    e.addOpt("alts", args.alts);
    e.addOpt("reason", args.reason);
    e.addOpt("confidence", args.confidence);
    e.add("module", args.module ?? "unknown");
    e.addOpt("ctx", args.ctx);
    this.write(e);
  }

  codeGen(args: {
    lang: string;
    path: string;
    lines?: number;
    funcs?: string[];
    imports?: string[];
    module?: string;
    ctx?: Record<string, unknown>;
  }): void {
    const e = new Entry(this.compact);
    e.add("level", "CODE_GEN");
    e.add("msg", `Generated ${args.lang} code: ${args.path}`);
    e.add("lang", args.lang);
    e.add("path", args.path);
    e.addOpt("lines", args.lines);
    e.addOpt("funcs", args.funcs);
    e.addOpt("imports", args.imports);
    e.add("module", args.module ?? "unknown");
    e.addOpt("ctx", args.ctx);
    this.write(e);
  }

  contextSwitch(args: {
    toTask: string;
    fromTask?: string;
    reason?: string;
    module?: string;
    ctx?: Record<string, unknown>;
  }): void {
    const e = new Entry(this.compact);
    e.add("level", "CONTEXT");
    e.add("msg", `Switching to: ${args.toTask}`);
    e.add("to_task", args.toTask);
    e.addOpt("from_task", args.fromTask);
    e.addOpt("reason", args.reason);
    e.add("module", args.module ?? "unknown");
    e.addOpt("ctx", args.ctx);
    this.write(e);
  }

  // ---- internals ----------------------------------------------------------

  private write(e: Entry): void {
    this.seq += 1;
    e.add("ts", nowIso());
    e.add("pid", this.pid); // stored as STRING
    e.add("rid", this.rid);
    e.add("seq", this.seq); // unquoted number
    try {
      this.appendRaw(e.toString());
    } catch (err) {
      // Never throw from logging (matches Python: print to stderr).
      console.error("[agentic-logger] write failed:", err);
    }
  }

  private appendRaw(line: string): void {
    appendFileSync(this.filePath, line + "\n");
  }

  /** Path of the `.tracebacks` sidecar (contract §5). */
  get tracebackPath(): string {
    return this.filePath.replace(/\.jsonl$/, ".tracebacks");
  }

  /** Persist a traceback to the sidecar; returns the generated tid (tb_+8hex).
   *  Sidecar always uses FULL keys (never compacted). */
  saveTraceback(excType: string, excMsg: string, traceback: string): string {
    const tid = "tb_" + genRid();
    this.saveTracebackText(tid, excType, excMsg, traceback);
    return tid;
  }

  saveTracebackText(tid: string, excType: string, excMsg: string, traceback: string): void {
    // Full-key sidecar record (NOT compacted) — matches Python.
    const rec = [
      `"tid": ${JSON.stringify(tid)}`,
      `"exception_type": ${JSON.stringify(excType)}`,
      `"exception_msg": ${JSON.stringify(excMsg)}`,
      `"traceback": ${JSON.stringify(traceback)}`,
    ].join(", ");
    try {
      appendFileSync(this.tracebackPath, `{${rec}}\n`);
    } catch (err) {
      console.error("[agentic-logger] traceback write failed:", err);
    }
  }
}

/**
 * Ordered list of pre-stringified `"key": value` fragments, joined with ", ".
 * Using JSON.stringify per value guarantees correct escaping + raw UTF-8
 * (ensure_ascii=false); joining manually guarantees the ", " / ": " separators
 * the Python byte-level query path depends on.
 */
class Entry {
  private parts: string[] = [];
  constructor(private readonly compact: boolean = false) {}
  add(key: string, value: unknown): void {
    const k = this.compact ? (COMPACT_MAP[key] ?? key) : key;
    this.parts.push(`"${k}": ${JSON.stringify(value)}`);
  }
  /** Add only when value is not undefined/null (None omission, contract §2). */
  addOpt(key: string, value: unknown): void {
    if (value !== undefined && value !== null) this.add(key, value);
  }
  toString(): string {
    return "{" + this.parts.join(", ") + "}";
  }
}

function truncate(s: string, max: number): string {
  // Array.from handles astral plane; slice on code points.
  const arr = Array.from(s);
  return arr.length > max ? arr.slice(0, max).join("") : s;
}
