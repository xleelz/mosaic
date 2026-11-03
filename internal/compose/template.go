// Package compose is mosaic's local workflow emulator (docs/DESIGN.md
// §14.9, §14.11). It runs workflow templates with the semantics of
// requirements/fae-hierarchical-workflows.md, under the same names: dynamic
// parallel fanouts, subworkflows inside branches, recursion budgets,
// workflow signatures, detached children, change requests, artifact-only
// output directories, role caps with cap_scope, and the run tree. It does
// not emulate fae's kernel floors, leases or authority model.
package compose

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"sigs.k8s.io/yaml"

	"github.com/xleelz/mosaic/internal/expr"
)

// Stage kinds.
const (
	KindAgentTurn     = "agent_turn"
	KindFanout        = "fanout"
	KindSubworkflow   = "subworkflow"
	KindGate          = "gate"
	KindCommand       = "command"
	KindChangeRequest = "change_request"
)

// Cap scopes (FAE-SCH-023).
const (
	ScopeWorkflow = "workflow"
	ScopeTree     = "tree"
	ScopeTask     = "task"
)

// Defaults and bounds (fae Appendix A).
const (
	DefaultMaxBranches = 64
	MaxBranchesBound   = 1024
	DepthCeiling       = 8 // the instance recursion ceiling
	NestingLimit       = 4 // nesting depth for templates without recursion
)

// Schema is a JSON Schema as decoded JSON.
type Schema = map[string]any

// Template is a parsed workflow template.
type Template struct {
	ID        string
	Version   string
	Produces  string // "" or "artifacts"
	Inputs    map[string]Schema
	Outputs   map[string]Schema
	Recursion *Recursion
	Roles     map[string]Role
	Stages    []*Stage

	Source string          // file the template came from, if any
	Raw    json.RawMessage // the template as JSON, stored in run.json
}

// Recursion is a template's recursion budget (FAE-WF-098). Zero means
// unbounded for max_descendants and max_children_per_visit.
type Recursion struct {
	MaxDepth            int `json:"max_depth"`
	MaxDescendants      int `json:"max_descendants,omitempty"`
	MaxChildrenPerVisit int `json:"max_children_per_visit,omitempty"`
}

// Role is a role's concurrency cap.
type Role struct {
	Cap      int
	CapScope string
}

// Join is a fanout's join rule: all, any or k-of-n.
type Join struct {
	Mode string // "all", "any" or "k"
	K    int
}

func (j Join) String() string {
	if j.Mode == "k" {
		return fmt.Sprintf("{k: %d}", j.K)
	}
	return j.Mode
}

// Budget is an agent_turn's run budget (DESIGN §14.13): at most MaxTurns
// agent turns, cancelled after Timeout. Zero means unbounded.
type Budget struct {
	MaxTurns int
	Timeout  time.Duration
}

// OutputSpec is an agent_turn's declared output.
type OutputSpec struct {
	Name   string
	Schema Schema
}

// Stage is one stage of a template or of a fanout branch.
type Stage struct {
	ID     string
	Kind   string
	Path   string   // location in the template, e.g. stages[2].branch.stages[0]
	After  []string // explicit ordering on other stages of the same scope
	OnFail string   // "" or "fail" fails the scope; otherwise a handler stage id

	// agent_turn (Bindings also on gate and command)
	Role     string
	Brief    string
	Bindings []string
	Output   *OutputSpec
	Tools    []string
	Model    string
	Budget   *Budget

	// fanout
	BranchesFrom string // an artifact reference
	MaxBranches  int
	Parallel     bool
	Join         Join
	JoinOutput   string // join artifact name (default: stage id)
	Branch       *Branch

	// subworkflow
	Workflow  string            // a template id, or "self"
	InputMap  map[string]string // child input -> reference or "=cel"
	OutputMap map[string]string // artifact here -> child output

	// gate
	Expr string

	// command
	Argv      []string
	CmdOutput string // artifact name (default: stage id)

	// change_request
	Target         string // "parent" or a task id
	From           string // artifact reference
	TargetArtifact string // the target's artifact the request is about

	deps []string // artifact names this stage reads (computed)
}

