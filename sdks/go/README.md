# agentic-logger-go

Go SDK for AgenticLogger. Each field value is marshaled with
`json.Encoder` (`SetEscapeHTML(false)`) and joined manually so the on-disk
separators match Python exactly.

## Install

```bash
go get github.com/agenticlogger/agentic-logger-go
```

```go
import agenticlogger "github.com/agenticlogger/agentic-logger-go"
```

## Usage

```go
lg, _ := agenticlogger.New("my_agent", "build", "./logs", "")
lg.Info("Processing started", "parser")
lg.InfoFull("with ctx", "net", 0, "", "", map[string]interface{}{"endpoint": "/x"})
lg.ToolCall("bash", "npm install", 0, 1234, "", "", "added 50 pkgs", "", nil)
lg.Error("Build failed", "build", agenticlogger.ErrExecNonZero, "tb_abcd1234")
lg.FileOp("write", "/p/f.go", true, 2048, "", "", 5, nil)
alts := []string{"redis", "memcached"}
lg.Decision("use_redis", alts, "perf", 0.85, "arch", nil)
defer lg.Close()
```

## Notes

- `pid` is a string; `dur`/`exit`/`size`/`seq` are unquoted numbers.
- Go's default `json.Marshal` would HTML-escape `<>&` and use compact separators
  — both break the Python byte-level query path, so this SDK marshals per-field.
- Optional fields (`dur==0`, empty strings) are omitted (None omission).
- Tests: `go test ./...`. Sample: `go run ./examples/emit.go <dir>`.
