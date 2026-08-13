//! JSON formatter producing Python-compatible separators (`", "` / `": "`).
//!
//! serde_json's default compact formatter emits `{"a":1,"b":2}` (no spaces).
//! The AgenticLogger Python `stats` byte-counter searches for `'"level": "'`
//! (with the space), so a compact Rust file would make every entry bucket as
//! `unknown` — a correctness bug, not just a slowdown. Overriding just two
//! formatter methods makes the bytes identical to Python `json.dumps`.
//!
//! String escaping / unicode handling stay at serde_json defaults, which
//! already match Python `ensure_ascii=False` (raw UTF-8, no `\uXXXX`).

use serde_json::ser::Formatter;
use std::io;

/// Zero-state formatter; cheap to construct.
pub struct PythonFormatter;

impl Formatter for PythonFormatter {
    #[inline]
    fn begin_object_key<W>(&mut self, writer: &mut W, first: bool) -> io::Result<()>
    where
        W: ?Sized + io::Write,
    {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }

    #[inline]
    fn begin_object_value<W>(&mut self, writer: &mut W) -> io::Result<()>
    where
        W: ?Sized + io::Write,
    {
        writer.write_all(b": ")
    }

    // Array separators: keep default `","`? Python json.dumps joins array
    // elements with ", " too (e.g. ["a", "b"]). Override for full parity.
    #[inline]
    fn begin_array_value<W>(&mut self, writer: &mut W, first: bool) -> io::Result<()>
    where
        W: ?Sized + io::Write,
    {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;
    use serde_json::ser::Serializer;
    use serde_json::Value;

    fn serialize(v: &Value) -> String {
        let mut buf = Vec::new();
        let mut ser = Serializer::with_formatter(&mut buf, PythonFormatter);
        v.serialize(&mut ser).unwrap();
        String::from_utf8(buf).unwrap()
    }

    #[test]
    fn matches_python_separators() {
        // Map keys are BTreeMap-sorted alphabetically (serde_json default);
        // key ORDER is irrelevant to readers — only separators/escaping matter.
        let v: Value = serde_json::json!({"level": "INFO", "exit": 0, "alts": ["a", "b"]});
        let s = serialize(&v);
        assert!(s.contains("\"level\": \"INFO\""), "colon must be ': ': {s}");
        assert!(s.contains("\"exit\": 0,"), "comma must be ', ': {s}");
        assert!(s.contains("[\"a\", \"b\"]"), "array sep must be ', ': {s}");
    }

    #[test]
    fn no_unicode_escaping() {
        let v: Value = serde_json::json!({"msg": "中文 ✓"});
        let s = serialize(&v);
        assert!(s.contains("中文"));
        assert!(!s.contains("\\u"));
    }
}