// Branch is a fanout's branch sub-graph.
type Branch struct {
	Stages []*Stage
	Output string // the branch artifact joined in order
}

// Error is one template validation error at a path.
type Error struct {
	Path    string `json:"path"`
	Message string `json:"message"`
}

func (e Error) String() string {
	if e.Path == "" {
		return e.Message
	}
	return e.Path + ": " + e.Message
}

// ValidationError lists every error found in a template.
type ValidationError struct {
	Source string
	Errors []Error
}

func (e *ValidationError) Error() string {
	var b strings.Builder
	name := e.Source
	if name == "" {
		name = "template"
	}
	fmt.Fprintf(&b, "%s: %d error(s)", name, len(e.Errors))
	for _, x := range e.Errors {
		b.WriteString("\n  " + x.String())
	}
	return b.String()
}

// Resolver finds a template by workflow id, for subworkflow stages.
type Resolver func(id string) (*Template, error)

var (
	idRe       = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]*$`)
	nameRe     = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)
	artRefRe   = regexp.MustCompile(`\bartifacts\.([A-Za-z_][A-Za-z0-9_]*)`)
	artIndexRe = regexp.MustCompile(`index\s+\.artifacts\s+"([^"]+)"`)
)

// LoadFile reads and parses a template file (YAML or JSON). It does not
// resolve other templates; call Validate for cross-template checks.
func LoadFile(path string) (*Template, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	t, err := Parse(data)
	if t != nil {
		t.Source = path
	}
	if ve, ok := err.(*ValidationError); ok {
		ve.Source = path
	}
	return t, err
}

// Parse parses a template and checks it on its own. It returns every error
// it finds, with its path, as a *ValidationError; the template is returned
// too, as far as it could be built.
func Parse(data []byte) (*Template, error) {
	js, err := yaml.YAMLToJSON(data)
	if err != nil {
		return nil, &ValidationError{Errors: []Error{{Message: "invalid YAML: " + err.Error()}}}
	}
	dec := json.NewDecoder(bytes.NewReader(js))
	dec.UseNumber()
	var doc any
	if err := dec.Decode(&doc); err != nil {
		return nil, &ValidationError{Errors: []Error{{Message: "invalid document: " + err.Error()}}}
	}
	doc = expr.Native(doc)
	p := &parser{}
	t := p.template(doc)
	t.Raw = js
	if len(p.errs) == 0 {
		p.check(t, nil)
	}
	if len(p.errs) > 0 {
		return t, &ValidationError{Errors: p.errs}
	}
	return t, nil
}

// Validate runs the checks that need other templates: subworkflow
// signatures and mutual recursion. resolve may be nil.
func Validate(t *Template, resolve Resolver) error {
	p := &parser{}
	p.check(t, resolve)
	if len(p.errs) > 0 {
		return &ValidationError{Source: t.Source, Errors: p.errs}
	}
	return nil
}

type parser struct{ errs []Error }

func (p *parser) errf(path, format string, a ...any) {
	p.errs = append(p.errs, Error{Path: path, Message: fmt.Sprintf(format, a...)})
}

func join(path, key string) string {
	if path == "" {
		return key
	}
	return path + "." + key
}

// object checks that v is an object with only the allowed keys.
func (p *parser) object(path string, v any, allowed ...string) map[string]any {
	m, ok := v.(map[string]any)
	if !ok {
		p.errf(path, "must be an object")
		return nil
	}
	ok2 := map[string]bool{}
	for _, k := range allowed {
		ok2[k] = true
	}
	for _, k := range sortedKeys(m) {
		if !ok2[k] {
			p.errf(join(path, k), "unknown field")
		}
	}
	return m
}

func (p *parser) str(path string, m map[string]any, key string, required bool) string {
	v, ok := m[key]
	if !ok || v == nil {
		if required {
			p.errf(join(path, key), "is required")
		}
		return ""
	}
	s, ok := v.(string)
	if !ok {
		p.errf(join(path, key), "must be a string")
		return ""
	}
	if required && s == "" {
		p.errf(join(path, key), "is required")
	}
	return s
}

func (p *parser) integer(path string, m map[string]any, key string, def int) int {
	v, ok := m[key]
	if !ok || v == nil {
		return def
	}
	n, ok := v.(int64)
	if !ok {
		p.errf(join(path, key), "must be an integer")
		return def
	}
	return int(n)
}

