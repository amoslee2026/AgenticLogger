# agentic-logger (TypeScript / JavaScript)

One npm package, written in TypeScript, emitting ESM + `.d.ts`. Serves both TS
and JS users. JSON is built per-field (`": "` / `", "` separators, raw UTF-8)
to match the Python byte-level query path.

## Install

```bash
npm install agentic-logger     # or: bun add agentic-logger
```

## Usage (TypeScript / ESM)

```ts
import { AgentLogger, ErrorCode } from "agentic-logger";

const lg = new AgentLogger({ program: "my_agent", command: "build", logDir: "./logs" });
lg.info("Processing started", { module: "parser", dur: 12, ctx: { file: "data.json" } });
lg.toolCall({ tool: "bash", cmd: "npm install", exit: 0, dur: 1234, stdout: "added 50 pkgs" });
lg.error("Build failed", { module: "build", errorCode: ErrorCode.EXEC_NON_ZERO, tid: "tb_abcd1234" });
lg.fileOp({ op: "write", path: "/p/f.ts", ok: true, size: 2048, dur: 5 });
lg.decision({ choice: "use_redis", alts: ["redis", "memcached"], reason: "perf", confidence: 0.85, module: "arch" });
```

The same API works from plain JavaScript (`.js`) — just drop the type annotations.

## Notes

- Node ≥ 18 (uses `node:crypto`, `node:fs`).
- `pid` stored as a string; numeric fields unquoted; `null`/`undefined` omitted.
- Build: `npm run build` (tsc → `dist/`). Type-check: `npm run typecheck`.
- Tests: `bun test`. Sample emitter: `bun examples/emit.ts <dir>`.
