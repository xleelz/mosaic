package sim

import (
	"fmt"
	"net/url"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Request-level addressing (§13.1 item 26): a call step whose call is a
// route object. The step's attempt resolves {host or component, method,
// path} against the callee's router, fills the matched interface's input from
// the headers, query, body and path parameters, and, with follow_redirects,
// follows 3xx responses that carry a location header.

// routeReq is one hop of a route call.
type routeReq struct {
	host, comp    string
	method, path  string
	query         string
	headers       map[string]any // keys in lower case
	body          any
	hasBody       bool
	match         model.RouteMatch
	cleanTo       string // the router redirects to this cleaned path
	cleanStatus   int
	fail          *Error // the request could not be addressed
	redirects     []any  // the hops followed so far
	firstInstance bool   // this hop goes to the component the step's on names
	depth         int    // the calling frame's depth, for a streamed call (§15.3)
	exit          *exit  // an exit from a streamed call's on_item steps (§15.3)
}

func (q *routeReq) line() string {
	s := q.method + " "
	if q.host != "" {
		s += q.host
	}
	s += q.path
	if q.query != "" {
		s += "?" + q.query
	}
	return s
}

// routeRequest evaluates a route call's fields and resolves its first hop.
func (r *run) routeRequest(s model.Step, act map[string]any, p string) (*routeReq, error) {
	rc := s.Route
	p += ".call"
	str := func(name, v string) (string, error) {
		src, ok := expr.ExprOf(v)
		if !ok {
			return v, nil
		}
		out, err := expr.Behavior.Eval(src, act)
		if err != nil {
			return "", abortf("%s.%s: %v", p, name, err)
		}
		o, ok := out.(string)
		if !ok {
			return "", abortf("%s.%s: must give a string, got %T", p, name, out)
		}
		return o, nil
	}
	tpl := func(name string, raw []byte) (any, error) {
		if raw == nil {
			return nil, nil
		}
		t, err := expr.DecodeTemplate(raw)
		if err != nil {
			return nil, abortf("%s.%s: %v", p, name, err)
		}
		v, err := expr.Behavior.Template(t, act)
		if err != nil {
			return nil, abortf("%s.%s: %v", p, name, err)
		}
		return v, nil
	}
	q := &routeReq{headers: map[string]any{}, firstInstance: true}
	var err error
	var host, comp, path string
	if host, err = str("host", rc.Host); err != nil {
		return nil, err
	}
	if comp, err = str("component", rc.Component); err != nil {
		return nil, err
	}
	if q.method, err = str("method", rc.Method); err != nil {
		return nil, err
	}
	if q.method = strings.ToUpper(q.method); q.method == "" {
		q.method = "GET"
	}
	if path, err = str("path", rc.Path); err != nil {
		return nil, err
	}
	h, err := tpl("headers", rc.Headers)
	if err != nil {
		return nil, err
	}
	if h != nil {
		hm, ok := h.(map[string]any)
		if !ok {
			return nil, abortf("%s.headers: must give an object, got %T", p, h)
		}
		for k, v := range hm {
			q.headers[strings.ToLower(k)] = v
		}
	}
	if q.body, err = tpl("body", rc.Body); err != nil {
		return nil, err
	}
	q.hasBody = rc.Body != nil
	u, perr := url.Parse(path)
	if perr != nil {
		q.fail = &Error{Code: "invalid_request", Message: fmt.Sprintf("invalid path %q: %v", path, perr)}
		return q, nil
	}
	if u.Host != "" {
		host, comp = u.Host, ""
	}
	q.path, q.query = u.EscapedPath(), u.RawQuery
	if !strings.HasPrefix(q.path, "/") {
		q.path = "/" + q.path
	}
	r.address(q, host, comp)
	return q, nil
}

// address points a hop at a host or component and resolves its route.
func (r *run) address(q *routeReq, host, comp string) {
	q.host, q.comp = host, comp
	q.fail, q.cleanTo, q.match = nil, "", model.RouteMatch{}
	if comp == "" {
		c, ok := r.x.HostComponent(host)
		if !ok {
			q.fail = &Error{Code: "unknown_host", Message: fmt.Sprintf("no component serves host %q", host)}
			return
		}
		q.comp = c
	} else if _, ok := r.x.Components[comp]; !ok {
		q.fail = &Error{Code: "invalid_target", Message: fmt.Sprintf("unknown component %q", comp)}
		return
	}
	spec := r.x.Router(q.comp)
	if spec.CleanPath != 0 {
		if c := model.CleanPath(q.path); c != q.path {
			q.cleanTo, q.cleanStatus = c, spec.CleanPath
			return
		}
	}
	q.match = r.x.ResolveRoute(q.comp, q.method, q.path)
}

// routeInput builds the matched interface's input: the callee's fake request
// with fill, under the request (each header at its HeaderKey, the query
// under query, the body under body, each path parameter at its ParamKey,
// and request: {method, path, host, headers, pattern}), under the step's
// input.
func (r *run) routeInput(q *routeReq, s model.Step, inputTpl any, act map[string]any, p string) (any, error) {
	callee := r.x.Interfaces[q.match.Interface]
	in := map[string]any{}
	var reqSchema map[string]any
	if callee != nil {
		reqSchema, _ = r.x.ResolveSchema(callee.Request)
	}
	for _, k := range sortedHeaderKeys(q.headers) {
		in[model.HeaderKey(k)] = deepCopy(q.headers[k])
	}
	if q.query != "" {
		vals, _ := url.ParseQuery(q.query)
		qm := map[string]any{}
		for k, v := range vals {
			if len(v) > 0 {
				qm[k] = v[0]
			}
		}
		in["query"] = qm
	}
	if q.hasBody {
		in["body"] = deepCopy(q.body)
	}
	for k, v := range q.match.Params {
		in[model.ParamKey(k, reqSchema)] = v
	}
	in["request"] = map[string]any{"method": q.method, "path": q.path, "host": q.host, "headers": deepCopy(q.headers),
		"pattern": q.match.Pattern}
	var out any = in
	if s.Fill && callee != nil {
		out = deepMerge(r.fake(callee.Request), in)
	}
	if s.Input != nil {
		v, err := expr.Behavior.Template(inputTpl, act)
		if err != nil {
			return nil, abortf("%s.input: %v", p, err)
		}
		out = deepMerge(out, v)
	}
	return out, nil
}

func sortedHeaderKeys(m map[string]any) []string {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}

// routeInvoke runs a route call's attempt: its hops, each traced by a route
// event, following redirects when the step asks.
func (r *run) routeInvoke(f *frame, s model.Step, q *routeReq, cs callSpec, tok string, inputTpl any, act map[string]any, p string) (callResult, error) {
	rc := s.Route
	limit := rc.MaxRedirects
	if limit <= 0 {
		limit = model.DefaultMaxRedirects
	}
	for hop := 0; ; hop++ {
		if hop > 0 {
			cs.callID = r.nextCall()
			cs.target = q.match.Interface
			var err error
			if cs.target != "" {
				if cs.input, err = r.routeInput(q, s, inputTpl, act, p); err != nil {
					return callResult{}, err
				}
			}
			on := ""
			if q.firstInstance {
				on = s.On
			}
			if cs.inst, cs.badInst, err = r.targetInstance(f.comp, f.inst, cs.target, on, expr.Behavior, act); err != nil {
				return callResult{}, abortf("%s.on: %v", p, err)
			}
		}
		ev := Event{Type: "route", Span: cs.parent, Call: cs.callID, Component: cs.from, From: cs.from, To: q.comp,
			Interface: q.match.Interface, Attempt: cs.attempt, Instance: cs.fromInst, Message: q.line(), Key: q.match.Pattern,
			Input: map[string]any{"method": q.method, "path": q.path, "query": q.query, "host": q.host}}
		var res callResult
		switch {
		case q.fail != nil:
			res = callResult{err: q.fail}
			ev.Error = q.fail
		case q.cleanTo != "":
			loc := q.cleanTo
			if q.query != "" {
				loc += "?" + q.query
			}
			res = callResult{ok: true, value: map[string]any{"status": int64(q.cleanStatus), "headers": map[string]any{"location": loc}}}
			ev.Output = deepCopy(res.value)
		case q.match.Interface == "":
			e := &Error{Code: q.match.Code, Status: q.match.Status, Message: fmt.Sprintf("%s: no route on %s", q.line(), q.comp)}
			res = callResult{err: e}
			ev.Error = e
		}
		if err := r.ev(ev); err != nil {
			return callResult{}, err
		}
		if q.fail == nil && q.cleanTo == "" && q.match.Interface != "" {
			var err error
			switch {
			case s.Stream: // a route call may stream (§15.3)
				res, q.exit, err = r.invokeStream(f, s, tok, cs, q.depth, p)
				if err == nil && q.exit != nil {
					return res, nil
				}
			case tok != "" || cs.session != "":
				res, err = r.invokeBound(tok, cs)
			default:
				res, err = r.invoke(cs)
			}
			if err != nil {
				return callResult{}, err
			}
		}
		if !rc.FollowRedirects || !res.ok {
			return res, nil
		}
		status, loc, ok := redirectOf(res.value)
		if !ok {
			return res, nil
		}
		if hop >= limit {
			return callResult{err: &Error{Code: "too_many_redirects", Message: fmt.Sprintf("stopped after %d redirects", limit)}, target: res.target}, nil
		}
		q.redirects = append(q.redirects, map[string]any{"status": status, "location": loc, "method": q.method, "path": q.path,
			"interface": res.target})
		if err := r.nextHop(q, status, loc); err != nil {
			return callResult{err: err, target: res.target}, nil
		}
	}
}

// redirectOf reads a 3xx response with a location header.
func redirectOf(v any) (int64, string, bool) {
	m, ok := v.(map[string]any)
	if !ok {
		return 0, "", false
	}
	st, ok := toInt(m["status"])
	if !ok || st < 300 || st > 399 {
		return 0, "", false
	}
	hs, _ := m["headers"].(map[string]any)
	for k, x := range hs {
		if strings.EqualFold(k, "location") {
			if s, ok := x.(string); ok && s != "" {
				return st, s, true
			}
		}
	}
	return 0, "", false
}

// nextHop points the request at a redirect's location, as Go's http.Client
// does: 301, 302 and 303 turn a request other than GET or HEAD into a
// bodiless GET; a hop to another host drops authorization and cookie.
func (r *run) nextHop(q *routeReq, status int64, loc string) *Error {
	base := &url.URL{Path: q.path, RawQuery: q.query}
	if p, err := url.Parse(q.path); err == nil {
		base = p
		base.RawQuery = q.query
	}
	if q.host != "" {
		base.Scheme, base.Host = "http", q.host
	}
	u, err := url.Parse(loc)
	if err != nil {
		return &Error{Code: "invalid_redirect", Message: fmt.Sprintf("invalid location %q: %v", loc, err)}
	}
	n := base.ResolveReference(u)
	if (status == 301 || status == 302 || status == 303) && q.method != "GET" && q.method != "HEAD" {
		q.method, q.body, q.hasBody = "GET", nil, false
	}
	q.path, q.query = n.EscapedPath(), n.RawQuery
	if q.path == "" {
		q.path = "/"
	}
	host, comp := q.host, q.comp
	if n.Host != "" && !strings.EqualFold(n.Host, q.host) {
		host, comp = n.Host, ""
		delete(q.headers, "authorization")
		delete(q.headers, "cookie")
	}
	before := q.comp
	r.address(q, host, comp)
	if q.comp != before {
		q.firstInstance = false
	}
	return nil
}

// summary is the route an attempt took, as vars.<as>.route.
func (q *routeReq) summary() map[string]any {
	out := map[string]any{"method": q.method, "path": q.path, "host": q.host, "component": q.comp,
		"interface": q.match.Interface, "pattern": q.match.Pattern, "redirects": q.redirects}
	if q.redirects == nil {
		out["redirects"] = []any{}
	}
	if q.query != "" {
		out["query"] = q.query
	}
	return out
}
