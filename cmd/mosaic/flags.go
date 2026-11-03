package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// stdin is read by "-f -". Tests replace it.
var stdin io.Reader = os.Stdin

// stringList is a repeatable string flag.
type stringList []string

func (l *stringList) String() string { return strings.Join(*l, ", ") }
func (l *stringList) Set(v string) error {
	*l = append(*l, v)
	return nil
}

// choiceFlag is the repeatable --choice KEY=OPTION.
type choiceFlag map[string]string

func (c choiceFlag) String() string { return "" }
func (c choiceFlag) Set(v string) error {
	key, option, ok := strings.Cut(v, "=")
	key, option = strings.TrimSpace(key), strings.TrimSpace(option)
	if !ok || key == "" || option == "" {
		return fmt.Errorf("want KEY=OPTION, such as throttle.check.rate_limit=limited; got %q", v)
	}
	if prev, dup := c[key]; dup && prev != option {
		return fmt.Errorf("choice %s is given twice (%s and %s)", key, prev, option)
	}
	c[key] = option
	return nil
}

// stateFlag is the repeatable --state COMPONENT.PATH=VALUE. It builds nested
// maps under each component. VALUE is parsed as JSON and falls back to a string.
type stateFlag map[string]map[string]any

func (s stateFlag) String() string { return "" }
func (s stateFlag) Set(v string) error {
	key, raw, ok := strings.Cut(v, "=")
	if !ok {
		return fmt.Errorf("want COMPONENT.PATH=VALUE, such as redis-ledger.free_slots=0; got %q", v)
	}
	comp, path, hasPath := strings.Cut(strings.TrimSpace(key), ".")
	if comp == "" {
		return fmt.Errorf("%q: missing the component id before the first dot", v)
	}
	val := parseValue(raw)
	root := s[comp]
	if root == nil {
		root = map[string]any{}
	}
	if !hasPath {
		obj, isObj := val.(map[string]any)
		if !isObj {
			return fmt.Errorf("%q: without a path after %s, VALUE must be a JSON object", v, comp)
		}
		for k, x := range obj {
			root[k] = x
		}
		s[comp] = root
		return nil
	}
	segs := strings.Split(path, ".")
	m := root
	for i, seg := range segs {
		if seg == "" {
			return fmt.Errorf("%q: empty path segment", v)
		}
		if i == len(segs)-1 {
			m[seg] = val
			break
		}
		switch next := m[seg].(type) {
		case map[string]any:
			m = next
		case nil:
			n := map[string]any{}
			m[seg] = n
			m = n
		default:
			return fmt.Errorf("%q: %s.%s is already set to a value that is not an object", v, comp, strings.Join(segs[:i+1], "."))
		}
	}
	s[comp] = root
	return nil
}

// topologyFlag is the repeatable --topology COMPONENT=INSTANCE,INSTANCE,...
// (§11.1). A later entry for the same component replaces the earlier one.
type topologyFlag map[string][]string

func (t topologyFlag) String() string { return "" }
func (t topologyFlag) Set(v string) error {
	comp, list, ok := strings.Cut(v, "=")
	comp = strings.TrimSpace(comp)
	if !ok || comp == "" {
		return fmt.Errorf("want COMPONENT=INSTANCE,INSTANCE,..., such as cassandra-node=n1,n2,n3; got %q", v)
	}
	var names []string
	for _, n := range strings.Split(list, ",") {
		n = strings.TrimSpace(n)
		if n == "" {
			return fmt.Errorf("%q: empty instance name", v)
		}
		if slices.Contains(names, n) {
			return fmt.Errorf("%q: instance %s is listed twice", v, n)
		}
		names = append(names, n)
	}
	t[comp] = names
	return nil
}

// resolutionFlag is the repeatable --resolution COMPONENT=refined|black_box
// (§14.5, §14.11).
type resolutionFlag map[string]string

func (r resolutionFlag) String() string { return "" }
func (r resolutionFlag) Set(v string) error {
	comp, res, ok := strings.Cut(v, "=")
	comp, res = strings.TrimSpace(comp), strings.TrimSpace(res)
	if !ok || comp == "" || (res != model.ResolutionRefined && res != model.ResolutionBlackBox) {
		return fmt.Errorf("want COMPONENT=refined or COMPONENT=black_box, such as engine=refined; got %q", v)
	}
	r[comp] = res
	return nil
}

// configFlag is the repeatable --config ID=VALUE (§11.6). VALUE is parsed as
// JSON and falls back to a string.
type configFlag map[string]any

func (c configFlag) String() string { return "" }
func (c configFlag) Set(v string) error {
	id, raw, ok := strings.Cut(v, "=")
	id = strings.TrimSpace(id)
	if !ok || id == "" {
		return fmt.Errorf("want ID=VALUE, such as write-request-timeout-ms=500; got %q", v)
	}
	c[id] = parseValue(raw)
	return nil
}

