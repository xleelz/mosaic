package compose

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// fakeClaude is a stand-in for the claude binary. Per invocation n (1-based)
// it records its argv, its stdin (the prompt) and its working directory, then
// writes $FAKE_OUT_<n> (if set) to $FAKE_TARGET and prints $FAKE_RESULT
// (default: a success result).
//
// `--help` prints $FAKE_HELP and is not counted. When $FAKE_TARGET is empty,
// the output path is read from the prompt. $FAKE_SLEEP delays the session;
// $FAKE_RESULT_<n> overrides $FAKE_RESULT for invocation n. $FAKE_STREAM, when
// set, is printed instead of the result (stream-json events, one per line),
// and $FAKE_HANG then keeps the session, and a child process in its group,
// alive that many seconds.
const fakeClaude = `#!/bin/sh
if [ "$1" = "--help" ]; then printf '%s\n' "${FAKE_HELP:-Usage: claude [options]}"; exit 0; fi
n=$(( $(cat "$FAKE_DIR/count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$FAKE_DIR/count"
pwd > "$FAKE_DIR/pwd.$n"
for a in "$@"; do printf '%s\n--ARG--\n' "$a"; done > "$FAKE_DIR/args.$n"
cat > "$FAKE_DIR/stdin.$n"
target="$FAKE_TARGET"
if [ -z "$target" ]; then target=$(sed -n 's/.*JSON document to .\([^ ]*\.json\).. Write only.*/\1/p' "$FAKE_DIR/stdin.$n" | head -n 1); fi
if [ -n "$FAKE_SLEEP" ]; then sleep "$FAKE_SLEEP"; fi
eval "body=\${FAKE_OUT_$n:-\$FAKE_OUT}"
if [ -n "$body" ]; then printf '%s' "$body" > "$target"; fi
if [ -n "$FAKE_EXIT" ]; then echo "boom" >&2; exit "$FAKE_EXIT"; fi
if [ -n "$FAKE_STREAM" ]; then printf '%s\n' "$FAKE_STREAM"; if [ -n "$FAKE_HANG" ]; then sleep "$FAKE_HANG" & wait; fi; exit 0; fi
eval "res=\${FAKE_RESULT_$n:-\$FAKE_RESULT}"
if [ -n "$res" ]; then printf '%s' "$res"; exit 0; fi
printf '%s' '{"type":"result","subtype":"success","is_error":false,"result":"done","session_id":"s1"}'
`

type fakeRun struct {
	dir  string // where the fake records its calls
	work string // the turn's Dir
	exec *ClaudeExecutor
}

func newFake(t *testing.T, env ...string) *fakeRun {
	t.Helper()
	root := t.TempDir()
	f := &fakeRun{dir: filepath.Join(root, "fake"), work: filepath.Join(root, "repo")}
	for _, d := range []string{f.dir, f.work} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	bin := filepath.Join(f.dir, "claude")
	if err := os.WriteFile(bin, []byte(fakeClaude), 0o755); err != nil {
		t.Fatal(err)
	}
	f.exec = &ClaudeExecutor{
		Command: []string{bin},
		Env: append([]string{
			"FAKE_DIR=" + f.dir,
			"FAKE_TARGET=" + filepath.Join(f.work, "out", "artifact.json"),
		}, env...),
	}
	return f
}

func (f *fakeRun) calls(t *testing.T) int {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(f.dir, "count"))
	if err != nil {
		return 0
	}
	var n int
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(b))), &n); err != nil {
		t.Fatal(err)
	}
	return n
}

// argv returns invocation n's command-line arguments as passed.
func (f *fakeRun) argv(t *testing.T, n int) []string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join(f.dir, "args."+itoa(n)))
	if err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(string(b), "\n--ARG--\n")
	return parts[:len(parts)-1]
}

// args returns invocation n's arguments with the prompt, read from its stdin,
// placed after -p: ["-p", prompt, flags...].
func (f *fakeRun) args(t *testing.T, n int) []string {
	t.Helper()
	in, err := os.ReadFile(filepath.Join(f.dir, "stdin."+itoa(n)))
	if err != nil {
		t.Fatal(err)
	}
	a := f.argv(t, n)
	return append([]string{a[0], string(in)}, a[1:]...)
}