func (p *parser) boolean(path string, m map[string]any, key string) bool {
	v, ok := m[key]
	if !ok || v == nil {
		return false
	}
	b, ok := v.(bool)
	if !ok {
		p.errf(join(path, key), "must be a boolean")
	}
	return b
}

func (p *parser) strList(path string, m map[string]any, key string) []string {
	v, ok := m[key]
	if !ok || v == nil {
		return nil
	}
	l, ok := v.([]any)
	if !ok {
		p.errf(join(path, key), "must be a list of strings")
		return nil
	}
	out := make([]string, 0, len(l))
	for i, x := range l {
		s, ok := x.(string)
		if !ok {
			p.errf(fmt.Sprintf("%s[%d]", join(path, key), i), "must be a string")
			continue
		}
		out = append(out, s)
	}
	return out
}

func (p *parser) strMap(path string, m map[string]any, key string) map[string]string {
	v, ok := m[key]
	if !ok || v == nil {
		return nil
	}
	mm, ok := v.(map[string]any)
	if !ok {
		p.errf(join(path, key), "must be a map of strings")
		return nil
	}
	out := map[string]string{}
	for _, k := range sortedKeys(mm) {
		s, ok := mm[k].(string)
		if !ok {
			p.errf(join(join(path, key), k), "must be a string")
			continue
		}
		out[k] = s
	}
	return out
}

func (p *parser) schemas(path string, m map[string]any, key string) map[string]Schema {
	v, ok := m[key]
	if !ok || v == nil {
		return nil
	}
	mm, ok := v.(map[string]any)
	if !ok {
		p.errf(join(path, key), "must be a map of names to JSON Schemas")
		return nil
	}
	out := map[string]Schema{}
	for _, k := range sortedKeys(mm) {
		kp := join(join(path, key), k)
		if !nameRe.MatchString(k) {
			p.errf(kp, "name must match %s", nameRe)
		}
		s, ok := mm[k].(map[string]any)
		if !ok {
			p.errf(kp, "must be a JSON Schema object")
			continue
		}
		out[k] = s
	}
	return out
}

func (p *parser) template(doc any) *Template {
	t := &Template{}
	m := p.object("", doc, "id", "version", "description", "inputs", "outputs", "produces", "recursion", "roles", "stages")
	if m == nil {
		return t
	}
	t.ID = p.str("", m, "id", true)
	if t.ID != "" && !idRe.MatchString(t.ID) {
		p.errf("id", "must match %s", idRe)
	}
	switch v := m["version"].(type) {
	case nil:
	case string:
		t.Version = v
	case int64:
		t.Version = fmt.Sprint(v)
	case float64:
		t.Version = fmt.Sprint(v)
	default:
		p.errf("version", "must be a string or a number")
	}
	p.str("", m, "description", false)
	t.Produces = p.str("", m, "produces", false)
	if t.Produces != "" && t.Produces != "artifacts" {
		p.errf("produces", "must be \"artifacts\" (the emulator produces no commits)")
	}
	t.Inputs = p.schemas("", m, "inputs")
	t.Outputs = p.schemas("", m, "outputs")
	if r, ok := m["recursion"]; ok && r != nil {
		rm := p.object("recursion", r, "max_depth", "max_descendants", "max_children_per_visit")
		if rm != nil {
			t.Recursion = &Recursion{
				MaxDepth:            p.integer("recursion", rm, "max_depth", 0),
				MaxDescendants:      p.integer("recursion", rm, "max_descendants", 0),
				MaxChildrenPerVisit: p.integer("recursion", rm, "max_children_per_visit", 0),
			}
			switch {
			case t.Recursion.MaxDepth < 1:
				p.errf("recursion.max_depth", "is required and must be at least 1")
			case t.Recursion.MaxDepth > DepthCeiling:
				p.errf("recursion.max_depth", "%d exceeds the instance ceiling %d", t.Recursion.MaxDepth, DepthCeiling)
			}
			if t.Recursion.MaxDescendants < 0 {
				p.errf("recursion.max_descendants", "must not be negative")
			}
			if t.Recursion.MaxChildrenPerVisit < 0 {
				p.errf("recursion.max_children_per_visit", "must not be negative")
			}
		}
	}
	if r, ok := m["roles"]; ok && r != nil {
		rm, ok := r.(map[string]any)
		if !ok {
			p.errf("roles", "must be a map of role names to {cap, cap_scope}")
		}
		t.Roles = map[string]Role{}
		for _, name := range sortedKeys(rm) {
			path := "roles." + name
			om := p.object(path, rm[name], "cap", "cap_scope")
			if om == nil {
				continue
			}
			role := Role{Cap: p.integer(path, om, "cap", 0), CapScope: p.str(path, om, "cap_scope", false)}
			if role.CapScope == "" {
				role.CapScope = ScopeWorkflow
			}
			if role.Cap < 0 {
				p.errf(path+".cap", "must not be negative (0 means uncapped)")
			}
			switch role.CapScope {
			case ScopeWorkflow, ScopeTree, ScopeTask:
			default:
				p.errf(path+".cap_scope", "must be workflow, tree or task")
			}
			t.Roles[name] = role
		}
	}
	t.Stages = p.stages("stages", m["stages"], false)
	if len(t.Stages) == 0 {
		if _, ok := m["stages"]; !ok {
			p.errf("stages", "is required")
		}
	}
	return t
}

