# AgenticLogger Cross-Language Interchange Format

**Status**: Canonical contract — single source of truth for every language SDK.
**Goal**: A log file written by *any* SDK (Python, Rust, Go, TS/JS, Bash, SystemVerilog, Verilog-2001, Tcl) MUST be readable byte-for-byte by the Python query layer (`cli` / `mcp_server` / `JSONLBackend.query|stats|tail`).

If this document and a language SDK disagree, **this document wins** and the SDK is buggy.

---

## 1. File layout

```
logs/
└── {program}_{command}_{YYYYMMDD}_{HHmmssffffff}.jsonl          # one run = one file
    └── {program}_{command}_{YYYYMMDD}_{HHmmssffffff}.tracebacks  # optional sidecar
```

- Encoding: **UTF-8**.
- One JSON object per line, terminated by `\n` (LF). The final line MUST also end with `\n`.
- The file is **append-only** during a run; readers may `tail -f`.

### 1.1 Filename rule (MUST match exactly)

```
{program}_{command}_{YYYYMMDD}_{HHmmssffffff}.jsonl
```

- `program` and `command`: each sanitised by replacing every char **not** in `[A-Za-z0-9_-]` with `_`, then truncated to **50 chars**.
- `command` defaults to `pid{PID}` (e.g. `pid12345`) when the caller does not supply one.
- `YYYYMMDD` = local date, `HHmmssffffff` = local time + **6-digit microseconds** (avoids same-second collisions).
- Extension: `.jsonl` for JSONL backend. (`.sqlite` is Python-only in v1; other SDKs always emit `.jsonl`.)

### 1.2 Global-context header (optional first line)

If the SDK writes global context, the **first line** of the file is:

```json
{"ts": "<iso>", "level": "__GLOBAL_CTX__", "msg": "Global context", "module": "__system__", "rid": "<rid>", "pid": "<pid>", "seq": 0, "program": "<program>", "command": "<command>", ...extra}
```

Readers **skip** any line whose `level == "__GLOBAL_CTX__"` when counting/returning data entries. `seq` of the header is `0`; the first data entry's `seq` is `1`.

---

## 2. JSON serialization rules (byte-level)

These rules exist so the Python fast query path (byte substring narrowing, e.g. `"level": "INFO"`) works on logs from every SDK. They are **mandatory**.

| Rule | Value | Why |
|------|-------|-----|
| Object separator | `", "` (comma + space) | matches Python `json.dumps` default |
| Key/value separator | `": "` (colon + space) | matches Python default; byte-narrow needles are `"key": "val"` |
| Unicode escaping | **OFF** — write raw UTF-8, do NOT emit `\uXXXX` | matches Python `ensure_ascii=False` |
| Key order | irrelevant (JSON objects are unordered) | readers parse, never index by position |
| Numbers | unquoted JSON numbers: `1`, `1234`, `0.85` | `seq`, `dur`, `exit`, `size`, `confidence`, `lines` |
| Booleans | `true` / `false` | `ok` |
| `null`/`None` fields | **OMIT the key entirely** | never write `"dur": null` |

> Example of a conformant line (note the spaces, unquoted numbers, omitted nulls):
> ```
> {"level": "INFO", "msg": "hi", "module": "parser", "dur": 12, "ts": "2026-08-13T05:49:19.717+00:00", "pid": "3896991", "rid": "b1e87627", "seq": 1}
> ```

---

## 3. Field dictionary

### 3.1 Auto fields (every SDK fills these; callers never pass them)

| Field | Type | Required | Format |
|-------|------|----------|--------|
| `ts` | string | ✅ | ISO 8601, **millisecond** precision, **with timezone offset**. Example: `2026-08-13T05:49:19.717+00:00`. UTC recommended. **Must include the offset** — readers compare `ts` as strings for `since`/`until`. |
| `pid` | **string** | ✅ | OS process id as a string, e.g. `"3896991"`. (Stored as a string, NOT a number.) |
| `rid` | string | ✅ | Run id: **8 hex chars** (`uuid4().hex[:8]` equivalent, e.g. `b1e87627`). Fixed for the lifetime of one logger instance. |
| `seq` | **integer** | ✅ | Monotonic, starts at `1` for the first data entry, increments by 1 per entry. |

> `pid` is a STRING and `seq` is a NUMBER — do not swap these. The Python `stats` byte-count treats `seq/dur/exit/size` as unquoted numbers and excludes `pid`.

### 3.2 Common fields

| Field | Type | Notes |
|-------|------|-------|
| `level` | string | One of: `DEBUG`, `INFO`, `WARN`, `ERROR`, `TOOL`, `FILE_OP`, `DECISION`, `CODE_GEN`, `CONTEXT`. |
| `msg` | string | One-line summary. Truncate to **4096 chars**. |
| `module` | string | Dotted module/function path. Other SDKs have no stack-introspection equivalent — require it as a parameter (or default `"unknown"`). |
| `dur` | integer (ms) | Operation duration. Optional. |
| `error_code` | string | UPPER_SNAKE error code. **Omit when None.** See §6. |
| `tid` | string | Traceback reference id (links to sidecar §5). Optional. |
| `ctx` | object | Small key-value context. Optional. Values must be JSON-serializable. |

