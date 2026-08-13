// Package agenticlogger — main logger.
//
// Why we build JSON by hand instead of json.Marshal(map): Go's encoding/json
// emits compact separators (",", ":") and HTML-escapes "<>&". The AgenticLogger
// Python `stats` byte-counter searches for `'"level": "'` (with the space), so
// compact separators make every entry bucket as "unknown" — a correctness bug.
// We marshal each VALUE with json.Encoder (SetEscapeHTML=false) for correct
// escaping, then join `"key": <value>` parts with ", " — identical bytes to
// Python json.dumps(ensure_ascii=False).
//
// @contract: sdks/INTERCHANGE.md
package agenticlogger

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// AgentLogger is one run → one JSONL file. Safe for concurrent use.
type AgentLogger struct {
	program  string
	command  string
	filePath string
	rid      string
	pid      string
	logDir   string

	mu  sync.Mutex
	seq     uint64
	compact bool
	f       *os.File
}

// New creates a logger and writes the global-context header.
//
//   - program: program name (filename component, sanitised)
//   - command: sub-command; "" → "pid<PID>"
//   - logDir:  directory for log files
//   - rid:     run-id override; "" → random 8 hex chars
func New(program, command, logDir, rid string) (*AgentLogger, error) {
	return NewCompact(program, command, logDir, rid, false)
}

// NewCompact is like New but enables compact-key mode (contract §4).
func NewCompact(program, command, logDir, rid string, compact bool) (*AgentLogger, error) {
	pid := strconv.Itoa(os.Getpid())
	if rid == "" {
		rid = genRid()
	}
	safeProgram := sanitize(program)
	cmd := command
	if cmd == "" {
		cmd = "pid" + pid
	}
	safeCommand := sanitize(cmd)

	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return nil, err
	}
	stamp := filenameStamp()
	fp := filepath.Join(logDir, fmt.Sprintf("%s_%s_%s.jsonl", safeProgram, safeCommand, stamp))

	f, err := os.OpenFile(fp, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, err
	}

	lg := &AgentLogger{
		program:  safeProgram,
		command:  safeCommand,
		filePath: fp,
		rid:      rid,
		pid:      pid,
		logDir:   logDir,
		compact:  compact,
		f:        f,
	}

	// Global-context header (contract §1.2).
	hdr := newEntry(compact)
	hdr.addString("ts", nowISO())
	hdr.addString("level", "__GLOBAL_CTX__")
	hdr.addString("msg", "Global context")
	hdr.addString("module", "__system__")
	hdr.addString("rid", rid)
	hdr.addString("pid", pid)
	hdr.addNumber("seq", 0)
	hdr.addString("program", safeProgram)
	hdr.addString("command", safeCommand)
	if err := lg.writeRaw(hdr); err != nil {
		f.Close()
		return nil, err
	}
	return lg, nil
}

// FilePath returns the active log file path.
func (l *AgentLogger) FilePath() string { return l.filePath }

// RID returns this logger's run id.
func (l *AgentLogger) RID() string { return l.rid }

// Close releases the file handle.
func (l *AgentLogger) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.f != nil {
		err := l.f.Close()
		l.f = nil
		return err
	}
	return nil
}

// ---- basic levels ---------------------------------------------------------

// Info logs an INFO entry. module may be "".
func (l *AgentLogger) Info(msg, module string) error {
	return l.infoFull(msg, module, 0, "", "", nil)
}

// InfoFull logs INFO with all optional fields. dur==0 omitted; errorCode/tid=="" omitted.
func (l *AgentLogger) InfoFull(msg, module string, dur int64, errorCode, tid string, ctx map[string]interface{}) error {
	return l.infoFull(msg, module, dur, errorCode, tid, ctx)
}
func (l *AgentLogger) infoFull(msg, module string, dur int64, errorCode, tid string, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "INFO")
	e.addString("msg", truncate(msg, 4096))
	e.addString("module", orUnknown(module))
	e.addNumberOpt("dur", dur)
	e.addStringOpt("error_code", errorCode)
	e.addStringOpt("tid", tid)
	e.addCtxOpt(ctx)
	return l.write(e)
}

func (l *AgentLogger) Warn(msg, module string) error {
	return l.WarnFull(msg, module, 0, "", "", nil)
}
func (l *AgentLogger) WarnFull(msg, module string, dur int64, errorCode, tid string, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "WARN")
	e.addString("msg", truncate(msg, 4096))
	e.addString("module", orUnknown(module))
	e.addNumberOpt("dur", dur)
	e.addStringOpt("error_code", errorCode)
	e.addStringOpt("tid", tid)
	e.addCtxOpt(ctx)
	return l.write(e)
}

