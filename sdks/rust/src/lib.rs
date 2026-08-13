//! # agentic-logger (Rust)
//!
//! Structured logging SDK for Coding Agents. Emits **byte-compatible** JSONL
//! that the AgenticLogger Python query layer (`cli` / `mcp_server`) reads
//! without any conversion.
//!
//! @contract: sdks/INTERCHANGE.md
//!
//! ```
//! use agentic_logger::{AgentLogger, ErrorCode};
//! use serde_json::json;
//!
//! let logger = AgentLogger::new("my_agent", Some("build"), "./logs", None).unwrap();
//! logger.info("Processing started", Some("parser")).ok();
//! logger.tool_call("bash", "npm install", 0, 1234, None, None, None, None, None).ok();
//! logger.error("Build failed", Some("build"), ErrorCode::ExecNonZero, None).ok();
//! logger.info_full("with ctx", Some("net"), None, None, None, Some(json!({"endpoint": "/x"}))).ok();
//! ```

mod error_codes;
mod fmt;
mod time;

pub use error_codes::ErrorCode;

use serde::Serialize;
use serde_json::{Map, Value};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use uuid::Uuid;

// Compact-key map (contract §4). Top-level entry keys only.
const COMPACT_MAP: &[(&str, &str)] = &[
    ("ts","t"),("level","l"),("module","n"),("msg","m"),("pid","p"),("rid","r"),("seq","q"),
    ("error_code","e"),("dur","d"),("tool","o"),("cmd","c"),("exit","x"),("op","w"),("path","h"),
    ("ctx","z"),("tid","i"),("lines","s"),("funcs","f"),("lang","g"),("choice","k"),("alts","a"),
    ("reason","u"),("stdout","v"),("stderr","b"),("ok","y"),("size","j"),
];

fn compact_entry(entry: Map<String, Value>) -> Map<String, Value> {
    entry.into_iter().map(|(k, v)| {
        let k = COMPACT_MAP.iter().find(|(full, _)| *full == k).map(|(_, c)| (*c).to_string()).unwrap_or(k);
        (k, v)
    }).collect()
}

/// The structured logger. One instance == one run == one JSONL file.
///
/// Thread-safe: the underlying file handle is guarded by a `Mutex` and the
/// sequence counter is atomic.
pub struct AgentLogger {
    program: String,
    command: String,
    file_path: PathBuf,
    rid: String,
    pid: String,
    seq: AtomicU64,
    file: Mutex<File>,
    compact: bool,
}

impl AgentLogger {
    /// Create a new logger (and its log file).
    ///
    /// * `program`   – program name (filename component, sanitised).
    /// * `command`   – sub-command; `None` → `pid{PID}`.
    /// * `log_dir`   – directory for log files (`./logs` is typical).
    /// * `rid`       – run id override; `None` → random 8 hex chars.
    pub fn new(
        program: &str,
        command: Option<&str>,
        log_dir: impl AsRef<Path>,
        rid: Option<&str>,
    ) -> std::io::Result<Self> {
        Self::new_compact(program, command, log_dir, rid, false)
    }

    /// Like [`new`], but enables compact-key mode (contract §4).
    pub fn new_compact(
        program: &str,
        command: Option<&str>,
        log_dir: impl AsRef<Path>,
        rid: Option<&str>,
        compact: bool,
    ) -> std::io::Result<Self> {
        let pid = std::process::id().to_string();
        let rid = rid.map(|s| s.to_string()).unwrap_or_else(|| {
            Uuid::new_v4().simple().to_string()[..8].to_string()
        });

        let safe_program = sanitize(program);
        let command_str = command.map(|c| c.to_string()).unwrap_or_else(|| format!("pid{}", pid));
        let safe_command = sanitize(&command_str);

        let log_dir = log_dir.as_ref().to_path_buf();
        std::fs::create_dir_all(&log_dir)?;

        let stamp = time::filename_stamp();
        let filename = format!("{}_{}_{}.jsonl", safe_program, safe_command, stamp);
        let file_path = log_dir.join(&filename);

        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&file_path)?;