// parseClockEpoch reads --clock-epoch: an RFC 3339 time, or whole
// milliseconds since the Unix epoch (§11.3).
func parseClockEpoch(s string) (*model.Clock, error) {
	s = strings.TrimSpace(s)
	if ms, err := strconv.ParseInt(s, 10, 64); err == nil {
		return &model.Clock{EpochMS: ms}, nil
	}
	c := &model.Clock{Epoch: s}
	if _, err := c.EpochMillis(); err != nil {
		return nil, usageErrorf("--clock-epoch: want an RFC 3339 time such as 2026-10-30T00:00:00Z or milliseconds; got %q", s)
	}
	return c, nil
}

// parseValue parses s as JSON (numbers keep their text) or returns it as a string.
func parseValue(s string) any {
	var v any
	if err := model.Decode([]byte(s), &v); err == nil {
		return v
	}
	return s
}

// faultFlag is the repeatable --fault, in JSON or compact form.
type faultFlag []model.Fault

func (f *faultFlag) String() string { return "" }
func (f *faultFlag) Set(v string) error {
	ft, err := parseFault(v)
	if err != nil {
		return err
	}
	*f = append(*f, ft)
	return nil
}

const faultForm = "TARGET:TYPE[:CODE[:STATUS]][@N,M], TARGET:crash:AFTER_STEPS[@N,M], COMPONENT:kill:AT_MS[:INSTANCE] or a JSON object"

// parseFault parses a fault given as a JSON object (starting with '{') or in
// the compact form TARGET:TYPE[:CODE[:STATUS]][@N,M], where @ lists the
// 1-based invocations of the target that fail. For type latency the third
// field is the added latency in milliseconds: TARGET:latency:MS[@N,M].
func parseFault(s string) (model.Fault, error) {
	s = strings.TrimSpace(s)
	var f model.Fault
	if strings.HasPrefix(s, "{") {
		if err := model.Decode([]byte(s), &f); err != nil {
			return f, fmt.Errorf("invalid fault JSON %s: %v", s, err)
		}
		return f, checkFault(s, f)
	}
	spec := s
	if i := strings.LastIndex(s, "@"); i >= 0 {
		spec = s[:i]
		list := strings.TrimSpace(s[i+1:])
		if list == "" {
			return f, fmt.Errorf("fault %q: @ must be followed by call numbers, such as @1,2", s)
		}
		for _, p := range strings.Split(list, ",") {
			n, err := strconv.Atoi(strings.TrimSpace(p))
			if err != nil || n < 1 {
				return f, fmt.Errorf("fault %q: call numbers are integers from 1, got %q", s, p)
			}
			f.Calls = append(f.Calls, n)
		}
	}
	parts := strings.Split(spec, ":")
	if len(parts) < 2 || len(parts) > 4 {
		return f, fmt.Errorf("fault %q: want %s", s, faultForm)
	}
	f.Target, f.Type = strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
	if f.Type == "kill" {
		if len(parts) < 3 || len(f.Calls) > 0 {
			return f, fmt.Errorf("fault %q: a kill fault is COMPONENT:kill:AT_MS[:INSTANCE]", s)
		}
		at, err := strconv.ParseFloat(strings.TrimSpace(parts[2]), 64)
		if err != nil || at < 0 {
			return f, fmt.Errorf("fault %q: kill time must be milliseconds, got %q", s, parts[2])
		}
		f.AtMS = &at
		if len(parts) == 4 {
			f.Instance = strings.TrimSpace(parts[3])
		}
		return f, checkFault(s, f)
	}
	if f.Type == model.FaultCrash {
		if len(parts) != 3 {
			return f, fmt.Errorf("fault %q: a crash fault is TARGET:crash:AFTER_STEPS[@N,M]", s)
		}
		n, err := strconv.Atoi(strings.TrimSpace(parts[2]))
		if err != nil || n < 0 {
			return f, fmt.Errorf("fault %q: after_steps must be a whole number from 0, got %q", s, parts[2])
		}
		f.AfterSteps = &n
		return f, checkFault(s, f)
	}
	if f.Type == "latency" {
		if len(parts) > 3 {
			return f, fmt.Errorf("fault %q: a latency fault is TARGET:latency:MS[@N,M]", s)
		}
		if len(parts) == 3 {
			ms, err := strconv.ParseInt(strings.TrimSpace(parts[2]), 10, 64)
			if err != nil {
				return f, fmt.Errorf("fault %q: latency must be whole milliseconds, got %q", s, parts[2])
			}
			f.LatencyMS = float64(ms)
		}
		return f, checkFault(s, f)
	}
	if len(parts) >= 3 {
		f.Code = strings.TrimSpace(parts[2])
	}
	if len(parts) == 4 {
		st, err := strconv.Atoi(strings.TrimSpace(parts[3]))
		if err != nil {
			return f, fmt.Errorf("fault %q: status must be an HTTP status code, got %q", s, parts[3])
		}
		f.Status = st
	}
	return f, checkFault(s, f)
}