func (p *parser) stages(path string, v any, inBranch bool) []*Stage {
	if v == nil {
		return nil
	}
	l, ok := v.([]any)
	if !ok {
		p.errf(path, "must be a list of stages")
		return nil
	}
	var out []*Stage
	for i, x := range l {
		if s := p.stage(fmt.Sprintf("%s[%d]", path, i), x, inBranch); s != nil {
			out = append(out, s)
		}
	}
	return out
}

var kindFields = map[string][]string{
	KindAgentTurn:     {"role", "brief", "inputs", "output", "tools", "model", "budget"},
	KindFanout:        {"branches_from", "max_branches", "parallel", "join", "output", "branch"},
	KindSubworkflow:   {"workflow", "inputs", "outputs"},
	KindGate:          {"expr", "inputs"},
	KindCommand:       {"argv", "inputs", "output"},
	KindChangeRequest: {"target", "from", "artifact"},
}

func (p *parser) stage(path string, v any, inBranch bool) *Stage {
	raw, ok := v.(map[string]any)
	if !ok {
		p.errf(path, "must be an object")
		return nil
	}
	s := &Stage{Path: path}
	s.Kind, _ = raw["kind"].(string)
	fields, known := kindFields[s.Kind]
	if !known {
		if raw["kind"] == nil {
			p.errf(path+".kind", "is required")
		} else {
			p.errf(path+".kind", "unknown kind %v (want agent_turn, fanout, subworkflow, gate, command or change_request)", raw["kind"])
		}
		fields = nil
		for _, f := range kindFields {
			fields = append(fields, f...)
		}
	}
	m := p.object(path, raw, append([]string{"id", "kind", "after", "on_fail", "description"}, fields...)...)
	s.ID = p.str(path, m, "id", true)
	if s.ID != "" && !idRe.MatchString(s.ID) {
		p.errf(path+".id", "must match %s (no dots: task ids use them)", idRe)
	}
	p.str(path, m, "description", false)
	s.After = p.strList(path, m, "after")
	s.OnFail = p.str(path, m, "on_fail", false)
	switch s.Kind {
	case KindAgentTurn:
		s.Role = p.str(path, m, "role", true)
		s.Brief = p.str(path, m, "brief", true)
		s.Bindings = p.strList(path, m, "inputs")
		s.Tools = p.strList(path, m, "tools")
		s.Model = p.str(path, m, "model", false)
		s.Budget = p.budget(path+".budget", m["budget"])
		if om := p.object(path+".output", m["output"], "name", "schema"); om != nil {
			s.Output = &OutputSpec{Name: p.str(path+".output", om, "name", true)}
			if sc, ok := om["schema"].(map[string]any); ok {
				s.Output.Schema = sc
			} else {
				p.errf(path+".output.schema", "is required and must be a JSON Schema object")
			}
		}
	case KindFanout:
		if inBranch {
			p.errf(path, "a fanout branch can't contain a fanout")
		}
		s.BranchesFrom = p.str(path, m, "branches_from", true)
		s.MaxBranches = p.integer(path, m, "max_branches", DefaultMaxBranches)
		if s.MaxBranches < 1 || s.MaxBranches > MaxBranchesBound {
			p.errf(path+".max_branches", "must be between 1 and %d", MaxBranchesBound)
		}
		s.Parallel = p.boolean(path, m, "parallel")
		s.Join = p.join(path+".join", m["join"])
		s.JoinOutput = p.str(path, m, "output", false)
		if s.JoinOutput == "" {
			s.JoinOutput = s.ID
		}
		if bm := p.object(path+".branch", m["branch"], "stages", "output"); bm != nil {
			s.Branch = &Branch{Output: p.str(path+".branch", bm, "output", false)}
			s.Branch.Stages = p.stages(path+".branch.stages", bm["stages"], true)
			if len(s.Branch.Stages) == 0 {
				p.errf(path+".branch.stages", "must list at least one stage")
			}
		}
	case KindSubworkflow:
		s.Workflow = p.str(path, m, "workflow", true)
		s.InputMap = p.strMap(path, m, "inputs")
		s.OutputMap = p.strMap(path, m, "outputs")
	case KindGate:
		s.Expr = p.str(path, m, "expr", true)
		s.Bindings = p.strList(path, m, "inputs")
		if s.Expr != "" {
			if _, err := gateEnv.compile(s.Expr); err != nil {
				p.errf(path+".expr", "%v", err)
			}
		}
	case KindCommand:
		s.Argv = p.strList(path, m, "argv")
		if len(s.Argv) == 0 {
			p.errf(path+".argv", "is required and must not be empty")
		}
		s.Bindings = p.strList(path, m, "inputs")
		s.CmdOutput = p.str(path, m, "output", false)
		if s.CmdOutput == "" {
			s.CmdOutput = s.ID
		}
	case KindChangeRequest:
		s.Target = p.str(path, m, "target", true)
		s.From = p.str(path, m, "from", true)
		s.TargetArtifact = p.str(path, m, "artifact", false)
	}
	return s
}