        // Global-context header (contract §1.2).
        let mut header = Map::new();
        header.insert("ts".into(), Value::String(time::now_iso()));
        header.insert("level".into(), Value::String("__GLOBAL_CTX__".into()));
        header.insert("msg".into(), Value::String("Global context".into()));
        header.insert("module".into(), Value::String("__system__".into()));
        header.insert("rid".into(), Value::String(rid.clone()));
        header.insert("pid".into(), Value::String(pid.clone()));
        header.insert("seq".into(), Value::Number(0u64.into()));
        header.insert("program".into(), Value::String(safe_program.clone()));
        header.insert("command".into(), Value::String(safe_command.clone()));
        let header = if compact { compact_entry(header) } else { header };
        write_value(&mut file, &Value::Object(header))?;
        file.write_all(b"\n")?;

        Ok(Self {
            program: safe_program,
            command: safe_command,
            file_path,
            rid,
            pid,
            seq: AtomicU64::new(0),
            file: Mutex::new(file),
            compact,
        })
    }

    /// Absolute path of the active log file.
    pub fn file_path(&self) -> &Path {
        &self.file_path
    }
    pub fn rid(&self) -> &str {
        &self.rid
    }
    pub fn program(&self) -> &str {
        &self.program
    }
    pub fn command(&self) -> &str {
        &self.command
    }

    // ---- core write -------------------------------------------------------

    fn write_entry(&self, mut entry: Map<String, Value>) -> std::io::Result<()> {
        let seq = self.seq.fetch_add(1, Ordering::SeqCst) + 1;
        entry.insert("ts".into(), Value::String(time::now_iso()));
        entry.insert("pid".into(), Value::String(self.pid.clone()));
        entry.insert("rid".into(), Value::String(self.rid.clone()));
        entry.insert("seq".into(), Value::Number(seq.into()));
        if self.compact {
            entry = compact_entry(entry);
        }
        let mut f = self.file.lock().expect("poisoned lock");
        write_value(&mut *f, &Value::Object(entry))?;
        f.write_all(b"\n")?;
        Ok(())
    }

    // ---- traceback sidecar (contract §5; sidecar always uses FULL keys) ---

    /// Persist a traceback to the `.tracebacks` sidecar; returns the generated tid.
    pub fn save_traceback(&self, exc_type: &str, exc_msg: &str, traceback: &str) -> std::io::Result<String> {
        let tid = format!("tb_{}", &Uuid::new_v4().simple().to_string()[..8]);
        self.save_traceback_text(&tid, exc_type, exc_msg, traceback)?;
        Ok(tid)
    }

    pub fn save_traceback_text(&self, tid: &str, exc_type: &str, exc_msg: &str, traceback: &str) -> std::io::Result<()> {
        let tb_path = self.file_path.with_extension("tracebacks");
        let mut rec = Map::new();
        rec.insert("tid".into(), Value::String(tid.into()));
        rec.insert("exception_type".into(), Value::String(exc_type.into()));
        rec.insert("exception_msg".into(), Value::String(exc_msg.into()));
        rec.insert("traceback".into(), Value::String(traceback.into()));
        let mut f = OpenOptions::new().create(true).append(true).open(tb_path)?;
        write_value(&mut f, &Value::Object(rec))?;
        f.write_all(b"\n")?;
        Ok(())
    }

    // ---- basic levels -----------------------------------------------------

    /// `logger.info(msg, module, dur?, error_code?, tid?, ctx?)`
    pub fn info(&self, msg: &str, module: Option<&str>) -> std::io::Result<()> {
        self.info_full(msg, module, None, None, None, None)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn info_full(
        &self,
        msg: &str,
        module: Option<&str>,
        dur: Option<u64>,
        error_code: Option<&str>,
        tid: Option<&str>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("INFO".into()));
        e.insert("msg".into(), Value::String(truncate_msg(msg)));
        basic_fields(&mut e, module, dur, error_code, tid, ctx);
        self.write_entry(e)
    }

    pub fn warn(&self, msg: &str, module: Option<&str>) -> std::io::Result<()> {
        self.warn_full(msg, module, None, None, None, None)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn warn_full(
        &self,
        msg: &str,
        module: Option<&str>,
        dur: Option<u64>,
        error_code: Option<&str>,
        tid: Option<&str>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("WARN".into()));
        e.insert("msg".into(), Value::String(truncate_msg(msg)));
        basic_fields(&mut e, module, dur, error_code, tid, ctx);
        self.write_entry(e)
    }

    pub fn error(
        &self,
        msg: &str,
        module: Option<&str>,
        error_code: ErrorCode,
        tid: Option<&str>,
    ) -> std::io::Result<()> {
        self.error_full(msg, module, error_code.as_str(), tid, None, None)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn error_full(
        &self,
        msg: &str,
        module: Option<&str>,
        error_code: &str,
        tid: Option<&str>,
        dur: Option<u64>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("ERROR".into()));
        e.insert("msg".into(), Value::String(truncate_msg(msg)));
        if let Some(m) = module {
            e.insert("module".into(), Value::String(m.into()));
        }
        e.insert("error_code".into(), Value::String(error_code.into()));
        if let Some(t) = tid {
            e.insert("tid".into(), Value::String(t.into()));
        }
        if let Some(d) = dur {
            e.insert("dur".into(), Value::Number(d.into()));
        }
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        self.write_entry(e)
    }

    // ---- specialised ------------------------------------------------------

    /// `tool_call(tool, cmd, exit, dur, error_code?, tid?, stdout?, stderr?, ctx?)`.
    /// Like Python, requires `error_code` semantics for failures are the caller's
    /// responsibility (this SDK accepts it optionally).
    #[allow(clippy::too_many_arguments)]
    pub fn tool_call(
        &self,
        tool: &str,
        cmd: &str,
        exit: i64,
        dur: u64,
        error_code: Option<&str>,
        tid: Option<&str>,
        stdout: Option<&str>,
        stderr: Option<&str>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        let ok = exit == 0;
        e.insert(
            "level".into(),
            Value::String("TOOL".into()),
        );
        e.insert(
            "msg".into(),
            Value::String(format!("Tool {} {}", tool, if ok { "succeeded" } else { "failed" })),
        );
        e.insert("tool".into(), Value::String(tool.into()));
        e.insert("cmd".into(), Value::String(cmd.into()));
        e.insert("exit".into(), Value::Number(exit.into()));
        e.insert("dur".into(), Value::Number(dur.into()));
        if let Some(ec) = error_code {
            e.insert("error_code".into(), Value::String(ec.into()));
        }
        if let Some(t) = tid {
            e.insert("tid".into(), Value::String(t.into()));
        }
        if let Some(o) = stdout {
            e.insert("stdout".into(), Value::String(truncate64k(o)));
        }
        if let Some(s) = stderr {
            e.insert("stderr".into(), Value::String(truncate64k(s)));
        }
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        e.insert(
            "module".into(),
            Value::String("unknown".into()),
        );
        self.write_entry(e)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn file_op(
        &self,
        op: &str,
        path: &str,
        ok: bool,
        size: Option<u64>,
        error_code: Option<&str>,
        tid: Option<&str>,
        dur: Option<u64>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("FILE_OP".into()));
        e.insert(
            "msg".into(),
            Value::String(format!("File {} {}: {}", op, if ok { "succeeded" } else { "failed" }, path)),
        );
        e.insert("op".into(), Value::String(op.into()));
        e.insert("path".into(), Value::String(path.into()));
        e.insert("ok".into(), Value::Bool(ok));
        if let Some(s) = size {
            e.insert("size".into(), Value::Number(s.into()));
        }
        if let Some(ec) = error_code {
            e.insert("error_code".into(), Value::String(ec.into()));
        }
        if let Some(t) = tid {
            e.insert("tid".into(), Value::String(t.into()));
        }
        if let Some(d) = dur {
            e.insert("dur".into(), Value::Number(d.into()));
        }
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        e.insert("module".into(), Value::String("unknown".into()));
        self.write_entry(e)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn decision(
        &self,
        choice: &str,
        alts: Option<&[&str]>,
        reason: Option<&str>,
        confidence: Option<f64>,
        module: Option<&str>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("DECISION".into()));
        e.insert("msg".into(), Value::String(format!("Decision: {}", choice)));
        e.insert("choice".into(), Value::String(choice.into()));
        if let Some(a) = alts {
            e.insert(
                "alts".into(),
                Value::Array(a.iter().map(|s| Value::String((*s).into())).collect()),
            );
        }
        if let Some(r) = reason {
            e.insert("reason".into(), Value::String(r.into()));
        }
        if let Some(c) = confidence {
            e.insert("confidence".into(), serde_json::Number::from_f64(c).map(Value::Number).unwrap_or(Value::Null));
        }
        if let Some(m) = module {
            e.insert("module".into(), Value::String(m.into()));
        } else {
            e.insert("module".into(), Value::String("unknown".into()));
        }
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        self.write_entry(e)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn code_gen(
        &self,
        lang: &str,
        path: &str,
        lines: Option<u64>,
        funcs: Option<&[&str]>,
        imports: Option<&[&str]>,
        module: Option<&str>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("CODE_GEN".into()));
        e.insert("msg".into(), Value::String(format!("Generated {} code: {}", lang, path)));
        e.insert("lang".into(), Value::String(lang.into()));
        e.insert("path".into(), Value::String(path.into()));
        if let Some(l) = lines {
            e.insert("lines".into(), Value::Number(l.into()));
        }
        if let Some(f) = funcs {
            e.insert(
                "funcs".into(),
                Value::Array(f.iter().map(|s| Value::String((*s).into())).collect()),
            );
        }
        if let Some(im) = imports {
            e.insert(
                "imports".into(),
                Value::Array(im.iter().map(|s| Value::String((*s).into())).collect()),
            );
        }
        e.insert("module".into(), Value::String(module.unwrap_or("unknown").into()));
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        self.write_entry(e)
    }

    pub fn context_switch(
        &self,
        to_task: &str,
        from_task: Option<&str>,
        reason: Option<&str>,
        module: Option<&str>,
        ctx: Option<Value>,
    ) -> std::io::Result<()> {
        let mut e = Map::new();
        e.insert("level".into(), Value::String("CONTEXT".into()));
        e.insert("msg".into(), Value::String(format!("Switching to: {}", to_task)));
        e.insert("to_task".into(), Value::String(to_task.into()));
        if let Some(f) = from_task {
            e.insert("from_task".into(), Value::String(f.into()));
        }
        if let Some(r) = reason {
            e.insert("reason".into(), Value::String(r.into()));
        }
        e.insert("module".into(), Value::String(module.unwrap_or("unknown").into()));
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        self.write_entry(e)
    }
}

