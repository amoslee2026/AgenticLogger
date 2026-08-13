package agenticlogger

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeFileAndParse(t *testing.T) (string, []map[string]interface{}) {
	t.Helper()
	dir := t.TempDir()
	lg, err := New("go_probe", "demo", dir, "deadbeef")
	if err != nil {
		t.Fatal(err)
	}

	ctx := map[string]interface{}{"file": "data.json", "size": 1024}
	if err := lg.InfoFull("Processing started", "parser", 12, "", "", ctx); err != nil {
		t.Fatal(err)
	}
	if err := lg.ToolCall("bash", "npm install", 0, 1234, "", "", "added 50 pkgs", "", nil); err != nil {
		t.Fatal(err)
	}
	if err := lg.Error("Build failed", "build", ErrExecNonZero, "tb_abcd1234"); err != nil {
		t.Fatal(err)
	}
	if err := lg.FileOp("write", "/p/f.go", true, 2048, "", "", 5, nil); err != nil {
		t.Fatal(err)
	}
	if err := lg.Decision("use_redis", []string{"redis", "memcached"}, "perf", 0.85, "arch", nil); err != nil {
		t.Fatal(err)
	}
	if err := lg.CodeGen("go", "main.go", 50, []string{"main", "helper"}, nil, "", nil); err != nil {
		t.Fatal(err)
	}
	if err := lg.ContextSwitch("test", "build", "done", "", nil); err != nil {
		t.Fatal(err)
	}
	lg.Close()

	entries := mustReadJSONL(t, lg.filePath)
	return lg.filePath, entries
}

func mustReadJSONL(t *testing.T, path string) []map[string]interface{} {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
	var out []map[string]interface{}
	for i, ln := range lines {
		var m map[string]interface{}
		if err := json.Unmarshal([]byte(ln), &m); err != nil {
			t.Fatalf("line %d not JSON: %v\n%s", i, err, ln)
		}
		out = append(out, m)
	}
	return out
}

func TestByteCompatibleFormat(t *testing.T) {
	_, entries := writeFileAndParse(t)
	// header + 7 entries
	if len(entries) != 8 {
		t.Fatalf("want 8 lines, got %d", len(entries))
	}
	hdr := entries[0]
	if hdr["level"] != "__GLOBAL_CTX__" {
		t.Fatalf("first line must be global ctx header, got %v", hdr["level"])
	}
	// pid is a STRING in JSON (not number)
	for i, e := range entries {
		switch v := e["pid"].(type) {
		case string:
		default:
			t.Fatalf("line %d pid must be string, got %T (%v)", i, v, v)
		}
		switch v := e["seq"].(type) {
		case float64: // json numbers decode to float64
		default:
			t.Fatalf("line %d seq must be number, got %T (%v)", i, v, v)
		}
		if e["rid"] != "deadbeef" {
			t.Fatalf("line %d rid mismatch: %v", i, e["rid"])
		}
	}
}

func TestSeparatorsMatchPython(t *testing.T) {
	dir := t.TempDir()
	lg, _ := New("sep", "demo", dir, "caf00000")
	lg.Info("hi 中文 <b>", "m")
	lg.Close()
	data, _ := os.ReadFile(lg.filePath)
	s := string(data)
	// critical: Python stats byte-counts '"level": "' (with the space)
	if !strings.Contains(s, `"level": "INFO"`) {
		t.Fatalf("missing python-style separator in:\n%s", s)
	}
	// no HTML escaping of '<'
	if strings.Contains(s, `\u003c`) {
		t.Fatalf("must not HTML-escape; got \u003c in:\n%s", s)
	}
	// no unicode escaping (ensure_ascii=false equivalent)
	if !strings.Contains(s, "中文") || strings.Contains(s, `\u4e2d`) {
		t.Fatalf("unicode must be raw UTF-8; got:\n%s", s)
	}
}

func TestCompactMode(t *testing.T) {
	dir := t.TempDir()
	lg, err := NewCompact("cp", "d", dir, "cafe0000", true)
	if err != nil {
		t.Fatal(err)
	}
	lg.InfoFull("hi", "parser", 12, "", "", map[string]interface{}{"f": "d.json"})
	lg.Close()
	raw, _ := os.ReadFile(lg.filePath)
	s := string(raw)
	if !strings.Contains(s, `"l": "INFO"`) { t.Fatalf("level→l: %s", s) }
	if !strings.Contains(s, `"n": "parser"`) { t.Fatalf("module→n") }
	if !strings.Contains(s, `"d": 12`) { t.Fatalf("dur→d") }
	if !strings.Contains(s, `"q": 1`) { t.Fatalf("seq→q") }
	if !strings.Contains(s, `"z"`) { t.Fatalf("ctx→z") }
}

func TestTracebackSidecar(t *testing.T) {
	dir := t.TempDir()
	lg, _ := New("tb", "d", dir, "")
	tid, err := lg.SaveTraceback("ValueError", "bad", "Traceback:\n  boom")
	if err != nil { t.Fatal(err) }
	if !strings.HasPrefix(tid, "tb_") { t.Fatalf("tid: %s", tid) }
	lg.Close()
	tbPath := strings.TrimSuffix(lg.filePath, ".jsonl") + ".tracebacks"
	line, _ := os.ReadFile(tbPath)
	s := string(line)
	if !strings.Contains(s, `"exception_type": "ValueError"`) { t.Fatalf("sidecar: %s", s) }
	if !strings.Contains(s, `"tid": "`) { t.Fatalf("tid key: %s", s) }
}

func TestSanitizeFilename(t *testing.T) {
	dir := t.TempDir()
	lg, _ := New("weird/prog name!", "a b", dir, "")
	name := filepath.Base(lg.filePath)
	if !strings.HasPrefix(name, "weird_prog_name_") {
		t.Fatalf("unexpected filename: %s", name)
	}
	lg.Close()
}
