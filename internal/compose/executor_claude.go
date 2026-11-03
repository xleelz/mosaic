package compose

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/xleelz/mosaic/internal/jsonschema"
)

// ClaudeExecutor runs an agent_turn as a headless Claude Code session
// (DESIGN §14.11, "Executors"):
//
//	claude -p --output-format json --permission-mode <mode> \
//	  --allowedTools=<tools> [--model <model>] [--max-turns <n>]
//
// in the turn's directory. The agent must write the stage's output artifact
// as JSON to the turn's OutputPath. The executor reads that file, validates
// it against OutputSchema, and retries once with the validation errors
// appended to the brief.
//
// When the turn has budget.max_turns and the CLI lacks --max-turns (DESIGN
// §15.7), the session runs with --output-format stream-json --verbose
// instead. The executor counts its assistant turns as the events arrive;
// past the limit it kills the session's process group and fails the turn
// with ErrBudget. A session that ends on its own still reports the stats of
// its final result event.
type ClaudeExecutor struct {
	// Command is the argv prefix that starts Claude Code. Default: ["claude"].
	// Tests point it at a fake script.
	Command []string
	// PermissionMode is passed as --permission-mode. Default "dontAsk": tools
	// outside the allowed list are denied rather than prompted for, since
	// nobody can answer a prompt in a headless run.
	PermissionMode string
	// DefaultTools is used when a turn declares no tools.
	DefaultTools []string
	// Retries is the number of extra attempts after a schema failure.
	// Negative means none; zero means the default of one.
	Retries int
	// Env is appended to the inherited environment.
	Env []string

	maxTurnsOnce sync.Once
	maxTurnsOK   bool
}

// MaxTurnsFlagEnv overrides the --max-turns probe: "1" passes the flag
// without probing, "0" never passes it (the executor then counts the turns
// from the event stream).
const MaxTurnsFlagEnv = "MOSAIC_CLAUDE_MAX_TURNS_FLAG"

// defaultClaudeTools is what an agent turn gets when the template lists no
// tools: read the repo, write its artifacts, and run the mosaic CLI and check.
var defaultClaudeTools = []string{"Read", "Grep", "Glob", "Write", "Edit", "Bash"}

func init() { Register("claude", &ClaudeExecutor{}) }

// claudeResult is the subset of `claude -p --output-format json` we read.
type claudeResult struct {
	Type       string  `json:"type"`
	Subtype    string  `json:"subtype"`
	IsError    bool    `json:"is_error"`
	Result     string  `json:"result"`
	SessionID  string  `json:"session_id"`
	CostUSD    float64 `json:"total_cost_usd"`
	NumTurns   int     `json:"num_turns"`
	DurationMS int64   `json:"duration_ms"`
}