// ---- helpers --------------------------------------------------------------

fn write_value(w: &mut impl Write, v: &Value) -> std::io::Result<()> {
    use serde_json::ser::Serializer;
    let mut ser = Serializer::with_formatter(w, fmt::PythonFormatter);
    v.serialize(&mut ser)
        .map_err(std::io::Error::other)?;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn basic_fields(
    e: &mut Map<String, Value>,
    module: Option<&str>,
    dur: Option<u64>,
    error_code: Option<&str>,
    tid: Option<&str>,
    ctx: Option<Value>,
) {
    e.insert("module".into(), Value::String(module.unwrap_or("unknown").into()));
    if let Some(d) = dur {
        e.insert("dur".into(), Value::Number(d.into()));
    }
    if let Some(ec) = error_code {
        e.insert("error_code".into(), Value::String(ec.into()));
    }
    if let Some(t) = tid {
        e.insert("tid".into(), Value::String(t.into()));
    }
    if let Some(c) = ctx {
        e.insert("ctx".into(), c);
    }
}

fn truncate_msg(s: &str) -> String {
    if s.chars().count() <= 4096 {
        s.to_string()
    } else {
        s.chars().take(4096).collect()
    }
}
fn truncate64k(s: &str) -> String {
    if s.len() <= 65536 {
        s.to_string()
    } else {
        s[..65536].to_string()
    }
}

/// Sanitise a filename component: keep `[A-Za-z0-9_-]`, else `_`, cap 50 chars.
fn sanitize(s: &str) -> String {
    s.chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c } else { '_' })
        .take(50)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir() -> PathBuf {
        let d = std::env::temp_dir().join(format!("agentic_rust_test_{}", Uuid::new_v4().simple()));
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn writes_byte_compatible_jsonl() {
        let d = tmpdir();
        let lg = AgentLogger::new("rust_probe", Some("demo"), &d, Some("cafebabe")).unwrap();
        lg.info_full(
            "Processing started",
            Some("parser"),
            Some(12),
            None,
            None,
            Some(serde_json::json!({"file": "data.json", "size": 1024})),
        )
        .unwrap();
        lg.tool_call("bash", "npm install", 0, 1234, None, None, Some("added 50 pkgs"), None, None)
            .unwrap();
        lg.error("Build failed", Some("build"), ErrorCode::ExecNonZero, Some("tb_abcd1234"))
            .unwrap();
        lg.file_op("write", "/p/f.rs", true, Some(2048), None, None, Some(5), None).unwrap();
        lg.decision("use_redis", Some(&["redis", "memcached"]), Some("perf"), Some(0.85), Some("arch"), None)
            .unwrap();
        lg.code_gen("rust", "src/main.rs", Some(50), Some(&["main", "helper"]), None, None, None)
            .unwrap();
        lg.context_switch("test", Some("build"), Some("done"), None, None).unwrap();
        drop(lg);

        let content = std::fs::read_to_string(lg_file(&d)).unwrap();
        let lines: Vec<&str> = content.trim_end().split('\n').collect();
        assert_eq!(lines.len(), 8); // 1 header + 7 entries

        for (i, line) in lines.iter().enumerate() {
            let v: Value = serde_json::from_str(line).unwrap_or_else(|e| panic!("line {i} not JSON: {e}\n{line}"));
            let obj = v.as_object().unwrap();
            assert!(obj.get("ts").unwrap().is_string(), "ts must be string");
            assert!(obj.get("pid").unwrap().is_string(), "pid must be string");
            assert!(obj.get("seq").unwrap().is_i64(), "seq must be number");
            assert_eq!(obj.get("rid").unwrap(), &Value::String("cafebabe".into()));
        }

        // Header line.
        let hdr: Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(hdr["level"], "__GLOBAL_CTX__");
        assert_eq!(hdr["seq"], 0);

        // Byte-level contract: separators contain ": " and ", ".
        assert!(content.contains("\"level\": \"INFO\""), "missing python-style separator");
        assert!(content.contains("\"exit\": 0"), "exit must be unquoted number");
        assert!(!content.contains("\\u"), "must not emit \\uXXXX escapes (ensure_ascii=false)");
    }

    fn lg_file(d: &Path) -> PathBuf {
        std::fs::read_dir(d)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.path())
            .find(|p| p.extension().and_then(|s| s.to_str()) == Some("jsonl"))
            .unwrap()
    }

    #[test]
    fn compact_mode_matches_python_keys() {
        let d = tmpdir();
        let lg = AgentLogger::new_compact("cp", Some("d"), &d, Some("cafe0000"), true).unwrap();
        lg.info_full("hi", Some("parser"), Some(12), None, None, Some(serde_json::json!({"f":"d.json"}))).unwrap();
        drop(lg);
        let content = std::fs::read_to_string(lg_file(&d)).unwrap();
        assert!(content.contains("\"l\": \"INFO\""), "level→l: {content}");
        assert!(content.contains("\"n\": \"parser\""), "module→n");
        assert!(content.contains("\"d\": 12"), "dur→d");
        assert!(content.contains("\"q\": 1"), "seq→q");
        // nested ctx keys NOT compacted
        assert!(content.contains("\"z\""), "ctx→z");
    }

    #[test]
    fn traceback_sidecar_full_keys() {
        let d = tmpdir();
        let lg = AgentLogger::new("tb", Some("d"), &d, None).unwrap();
        let tid = lg.save_traceback("ValueError", "bad", "Traceback:\n  boom").unwrap();
        assert!(tid.starts_with("tb_"));
        drop(lg);
        let tb = std::fs::read_dir(&d).unwrap()
            .filter_map(|e| e.ok()).map(|e| e.path())
            .find(|p| p.extension().and_then(|s| s.to_str()) == Some("tracebacks")).unwrap();
        let line = std::fs::read_to_string(tb).unwrap();
        assert!(line.contains("\"exception_type\": \"ValueError\""), "{line}");
        assert!(line.contains("\"tid\": "), "{line}");
    }

    #[test]
    fn sanitizes_filename() {
        let d = tmpdir();
        let lg = AgentLogger::new("weird/prog name!", Some("a b"), &d, None).unwrap();
        let name = lg.file_path().file_name().unwrap().to_str().unwrap();
        assert!(name.starts_with("weird_prog_name_"), "got {name}");
    }

    #[test]
    fn msg_truncation() {
        assert_eq!(truncate_msg("hi"), "hi");
        let big: String = "a".repeat(5000);
        assert_eq!(truncate_msg(&big).chars().count(), 4096);
    }
}