### 3.3 Level-specific fields (omit keys whose value is None)

| Level | Extra fields |
|-------|-------------|
| `TOOL` | `tool`(str), `cmd`(str), `exit`(int), `stdout`(str), `stderr`(str) |
| `FILE_OP` | `op`(str: `read`\|`write`\|`delete`\|`move`\|`copy`), `path`(str), `ok`(bool), `size`(int) |
| `DECISION` | `choice`(str), `alts`([str]), `reason`(str), `confidence`(float 0–1) |
| `CODE_GEN` | `lang`(str), `path`(str), `lines`(int), `funcs`([str]), `imports`([str]) |
| `CONTEXT` | `to_task`(str), `from_task`(str), `reason`(str) |

> **Error-code enforcement** (matches Python): when a failure is logged (`error()` with no code, `tool_call` with `exit != 0`, `file_op` with `ok == false`), the SDK SHOULD require/emit an `error_code`. Other SDKs SHOULD mimic Python's behaviour: error → default `UNKNOWN`; tool/file failures → raise/return an error if no code given.

---

## 4. Compact-key mode (optional optimization)

To shrink per-entry size ~40%, an SDK MAY rewrite keys to single chars. **Off by default in every SDK.** The mapping (identical to `src/agentic_logger/logger.py:COMPACT_MAP`):

```
ts→t  level→l  module→n  msg→m   pid→p  rid→r  seq→q  error_code→e
dur→d tool→o   cmd→c     exit→x  op→w   path→h ctx→z  tid→i
lines→s funcs→f lang→g   choice→k alts→a reason→u stdout→v stderr→b
ok→y  size→j
```

When compact mode is on, the global-context header is also compacted. Readers auto-detect and expand. **v1 of the non-Python SDKs ship compact=off**; it is documented here so any SDK can opt in later without a format change.

---

## 5. Traceback sidecar

Large stack traces live in a sibling file `<logfile>.tracebacks` (one JSON record per line), referenced from the main log by `tid`.

```json
{"tid": "tb_abcd1234", "exception_type": "ValueError", "exception_msg": "bad input", "traceback": "Traceback (most recent call last):\n  File ..."}
```

- `tid` format: `tb_` + 8 hex chars.
- `traceback` text has its newlines represented as the JSON-escaped `\n` (standard JSON string escaping) so each record stays on exactly one physical line.
- v1 SDKs MAY skip the sidecar; if they write tracebacks at all they MUST use this exact record shape.

---

## 6. Error-code taxonomy (identical everywhere)

Format: `{CATEGORY}_{SPECIFIC}`, UPPER_SNAKE. The canonical list (from `error_codes.py`):

```
PARSE_JSON  PARSE_YAML  PARSE_XML  PARSE_CSV  PARSE_REGEX  PARSE_ENCODING
IO_NOT_FOUND  IO_PERMISSION  IO_DISK_FULL  IO_READ_FAIL  IO_WRITE_FAIL  IO_LOCK_FAIL
EXEC_NON_ZERO  EXEC_TIMEOUT  EXEC_NOT_FOUND  EXEC_KILLED  EXEC_CRASH
NET_TIMEOUT  NET_DNS_FAIL  NET_CONN_REFUSED  NET_SSL_ERROR  NET_HTTP_ERROR
AUTH_LOGIN_FAIL  AUTH_TOKEN_EXPIRED  AUTH_FORBIDDEN  AUTH_UNAUTHORIZED
CONFIG_MISSING  CONFIG_INVALID  CONFIG_RANGE
RES_MEMORY  RES_DISK  RES_CPU  RES_FD
TIMEOUT_API  TIMEOUT_DB  TIMEOUT_LOCK
CONFLICT_VERSION  CONFLICT_LOCK  CONFLICT_DUPLICATE
INTERNAL_UNEXPECTED  INTERNAL_ASSERT  INTERNAL_TYPE  INTERNAL_KEY  INTERNAL_INDEX
UNKNOWN
```

Each SDK exposes these as an `ErrorCode` enum/constants. Custom codes are allowed as long as they keep the `CATEGORY_SPECIFIC` shape.

---

## 7. Conformance checklist (every SDK)

- [ ] Filename matches §1.1.
- [ ] Writes UTF-8 JSONL, one object per line, LF-terminated.
- [ ] Separators `": "` / `", "`, no `\u` escaping (§2).
- [ ] `pid` is a string; `seq`/`dur`/`exit`/`size` are unquoted numbers; `ok` is a boolean.
- [ ] `None`/null fields are omitted, never written as `null`.
- [ ] `ts` is ISO 8601 with timezone offset, millisecond precision.
- [ ] `rid` is 8 hex chars, stable per instance; `seq` starts at 1.
- [ ] Core methods: `info`, `warn`, `error`, `tool_call`, `file_op`, `decision`, `code_gen`, `context_switch`.
- [ ] `ErrorCode` constants cover §6.
- [ ] Optional: global-context header (§1.2), traceback sidecar (§5).
- [ ] Output of the SDK is readable by `uv run python -m agentic_logger.cli query <file>` and yields correct `stats`/`tail`.