func itoa(n int) string { b, _ := json.Marshal(n); return string(b) }

var areaSchema = json.RawMessage(`{
  "type": "object",
  "required": ["areas"],
  "properties": {"areas": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/area"}}},
  "$defs": {"area": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}}
}`)

func turn(f *fakeRun) Turn {
	return Turn{
		TaskID: "root", StageID: "skeleton", Role: "coordinator",
		Brief:        "Write the skeleton.",
		OutputPath:   "out/artifact.json", // relative: resolved against Dir
		OutputSchema: areaSchema,
		Tools:        []string{"Read", "Bash(mosaic *)"},
		Model:        "sonnet",
		Dir:          f.work,
	}
}

func TestClaudeExecutorSuccess(t *testing.T) {
	f := newFake(t, `FAKE_OUT_1={ "areas": [ {"id": "api"}, {"id": "store"} ] }`)
	got, err := f.exec.Run(context.Background(), turn(f))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"areas":[{"id":"api"},{"id":"store"}]}` {
		t.Fatalf("artifact = %s", got)
	}
	if n := f.calls(t); n != 1 {
		t.Fatalf("calls = %d, want 1", n)
	}
	pwd, _ := os.ReadFile(filepath.Join(f.dir, "pwd.1"))
	if real, _ := filepath.EvalSymlinks(f.work); strings.TrimSpace(string(pwd)) != real && strings.TrimSpace(string(pwd)) != f.work {
		t.Fatalf("ran in %q, want %q", pwd, f.work)
	}
	for _, a := range f.argv(t, 1) {
		if strings.Contains(a, "Write the skeleton.") {
			t.Fatal("the prompt is in argv; it must go on stdin (a long brief exceeds the argument limit)")
		}
	}
	args := f.args(t, 1)
	if args[0] != "-p" || !strings.HasPrefix(args[1], "Write the skeleton.") {
		t.Fatalf("argv starts %q", args[:2])
	}
	if !strings.Contains(args[1], filepath.Join(f.work, "out", "artifact.json")) || !strings.Contains(args[1], `"areas"`) {
		t.Fatalf("prompt lacks the output path or schema:\n%s", args[1])
	}
	want := []string{"--output-format", "json", "--permission-mode", "dontAsk",
		"--allowedTools=Read,Bash(mosaic *),Write", "--model", "sonnet"}
	if strings.Join(args[2:], " ") != strings.Join(want, " ") {
		t.Fatalf("flags = %q, want %q", args[2:], want)
	}
}

func TestClaudeExecutorRetriesWithErrors(t *testing.T) {
	f := newFake(t, `FAKE_OUT_1={"areas": [{"name": "api"}]}`, `FAKE_OUT_2={"areas": [{"id": "api"}]}`)
	got, err := f.exec.Run(context.Background(), turn(f))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"areas":[{"id":"api"}]}` {
		t.Fatalf("artifact = %s", got)
	}
	if n := f.calls(t); n != 2 {
		t.Fatalf("calls = %d, want 2", n)
	}
	retry := f.args(t, 2)[1]
	if !strings.Contains(retry, "previous attempt was rejected") || !strings.Contains(retry, "id") {
		t.Fatalf("retry prompt lacks the errors:\n%s", retry)
	}
	if strings.Contains(f.args(t, 1)[1], "rejected") {
		t.Fatal("first prompt mentions a rejection")
	}
}

