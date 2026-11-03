package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Contract conformance beyond OpenAPI (DESIGN §13.1 item 34).
//
// --contract FILE (repeatable) reads contracts: [{id, match, request,
// response, errors, stream, sources}] written from the code in the repo's
// prep (zod and tRPC routers, SSE emitters, event schemas) and compares the
// interfaces each one matches, reusing the OpenAPI comparison (item 21,
// conformance.go):
//
//   - match: {interface: <id or glob>}, {route: {method, path}} (path
//     parameter names are ignored, ANY matches every method) or
//     {attributes: {k: v}} (every listed attribute equal, case-insensitive).
//     A route or attribute match never selects a client wrapper. Every
//     matched interface is compared; a contract matching none is unmodeled.
//   - request: a JSON Schema. When it has a "body" property it is an
//     envelope: body is the request body, the properties of "query" are
//     query parameters, the other properties top-level fields. Otherwise it
//     is the body, compared against the model's "body" or, without one,
//     against the request's top-level fields. "authorization" and x_*
//     headers are ambient, as in item 21. Without request, nothing is
//     compared.
//   - response: a JSON Schema; one with a "body" property is an envelope
//     whose status const or enum pins the success status. It is compared
//     against the model's envelope body (or the whole response without one).
//   - errors: [{code, status}]. Each must be declared by the interface,
//     raised by its fail steps or reachable through its calls, matched by
//     status, or by code when the entry has no status. Each error the
//     interface declares must be listed (by status or code), except a 500
//     the contract doesn't list. Without errors, nothing is compared;
//     errors: [] means none.
//   - stream: {frames: [{name, schema}], terminator, order}. Yields are
//     values only known at run time, so the interface's yields are read
//     from the traces of the run scenarios, one sequence per call. A yield
//     belongs to the frame whose const and enum constraints it meets (the
//     one it fits best when several do) and is then validated against it
//     (missing, type and extra issues prefixed "frame <name>"); a yield no
//     frame accepts is frame-extra. The sequence of frame names, joined by
//     spaces, must match order (anchored) or, without order, follow the
//     frames' list order (frame-order). terminator, a frame name or else a
//     literal value (also matched as an object's "data"), must be the last
//     yield of every call that ends without an error (terminator). A frame
//     no yield step of the behavior can produce (no yield step at all, or
//     only literal templates that don't fit it) is frame-missing; a frame
//     some step could produce but no scenario yielded is counted as not
//     compared.
//   - sources: cited code; a contract without sources is warned about.
//
// --max-contract-issues N fails above N issues.

var contractKinds = []string{"missing", "extra", "required", "type", "status", "error-missing", "error-extra", "unmodeled",
	"frame-missing", "frame-extra", "frame-order", "terminator"}

type contractFile struct {
	Contracts []contract `json:"contracts"`
}

type contract struct {
	ID       string           `json:"id"`
	Match    contractMatch    `json:"match"`
	Request  any              `json:"request,omitempty"`
	Response any              `json:"response,omitempty"`
	Errors   *[]contractError `json:"errors,omitempty"`
	Stream   *contractStream  `json:"stream,omitempty"`
	Sources  any              `json:"sources,omitempty"`

	file *oaDoc // the file, to resolve "$ref"
}

type contractMatch struct {
	Interface  string         `json:"interface,omitempty"`
	Route      *contractRoute `json:"route,omitempty"`
	Attributes map[string]any `json:"attributes,omitempty"`
}

type contractRoute struct {
	Method string `json:"method"`
	Path   string `json:"path"`
}

type contractError struct {
	Code   string `json:"code,omitempty"`
	Status int    `json:"status,omitempty"`
}

type contractStream struct {
	Frames     []contractFrame `json:"frames"`
	Terminator any             `json:"terminator,omitempty"`
	Order      string          `json:"order,omitempty"`
}

type contractFrame struct {
	Name   string `json:"name"`
	Schema any    `json:"schema"`
}

// contractResult is one contract against one interface (Iface "" when the
// contract matches none).
type contractResult struct {
	File, ID string
	Iface    string
	Issues   []confIssue
	op       *confOp // the item-21 counters
	// Stream counters.
	calls, errCalls, emptyCalls int
	unrunFrames                 []string
	streamUnrun                 bool // a stream contract whose interface no scenario called
}

