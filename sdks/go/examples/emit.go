package main

import (
	"os"
	"github.com/agenticlogger/agentic-logger-go"
)

func main() {
	dir := "/tmp/xlang_go"
	if len(os.Args) > 1 {
		dir = os.Args[1]
	}
	os.MkdirAll(dir, 0o755)
	lg, _ := agenticlogger.New("go_probe", "demo", dir, "cafebabe")
	defer lg.Close()
	ctx := map[string]interface{}{"file": "data.json", "size": 1024}
	lg.InfoFull("Processing started", "parser", 12, "", "", ctx)
	lg.ToolCall("bash", "npm install", 0, 1234, "", "", "added 50 pkgs", "", nil)
	lg.Error("Build failed", "build", agenticlogger.ErrExecNonZero, "tb_abcd1234")
	lg.FileOp("write", "/p/f.go", true, 2048, "", "", 5, nil)
	lg.Decision("use_redis", []string{"redis", "memcached"}, "perf", 0.85, "arch", nil)
	lg.CodeGen("go", "main.go", 50, []string{"main", "helper"}, nil, "", nil)
	lg.ContextSwitch("test", "build", "done", "", nil)
	println(lg.FilePath())
}