// budget parses {max_turns, timeout_min}; timeout_min may be fractional.
func (p *parser) budget(path string, v any) *Budget {
	if v == nil {
		return nil
	}
	m := p.object(path, v, "max_turns", "timeout_min")
	if m == nil {
		return nil
	}
	b := &Budget{MaxTurns: p.integer(path, m, "max_turns", 0)}
	if _, ok := m["max_turns"]; ok && b.MaxTurns < 1 {
		p.errf(path+".max_turns", "must be at least 1")
	}
	switch x := m["timeout_min"].(type) {
	case nil:
	case int64:
		b.Timeout = time.Duration(x) * time.Minute
	case float64:
		b.Timeout = time.Duration(x * float64(time.Minute))
	default:
		p.errf(path+".timeout_min", "must be a number of minutes")
	}
	if _, ok := m["timeout_min"]; ok && b.Timeout <= 0 {
		p.errf(path+".timeout_min", "must be positive")
	}
	if len(m) == 0 {
		p.errf(path, "must give max_turns or timeout_min")
	}
	return b
}

func (p *parser) join(path string, v any) Join {
	switch t := v.(type) {
	case nil:
		return Join{Mode: "all"}
	case string:
		if t == "all" || t == "any" {
			return Join{Mode: t}
		}
	case map[string]any:
		if m := p.object(path, t, "k"); m != nil {
			k := p.integer(path, m, "k", 0)
			if k < 1 {
				p.errf(path+".k", "must be at least 1")
			}
			return Join{Mode: "k", K: k}
		}
		return Join{Mode: "all"}
	}
	p.errf(path, "must be all, any or {k: N}")
	return Join{Mode: "all"}
}

// produced returns the artifact names a stage records.
func (s *Stage) produced() []string {
	switch s.Kind {
	case KindAgentTurn:
		if s.Output != nil && s.Output.Name != "" {
			return []string{s.Output.Name}
		}
	case KindFanout:
		return []string{s.JoinOutput}
	case KindSubworkflow:
		return sortedKeys(s.OutputMap)
	case KindCommand:
		return []string{s.CmdOutput}
	}
	return nil
}