type contractReport struct {
	Results    []*contractResult
	Files      int
	Contracts  int
	NoSources  []string
	BadMatch   []string // contracts with no or several match kinds
	Unrunnable bool     // streams not compared: the scenarios could not run
}

// loadContracts reads a contract file (YAML or JSON).
func loadContracts(p string) ([]*contract, error) {
	b, err := os.ReadFile(p)
	if err != nil {
		return nil, err
	}
	j, err := model.ToJSON(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", p, err)
	}
	var root map[string]any
	if err := json.Unmarshal(j, &root); err != nil {
		return nil, fmt.Errorf("%s: %w", p, err)
	}
	// Other top-level keys (definitions for "$ref") are allowed; contracts
	// are decoded strictly.
	var f contractFile
	cj, _ := json.Marshal(map[string]any{"contracts": root["contracts"]})
	dec := json.NewDecoder(strings.NewReader(string(cj)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&f); err != nil {
		return nil, fmt.Errorf("%s: %w", p, err)
	}
	d := &oaDoc{Path: p, Root: root}
	out := make([]*contract, 0, len(f.Contracts))
	seen := map[string]bool{}
	for i := range f.Contracts {
		c := &f.Contracts[i]
		if c.ID == "" {
			return nil, fmt.Errorf("%s: contracts[%d] has no id", p, i)
		}
		if seen[c.ID] {
			return nil, fmt.Errorf("%s: duplicate contract id %q", p, c.ID)
		}
		seen[c.ID] = true
		if c.Stream != nil && c.Stream.Order != "" {
			if _, err := regexp.Compile(c.Stream.Order); err != nil {
				return nil, fmt.Errorf("%s: contract %s: stream.order: %w", p, c.ID, err)
			}
		}
		c.file = d
		out = append(out, c)
	}
	return out, nil
}

func (m contractMatch) kinds() int {
	n := 0
	if m.Interface != "" {
		n++
	}
	if m.Route != nil {
		n++
	}
	if len(m.Attributes) > 0 {
		n++
	}
	return n
}

// matchContract returns the interfaces a contract's match selects, in id
// order.
func matchContract(doc *model.Document, m contractMatch) []*model.Interface {
	var out []*model.Interface
	for i := range doc.Interfaces {
		ifc := &doc.Interfaces[i]
		switch {
		case m.Interface != "":
			ok, _ := path.Match(m.Interface, ifc.ID)
			if !ok && m.Interface != ifc.ID {
				continue
			}
		case m.Route != nil:
			if isClient(ifc) {
				continue
			}
			im, ip, ok := ifaceRoute(ifc)
			if !ok || routeKey(ip) != routeKey(m.Route.Path) {
				continue
			}
			want := strings.ToUpper(m.Route.Method)
			if want != "" && want != "ANY" && want != "*" && im != want && im != "ANY" && im != "*" {
				continue
			}
		case len(m.Attributes) > 0:
			if isClient(ifc) {
				continue
			}
			ok := true
			for k, v := range m.Attributes {
				av, has := ifc.Attributes[k]
				if !has || !strings.EqualFold(fmt.Sprint(av), fmt.Sprint(v)) {
					ok = false
					break
				}
			}
			if !ok {
				continue
			}
		default:
			continue
		}
		out = append(out, ifc)
	}
	sort.Slice(out, func(a, b int) bool { return out[a].ID < out[b].ID })
	return out
}

// contractOp builds the item-21 operation a contract stands for.
func contractOp(c *contract, ifc *model.Interface, resolveModel func(string) (any, bool)) *oaOp {
	o := &oaOp{ID: c.ID, Security: true}
	if c.Request != nil {
		rq, _ := c.file.deref(c.Request).(map[string]any)
		props, _ := rq["properties"].(map[string]any)
		if b, ok := props["body"]; ok {
			req := map[string]bool{}
			if rl, ok := rq["required"].([]any); ok {
				for _, r := range rl {
					if s, ok := r.(string); ok {
						req[s] = true
					}
				}
			}
			o.HasBody, o.Body, o.BodyRequired = true, b, req["body"]
			for _, k := range sortedKeys(props) {
				switch k {
				case "body":
				case "query":
					q, _ := c.file.deref(props[k]).(map[string]any)
					qp, _ := q["properties"].(map[string]any)
					qreq := map[string]bool{}
					if rl, ok := q["required"].([]any); ok {
						for _, r := range rl {
							if s, ok := r.(string); ok {
								qreq[s] = true
							}
						}
					}
					for _, n := range sortedKeys(qp) {
						o.Params = append(o.Params, oaParam{Name: n, In: "query", Required: qreq[n], Schema: qp[n]})
					}
				default:
					o.Params = append(o.Params, oaParam{Name: k, In: "field", Required: req[k], Schema: props[k]})
				}
			}
		} else {
			o.HasBody, o.Body, o.BodyRequired = true, c.Request, true
			if ms := buildShape(ifc.Request, resolveModel, 0); ms.Props != nil {
				if _, ok := ms.Props["body"]; ok {
					o.BodyRequired = ms.Required["body"] // the contract says nothing on the body's presence
				}
			}
		}
	}
	if c.Response != nil {
		o.RespContent = true
		o.Resp = c.Response
		rs, _ := c.file.deref(c.Response).(map[string]any)
		props, _ := rs["properties"].(map[string]any)
		if b, ok := props["body"]; ok {
			o.Resp = b
			o.Success = statusValues(rs, func(r string) (any, bool) { return c.file.pointer(r) })
		}
	}
	return o
}

// compareContract compares one contract with one interface.
func compareContract(c *contract, ifc *model.Interface, ifaces map[string]*model.Interface, resolveModel func(string) (any, bool)) *contractResult {
	co := &confOp{ID: c.ID, Iface: ifc.ID}
	o := contractOp(c, ifc, resolveModel)
	resolveSpec := func(r string) (any, bool) { return c.file.pointer(r) }
	compareOp(co, o, ifc, ifaces, resolveSpec, resolveModel)
	res := &contractResult{File: c.file.Path, ID: c.ID, Iface: ifc.ID, op: co}
	for _, is := range co.Issues {
		if strings.HasPrefix(is.Kind, "error-") {
			continue // compared below, by status or code
		}
		if c.Request == nil && strings.HasPrefix(is.Msg, "request") {
			continue
		}
		res.Issues = append(res.Issues, is)
	}
	if c.Request == nil {
		co.ambient, co.untypedReq, co.enforced = 0, 0, 0
	}
	if c.Errors != nil {
		res.Issues = append(res.Issues, compareErrors(*c.Errors, ifc, ifaces)...)
	}
	return res
}

// compareErrors compares a contract's errors with the interface's.
func compareErrors(want []contractError, ifc *model.Interface, ifaces map[string]*model.Interface) []confIssue {
	var out []confIssue
	statuses := effectiveStatuses(ifc, ifaces)
	codes := effectiveCodes(ifc, ifaces)
	wantSt, wantCode := map[int]bool{}, map[string]bool{}
	for _, e := range want {
		if e.Status > 0 {
			wantSt[e.Status] = true
		}
		if e.Code != "" {
			wantCode[normName(e.Code)] = true
		}
		var ok bool
		var label string
		switch {
		case e.Status > 0:
			ok = statuses[e.Status]
			label = fmt.Sprintf("error status %d", e.Status)
			if e.Code != "" {
				label += " (" + e.Code + ")"
			}
		case e.Code != "":
			ok = codes[normName(e.Code)]
			label = "error code " + e.Code
		default:
			continue
		}
		if !ok {
			out = append(out, confIssue{"error-missing", label})
		}
	}
	for _, e := range ifc.Errors {
		if e.Status == 500 && !wantSt[500] {
			continue // the generic internal error
		}
		if (e.Status > 0 && wantSt[e.Status]) || (e.Code != "" && wantCode[normName(e.Code)]) {
			continue
		}
		label := e.Code
		if e.Status > 0 {
			label = fmt.Sprintf("error status %d (%s)", e.Status, e.Code)
		} else {
			label = "error code " + label
		}
		out = append(out, confIssue{"error-extra", label})
	}
	return out
}

// effectiveCodes is effectiveStatuses for error codes (normalized).
func effectiveCodes(root *model.Interface, ifaces map[string]*model.Interface) map[string]bool {
	out := map[string]bool{}
	seen := map[string]bool{}
	var visit func(f *model.Interface, depth int)
	visit = func(f *model.Interface, depth int) {
		if f == nil || seen[f.ID] || depth > 12 {
			return
		}
		seen[f.ID] = true
		for _, e := range f.Errors {
			if e.Code != "" {
				out[normName(e.Code)] = true
			}
		}
		walkConfSteps(f.Behavior, func(s model.Step) {
			if len(s.Fail) > 0 {
				var fs struct {
					Code any `json:"code"`
				}
				if json.Unmarshal(s.Fail, &fs) == nil {
					if c, ok := fs.Code.(string); ok {
						if _, isExpr := expr.ExprOf(c); !isExpr {
							out[normName(c)] = true
						}
					}
				}
			}
			if s.Call != "" {
				visit(ifaces[s.Call], depth+1)
			}
		})
	}
	visit(root, 0)
	return out
}

// contracts compares every contract with the interfaces it matches. yields
// holds the run scenarios' yield sequences per interface (nil when the
// scenarios didn't run).
func contracts(doc *model.Document, cs []*contract, yields map[string][]yieldCall) *contractReport {
	idx := model.NewIndex(doc)
	resolveModel := func(r string) (any, bool) { return idx.ResolveSchema(r) }
	ifaces := map[string]*model.Interface{}
	for i := range doc.Interfaces {
		ifaces[doc.Interfaces[i].ID] = &doc.Interfaces[i]
	}
	rep := &contractReport{Contracts: len(cs), Unrunnable: yields == nil}
	files := map[string]bool{}
	for _, c := range cs {
		files[c.file.Path] = true
		if c.Sources == nil {
			rep.NoSources = append(rep.NoSources, c.ID)
		}
		if c.Match.kinds() != 1 {
			rep.BadMatch = append(rep.BadMatch, c.ID)
			continue
		}
		matched := matchContract(doc, c.Match)
		if len(matched) == 0 {
			rep.Results = append(rep.Results, &contractResult{File: c.file.Path, ID: c.ID, op: &confOp{},
				Issues: []confIssue{{"unmodeled", fmt.Sprintf("%s matches no interface (%s)", c.ID, c.Match)}}})
			continue
		}
		for _, ifc := range matched {
			r := compareContract(c, ifc, ifaces, resolveModel)
			if c.Stream != nil {
				compareStream(r, c, ifc, yields)
			}
			rep.Results = append(rep.Results, r)
		}
	}
	rep.Files = len(files)
	return rep
}

func (m contractMatch) String() string {
	switch {
	case m.Interface != "":
		return "interface " + m.Interface
	case m.Route != nil:
		return "route " + strings.ToUpper(m.Route.Method) + " " + m.Route.Path
	default:
		var kv []string
		for _, k := range sortedKeys(m.Attributes) {
			kv = append(kv, fmt.Sprintf("%s=%v", k, m.Attributes[k]))
		}
		return "attributes " + strings.Join(kv, ",")
	}
}

func (r *contractReport) totals() (map[string]int, int) {
	t := map[string]int{}
	n := 0
	for _, res := range r.Results {
		for _, is := range res.Issues {
			t[is.Kind]++
			n++
		}
	}
	return t, n
}

// print writes the report; it returns true when the issues exceed max (max
// < 0: no gate).
func (r *contractReport) print(w io.Writer, max int, quiet bool) bool {
	var matched, clean, unmodeled, ambient, untReq, untResp, complex, u500, enf int
	var calls, errCalls, emptyCalls, unrunFrames, unrunStreams int
	for _, res := range r.Results {
		o := res.op
		ambient += o.ambient
		untReq += o.untypedReq
		untResp += o.untypedResp
		complex += o.complex
		u500 += o.undeclared500
		enf += o.enforced
		calls += res.calls
		errCalls += res.errCalls
		emptyCalls += res.emptyCalls
		unrunFrames += len(res.unrunFrames)
		if res.streamUnrun {
			unrunStreams++
		}
		if res.Iface == "" {
			unmodeled++
			continue
		}
		matched++
		if len(res.Issues) == 0 {
			clean++
		}
	}
	if !quiet {
		for _, id := range r.BadMatch {
			fmt.Fprintf(w, "! contract %s: match needs exactly one of interface, route or attributes; skipped\n", id)
		}
		for _, id := range r.NoSources {
			fmt.Fprintf(w, "! contract %s cites no sources\n", id)
		}
		for _, res := range r.Results {
			if res.Iface == "" || len(res.Issues) == 0 {
				continue
			}
			fmt.Fprintf(w, "✗ contract %s -> %s (%s)\n", res.ID, res.Iface, res.File)
			for _, is := range res.Issues {
				fmt.Fprintf(w, "    %s: %s\n", is.Kind, is.Msg)
			}
		}
		for _, res := range r.Results {
			if res.Iface == "" {
				for _, is := range res.Issues {
					fmt.Fprintf(w, "✗ contract unmodeled: %s\n", is.Msg)
				}
			}
		}
		for _, res := range r.Results {
			if len(res.unrunFrames) > 0 {
				fmt.Fprintf(w, "~ contract %s -> %s: frames no scenario yielded: %s\n", res.ID, res.Iface, strings.Join(res.unrunFrames, ", "))
			}
		}
	}
	t, n := r.totals()
	var parts []string
	for _, k := range contractKinds {
		parts = append(parts, fmt.Sprintf("%s %d", k, t[k]))
	}
	fmt.Fprintf(w, "contracts: %d contracts in %d files, %d interfaces compared (%d clean), %d unmodeled; %d issues: %s\n",
		r.Contracts, r.Files, matched, clean, unmodeled, n, strings.Join(parts, ", "))
	streams := fmt.Sprintf("%d streamed calls read, %d frames no scenario yielded, %d streams no scenario ran, %d calls ended in an error (terminator not checked), %d calls yielded nothing",
		calls, unrunFrames, unrunStreams, errCalls, emptyCalls)
	if r.Unrunnable {
		streams = "streams not run (the document has validation errors)"
	}
	fmt.Fprintf(w, "contracts not compared: %d untyped request parts, %d untyped response bodies, %d undeclared x-headers, %d undeclared 500s, %d required fields the behavior enforces, skipped: complex %d; %s\n",
		untReq, untResp, ambient, u500, enf, complex, streams)
	if max >= 0 && n > max {
		fmt.Fprintf(w, "✗ contracts: %d issues, above --max-contract-issues %d\n", n, max)
		return true
	}
	return false
}

// contractOpts configures runContracts.
type contractOpts struct {
	Code  string         // a relative path missing here is resolved against it
	Max   int            // --max-contract-issues, < 0 for no gate
	Quiet bool           // print only the totals
	Only  *regexp.Regexp // --scenario
	Run   bool           // the document is valid: scenarios can run for streams
}

// runContracts loads the contract files, compares and prints. It returns true
// when the gate fails.
func runContracts(w io.Writer, doc *model.Document, paths []string, o contractOpts) (bool, error) {
	var cs []*contract
	ids := map[string]string{}
	for _, p := range paths {
		if _, err := os.Stat(p); err != nil && o.Code != "" && !filepath.IsAbs(p) {
			p = filepath.Join(o.Code, p)
		}
		got, err := loadContracts(p)
		if err != nil {
			return false, err
		}
		for _, c := range got {
			if prev, ok := ids[c.ID]; ok {
				return false, fmt.Errorf("contract id %q in both %s and %s", c.ID, prev, p)
			}
			ids[c.ID] = p
		}
		cs = append(cs, got...)
	}
	var yields map[string][]yieldCall
	if o.Run {
		want := map[string]bool{}
		for _, c := range cs {
			if c.Stream == nil || c.Match.kinds() != 1 {
				continue
			}
			for _, ifc := range matchContract(doc, c.Match) {
				want[ifc.ID] = true
			}
		}
		yields = collectYields(doc, want, o.Only)
	}
	return contracts(doc, cs, yields).print(w, o.Max, o.Quiet), nil
}