// Run executes the turn, retrying once when the artifact is missing, is not
// JSON, or fails its schema. A turn with a Timeout is cancelled when it
// expires, and one that runs out of time or turns fails with ErrBudget. Each
// attempt's session stats go to the context's TurnObserver.
func (c *ClaudeExecutor) Run(ctx context.Context, t Turn) (json.RawMessage, error) {
	parent := ctx
	if t.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, t.Timeout)
		defer cancel()
	}
	obs, _ := TurnObserverFrom(ctx)
	// Without --max-turns, the executor counts the turns itself.
	stream := t.MaxTurns > 0 && !c.supportsMaxTurns(ctx, t)
	if t.OutputPath == "" {
		return nil, fmt.Errorf("claude executor: turn %s/%s has no output path", t.TaskID, t.StageID)
	}
	out := t.OutputPath
	if !filepath.IsAbs(out) && t.Dir != "" {
		out = filepath.Join(t.Dir, out)
	}
	if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
		return nil, fmt.Errorf("claude executor: %w", err)
	}
	var schema map[string]any
	if len(bytes.TrimSpace(t.OutputSchema)) > 0 {
		if err := json.Unmarshal(t.OutputSchema, &schema); err != nil {
			return nil, fmt.Errorf("claude executor: output schema of %s: %w", t.StageID, err)
		}
	}
	retries := c.Retries
	if retries == 0 {
		retries = 1
	} else if retries < 0 {
		retries = 0
	}

	var problems []string
	for attempt := 0; attempt <= retries; attempt++ {
		// A stale artifact from an earlier run must not pass for this one.
		if err := os.Remove(out); err != nil && !errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("claude executor: %w", err)
		}
		prompt := c.prompt(t, out, problems)
		start := time.Now()
		res, err := c.invoke(ctx, t, prompt, stream)
		if err != nil && parent.Err() == nil && errors.Is(ctx.Err(), context.DeadlineExceeded) {
			err = fmt.Errorf("claude executor: %s/%s: timeout of %s exceeded: %w", t.TaskID, t.StageID, t.Timeout, ErrBudget)
		}
		if obs != nil {
			st := SessionStats{Attempt: attempt + 1, WallMS: time.Since(start).Milliseconds()}
			if res != nil {
				st.SessionID, st.Subtype, st.IsError = res.SessionID, res.Subtype, res.IsError
				st.NumTurns, st.DurationMS, st.CostUSD = res.NumTurns, res.DurationMS, res.CostUSD
			}
			if err != nil {
				st.Error = err.Error()
			}
			obs.SessionStats(st)
		}
		if err != nil {
			return nil, err
		}
		val, errs := claudeReadArtifact(out, schema)
		if len(errs) == 0 {
			return val, nil
		}
		problems = errs
	}
	return nil, fmt.Errorf("claude executor: %s/%s: artifact %s still invalid after %d attempt(s):\n  %s",
		t.TaskID, t.StageID, out, retries+1, strings.Join(problems, "\n  "))
}

// prompt is the rendered brief plus the output contract and, on a retry, the
// previous attempt's problems.
func (c *ClaudeExecutor) prompt(t Turn, out string, problems []string) string {
	var b strings.Builder
	b.WriteString(strings.TrimRight(t.Brief, "\n"))
	b.WriteString("\n\n## Output artifact\n\n")
	fmt.Fprintf(&b, "Write your result as one JSON document to `%s`. Write only that JSON to the file: no prose, no code fences.", out)
	if len(bytes.TrimSpace(t.OutputSchema)) > 0 {
		b.WriteString(" It must validate against this JSON Schema:\n\n```json\n")
		var pretty bytes.Buffer
		if json.Indent(&pretty, t.OutputSchema, "", "  ") == nil {
			b.Write(pretty.Bytes())
		} else {
			b.Write(t.OutputSchema)
		}
		b.WriteString("\n```\n")
	} else {
		b.WriteString("\n")
	}
	if len(problems) > 0 {
		b.WriteString("\n## Your previous attempt was rejected\n\nFix every problem below and write the file again:\n\n")
		for _, p := range problems {
			b.WriteString("- " + p + "\n")
		}
	}
	return b.String()
}

// args builds the Claude Code argv after the command prefix. stream selects
// stream-json output (which -p only allows with --verbose) for a turn limit
// the executor enforces.
func (c *ClaudeExecutor) args(t Turn, stream bool) []string {
	mode := c.PermissionMode
	if mode == "" {
		mode = "dontAsk"
	}
	tools := t.Tools
	if len(tools) == 0 {
		tools = c.DefaultTools
	}
	if len(tools) == 0 {
		tools = defaultClaudeTools
	}
	var addDirs []string
	if len(t.WriteScope) > 0 {
		tools, addDirs = claudeScopeTools(tools, t.WriteScope, t.Dir)
	} else if !claudeHasTool(tools, "Write") {
		// The agent must be able to write its artifact.
		tools = append(append([]string{}, tools...), "Write")
	}
	// The prompt goes on stdin (invoke), not in argv: a large brief exceeds the
	// OS argument limit (E2BIG). --allowedTools uses the = form, so the
	// variadic flag can't swallow anything.
	format := []string{"--output-format", "json"}
	if stream {
		format = []string{"--output-format", "stream-json", "--verbose"}
	}
	args := append(append([]string{"-p"}, format...),
		"--permission-mode", mode, "--allowedTools="+strings.Join(tools, ","))
	for _, d := range addDirs {
		args = append(args, "--add-dir="+d)
	}
	if t.Model != "" {
		args = append(args, "--model", t.Model)
	}
	if t.MaxTurns > 0 && c.maxTurnsOK && !stream {
		args = append(args, "--max-turns", fmt.Sprint(t.MaxTurns))
	}
	return args
}