func TestClaudeExecutorMissingFileRetriesThenFails(t *testing.T) {
	// A stale artifact from an earlier run must not count.
	f := newFake(t)
	if err := os.MkdirAll(filepath.Join(f.work, "out"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(f.work, "out", "artifact.json"), []byte(`{"areas":[{"id":"old"}]}`), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := f.exec.Run(context.Background(), turn(f))
	if err == nil || !strings.Contains(err.Error(), "was not written") {
		t.Fatalf("err = %v", err)
	}
	if n := f.calls(t); n != 2 {
		t.Fatalf("calls = %d, want 2 (one retry)", n)
	}
	if !strings.Contains(f.args(t, 2)[1], "was not written") {
		t.Fatal("retry prompt lacks the missing-file problem")
	}
}

func TestClaudeExecutorInvalidJSON(t *testing.T) {
	f := newFake(t, "FAKE_OUT_1=not json", "FAKE_OUT_2=```json\n{}\n```")
	_, err := f.exec.Run(context.Background(), turn(f))
	if err == nil || !strings.Contains(err.Error(), "not valid JSON") {
		t.Fatalf("err = %v", err)
	}
}

func TestClaudeExecutorSessionErrors(t *testing.T) {
	f := newFake(t, `FAKE_RESULT={"type":"result","subtype":"error_max_turns","is_error":true,"result":"ran out","session_id":"s9"}`)
	_, err := f.exec.Run(context.Background(), turn(f))
	if err == nil || !strings.Contains(err.Error(), "error_max_turns") {
		t.Fatalf("err = %v", err)
	}
	if n := f.calls(t); n != 1 {
		t.Fatalf("a session error is not retried; calls = %d", n)
	}

	g := newFake(t, "FAKE_EXIT=3")
	_, err = g.exec.Run(context.Background(), turn(g))
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("err = %v", err)
	}
}

func TestClaudeExecutorDefaults(t *testing.T) {
	f := newFake(t, `FAKE_OUT_1={"anything": true}`)
	tr := turn(f)
	tr.Tools, tr.Model, tr.OutputSchema = nil, "", nil
	f.exec.PermissionMode = "acceptEdits"
	got, err := f.exec.Run(context.Background(), tr)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"anything":true}` {
		t.Fatalf("artifact = %s", got)
	}
	flags := strings.Join(f.args(t, 1)[2:], " ")
	if flags != "--output-format json --permission-mode acceptEdits --allowedTools=Read,Grep,Glob,Write,Edit,Bash" {
		t.Fatalf("flags = %s", flags)
	}
}

func TestClaudeExecutorRegistered(t *testing.T) {
	e, ok := Lookup("claude")
	if !ok {
		t.Fatal("claude executor is not registered")
	}
	if _, ok := e.(*ClaudeExecutor); !ok {
		t.Fatalf("claude is a %T", e)
	}
}

// streamTurn is a turn with a turn limit, run by a fake claude whose --help
// lists no --max-turns, so the executor counts turns from the event stream.
func streamTurn(t *testing.T, maxTurns int, env ...string) (*fakeRun, Turn) {
	t.Helper()
	f := newFake(t, append([]string{"FAKE_HELP=Usage: claude [options]", MaxTurnsFlagEnv + "="}, env...)...)
	tr := turn(f)
	tr.MaxTurns = maxTurns
	return f, tr
}

func streamEvents(lines ...string) string { return strings.Join(lines, "\n") }

const (
	evInit = `{"type":"system","subtype":"init","session_id":"s7"}`
	evUser = `{"type":"user","message":{"role":"user"},"parent_tool_use_id":null,"session_id":"s7"}`
)

func evAssistant(id string) string {
	return `{"type":"assistant","message":{"id":"` + id + `","role":"assistant"},"parent_tool_use_id":null,"session_id":"s7"}`
}

func TestClaudeExecutorStreamCountsTurnsAndReadsResult(t *testing.T) {
	// Two turns within a limit of 3: the second message arrives as two events
	// (one per content block), and a subagent's message doesn't count.
	stream := streamEvents(evInit, evAssistant("m1"), evUser, evAssistant("m2"), evAssistant("m2"),
		`{"type":"assistant","message":{"id":"sub1"},"parent_tool_use_id":"tool1","session_id":"s7"}`,
		`{"type":"assistant","message":{"id":"sub2"},"parent_tool_use_id":"tool1","session_id":"s7"}`,
		result("s7", 2, 900, 0.125))
	f, tr := streamTurn(t, 3, `FAKE_OUT_1={"areas": [{"id": "api"}]}`, "FAKE_STREAM="+stream)
	rec := &recorder{}
	got, err := f.exec.Run(WithTurnObserver(context.Background(), rec), tr)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"areas":[{"id":"api"}]}` {
		t.Fatalf("artifact = %s", got)
	}
	flags := strings.Join(f.args(t, 1)[2:], " ")
	if !strings.HasPrefix(flags, "--output-format stream-json --verbose ") || strings.Contains(flags, "--max-turns") {
		t.Fatalf("flags = %s", flags)
	}
	if len(rec.warnings) != 0 || len(rec.stats) != 1 {
		t.Fatalf("stats %+v, warnings %v", rec.stats, rec.warnings)
	}
	if s := rec.stats[0]; s.SessionID != "s7" || s.NumTurns != 2 || s.DurationMS != 900 || s.CostUSD != 0.125 || s.Subtype != "success" || s.IsError {
		t.Fatalf("stats = %+v", s)
	}
}

