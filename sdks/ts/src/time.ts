/**
 * Time & filename helpers (no external deps).
 * @contract: sdks/INTERCHANGE.md §1.1, §3.1
 */
import { randomBytes } from "node:crypto";

/** ISO 8601 UTC, ms precision, +00:00 offset (matches Python datetime.now(utc)). */
export function nowIso(): string {
  // toISOString() → "2026-08-13T06:00:22.060Z"; swap trailing Z → +00:00.
  return new Date().toISOString().replace(/Z$/, "+00:00");
}

let _nameSeq = 0;
/** `YYYYMMDD_HHMMSSffffff` in LOCAL time (matches Python filename convention). */
export function filenameStamp(): string {
  const d = new Date();
  _nameSeq = (_nameSeq + 1) % 1_000_000;
  const p = (n: number, w = 2): string => String(n).padStart(w, "0");
  const date = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`;
  // ms*1000 + sub-ms counter → 6 digits (microsecond slot).
  const micros = d.getMilliseconds() * 1000 + (_nameSeq % 1000);
  const time = `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}${p(micros, 6)}`;
  return `${date}_${time}`;
}

/** Keep [A-Za-z0-9_-], else '_', truncate 50. */
export function sanitize(s: string): string {
  return s.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 50);
}

/** 8 hex chars (uuid4 hex[:8] equivalent). */
export function genRid(): string {
  return randomBytes(4).toString("hex");
}