// Error logs an ERROR entry. errorCode should be one of the Err* constants.
func (l *AgentLogger) Error(msg, module, errorCode, tid string) error {
	return l.ErrorFull(msg, module, errorCode, tid, 0, nil)
}
func (l *AgentLogger) ErrorFull(msg, module, errorCode, tid string, dur int64, ctx map[string]interface{}) error {
	if errorCode == "" {
		errorCode = ErrUnknown
	}
	e := newEntry(l.compact)
	e.addString("level", "ERROR")
	e.addString("msg", truncate(msg, 4096))
	e.addString("module", orUnknown(module))
	e.addString("error_code", errorCode)
	e.addStringOpt("tid", tid)
	e.addNumberOpt("dur", dur)
	e.addCtxOpt(ctx)
	return l.write(e)
}

// ---- specialised ----------------------------------------------------------

// ToolCall logs a TOOL entry. exitCode==0 means success.
func (l *AgentLogger) ToolCall(tool, cmd string, exitCode, dur int64, errorCode, tid, stdout, stderr string, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "TOOL")
	if exitCode == 0 {
		e.addString("msg", "Tool "+tool+" succeeded")
	} else {
		e.addString("msg", "Tool "+tool+" failed")
	}
	e.addString("tool", tool)
	e.addString("cmd", cmd)
	e.addNumber("exit", exitCode)
	e.addNumber("dur", dur)
	e.addStringOpt("error_code", errorCode)
	e.addStringOpt("tid", tid)
	e.addStringOpt("stdout", truncate(stdout, 65536))
	e.addStringOpt("stderr", truncate(stderr, 65536))
	e.addString("module", "unknown")
	e.addCtxOpt(ctx)
	return l.write(e)
}

// FileOp logs a FILE_OP entry.
func (l *AgentLogger) FileOp(op, path string, ok bool, size int64, errorCode, tid string, dur int64, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "FILE_OP")
	if ok {
		e.addString("msg", "File "+op+" succeeded: "+path)
	} else {
		e.addString("msg", "File "+op+" failed: "+path)
	}
	e.addString("op", op)
	e.addString("path", path)
	e.addBool("ok", ok)
	e.addNumberOpt("size", size)
	e.addStringOpt("error_code", errorCode)
	e.addStringOpt("tid", tid)
	e.addNumberOpt("dur", dur)
	e.addString("module", "unknown")
	e.addCtxOpt(ctx)
	return l.write(e)
}

// Decision logs a DECISION entry.
func (l *AgentLogger) Decision(choice string, alts []string, reason string, confidence float64, module string, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "DECISION")
	e.addString("msg", "Decision: "+choice)
	e.addString("choice", choice)
	e.addStringsOpt("alts", alts)
	e.addStringOpt("reason", reason)
	if confidence >= 0 {
		e.addFloat("confidence", confidence)
	}
	e.addString("module", orUnknown(module))
	e.addCtxOpt(ctx)
	return l.write(e)
}

// CodeGen logs a CODE_GEN entry.
func (l *AgentLogger) CodeGen(lang, path string, lines int64, funcs, imports []string, module string, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "CODE_GEN")
	e.addString("msg", "Generated "+lang+" code: "+path)
	e.addString("lang", lang)
	e.addString("path", path)
	e.addNumberOpt("lines", lines)
	e.addStringsOpt("funcs", funcs)
	e.addStringsOpt("imports", imports)
	e.addString("module", orUnknown(module))
	e.addCtxOpt(ctx)
	return l.write(e)
}

// ContextSwitch logs a CONTEXT entry.
func (l *AgentLogger) ContextSwitch(toTask, fromTask, reason, module string, ctx map[string]interface{}) error {
	e := newEntry(l.compact)
	e.addString("level", "CONTEXT")
	e.addString("msg", "Switching to: "+toTask)
	e.addString("to_task", toTask)
	e.addStringOpt("from_task", fromTask)
	e.addStringOpt("reason", reason)
	e.addString("module", orUnknown(module))
	e.addCtxOpt(ctx)
	return l.write(e)
}