// supportsMaxTurns reports whether the CLI takes --max-turns: the
// MOSAIC_CLAUDE_MAX_TURNS_FLAG override, else `claude --help` (probed once).
func (c *ClaudeExecutor) supportsMaxTurns(ctx context.Context, t Turn) bool {
	c.maxTurnsOnce.Do(func() {
		switch c.getenv(MaxTurnsFlagEnv) {
		case "1", "true":
			c.maxTurnsOK = true
			return
		case "0", "false":
			return
		}
		pctx, cancel := context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
		argv := c.command()
		cmd := exec.CommandContext(pctx, argv[0], append(append([]string{}, argv[1:]...), "--help")...)
		cmd.Dir = t.Dir
		cmd.Env = append(os.Environ(), c.Env...)
		out, _ := cmd.CombinedOutput()
		c.maxTurnsOK = bytes.Contains(out, []byte("--max-turns"))
	})
	return c.maxTurnsOK
}

// getenv reads a variable from Env (last wins), else the process environment.
func (c *ClaudeExecutor) getenv(key string) string {
	for i := len(c.Env) - 1; i >= 0; i-- {
		if v, ok := strings.CutPrefix(c.Env[i], key+"="); ok {
			return v
		}
	}
	return os.Getenv(key)
}

func (c *ClaudeExecutor) command() []string {
	if len(c.Command) == 0 {
		return []string{"claude"}
	}
	return c.Command
}

// claudeFileTools are the tools that write files. Under a write scope they
// are allowed only on the scope's paths.
var claudeFileTools = []string{"Write", "Edit", "MultiEdit", "NotebookEdit"}

// claudeScopeTools restricts the file-writing tools to the write scope
// (DESIGN §16.7): every Write, Edit, MultiEdit or NotebookEdit entry, bare or
// with its own pattern, is replaced by Write(//<path>/**) and
// Edit(//<path>/**) for each scope directory (Write(//<file>) and
// Edit(//<file>) for a file). In Claude Code permission rules, "//" starts an
// absolute filesystem path, and Edit rules cover every file-editing tool.
// Other tools, reads included, are kept as configured. It also returns the
// scope directories outside dir, which the session needs as --add-dir.
func claudeScopeTools(tools, scope []string, dir string) ([]string, []string) {
	var out, addDirs []string
	for _, tool := range tools {
		file := false
		for _, ft := range claudeFileTools {
			if tool == ft || strings.HasPrefix(tool, ft+"(") {
				file = true
			}
		}
		if !file {
			out = append(out, tool)
		}
	}
	absDir := dir
	if a, err := filepath.Abs(dir); err == nil {
		absDir = a
	}
	for _, p := range scope {
		p = filepath.Clean(p)
		pattern := "/" + filepath.ToSlash(p)
		parent := filepath.Dir(p)
		if fi, err := os.Stat(p); err == nil && fi.IsDir() {
			pattern += "/**"
			parent = p
		}
		out = append(out, "Write("+pattern+")", "Edit("+pattern+")")
		if rel, err := filepath.Rel(absDir, parent); dir == "" || err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
			addDirs = append(addDirs, parent)
		}
	}
	return out, addDirs
}

func claudeHasTool(tools []string, name string) bool {
	for _, t := range tools {
		if t == name || strings.HasPrefix(t, name+"(") {
			return true
		}
	}
	return false
}

