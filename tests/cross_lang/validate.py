#!/usr/bin/env python3
"""Cross-language interchange validator.

Asserts that a JSONL file written by ANY AgenticLogger SDK conforms to the
canonical contract (sdks/INTERCHANGE.md §7) and is therefore readable by the
Python query layer. Exits non-zero on any violation.

Usage:
    python3 validate.py <file.jsonl> [--expect-entries N] [--expect-rid RID]
"""
import argparse
import json
import re
import sys

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}([+-]\d{2}:\d{2}|Z)$")
NUMERIC = {"seq", "dur", "exit", "size", "lines", "confidence"}
# Compact-key reverse map (contract §4). Auto-expand so compact files validate too.
EXPAND_MAP = {
    "t": "ts", "l": "level", "n": "module", "m": "msg", "p": "pid", "r": "rid", "q": "seq",
    "e": "error_code", "d": "dur", "o": "tool", "c": "cmd", "x": "exit", "w": "op", "h": "path",
    "z": "ctx", "i": "tid", "s": "lines", "f": "funcs", "g": "lang", "k": "choice", "a": "alts",
    "u": "reason", "v": "stdout", "b": "stderr", "y": "ok", "j": "size",
}


def _maybe_expand(d: dict) -> dict:
    """Expand single-char keys → full names when the entry looks compact."""
    short = [k for k in d if len(k) == 1 and k in EXPAND_MAP]
    if len(short) > len(d) * 0.4:
        return {EXPAND_MAP.get(k, k): v for k, v in d.items()}
    return d


def validate(path: str, expect_entries: int | None = None, expect_rid: str | None = None) -> list[str]:
    errors: list[str] = []
    raw = open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return ["empty file"]

    rids: set[str] = set()
    data_count = 0
    for i, line in enumerate(lines):
        prefix = f"line {i+1}: "
        # 1. parseable JSON
        try:
            d = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"{prefix}not JSON: {e}")
            continue
        if not isinstance(d, dict):
            errors.append(f"{prefix}not an object")
            continue
        d = _maybe_expand(d)  # expand compact keys so the same checks apply

        if d.get("level") == "__GLOBAL_CTX__":
            if i != 0:
                errors.append(f"{prefix}__GLOBAL_CTX__ header must be the first line")
            continue
        data_count += 1

        # 2. required auto fields
        for k in ("ts", "level", "msg", "module", "pid", "rid", "seq"):
            if k not in d:
                errors.append(f"{prefix}missing required field {k!r}")

        # 3. field types (contract §3.1 — pid is STRING, seq is NUMBER)
        if "pid" in d and not isinstance(d["pid"], str):
            errors.append(f"{prefix}pid must be a string, got {type(d['pid']).__name__}")
        if "seq" in d and not isinstance(d["seq"], int):
            errors.append(f"{prefix}seq must be an integer, got {type(d['seq']).__name__}")
        for k in NUMERIC:
            if k in d and not isinstance(d[k], (int, float)):
                errors.append(f"{prefix}{k} must be a number, got {type(d[k]).__name__}")
        if "ok" in d and not isinstance(d["ok"], bool):
            errors.append(f"{prefix}ok must be a boolean, got {type(d['ok']).__name__}")

        # 4. ts format (ISO 8601 ms + offset)
        ts = d.get("ts")
        if isinstance(ts, str) and not ISO_RE.match(ts):
            errors.append(f"{prefix}ts not ISO 8601 ms+offset: {ts!r}")

        # 5. no \uXXXX escaping (ensure_ascii=false)
        if "\\u" in line:
            errors.append(f"{prefix}contains \\uXXXX escape (must be raw UTF-8)")

        # 6. separators: must contain ": " (python json.dumps default)
        if '": ' not in line:
            errors.append(f"{prefix}missing ': ' separator (python incompat)")

        rids.add(str(d.get("rid")))

    # 7. rid consistency
    rids.discard("None")
    if len(rids) > 1:
        errors.append(f"inconsistent rids across entries: {rids}")
    if expect_rid and rids and expect_rid not in rids:
        errors.append(f"expected rid {expect_rid!r}, got {rids}")

    if expect_entries is not None and data_count != expect_entries:
        errors.append(f"expected {expect_entries} data entries, got {data_count}")

    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--expect-entries", type=int)
    ap.add_argument("--expect-rid")
    args = ap.parse_args()
    errs = validate(args.file, args.expect_entries, args.expect_rid)
    if errs:
        print(f"FAIL ({len(errs)} issue(s)) {args.file}:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK  {args.file}  ({len([l for l in open(args.file) if l.strip()])} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