// SaveTraceback persists a traceback to the `.tracebacks` sidecar (full keys)
// and returns the generated tid.
func (l *AgentLogger) SaveTraceback(excType, excMsg, traceback string) (string, error) {
	tid := "tb_" + genRid()
	return tid, l.SaveTracebackText(tid, excType, excMsg, traceback)
}
func (l *AgentLogger) SaveTracebackText(tid, excType, excMsg, traceback string) error {
	tbPath := strings.TrimSuffix(l.filePath, ".jsonl") + ".tracebacks"
	e := newEntry(false) // sidecar always FULL keys
	e.addString("tid", tid)
	e.addString("exception_type", excType)
	e.addString("exception_msg", excMsg)
	e.addString("traceback", traceback)
	tb, err := os.OpenFile(tbPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer tb.Close()
	_, err = io.WriteString(tb, e.String()+"\n")
	return err
}

// ---- internals ------------------------------------------------------------

func (l *AgentLogger) write(e *entry) error {
	e.addString("ts", nowISO())
	e.addString("pid", l.pid)
	e.addString("rid", l.rid)
	l.mu.Lock()
	l.seq++
	e.addNumber("seq", int64(l.seq))
	_, err := io.WriteString(l.f, e.String()+"\n")
	l.mu.Unlock()
	return err
}

// writeRaw writes a pre-formed entry (header) without auto-fields.
func (l *AgentLogger) writeRaw(e *entry) error {
	l.mu.Lock()
	_, err := io.WriteString(l.f, e.String()+"\n")
	l.mu.Unlock()
	return err
}

// entry is an ordered list of pre-marshaled `"key": value` fragments.
type entry struct {
	compact bool
	parts   []string
}

// compactMap (contract §4): top-level entry keys only.
var compactMap = map[string]string{
	"ts": "t", "level": "l", "module": "n", "msg": "m", "pid": "p", "rid": "r", "seq": "q",
	"error_code": "e", "dur": "d", "tool": "o", "cmd": "c", "exit": "x", "op": "w", "path": "h",
	"ctx": "z", "tid": "i", "lines": "s", "funcs": "f", "lang": "g", "choice": "k", "alts": "a",
	"reason": "u", "stdout": "v", "stderr": "b", "ok": "y", "size": "j",
}

func (e *entry) ck(key string) string {
	if !e.compact {
		return key
	}
	if c, ok := compactMap[key]; ok {
		return c
	}
	return key
}

func newEntry(compact bool) *entry { return &entry{compact: compact, parts: make([]string, 0, 16)} }

func (e *entry) addRaw(part string) { e.parts = append(e.parts, part) }

func (e *entry) addString(key, v string) {
	raw, _ := marshalNoHTML(v)
	e.addRaw(`"` + e.ck(key) + `": ` + raw)
}
func (e *entry) addStringOpt(key, v string) {
	if v != "" {
		e.addString(key, v)
	}
}
func (e *entry) addNumber(key string, n int64) {
	e.addRaw(`"` + e.ck(key) + `": ` + strconv.FormatInt(n, 10))
}
func (e *entry) addNumberOpt(key string, n int64) {
	if n != 0 {
		e.addNumber(key, n)
	}
}
func (e *entry) addBool(key string, b bool) {
	e.addRaw(`"` + e.ck(key) + `": ` + strconv.FormatBool(b))
}
func (e *entry) addFloat(key string, f float64) {
	raw, _ := marshalNoHTML(f) // handles 0.85 → "0.85"
	e.addRaw(`"` + e.ck(key) + `": ` + raw)
}
func (e *entry) addStringsOpt(key string, ss []string) {
	if len(ss) == 0 {
		return
	}
	raw, _ := marshalNoHTML(ss)
	e.addRaw(`"` + e.ck(key) + `": ` + raw)
}
func (e *entry) addCtxOpt(ctx map[string]interface{}) {
	if len(ctx) == 0 {
		return
	}
	raw, err := marshalNoHTML(ctx)
	if err != nil {
		return
	}
	e.addRaw(`"` + e.ck("ctx") + `": ` + raw)
}

// String joins fragments with ", " and wraps in braces.
func (e *entry) String() string {
	return "{" + strings.Join(e.parts, ", ") + "}"
}

// marshalNoHTML serializes v with HTML escaping disabled, no trailing newline.
func marshalNoHTML(v interface{}) (string, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	return strings.TrimRight(buf.String(), "\n"), nil
}

// ---- helpers --------------------------------------------------------------

var sanitizeRe = regexp.MustCompile(`[^A-Za-z0-9_-]`)

func sanitize(s string) string {
	s = sanitizeRe.ReplaceAllString(s, "_")
	if len(s) > 50 {
		s = s[:50]
	}
	return s
}

func genRid() string {
	var b [4]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "00000000"
	}
	return hex.EncodeToString(b[:]) // 8 hex chars
}

func nowISO() string {
	return time.Now().UTC().Format("2006-01-02T15:04:05.000") + "+00:00"
}

func filenameStamp() string {
	now := time.Now()
	return now.Format("20060102_150405") + fmt.Sprintf("%06d", now.Nanosecond()/1000)
}

func truncate(s string, max int) string {
	// byte-safe truncation (sufficient for ASCII; code-points for UTF-8 below)
	if len(s) <= max {
		return s
	}
	// cut on rune boundary
	r := []rune(s)
	if len(r) > max {
		r = r[:max]
	}
	return string(r)
}

func orUnknown(s string) string {
	if s == "" {
		return "unknown"
	}
	return s
}