// invoke runs one Claude Code session and checks that it ended without
// error. It returns the session's result whenever one was read, also with an
// error. A session that hit its turn limit fails with ErrBudget: through
// --max-turns (subtype error_max_turns), or, with stream set, when the
// executor counts more assistant turns than t.MaxTurns and stops it.
func (c *ClaudeExecutor) invoke(ctx context.Context, t Turn, prompt string, stream bool) (*claudeResult, error) {
	argv := c.command()
	cmd := exec.CommandContext(ctx, argv[0], append(append([]string{}, argv[1:]...), c.args(t, stream)...)...)
	cmd.Dir = t.Dir
	cmd.Stdin = strings.NewReader(prompt)
	cmd.Env = append(os.Environ(), c.Env...)
	cmd.Env = append(cmd.Env,
		"MOSAIC_COMPOSE_TASK="+t.TaskID,
		"MOSAIC_COMPOSE_STAGE="+t.StageID,
		"MOSAIC_COMPOSE_ROLE="+t.Role)
	// On cancellation, kill the session's whole process group (its tool
	// subprocesses too), and don't wait long for pipes they hold open.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	killGroup := func() error { return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) }
	cmd.Cancel = killGroup
	cmd.WaitDelay = 5 * time.Second
	var stdout, stderr bytes.Buffer
	var sw *claudeStream
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if stream {
		sw = &claudeStream{max: t.MaxTurns, stop: func() { _ = killGroup() }, seen: map[string]bool{}}
		cmd.Stdout = sw
	}
	start := time.Now()
	err := cmd.Run()
	if ctx.Err() != nil {
		return nil, fmt.Errorf("claude executor: %s/%s: %w", t.TaskID, t.StageID, ctx.Err())
	}
	if sw != nil {
		sw.flush()
		if sw.stopped {
			res := sw.partial(time.Since(start).Milliseconds())
			return res, fmt.Errorf("claude executor: %s/%s: session %s passed budget.max_turns %d (counted by the executor; this claude has no --max-turns) and was stopped: %w",
				t.TaskID, t.StageID, res.SessionID, t.MaxTurns, ErrBudget)
		}
	}
	if err != nil {
		out := stdout.String()
		if sw != nil {
			out = sw.tail.String()
		}
		return nil, fmt.Errorf("claude executor: %s/%s: %v: %s", t.TaskID, t.StageID, err, claudeTail(stderr.String(), out))
	}
	var res claudeResult
	if sw != nil {
		if sw.result == nil {
			return nil, fmt.Errorf("claude executor: %s/%s: the event stream has no result: %s", t.TaskID, t.StageID, claudeTail(sw.tail.String()))
		}
		res = *sw.result
	} else if jerr := json.Unmarshal(bytes.TrimSpace(stdout.Bytes()), &res); jerr != nil {
		return nil, fmt.Errorf("claude executor: %s/%s: unreadable result (%v): %s", t.TaskID, t.StageID, jerr, claudeTail(stdout.String()))
	}
	if res.Subtype == "error_max_turns" {
		return &res, fmt.Errorf("claude executor: %s/%s: session %s ended with error_max_turns after %d turns: %w", t.TaskID, t.StageID, res.SessionID, res.NumTurns, ErrBudget)
	}
	if res.IsError || (res.Subtype != "" && res.Subtype != "success") {
		return &res, fmt.Errorf("claude executor: %s/%s: session %s ended with %s: %s", t.TaskID, t.StageID, res.SessionID, res.Subtype, claudeTail(res.Result))
	}
	return &res, nil
}

// claudeStream reads a session's stream-json events (one JSON object per
// line) as they arrive. It counts the session's assistant turns, calls stop
// once the count passes max, and keeps the final result event.
//
// An assistant turn is one assistant message of the main session: stream-json
// may emit a message once per content block, so events are counted by
// message id, and subagent messages (parent_tool_use_id set) don't count.
type claudeStream struct {
	max  int
	stop func()

	mu      sync.Mutex
	buf     []byte          // the incomplete last line
	seen    map[string]bool // assistant message ids counted
	turns   int
	session string
	stopped bool
	result  *claudeResult
	tail    bytes.Buffer // the last bytes of output, for error messages
}

// claudeEvent is the subset of a stream-json event we read.
type claudeEvent struct {
	Type            string          `json:"type"`
	SessionID       string          `json:"session_id"`
	ParentToolUseID *string         `json:"parent_tool_use_id"`
	Message         json.RawMessage `json:"message"`
}