// refHead returns the artifact a reference "name.path..." reads, or "" for
// a CEL expression.
func refHead(ref string) string {
	if strings.HasPrefix(ref, "=") {
		return ""
	}
	head, _, _ := strings.Cut(ref, ".")
	return head
}

func textRefs(s string) []string {
	var out []string
	for _, m := range artRefRe.FindAllStringSubmatch(s, -1) {
		out = append(out, m[1])
	}
	for _, m := range artIndexRe.FindAllStringSubmatch(s, -1) {
		out = append(out, m[1])
	}
	return out
}

// reads returns the artifact names a stage reads, from its bindings, its
// references and the artifacts its text and expressions mention.
func (s *Stage) reads() []string {
	set := map[string]bool{}
	add := func(names ...string) {
		for _, n := range names {
			if n != "" {
				set[n] = true
			}
		}
	}
	add(s.Bindings...)
	add(textRefs(s.Brief)...)
	add(textRefs(s.Expr)...)
	for _, a := range s.Argv {
		add(textRefs(a)...)
	}
	switch s.Kind {
	case KindFanout:
		add(refHead(s.BranchesFrom))
		add(textRefs(s.BranchesFrom)...)
	case KindSubworkflow:
		for _, k := range sortedKeys(s.InputMap) {
			add(refHead(s.InputMap[k]))
			add(textRefs(s.InputMap[k])...)
		}
	case KindChangeRequest:
		add(refHead(s.From))
		add(textRefs(s.From)...)
	}
	return sortedKeys(set)
}

// check runs the graph checks over a parsed template.
func (p *parser) check(t *Template, resolve Resolver) {
	outer := map[string]string{} // artifact -> producer ("input:x" for inputs)
	for name := range t.Inputs {
		outer[name] = "input:" + name
	}
	p.scope(t, t.Stages, outer, false, resolve)
	top := producers(t.Stages)
	for _, name := range sortedKeys(t.Outputs) {
		if _, ok := top[name]; !ok && t.Inputs[name] == nil {
			p.errf("outputs."+name, "no top-level stage produces %q", name)
		}
	}
	if resolve != nil {
		p.mutualRecursion(t, resolve)
	}
}

func producers(stages []*Stage) map[string]*Stage {
	out := map[string]*Stage{}
	for _, s := range stages {
		for _, n := range s.produced() {
			if _, dup := out[n]; !dup {
				out[n] = s
			}
		}
	}
	return out
}

// handlers returns the stage ids named by on_fail routes in a scope.
func handlers(stages []*Stage) map[string]bool {
	out := map[string]bool{}
	for _, s := range stages {
		if s.OnFail != "" && s.OnFail != "fail" {
			out[s.OnFail] = true
		}
	}
	return out
}

