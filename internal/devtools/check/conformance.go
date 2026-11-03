package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Contract conformance against an API spec (DESIGN §13.1 item 21).
//
// --openapi FILE reads an OpenAPI 3 document and matches each operation to
// the model's interface for it: one whose attributes.method and
// attributes.path name the route (path parameter names are ignored, ANY
// matches every method), or else one named routeSlug(method, path) on any
// component. Client wrappers (kind cli-command, or attributes.calls) are
// never implementations. The request, the 2xx response body and the
// declared error statuses are compared:
//
//   - request: path, query and header parameters, at the request's top level
//     or (query) under a "query" property, and the request body under
//     "body" (or flattened at the top level when the model has no "body").
//     Presence, required versus optional and types are compared; field names
//     match case- and separator-insensitively (orgId = org_id).
//   - response: the model's {status, body} envelope puts the body in "body";
//     a response without "body" and "status" is the body itself. Properties
//     and types are compared, not required.
//   - errors: the spec's 4xx/5xx statuses against the model's errors.
//
// "authorization" is the security scheme's header, never an extra field.
// Other headers the spec doesn't declare (x_*) are ambient: counted, not
// reported, unless the model makes one required, which no undeclared header
// can be. An untyped side ({} or {type: object} without properties) is
// counted as "not compared", not reported field by field. $ref, allOf and
// object oneOf/anyOf are resolved (oneOf: the union of the variants'
// properties, required in all of them); a oneOf of unlike types, or a
// reference outside the document, is skipped and counted as complex.
// Nullable fields (nullable: true, a "null" type, a oneOf with null) compare
// by their non-null type.

// conformance issue kinds, in report order.
var confKinds = []string{"missing", "extra", "required", "type", "status", "error-missing", "error-extra", "unmodeled", "orphan"}

type confIssue struct {
	Kind string
	Msg  string
}

type confOp struct {
	Spec          string
	ID            string
	Method        string
	Path          string
	Iface         string // matched interface id, or "" when unmodeled
	Also          []string
	Issues        []confIssue
	ambient       int
	untypedReq    int
	untypedResp   int
	complex       int
	undeclared500 int
	enforced      int
}

type confReport struct {
	Ops      []*confOp
	Orphans  []confIssue
	OutScope int // route interfaces on components that implement no operation
	Clients  int // client wrappers naming an operation's route
}

// oaParam is one OpenAPI parameter.
type oaParam struct {
	Name, In string
	Required bool
	Schema   any
}

type oaOp struct {
	ID, Method, Path string
	Params           []oaParam
	Body             any // request body schema, nil without one
	BodyRequired     bool
	HasBody          bool
	Success          []int // 2xx statuses
	Resp             any   // the first 2xx JSON schema
	RespContent      bool  // the first 2xx declares content
	RespNonJSON      bool
	Errors           []int
	Security         bool
}

type oaDoc struct {
	Path string
	Root map[string]any
	Ops  []oaOp
}

var httpMethods = []string{"get", "put", "post", "delete", "options", "head", "patch", "trace"}