func TestClaudeExecutorStreamStopsPastTheLimit(t *testing.T) {
	// The third assistant turn passes a limit of 2: the executor kills the
	// session's process group (the fake and its sleeping child) at once,
	// without waiting for the session or retrying it.
	stream := streamEvents(evInit, evAssistant("m1"), evUser, evAssistant("m2"), evUser, evAssistant("m3"))
	f, tr := streamTurn(t, 2, `FAKE_OUT_1={"areas": [{"id": "api"}]}`, "FAKE_STREAM="+stream, "FAKE_HANG=30")
	rec := &recorder{}
	start := time.Now()
	_, err := f.exec.Run(WithTurnObserver(context.Background(), rec), tr)
	if !errors.Is(err, ErrBudget) || !strings.Contains(err.Error(), "max_turns 2") {
		t.Fatalf("err = %v, want ErrBudget", err)
	}
	if d := time.Since(start); d > 4*time.Second {
		t.Fatalf("the session was not stopped: %s", d)
	}
	if n := f.calls(t); n != 1 {
		t.Fatalf("a budget failure is not retried; calls = %d", n)
	}
	if len(rec.stats) != 1 {
		t.Fatalf("stats = %+v", rec.stats)
	}
	if s := rec.stats[0]; s.SessionID != "s7" || s.NumTurns != 3 || s.Subtype != "error_max_turns" || !s.IsError || s.Error == "" {
		t.Fatalf("stats = %+v", s)
	}
}

func TestClaudeExecutorStreamWithinLimitWithoutTrailingNewline(t *testing.T) {
	// Exactly the limit is allowed; the default fake result (no newline, no
	// other events) is the stream's last line.
	f, tr := streamTurn(t, 1, `FAKE_OUT_1={"areas": [{"id": "api"}]}`,
		"FAKE_RESULT="+streamEvents(evAssistant("m1"), result("s3", 1, 10, 0.01)))
	if _, err := f.exec.Run(context.Background(), tr); err != nil {
		t.Fatal(err)
	}
}

func TestClaudeExecutorStreamWithoutResult(t *testing.T) {
	f, tr := streamTurn(t, 4, `FAKE_OUT_1={"areas": [{"id": "api"}]}`, "FAKE_STREAM="+streamEvents(evInit, evAssistant("m1")))
	_, err := f.exec.Run(context.Background(), tr)
	if err == nil || !strings.Contains(err.Error(), "no result") || errors.Is(err, ErrBudget) {
		t.Fatalf("err = %v", err)
	}
}

func TestClaudeExecutorStreamSessionError(t *testing.T) {
	// The final result's error still fails the turn.
	f, tr := streamTurn(t, 4, `FAKE_OUT_1={"areas": [{"id": "api"}]}`,
		"FAKE_STREAM="+streamEvents(evInit, `{"type":"result","subtype":"error_during_execution","is_error":true,"session_id":"s7","num_turns":1}`))
	_, err := f.exec.Run(context.Background(), tr)
	if err == nil || !strings.Contains(err.Error(), "error_during_execution") {
		t.Fatalf("err = %v", err)
	}
}