func (p *parser) scope(t *Template, stages []*Stage, outer map[string]string, inBranch bool, resolve Resolver) {
	ids := map[string]*Stage{}
	for _, s := range stages {
		if s.ID == "" {
			continue
		}
		if _, dup := ids[s.ID]; dup {
			p.errf(s.Path+".id", "duplicate stage id %q", s.ID)
		}
		ids[s.ID] = s
	}
	hs := handlers(stages)
	prod := map[string]*Stage{}
	for _, s := range stages {
		for _, n := range s.produced() {
			if !nameRe.MatchString(n) {
				p.errf(s.Path, "artifact name %q must match %s", n, nameRe)
			}
			if n == "item" || n == "failure" {
				p.errf(s.Path, "artifact name %q is reserved", n)
			}
			if prev, dup := prod[n]; dup && !hs[s.ID] && !hs[prev.ID] {
				p.errf(s.Path, "artifact %q is also produced by stage %q", n, prev.ID)
			}
			if _, ok := outer[n]; ok && !strings.HasPrefix(outer[n], "input:") {
				p.errf(s.Path, "artifact %q shadows one produced outside the branch", n)
			}
			if _, ok := prod[n]; !ok {
				prod[n] = s
			}
		}
	}
	for _, s := range stages {
		for _, a := range s.After {
			if _, ok := ids[a]; !ok {
				p.errf(s.Path+".after", "no stage %q in this scope", a)
			}
		}
		if s.OnFail != "" && s.OnFail != "fail" {
			if s.OnFail == s.ID {
				p.errf(s.Path+".on_fail", "a stage can't route to itself")
			} else if _, ok := ids[s.OnFail]; !ok {
				p.errf(s.Path+".on_fail", "no stage %q in this scope (want fail or a stage id)", s.OnFail)
			}
		}
		var deps []string
		for _, r := range s.reads() {
			switch {
			case r == "item" && inBranch:
			case r == "failure" && hs[s.ID]:
			case prod[r] != nil:
				if prod[r] == s {
					p.errf(s.Path, "stage reads its own output %q", r)
				}
			case outer[r] != "":
			default:
				p.errf(s.Path, "binding %q: no input or stage produces it", r)
			}
			deps = append(deps, r)
		}
		s.deps = deps
		if s.Kind == KindAgentTurn && s.Role != "" {
			if _, ok := t.Roles[s.Role]; !ok {
				p.errf(s.Path+".role", "role %q is not declared in roles", s.Role)
			}
		}
		if s.Kind == KindChangeRequest && s.Target == "" {
			p.errf(s.Path+".target", "is required (parent or a task id)")
		}
		if s.Kind == KindSubworkflow {
			p.subworkflow(t, s, resolve)
		}
		if s.Kind == KindFanout && s.Branch != nil {
			inner := map[string]string{}
			for k, v := range outer {
				inner[k] = v
			}
			for n, ps := range prod {
				inner[n] = ps.ID
			}
			p.scope(t, s.Branch.Stages, inner, true, resolve)
			// A fanout waits for everything its branches read from outside.
			bprod := producers(s.Branch.Stages)
			for _, bs := range s.Branch.Stages {
				for _, r := range bs.deps {
					if bprod[r] == nil && r != "item" && r != "failure" {
						s.deps = appendUnique(s.deps, r)
					}
				}
			}
			names := sortedKeys(bprod)
			switch {
			case s.Branch.Output != "":
				if bprod[s.Branch.Output] == nil {
					p.errf(s.Path+".branch.output", "no branch stage produces %q", s.Branch.Output)
				}
			case len(names) == 1:
				s.Branch.Output = names[0]
			case len(names) == 0:
				p.errf(s.Path+".branch", "branch stages produce no artifact to join")
			default:
				p.errf(s.Path+".branch.output", "is required: the branch produces %s", strings.Join(names, ", "))
			}
		}
	}
	p.cycles(stages, prod)
}

func appendUnique(l []string, s string) []string {
	for _, x := range l {
		if x == s {
			return l
		}
	}
	return append(l, s)
}

func (p *parser) cycles(stages []*Stage, prod map[string]*Stage) {
	ids := map[string]*Stage{}
	for _, s := range stages {
		ids[s.ID] = s
	}
	edges := func(s *Stage) []*Stage {
		var out []*Stage
		for _, d := range s.deps {
			if ps := prod[d]; ps != nil && ps != s {
				out = append(out, ps)
			}
		}
		for _, a := range s.After {
			if ps := ids[a]; ps != nil {
				out = append(out, ps)
			}
		}
		return out
	}
	const (
		white = iota
		grey
		black
	)
	color := map[*Stage]int{}
	var visit func(s *Stage) bool
	visit = func(s *Stage) bool {
		color[s] = grey
		for _, n := range edges(s) {
			if color[n] == grey {
				p.errf(s.Path, "dependency cycle through stage %q", n.ID)
				return true
			}
			if color[n] == white && visit(n) {
				return true
			}
		}
		color[s] = black
		return false
	}
	for _, s := range stages {
		if color[s] == white {
			visit(s)
		}
	}
}