// loadOpenAPI reads an OpenAPI document (YAML or JSON).
func loadOpenAPI(path string) (*oaDoc, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	j, err := model.ToJSON(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	var root map[string]any
	if err := json.Unmarshal(j, &root); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	d := &oaDoc{Path: path, Root: root}
	globalSec := false
	if s, ok := root["security"].([]any); ok && len(s) > 0 {
		globalSec = true
	}
	paths, _ := root["paths"].(map[string]any)
	keys := sortedKeys(paths)
	for _, p := range keys {
		item, _ := d.deref(paths[p]).(map[string]any)
		if item == nil {
			continue
		}
		common := d.params(item["parameters"])
		for _, m := range httpMethods {
			op, ok := item[m].(map[string]any)
			if !ok {
				continue
			}
			o := oaOp{Method: strings.ToUpper(m), Path: p, Security: globalSec}
			o.ID, _ = op["operationId"].(string)
			if s, ok := op["security"].([]any); ok {
				o.Security = false
				for _, r := range s {
					if rm, ok := r.(map[string]any); ok && len(rm) > 0 {
						o.Security = true
					}
				}
			}
			own := d.params(op["parameters"])
			seen := map[string]bool{}
			for _, q := range own {
				seen[q.In+"\x00"+q.Name] = true
			}
			o.Params = own
			for _, q := range common {
				if !seen[q.In+"\x00"+q.Name] {
					o.Params = append(o.Params, q)
				}
			}
			if rb, ok := d.deref(op["requestBody"]).(map[string]any); ok {
				o.HasBody = true
				o.BodyRequired, _ = rb["required"].(bool)
				o.Body, _ = jsonContent(rb["content"])
			}
			resps, _ := op["responses"].(map[string]any)
			for _, code := range sortedKeys(resps) {
				n, err := strconv.Atoi(code)
				if err != nil {
					continue
				}
				switch {
				case n >= 200 && n < 300:
					if len(o.Success) == 0 {
						r, _ := d.deref(resps[code]).(map[string]any)
						if c, ok := r["content"].(map[string]any); ok && len(c) > 0 {
							o.RespContent = true
							var isJSON bool
							o.Resp, isJSON = jsonContent(c)
							o.RespNonJSON = !isJSON
						}
					}
					o.Success = append(o.Success, n)
				case n >= 400:
					o.Errors = append(o.Errors, n)
				}
			}
			d.Ops = append(d.Ops, o)
		}
	}
	return d, nil
}

// jsonContent returns the JSON media type's schema of a content map.
func jsonContent(c any) (any, bool) {
	cm, _ := c.(map[string]any)
	for _, k := range sortedKeys(cm) {
		mt := strings.ToLower(strings.TrimSpace(strings.Split(k, ";")[0]))
		if mt == "application/json" || strings.HasSuffix(mt, "+json") {
			m, _ := cm[k].(map[string]any)
			return m["schema"], true
		}
	}
	return nil, false
}

// deref follows local "$ref" pointers (#/a/b) up to a depth.
func (d *oaDoc) deref(v any) any {
	for i := 0; i < 16; i++ {
		m, ok := v.(map[string]any)
		if !ok {
			return v
		}
		r, ok := m["$ref"].(string)
		if !ok {
			return v
		}
		t, ok := d.pointer(r)
		if !ok {
			return nil
		}
		v = t
	}
	return nil
}

func (d *oaDoc) pointer(ref string) (any, bool) {
	if !strings.HasPrefix(ref, "#/") {
		return nil, false
	}
	var cur any = d.Root
	for _, tok := range strings.Split(ref[2:], "/") {
		tok = strings.NewReplacer("~1", "/", "~0", "~").Replace(tok)
		m, ok := cur.(map[string]any)
		if !ok {
			return nil, false
		}
		if cur, ok = m[tok]; !ok {
			return nil, false
		}
	}
	return cur, true
}

func (d *oaDoc) params(v any) []oaParam {
	list, _ := v.([]any)
	var out []oaParam
	for _, x := range list {
		m, ok := d.deref(x).(map[string]any)
		if !ok {
			continue
		}
		p := oaParam{Schema: m["schema"]}
		p.Name, _ = m["name"].(string)
		p.In, _ = m["in"].(string)
		p.Required, _ = m["required"].(bool)
		if p.In == "path" {
			p.Required = true
		}
		out = append(out, p)
	}
	return out
}

// shape is a schema flattened for comparison.
type shape struct {
	Types    map[string]bool // without "null"
	Nullable bool
	Props    map[string]*shape // by normalized name
	Names    map[string]string // normalized name -> declared name
	Required map[string]bool   // normalized names
	Default  map[string]bool   // normalized names with a default (model)
	Items    *shape
	Complex  bool
	Open     bool // additionalProperties allows other fields
}

func (s *shape) isObject() bool {
	return s != nil && (s.Types["object"] || (len(s.Types) == 0 && s.Props != nil))
}

func (s *shape) typed() bool {
	return s != nil && (len(s.Types) > 0 || s.Props != nil || s.Complex)
}

// normName folds case and separators: orgId, org_id and Org-Id are one name.
func normName(s string) string {
	return strings.NewReplacer("_", "", "-", "", ".", "").Replace(strings.ToLower(s))
}

// buildShape flattens a schema; resolve follows "$ref" values.
func buildShape(v any, resolve func(string) (any, bool), depth int) *shape {
	s := &shape{Types: map[string]bool{}}
	if depth > 12 {
		return s
	}
	switch t := v.(type) {
	case string: // a model schema id
		r, ok := resolve(t)
		if !ok {
			s.Complex = true
			return s
		}
		return buildShape(r, resolve, depth+1)
	case map[string]any:
		if r, ok := t["$ref"].(string); ok {
			x, ok := resolve(r)
			if !ok {
				s.Complex = true
				return s
			}
			base := buildShape(x, resolve, depth+1)
			if n, _ := t["nullable"].(bool); n {
				base.Nullable = true
			}
			return base
		}
		switch ty := t["type"].(type) {
		case string:
			if ty == "null" {
				s.Nullable = true
			} else {
				s.Types[ty] = true
			}
		case []any:
			for _, x := range ty {
				if x == "null" {
					s.Nullable = true
				} else if xs, ok := x.(string); ok {
					s.Types[xs] = true
				}
			}
		}
		if n, _ := t["nullable"].(bool); n {
			s.Nullable = true
		}
		if c, ok := t["const"]; ok && len(s.Types) == 0 {
			if ty := jsonType(c); ty != "" {
				s.Types[ty] = true
			}
		}
		if ap, ok := t["additionalProperties"]; ok {
			if b, isBool := ap.(bool); !isBool || b {
				s.Open = true
			}
		}
		if ps, ok := t["properties"].(map[string]any); ok {
			s.Props, s.Names, s.Required, s.Default = map[string]*shape{}, map[string]string{}, map[string]bool{}, map[string]bool{}
			for name, p := range ps {
				n := normName(name)
				s.Props[n] = buildShape(p, resolve, depth+1)
				s.Names[n] = name
				if pm, ok := p.(map[string]any); ok {
					if _, d := pm["default"]; d {
						s.Default[n] = true
					}
				}
			}
			if req, ok := t["required"].([]any); ok {
				for _, r := range req {
					if rs, ok := r.(string); ok {
						s.Required[normName(rs)] = true
					}
				}
			}
		}
		if it, ok := t["items"]; ok {
			s.Items = buildShape(it, resolve, depth+1)
		}
		if all, ok := t["allOf"].([]any); ok {
			for _, x := range all {
				s.merge(buildShape(x, resolve, depth+1), true)
			}
		}
		for _, key := range []string{"oneOf", "anyOf"} {
			alts, ok := t[key].([]any)
			if !ok {
				continue
			}
			var vs []*shape
			for _, x := range alts {
				a := buildShape(x, resolve, depth+1)
				if len(a.Types) == 0 && a.Props == nil && a.Nullable && !a.Complex {
					s.Nullable = true // {type: "null"}
					continue
				}
				vs = append(vs, a)
			}
			s.union(vs)
		}
	}
	return s
}

func jsonType(v any) string {
	switch v.(type) {
	case string:
		return "string"
	case bool:
		return "boolean"
	case float64:
		return "number"
	case map[string]any:
		return "object"
	case []any:
		return "array"
	}
	return ""
}

// merge adds o's types and properties to s (allOf).
func (s *shape) merge(o *shape, keepRequired bool) {
	if o.Complex {
		s.Complex = true
	}
	for t := range o.Types {
		s.Types[t] = true
	}
	if o.Nullable {
		s.Nullable = true
	}
	if o.Open {
		s.Open = true
	}
	if o.Items != nil && s.Items == nil {
		s.Items = o.Items
	}
	if o.Props != nil {
		if s.Props == nil {
			s.Props, s.Names, s.Required, s.Default = map[string]*shape{}, map[string]string{}, map[string]bool{}, map[string]bool{}
		}
		for n, p := range o.Props {
			if _, ok := s.Props[n]; !ok {
				s.Props[n] = p
				s.Names[n] = o.Names[n]
			}
		}
		if keepRequired {
			for n := range o.Required {
				s.Required[n] = true
			}
		}
	}
}

// union folds oneOf/anyOf variants: objects union their properties and keep
// the fields every variant requires; scalars union their types; a mix of
// objects and scalars is complex.
func (s *shape) union(vs []*shape) {
	if len(vs) == 0 {
		return
	}
	objects, scalars := 0, 0
	for _, v := range vs {
		if v.Complex {
			s.Complex = true
			return
		}
		if v.isObject() {
			objects++
		} else {
			scalars++
		}
	}
	if objects > 0 && scalars > 0 {
		s.Complex = true
		return
	}
	req := map[string]int{}
	for _, v := range vs {
		s.merge(v, false)
		for n := range v.Required {
			req[n]++
		}
	}
	for n, c := range req {
		if c == len(vs) {
			s.Required[n] = true
		}
	}
}

// typeCompat: do two type sets overlap (integer and number are compatible)?
func typeCompat(a, b map[string]bool) bool {
	if len(a) == 0 || len(b) == 0 {
		return true
	}
	num := func(m map[string]bool) bool { return m["integer"] || m["number"] }
	if num(a) && num(b) {
		return true
	}
	for t := range a {
		if b[t] {
			return true
		}
	}
	return false
}

func typeList(s *shape) string {
	var ts []string
	for t := range s.Types {
		ts = append(ts, t)
	}
	sort.Strings(ts)
	if len(ts) == 0 {
		return "any"
	}
	return strings.Join(ts, "|")
}

// comparer compares spec shapes against model shapes for one operation.
type comparer struct {
	op      *confOp
	request bool
	// enforced: the behavior refuses a request without this input path.
	enforced map[string]bool
}

func (c *comparer) add(kind, f string, a ...any) {
	c.op.Issues = append(c.op.Issues, confIssue{kind, fmt.Sprintf(f, a...)})
}

// compare reports how model m departs from spec s at path p.
func (c *comparer) compare(p, in string, s, m *shape, depth int) {
	if s == nil || m == nil || depth > 8 {
		return
	}
	if s.Complex || m.Complex {
		c.op.complex++
		return
	}
	if !typeCompat(s.Types, m.Types) {
		c.add("type", "%s: spec %s, model %s", p, typeList(s), typeList(m))
		return
	}
	if s.Items != nil && m.Items != nil {
		c.compare(p+"[]", in+"[]", s.Items, m.Items, depth+1)
	}
	if s.Props == nil || len(s.Props) == 0 {
		return // a free-form object: nothing to compare
	}
	if m.Props == nil || len(m.Props) == 0 {
		if depth == 0 {
			if c.request {
				c.op.untypedReq++
			} else {
				c.op.untypedResp++
			}
		}
		return
	}
	c.fields(p, in, s, m, depth)
}

func (c *comparer) fields(p, in string, s, m *shape, depth int) {
	join := func(n string) string {
		if p == "" {
			return n
		}
		return p + "." + n
	}
	for _, n := range sortedKeys(s.Props) {
		name := s.Names[n]
		mp, ok := m.Props[n]
		if !ok {
			req := ""
			if c.request && s.Required[n] {
				req = ", required"
			}
			c.add("missing", "%s (%s%s)", join(name), typeList(s.Props[n]), req)
			continue
		}
		mi := m.Names[n]
		if in != "" {
			mi = in + "." + mi
		}
		if c.request {
			c.required(join(name), mi, s.Required[n], m.Required[n])
		}
		c.compare(join(name), mi, s.Props[n], mp, depth+1)
	}
	if s.Open {
		return
	}
	for _, n := range sortedKeys(m.Props) {
		if _, ok := s.Props[n]; !ok {
			c.add("extra", "%s (%s)", join(m.Names[n]), typeList(m.Props[n]))
		}
	}
}

// required compares required versus optional at label p; in is the model's
// input path. A model-optional field the behavior refuses to go without
// (a fail under !has(input.<in>) or input.<in> == null) counts as required.
func (c *comparer) required(p, in string, spec, mod bool) {
	if spec && !mod && c.enforced[in] {
		c.op.enforced++
		return
	}
	switch {
	case spec && !mod:
		c.add("required", "%s: spec required, model optional", p)
	case !spec && mod:
		c.add("required", "%s: spec optional, model required", p)
	}
}

var pathParam = regexp.MustCompile(`\{[^}]*\}`)

func routeKey(p string) string {
	p = pathParam.ReplaceAllString(p, "{}")
	if len(p) > 1 {
		p = strings.TrimRight(p, "/")
	}
	return strings.ToLower(p)
}

func isClient(ifc *model.Interface) bool {
	if ifc.Kind == "cli-command" {
		return true
	}
	_, calls := ifc.Attributes["calls"]
	return calls
}

func ifaceRoute(ifc *model.Interface) (string, string, bool) {
	m, _ := ifc.Attributes["method"].(string)
	p, _ := ifc.Attributes["path"].(string)
	if m == "" || p == "" || !strings.HasPrefix(p, "/") {
		return "", "", false
	}
	return strings.ToUpper(m), p, true
}

// conformance compares every operation of the specs to the model.
func conformance(doc *model.Document, specs []*oaDoc) *confReport {
	idx := model.NewIndex(doc)
	resolveModel := func(r string) (any, bool) {
		s, ok := idx.ResolveSchema(r)
		return s, ok
	}
	byRoute := map[string][]*model.Interface{} // key: path key
	byName := map[string][]*model.Interface{}
	ifaces := map[string]*model.Interface{}
	rep := &confReport{}
	for i := range doc.Interfaces {
		ifc := &doc.Interfaces[i]
		ifaces[ifc.ID] = ifc
		if m, p, ok := ifaceRoute(ifc); ok {
			if isClient(ifc) {
				continue
			}
			_ = m
			byRoute[routeKey(p)] = append(byRoute[routeKey(p)], ifc)
			continue
		}
		byName[ifc.Name] = append(byName[ifc.Name], ifc)
	}
	// Client wrappers name the implementation of their route (attributes.calls)
	// and sometimes the operation (attributes.operation_id).
	calledBy := map[string]bool{} // "<METHOD> <route key> <interface id>"
	opCalls := map[string]bool{}  // "<operationId> <interface id>"
	for i := range doc.Interfaces {
		ifc := &doc.Interfaces[i]
		m, p, ok := ifaceRoute(ifc)
		callee, _ := ifc.Attributes["calls"].(string)
		if !ok || callee == "" {
			continue
		}
		calledBy[m+" "+routeKey(p)+" "+callee] = true
		if op, _ := ifc.Attributes["operation_id"].(string); op != "" {
			opCalls[op+" "+callee] = true
		}
	}
	type pending struct {
		co    *confOp
		o     *oaOp
		d     *oaDoc
		cands []*model.Interface
	}
	var todo []pending
	svcScore := map[string]int{} // unambiguous matches per service
	for _, d := range specs {
		for i := range d.Ops {
			o := &d.Ops[i]
			co := &confOp{Spec: d.Path, ID: o.ID, Method: o.Method, Path: o.Path}
			rep.Ops = append(rep.Ops, co)
			var cands []*model.Interface
			for _, ifc := range byRoute[routeKey(o.Path)] {
				m, _, _ := ifaceRoute(ifc)
				if m == o.Method || m == "ANY" || m == "*" {
					cands = append(cands, ifc)
				}
			}
			if len(cands) == 0 {
				cands = byName[routeSlug(o.Method, o.Path)]
			}
			if len(cands) == 0 {
				co.Issues = append(co.Issues, confIssue{"unmodeled", fmt.Sprintf("%s %s %s", o.ID, o.Method, o.Path)})
				continue
			}
			if len(cands) == 1 {
				svcScore[serviceOf(idx, cands[0].Component)]++
			}
			todo = append(todo, pending{co, o, d, cands})
		}
	}
	used := map[string]bool{}
	for _, t := range todo {
		o, cands := t.o, t.cands
		// Several servers can serve one route (an engine's /v1/models beside
		// the gateway's): prefer the one a client wrapper names, then the
		// service that implements the spec's unambiguous operations.
		rank := func(ifc *model.Interface) [4]int {
			ev := 0
			if opCalls[o.ID+" "+ifc.ID] || calledBy[o.Method+" "+routeKey(o.Path)+" "+ifc.ID] {
				ev = -1
			}
			exact := 0
			if m, _, ok := ifaceRoute(ifc); !ok || m != o.Method {
				exact = 1
			}
			http := 0
			if ifc.Kind != "http" {
				http = 1
			}
			return [4]int{ev, -svcScore[serviceOf(idx, ifc.Component)], exact, http}
		}
		sort.SliceStable(cands, func(a, b int) bool {
			ra, rb := rank(cands[a]), rank(cands[b])
			for k := range ra {
				if ra[k] != rb[k] {
					return ra[k] < rb[k]
				}
			}
			return cands[a].ID < cands[b].ID
		})
		ifc := cands[0]
		t.co.Iface = ifc.ID
		used[ifc.ID] = true
		for _, x := range cands[1:] {
			if serviceOf(idx, x.Component) == serviceOf(idx, ifc.Component) {
				used[x.ID] = true
				t.co.Also = append(t.co.Also, x.ID)
			}
		}
		d := t.d
		compareOp(t.co, o, ifc, ifaces, func(r string) (any, bool) { return d.pointer(r) }, resolveModel)
	}
	// Orphans: route interfaces on components that implement an operation.
	inScope := map[string]bool{}
	for _, co := range rep.Ops {
		if co.Iface != "" {
			inScope[ifaces[co.Iface].Component] = true
		}
	}
	for i := range doc.Interfaces {
		ifc := &doc.Interfaces[i]
		m, p, ok := ifaceRoute(ifc)
		if !ok || used[ifc.ID] {
			continue
		}
		if isClient(ifc) {
			rep.Clients++
			continue
		}
		if !inScope[ifc.Component] {
			rep.OutScope++
			continue
		}
		rep.Orphans = append(rep.Orphans, confIssue{"orphan", fmt.Sprintf("%s: %s %s matches no operation", ifc.ID, m, p)})
	}
	sort.Slice(rep.Orphans, func(a, b int) bool { return rep.Orphans[a].Msg < rep.Orphans[b].Msg })
	return rep
}

// serviceOf is the nearest ancestor-or-self component of kind service, or
// the topmost ancestor.
func serviceOf(idx *model.Index, id string) string {
	top := id
	for i := 0; i < 32 && id != ""; i++ {
		c, ok := idx.Components[id]
		if !ok {
			break
		}
		if c.Kind == "service" {
			return id
		}
		top = id
		id = c.Parent
	}
	return top
}

// compareOp compares one operation with its interface.
func compareOp(co *confOp, o *oaOp, ifc *model.Interface, ifaces map[string]*model.Interface, resolveSpec, resolveModel func(string) (any, bool)) {
	req := buildShape(ifc.Request, resolveModel, 0)
	if ifc.Request == nil {
		req = &shape{Types: map[string]bool{}}
	}
	c := &comparer{op: co, request: true, enforced: enforcedInputs(ifc)}
	consumed := map[string]bool{}
	var query *shape
	if q, ok := req.Props["query"]; ok {
		query = q
	}
	for _, p := range o.Params {
		if p.In == "cookie" {
			continue
		}
		n := normName(p.Name)
		ps := buildShape(p.Schema, resolveSpec, 0)
		label := p.In + " " + p.Name
		where, mp := req, req.Props[n]
		if mp == nil && p.In == "query" && query != nil && query.Props != nil {
			where, mp = query, query.Props[n]
			label = "query." + p.Name
		}
		if mp == nil && p.In == "header" && strings.EqualFold(p.Name, "authorization") {
			continue
		}
		if mp == nil {
			if p.In == "query" && query != nil && len(query.Props) == 0 {
				co.untypedReq++
				consumed["query"] = true
				continue
			}
			req := ""
			if p.Required {
				req = ", required"
			}
			c.add("missing", "request %s (%s%s)", label, typeList(ps), req)
			continue
		}
		if where == req {
			consumed[n] = true
		} else {
			consumed["query"] = true
		}
		in := where.Names[n]
		if where != req {
			in = "query." + in
		}
		c.required("request "+label, in, p.Required, where.Required[n])
		c.compare("request "+label, in, ps, mp, 1)
	}
	if query != nil {
		consumed["query"] = true // a query object holds the query parameters
	}
	if o.HasBody {
		sb := buildShape(o.Body, resolveSpec, 0)
		if mb, ok := req.Props["body"]; ok {
			consumed["body"] = true
			c.required("request body", "body", o.BodyRequired, req.Required["body"])
			c.compare("request body", "body", sb, mb, 0)
		} else if sb.Props != nil && len(sb.Props) > 0 && !sb.Complex {
			// A flattened body: the body's fields at the request's top level.
			rest := &shape{Types: map[string]bool{"object": true}, Props: map[string]*shape{}, Names: map[string]string{}, Required: map[string]bool{}, Default: map[string]bool{}}
			for n, p := range req.Props {
				if !consumed[n] {
					rest.Props[n], rest.Names[n] = p, req.Names[n]
					rest.Required[n], rest.Default[n] = req.Required[n], req.Default[n]
				}
			}
			cc := &comparer{op: co, request: true, enforced: c.enforced}
			for n := range sb.Props {
				if _, ok := rest.Props[n]; ok {
					consumed[n] = true
				}
			}
			for _, n := range sortedKeys(sb.Props) {
				name := sb.Names[n]
				mp, ok := rest.Props[n]
				if !ok {
					r := ""
					if sb.Required[n] {
						r = ", required"
					}
					cc.add("missing", "request body.%s (%s%s)", name, typeList(sb.Props[n]), r)
					continue
				}
				cc.required("request body."+name, rest.Names[n], sb.Required[n] && o.BodyRequired, rest.Required[n])
				cc.compare("request body."+name, rest.Names[n], sb.Props[n], mp, 1)
			}
		} else if sb.typed() {
			c.add("missing", "request body (%s)", typeList(sb))
		}
	}
	shared := sharedSchemaName(ifc.Request)
	var sharedExtras []string
	for _, n := range sortedKeys(req.Props) {
		if consumed[n] {
			continue
		}
		name := req.Names[n]
		switch {
		case n == "authorization" && o.Security:
		case n == "body" && !o.HasBody:
			if mb := req.Props["body"]; mb.Props != nil && len(mb.Props) > 0 {
				c.add("extra", "request body (the spec declares none)")
			}
		case strings.HasPrefix(strings.ToLower(name), "x_") || strings.HasPrefix(strings.ToLower(name), "x-"):
			co.ambient++
			if req.Required[n] {
				c.add("required", "request %s: an undeclared header, model required", name)
			}
		case shared != "":
			sharedExtras = append(sharedExtras, name)
		default:
			c.add("extra", "request %s (%s)", name, typeList(req.Props[n]))
		}
	}
	if len(sharedExtras) > 0 {
		c.add("extra", "request fields of the shared schema %s this operation doesn't take: %s", shared, strings.Join(sharedExtras, ", "))
	}

	// Response.
	resp := buildShape(ifc.Response, resolveModel, 0)
	var body *shape
	status := map[int]bool{}
	if resp.Props != nil {
		if st, ok := resp.Props["status"]; ok {
			_ = st
			for _, v := range statusValues(ifc.Response, resolveModel) {
				status[v] = true
			}
		}
		_, hasStatus := resp.Props["status"]
		if b, ok := resp.Props["body"]; ok {
			body = b
		} else if !hasStatus {
			body = resp
		}
	} else if resp.typed() {
		body = resp
	}
	if len(status) > 0 && len(o.Success) > 0 {
		ok := false
		for _, s := range o.Success {
			if status[s] {
				ok = true
			}
		}
		if !ok {
			c.add("status", "success status: spec %v, model %v", o.Success, sortedInts(status))
		}
	}
	rc := &comparer{op: co}
	switch {
	case o.RespNonJSON:
	case o.RespContent && o.Resp != nil:
		sr := buildShape(o.Resp, resolveSpec, 0)
		if body == nil || !body.typed() {
			if sr.typed() {
				co.untypedResp++
			}
		} else {
			rc.compare("response body", "", sr, body, 0)
		}
	case !o.RespContent && len(o.Success) > 0:
		if body != nil && body.Props != nil && len(body.Props) > 0 {
			rc.add("extra", "response body (the spec's %d has no content)", o.Success[0])
		}
	}

	// Errors: a spec status is modeled when the interface declares it, fails
	// with it, or calls (at any depth) an interface that does; only its own
	// declared statuses can be extra. A 500 the spec doesn't declare is the
	// generic internal error, not a contract difference.
	modelSt := map[int]bool{}
	for _, e := range ifc.Errors {
		if e.Status >= 400 {
			modelSt[e.Status] = true
		}
	}
	reach := effectiveStatuses(ifc, ifaces)
	specSt := map[int]bool{}
	for _, s := range o.Errors {
		specSt[s] = true
		if !modelSt[s] && !reach[s] {
			c.add("error-missing", "error status %d", s)
		}
	}
	for _, s := range sortedInts(modelSt) {
		if s == 500 && !specSt[500] {
			co.undeclared500++
			continue
		}
		if !specSt[s] {
			var codes []string
			for _, e := range ifc.Errors {
				if e.Status == s {
					codes = append(codes, e.Code)
				}
			}
			c.add("error-extra", "error status %d (%s)", s, strings.Join(codes, ", "))
		}
	}
}

var absentInput = regexp.MustCompile(`!\s*has\(\s*input\.([A-Za-z0-9_.]+)\s*\)|input\.([A-Za-z0-9_.]+)\s*==\s*null`)

// enforcedInputs lists the input paths whose absence a behavior refuses: an
// if (or when) condition testing !has(input.X) or input.X == null whose then
// branch fails.
func enforcedInputs(ifc *model.Interface) map[string]bool {
	out := map[string]bool{}
	walkConfSteps(ifc.Behavior, func(s model.Step) {
		cond := s.If
		if cond == "" {
			cond = s.When
		}
		if cond == "" {
			return
		}
		fails := len(s.Fail) > 0
		walkConfSteps(s.Then, func(t model.Step) {
			if len(t.Fail) > 0 {
				fails = true
			}
		})
		if !fails {
			return
		}
		for _, m := range absentInput.FindAllStringSubmatch(cond, -1) {
			p := m[1]
			if p == "" {
				p = m[2]
			}
			out[p] = true
		}
	})
	return out
}

// sharedSchemaName is the schema id a request or response refers to, or "".
func sharedSchemaName(v any) string {
	switch t := v.(type) {
	case string:
		return strings.TrimPrefix(t, "#/schemas/")
	case map[string]any:
		if r, ok := t["$ref"].(string); ok && len(t) == 1 {
			return strings.TrimPrefix(r, "#/schemas/")
		}
	}
	return ""
}

// effectiveStatuses returns the error statuses an interface can answer
// with: its declared errors, its fail steps' statuses, and the same of every
// interface it calls, transitively (on_error handling is not modeled here).
func effectiveStatuses(root *model.Interface, ifaces map[string]*model.Interface) map[int]bool {
	out := map[int]bool{}
	seen := map[string]bool{}
	var visit func(f *model.Interface, depth int)
	visit = func(f *model.Interface, depth int) {
		if f == nil || seen[f.ID] || depth > 12 {
			return
		}
		seen[f.ID] = true
		for _, e := range f.Errors {
			if e.Status > 0 {
				out[e.Status] = true
			}
		}
		walkConfSteps(f.Behavior, func(s model.Step) {
			if len(s.Fail) > 0 {
				var fs struct {
					Status any `json:"status"`
				}
				if json.Unmarshal(s.Fail, &fs) == nil {
					if n, ok := fs.Status.(float64); ok {
						out[int(n)] = true
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

func walkConfSteps(steps []model.Step, fn func(model.Step)) {
	for _, s := range steps {
		fn(s)
		walkConfSteps(s.Then, fn)
		walkConfSteps(s.Else, fn)
		walkConfSteps(s.Steps, fn)
		for _, b := range s.Branches {
			walkConfSteps(b, fn)
		}
		for _, k := range sortedKeys(s.Options) {
			walkConfSteps(s.Options[k], fn)
		}
		if s.OnError != nil {
			walkConfSteps(s.OnError.Steps, fn)
		}
		walkConfSteps(s.OnLate, fn)
		walkConfSteps(s.OnItem, fn)
	}
}

// statusValues reads a response envelope's status: its const, enum or
// examples.
func statusValues(resp any, resolve func(string) (any, bool)) []int {
	var m map[string]any
	switch t := resp.(type) {
	case string:
		r, _ := resolve(t)
		m, _ = r.(map[string]any)
	case map[string]any:
		if r, ok := t["$ref"].(string); ok {
			x, _ := resolve(r)
			m, _ = x.(map[string]any)
		} else {
			m = t
		}
	}
	ps, _ := m["properties"].(map[string]any)
	st, _ := ps["status"].(map[string]any)
	var out []int
	add := func(v any) {
		if f, ok := v.(float64); ok {
			out = append(out, int(f))
		}
		if i, ok := v.(int); ok {
			out = append(out, i)
		}
	}
	if c, ok := st["const"]; ok {
		add(c)
	}
	if e, ok := st["enum"].([]any); ok {
		for _, v := range e {
			add(v)
		}
	}
	if len(out) == 0 {
		if e, ok := st["examples"].([]any); ok {
			for _, v := range e {
				add(v)
			}
		}
	}
	return out
}

func sortedInts(m map[int]bool) []int {
	out := make([]int, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Ints(out)
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// totals counts the issues by kind.
func (r *confReport) totals() (map[string]int, int) {
	t := map[string]int{}
	n := 0
	for _, o := range r.Ops {
		for _, is := range o.Issues {
			t[is.Kind]++
			n++
		}
	}
	t["orphan"] += len(r.Orphans)
	n += len(r.Orphans)
	return t, n
}

// print writes the report; it returns true when the issues exceed max (max
// < 0: no gate).
func (r *confReport) print(w io.Writer, max int, quiet bool) bool {
	var matched, clean, ambient, untReq, untResp, complex, unmodeled, u500, enf int
	for _, o := range r.Ops {
		u500 += o.undeclared500
		enf += o.enforced
		ambient += o.ambient
		untReq += o.untypedReq
		untResp += o.untypedResp
		complex += o.complex
		if o.Iface == "" {
			unmodeled++
			continue
		}
		matched++
		if len(o.Issues) == 0 {
			clean++
		}
	}
	if !quiet {
		for _, o := range r.Ops {
			if o.Iface == "" || len(o.Issues) == 0 {
				continue
			}
			name := o.ID
			if name == "" {
				name = "-"
			}
			fmt.Fprintf(w, "✗ conformance %s %s %s -> %s\n", name, o.Method, o.Path, o.Iface)
			if len(o.Also) > 0 {
				fmt.Fprintf(w, "    (also matched: %s)\n", strings.Join(o.Also, ", "))
			}
			for _, is := range o.Issues {
				fmt.Fprintf(w, "    %s: %s\n", is.Kind, is.Msg)
			}
		}
		for _, o := range r.Ops {
			if o.Iface == "" {
				for _, is := range o.Issues {
					fmt.Fprintf(w, "✗ conformance unmodeled: %s\n", is.Msg)
				}
			}
		}
		for _, is := range r.Orphans {
			fmt.Fprintf(w, "✗ conformance orphan route: %s\n", is.Msg)
		}
	}
	t, n := r.totals()
	var parts []string
	for _, k := range confKinds {
		parts = append(parts, fmt.Sprintf("%s %d", k, t[k]))
	}
	fmt.Fprintf(w, "conformance: %d operations, %d modeled (%d clean), %d unmodeled; %d issues: %s\n",
		len(r.Ops), matched, clean, unmodeled, n, strings.Join(parts, ", "))
	fmt.Fprintf(w, "conformance not compared: %d untyped request parts, %d untyped response bodies, %d undeclared x-headers, %d undeclared 500s, %d required fields the behavior enforces, skipped: complex %d; route interfaces on other components %d, client wrappers %d\n",
		untReq, untResp, ambient, u500, enf, complex, r.OutScope, r.Clients)
	if max >= 0 && n > max {
		fmt.Fprintf(w, "✗ conformance: %d issues, above --max-conformance-issues %d\n", n, max)
		return true
	}
	return false
}

// runConformance loads the specs (a relative path missing from the working
// directory is resolved against code), compares and prints. It returns true
// when the gate fails.
func runConformance(w io.Writer, doc *model.Document, paths []string, code string, max int, quiet bool) (bool, error) {
	var specs []*oaDoc
	for _, p := range paths {
		if _, err := os.Stat(p); err != nil && code != "" && !filepath.IsAbs(p) {
			p = filepath.Join(code, p)
		}
		d, err := loadOpenAPI(p)
		if err != nil {
			return false, err
		}
		specs = append(specs, d)
	}
	return conformance(doc, specs).print(w, max, quiet), nil
}