func checkFault(s string, f model.Fault) error {
	switch {
	case f.Target == "":
		return fmt.Errorf("fault %q: missing target (a component or interface id)", s)
	case f.Type == "kill":
		if f.AtMS == nil {
			return fmt.Errorf("fault %q: a kill fault needs a time (COMPONENT:kill:AT_MS or \"at_ms\")", s)
		}
	case !slices.Contains(model.FaultTypes, f.Type):
		return fmt.Errorf("fault %q: type must be one of %s, got %q", s, strings.Join(model.FaultTypes, ", "), f.Type)
	case f.Status != 0 && (f.Status < 100 || f.Status > 599):
		return fmt.Errorf("fault %q: status %d is not an HTTP status code", s, f.Status)
	case f.Type == "latency" && f.LatencyMS <= 0:
		return fmt.Errorf("fault %q: a latency fault needs a positive latency (TARGET:latency:MS or \"latency_ms\")", s)
	case f.Type == model.FaultCrash && (f.AfterSteps == nil || *f.AfterSteps < 0):
		return fmt.Errorf("fault %q: a crash fault needs after_steps from 0 (TARGET:crash:AFTER_STEPS or \"after_steps\")", s)
	case f.Type != model.FaultCrash && f.AfterSteps != nil:
		return fmt.Errorf("fault %q: after_steps goes with a crash fault", s)
	}
	for _, n := range f.Calls {
		if n < 1 {
			return fmt.Errorf("fault %q: call numbers start at 1", s)
		}
	}
	return nil
}

// int64Flag records whether it was set.
type int64Flag struct {
	v   int64
	set bool
}

func (i *int64Flag) String() string {
	if !i.set {
		return ""
	}
	return strconv.FormatInt(i.v, 10)
}
func (i *int64Flag) Set(s string) error {
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return fmt.Errorf("want an integer, got %q", s)
	}
	i.v, i.set = n, true
	return nil
}

// readInput reads FILE ("-" is stdin) and converts YAML or JSON to JSON.
func readInput(path string) (json.RawMessage, error) {
	var data []byte
	var err error
	if path == "-" {
		data, err = io.ReadAll(stdin)
	} else {
		data, err = os.ReadFile(path)
	}
	if err != nil {
		return nil, inputErrorf("%v", err)
	}
	name := path
	if path == "-" {
		name = "stdin"
	}
	return toJSON(name, data)
}

func toJSON(name string, data []byte) (json.RawMessage, error) {
	if len(strings.TrimSpace(string(data))) == 0 {
		return nil, inputErrorf("%s is empty", name)
	}
	js, err := model.ToJSON(data)
	if err != nil {
		return nil, inputErrorf("%s: %v", name, err)
	}
	if !json.Valid(js) {
		var v any
		err := json.Unmarshal(js, &v)
		return nil, inputErrorf("%s: invalid JSON: %v", name, err)
	}
	return js, nil
}

// parseInputFlag parses --input: inline JSON, or @FILE holding YAML or JSON.
func parseInputFlag(s string) (json.RawMessage, error) {
	if path, ok := strings.CutPrefix(s, "@"); ok {
		if path == "" {
			return nil, inputErrorf("--input @FILE: missing file name")
		}
		return readInput(path)
	}
	js := []byte(strings.TrimSpace(s))
	if !json.Valid(js) {
		var v any
		err := json.Unmarshal(js, &v)
		return nil, inputErrorf("--input: invalid JSON (%v); pass @FILE for YAML", err)
	}
	return js, nil
}

// specSource reads the -f FILE or --json JSON pair that put and patch take.
func specSource(file, inline string) (json.RawMessage, error) {
	switch {
	case file != "" && inline != "":
		return nil, usageErrorf("give either -f FILE or --json JSON, not both")
	case file != "":
		return readInput(file)
	case inline != "":
		return toJSON("--json", []byte(inline))
	}
	return nil, usageErrorf("missing -f FILE or --json JSON")
}

// checkRev accepts draft, latest, a revision number, or "" (the server default).
func checkRev(flagName, r string) error {
	if r == "" || r == "draft" || r == "latest" {
		return nil
	}
	if n, err := strconv.Atoi(r); err == nil && n >= 1 {
		return nil
	}
	return usageErrorf("--%s must be draft, latest or a revision number, got %q", flagName, r)
}

// parseFlags parses flags that may appear before, between or after
// positional arguments. "--" ends flag parsing.
func parseFlags(fs *flag.FlagSet, args []string) ([]string, error) {
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			if err == flag.ErrHelp {
				return nil, err
			}
			return nil, usageErrorf("%v", err)
		}
		rest := fs.Args()
		if len(rest) == 0 {
			return pos, nil
		}
		consumed := args[:len(args)-len(rest)]
		if len(consumed) > 0 && consumed[len(consumed)-1] == "--" {
			return append(pos, rest...), nil
		}
		pos = append(pos, rest[0])
		args = rest[1:]
	}
}