func (p *parser) subworkflow(t *Template, s *Stage, resolve Resolver) {
	var child *Template
	switch {
	case s.Workflow == "self" || s.Workflow == t.ID:
		if t.Recursion == nil {
			p.errf(s.Path+".workflow", "a template that selects itself must declare recursion: {max_depth, ...}")
		}
		child = t
	case resolve != nil && s.Workflow != "":
		c, err := resolve(s.Workflow)
		if err != nil {
			p.errf(s.Path+".workflow", "%v", err)
			return
		}
		child = c
	default:
		return
	}
	for _, name := range sortedKeys(child.Inputs) {
		if _, ok := s.InputMap[name]; !ok && !hasDefault(child.Inputs[name]) {
			p.errf(s.Path+".inputs", "required input %q of workflow %s is not mapped", name, child.ID)
		}
	}
	for _, name := range sortedKeys(s.InputMap) {
		if _, ok := child.Inputs[name]; !ok {
			p.errf(s.Path+".inputs."+name, "workflow %s declares no input %q", child.ID, name)
		}
	}
	for _, art := range sortedKeys(s.OutputMap) {
		if _, ok := child.Outputs[s.OutputMap[art]]; !ok {
			p.errf(s.Path+".outputs."+art, "workflow %s declares no output %q", child.ID, s.OutputMap[art])
		}
	}
}

func hasDefault(s Schema) bool {
	_, ok := s["default"]
	return ok
}

// subworkflowIDs lists the workflow ids a template's subworkflow stages
// select, other than itself.
func subworkflowIDs(t *Template) []string {
	set := map[string]bool{}
	var walk func([]*Stage)
	walk = func(stages []*Stage) {
		for _, s := range stages {
			if s.Kind == KindSubworkflow && s.Workflow != "self" && s.Workflow != t.ID && s.Workflow != "" {
				set[s.Workflow] = true
			}
			if s.Branch != nil {
				walk(s.Branch.Stages)
			}
		}
	}
	walk(t.Stages)
	return sortedKeys(set)
}

// mutualRecursion refuses a cycle of templates unless each declares a
// recursion budget (FAE-WF-098).
func (p *parser) mutualRecursion(t *Template, resolve Resolver) {
	seen := map[string]*Template{t.ID: t}
	var path []string
	onPath := map[string]bool{}
	var visit func(x *Template)
	visit = func(x *Template) {
		path = append(path, x.ID)
		onPath[x.ID] = true
		for _, id := range subworkflowIDs(x) {
			if onPath[id] {
				i := 0
				for path[i] != id {
					i++
				}
				cycle := append(append([]string{}, path[i:]...), id)
				for _, cid := range path[i:] {
					if seen[cid].Recursion == nil {
						p.errf("stages", "mutual recursion %s: workflow %s declares no recursion budget", strings.Join(cycle, " -> "), cid)
						break
					}
				}
				continue
			}
			if seen[id] != nil {
				continue
			}
			c, err := resolve(id)
			if err != nil {
				continue // reported by the stage check
			}
			seen[id] = c
			visit(c)
		}
		onPath[x.ID] = false
		path = path[:len(path)-1]
	}
	visit(t)
}

// DirResolver resolves workflow ids to the templates in dir (*.yaml, *.yml,
// *.json), plus the given templates.
func DirResolver(dir string, known ...*Template) Resolver {
	var (
		mu     sync.Mutex
		loaded bool
		byID   = map[string]*Template{}
		errs   = map[string]error{}
	)
	for _, k := range known {
		byID[k.ID] = k
	}
	return func(id string) (*Template, error) {
		mu.Lock()
		defer mu.Unlock()
		if t := byID[id]; t != nil {
			return t, nil
		}
		if !loaded {
			loaded = true
			entries, _ := os.ReadDir(dir)
			for _, e := range entries {
				ext := filepath.Ext(e.Name())
				if e.IsDir() || (ext != ".yaml" && ext != ".yml" && ext != ".json") {
					continue
				}
				t, err := LoadFile(filepath.Join(dir, e.Name()))
				if t == nil || t.ID == "" {
					continue
				}
				if _, dup := byID[t.ID]; dup {
					continue
				}
				if err != nil {
					errs[t.ID] = err
					continue
				}
				byID[t.ID] = t
			}
		}
		if t := byID[id]; t != nil {
			return t, nil
		}
		if err := errs[id]; err != nil {
			return nil, fmt.Errorf("workflow %s is invalid: %v", id, err)
		}
		return nil, fmt.Errorf("no template with id %q in %s", id, dir)
	}
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
