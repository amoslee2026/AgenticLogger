use agentic_logger::{AgentLogger, ErrorCode};
use serde_json::json;
fn main() {
    let dir = std::env::args().nth(1).unwrap_or_else(|| "/tmp/xlang_rust".into());
    let lg = AgentLogger::new("rust_probe", Some("demo"), &dir, Some("cafebabe")).unwrap();
    lg.info_full("Processing started", Some("parser"), Some(12), None, None, Some(json!({"file":"data.json","size":1024}))).ok();
    lg.tool_call("bash", "npm install", 0, 1234, None, None, Some("added 50 pkgs"), None, None).ok();
    lg.error("Build failed", Some("build"), ErrorCode::ExecNonZero, Some("tb_abcd1234")).ok();
    lg.file_op("write", "/p/f.rs", true, Some(2048), None, None, Some(5), None).ok();
    lg.decision("use_redis", Some(&["redis","memcached"]), Some("perf"), Some(0.85), Some("arch"), None).ok();
    lg.code_gen("rust", "src/main.rs", Some(50), Some(&["main","helper"]), None, None, None).ok();
    lg.context_switch("test", Some("build"), Some("done"), None, None).ok();
    println!("{}", lg.file_path().display());
}