func (w *claudeStream) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.tail.Write(p)
	if w.tail.Len() > 8192 {
		keep := append([]byte{}, w.tail.Bytes()[w.tail.Len()-4096:]...)
		w.tail.Reset()
		w.tail.Write(keep)
	}
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexByte(w.buf, '\n')
		if i < 0 {
			break
		}
		w.line(w.buf[:i])
		w.buf = w.buf[i+1:]
	}
	return len(p), nil
}

// flush handles a last line without a newline.
func (w *claudeStream) flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if len(bytes.TrimSpace(w.buf)) > 0 {
		w.line(w.buf)
	}
	w.buf = nil
}

// line handles one event. w.mu is held.
func (w *claudeStream) line(b []byte) {
	b = bytes.TrimSpace(b)
	if len(b) == 0 || b[0] != '{' {
		return
	}
	var ev claudeEvent
	if json.Unmarshal(b, &ev) != nil {
		return
	}
	if ev.SessionID != "" && w.session == "" {
		w.session = ev.SessionID
	}
	switch ev.Type {
	case "assistant":
		if ev.ParentToolUseID != nil && *ev.ParentToolUseID != "" {
			return
		}
		var msg struct {
			ID string `json:"id"`
		}
		_ = json.Unmarshal(ev.Message, &msg)
		if msg.ID != "" {
			if w.seen[msg.ID] {
				return
			}
			w.seen[msg.ID] = true
		}
		w.turns++
		if w.max > 0 && w.turns > w.max && !w.stopped {
			w.stopped = true
			w.stop()
		}
	case "result":
		var res claudeResult
		if json.Unmarshal(b, &res) == nil {
			w.result = &res
		}
	}
}

// partial is the stats of a session the executor stopped: it never wrote a
// result, so the turns are the executor's count (the limit plus the turn
// that passed it), and the duration is the wall time.
func (w *claudeStream) partial(wallMS int64) *claudeResult {
	w.mu.Lock()
	defer w.mu.Unlock()
	return &claudeResult{Type: "result", Subtype: "error_max_turns", IsError: true, SessionID: w.session,
		NumTurns: w.turns, DurationMS: wallMS}
}

// claudeReadArtifact reads and validates the output file. Every problem it returns
// is phrased for the agent's retry prompt.
func claudeReadArtifact(path string, schema map[string]any) (json.RawMessage, []string) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, []string{fmt.Sprintf("the output file %s was not written", path)}
	}
	if err != nil {
		return nil, []string{err.Error()}
	}
	var v any
	if err := json.Unmarshal(data, &v); err != nil {
		return nil, []string{fmt.Sprintf("%s is not valid JSON: %v", path, err)}
	}
	if schema != nil {
		if errs := jsonschema.Validate(schema, v, claudeLocalRefs(schema)); len(errs) > 0 {
			return nil, errs
		}
	}
	var compact bytes.Buffer
	if err := json.Compact(&compact, data); err != nil {
		return nil, []string{err.Error()}
	}
	return json.RawMessage(compact.Bytes()), nil
}

// claudeLocalRefs resolves "#/..." JSON pointers within the schema itself
// ($defs, definitions).
func claudeLocalRefs(root map[string]any) jsonschema.Resolver {
	return func(ref string) (map[string]any, bool) {
		if !strings.HasPrefix(ref, "#") {
			return nil, false
		}
		var cur any = root
		for _, part := range strings.Split(strings.TrimPrefix(strings.TrimPrefix(ref, "#"), "/"), "/") {
			if part == "" {
				continue
			}
			part = strings.ReplaceAll(strings.ReplaceAll(part, "~1", "/"), "~0", "~")
			m, ok := cur.(map[string]any)
			if !ok {
				return nil, false
			}
			if cur, ok = m[part]; !ok {
				return nil, false
			}
		}
		m, ok := cur.(map[string]any)
		return m, ok
	}
}

// claudeTail returns the last part of the first non-empty text, for error messages.
func claudeTail(texts ...string) string {
	for _, s := range texts {
		if s = strings.TrimSpace(s); s != "" {
			if len(s) > 2000 {
				s = "..." + s[len(s)-2000:]
			}
			return s
		}
	}
	return "(no output)"
}
