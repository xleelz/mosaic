package model

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/url"
	"path"
	"sort"
	"strings"
	"unicode"

	"github.com/xleelz/mosaic/internal/expr"
)

// Request-level addressing (§13.1 item 26). A call step's call may be an
// object instead of an interface id: a request to a host or component with a
// method and a path, which the callee's router resolves to the interface
// whose attributes.method and attributes.path match.

// RouteCall is a call addressed by route: {host or component, method, path,
// headers, body}. Host, Component, Method and Path are literals or "=cel";
// Headers and Body are templates. Path may carry a query ("/v1/x?a=b") and
// may be an absolute URL, whose host then addresses the call.
type RouteCall struct {
	Host      string          `json:"host,omitempty"`
	Component string          `json:"component,omitempty"`
	Method    string          `json:"method,omitempty"` // default GET
	Path      string          `json:"path"`
	Headers   json.RawMessage `json:"headers,omitempty"`
	Body      json.RawMessage `json:"body,omitempty"`
	// FollowRedirects makes the caller follow a 3xx response that carries a
	// location header, up to MaxRedirects hops (default 10).
	FollowRedirects bool `json:"follow_redirects,omitempty"`
	MaxRedirects    int  `json:"max_redirects,omitempty"`
}

// DefaultMaxRedirects is the hop limit of a call that follows redirects
// without max_redirects (Go's http.Client stops after 10).
const DefaultMaxRedirects = 10

// RouterSpec describes how a component answers route calls (§13.1 item 26).
// Its routes are the interfaces of the component and of its descendants that
// carry attributes.path (and attributes.method).
type RouterSpec struct {
	// Hosts are the host names that address the component: exact names or
	// "*.suffix" wildcards; a port in the request host is ignored.
	Hosts []string `json:"hosts,omitempty"`
	// Fallback is an interface that receives the requests no route matches.
	Fallback string `json:"fallback,omitempty"`
	// NotFound is the error code of an unmatched request (status 404),
	// "not_found" by default; MethodNotAllowed the code when the path
	// matches but the method does not (status 405), "method_not_allowed"
	// by default.
	NotFound         string `json:"not_found,omitempty"`
	MethodNotAllowed string `json:"method_not_allowed,omitempty"`
	// CleanPath, a 3xx status, makes the router answer a request whose path
	// has "." or ".." segments or repeated slashes with that status and a
	// location of the cleaned path, as Go's ServeMux does.
	CleanPath int `json:"clean_path,omitempty"`
}

// UnmarshalJSON decodes a step whose call is either an interface id or a
// route object.
func (s *Step) UnmarshalJSON(b []byte) error {
	type plain Step
	var aux struct {
		plain
		Call json.RawMessage `json:"call,omitempty"`
	}
	if err := Decode(b, &aux); err != nil {
		return err
	}
	*s = Step(aux.plain)
	raw := bytes.TrimSpace(aux.Call)
	switch {
	case len(raw) == 0 || bytes.Equal(raw, []byte("null")):
	case raw[0] == '"':
		if err := json.Unmarshal(raw, &s.Call); err != nil {
			return err
		}
	case raw[0] == '{':
		var rc RouteCall
		if err := Decode(raw, &rc); err != nil {
			return fmt.Errorf("call: %w", err)
		}
		s.Route = &rc
	default:
		return fmt.Errorf("call must be an interface id or a route {host or component, method, path}")
	}
	return nil
}

// MarshalJSON encodes a route call back under call.
func (s Step) MarshalJSON() ([]byte, error) {
	type plain Step
	if s.Route == nil {
		return json.Marshal(plain(s))
	}
	return json.Marshal(struct {
		plain
		Call *RouteCall `json:"call"`
	}{plain(s), s.Route})
}

// Route is an interface's route: its methods (empty means any) and its path
// pattern, from attributes.method and attributes.path.
type Route struct {
	Interface string
	Methods   []string
	Pattern   string
}

// RouteOf reads an interface's route. attributes.path must start with "/"
// (a Go 1.22 "METHOD /path" pattern is accepted too); attributes.method is a
// method, a list of methods, or "ANY" or "*" for any method.
func RouteOf(f *Interface) (Route, bool) {
	if f == nil || f.Attributes == nil {
		return Route{}, false
	}
	p, _ := f.Attributes["path"].(string)
	p = strings.TrimSpace(p)
	rt := Route{Interface: f.ID}
	if m, rest, ok := strings.Cut(p, " "); ok && !strings.HasPrefix(p, "/") {
		rt.Methods = []string{strings.ToUpper(m)}
		p = strings.TrimSpace(rest)
	}
	if !strings.HasPrefix(p, "/") {
		return Route{}, false
	}
	rt.Pattern = p
	add := func(m string) {
		m = strings.ToUpper(strings.TrimSpace(m))
		if m == "ANY" || m == "*" || m == "" {
			rt.Methods = nil
			return
		}
		rt.Methods = append(rt.Methods, m)
	}
	switch m := f.Attributes["method"].(type) {
	case string:
		if len(rt.Methods) == 0 {
			add(m)
		}
	case []any:
		for _, v := range m {
			if s, ok := v.(string); ok {
				add(s)
				if rt.Methods == nil {
					break
				}
			}
		}
	}
	return rt, true
}

// allows reports whether the route accepts the method; a GET route also
// answers HEAD.
func (rt Route) allows(method string) bool {
	if len(rt.Methods) == 0 {
		return true
	}
	for _, m := range rt.Methods {
		if m == method || (m == "GET" && method == "HEAD") {
			return true
		}
	}
	return false
}

// MatchPath matches a request path against a pattern. Segments are
// literals, "{name}" or ":name" (one segment), "{name...}" (the rest, maybe
// empty) or "{$}" (the end, after a trailing slash); a pattern ending in "/"
// matches every path under it. It returns the path parameters and a rank:
// a higher rank is a more specific match.
func MatchPath(pattern, reqPath string) (map[string]string, []int, bool) {
	ps := strings.Split(strings.TrimPrefix(pattern, "/"), "/")
	rs := strings.Split(strings.TrimPrefix(reqPath, "/"), "/")
	params := map[string]string{}
	var rank []int
	prefix := strings.HasSuffix(pattern, "/") && pattern != "/" && !strings.HasSuffix(pattern, "{$}")
	if pattern == "/" {
		// "/" alone matches everything, least specifically.
		return params, []int{-1}, true
	}
	if prefix {
		ps = ps[:len(ps)-1]
	}
	for i, seg := range ps {
		if seg == "{$}" {
			if i == len(rs)-1 && rs[i] == "" {
				return params, append(rank, 3), true
			}
			return nil, nil, false
		}
		if name, ok := restParam(seg); ok && i == len(ps)-1 {
			if i < len(rs) {
				params[name] = unescape(strings.Join(rs[i:], "/"))
			} else if i == len(rs) {
				params[name] = ""
			} else {
				return nil, nil, false
			}
			return params, append(rank, 0), true
		}
		if i >= len(rs) {
			return nil, nil, false
		}
		if name, ok := oneParam(seg); ok {
			if rs[i] == "" {
				return nil, nil, false
			}
			params[name] = unescape(rs[i])
			rank = append(rank, 1)
			continue
		}
		if seg != rs[i] && seg != unescape(rs[i]) {
			return nil, nil, false
		}
		rank = append(rank, 2)
	}
	if len(rs) == len(ps) {
		return params, append(rank, 3), true
	}
	if prefix && len(rs) > len(ps) {
		return params, append(rank, 0), true
	}
	return nil, nil, false
}

func oneParam(seg string) (string, bool) {
	if strings.HasPrefix(seg, "{") && strings.HasSuffix(seg, "}") && !strings.HasSuffix(seg, "...}") && len(seg) > 2 {
		return seg[1 : len(seg)-1], true
	}
	if strings.HasPrefix(seg, ":") && len(seg) > 1 {
		return seg[1:], true
	}
	return "", false
}

func restParam(seg string) (string, bool) {
	if strings.HasPrefix(seg, "{") && strings.HasSuffix(seg, "...}") {
		return seg[1 : len(seg)-4], true
	}
	if seg == "*" {
		return "*", true
	}
	return "", false
}

func unescape(s string) string {
	if u, err := url.PathUnescape(s); err == nil {
		return u
	}
	return s
}

// RouteMatch is the outcome of resolving a request against a router.
type RouteMatch struct {
	Interface string            // the matched interface, or the fallback
	Pattern   string            // the matched pattern; empty for the fallback
	Params    map[string]string // the path parameters
	Fallback  bool              // the request went to the router's fallback
	// Status is 404 (no route) or 405 (no route for the method) when
	// Interface is empty, with Code the router's declared error code.
	Status int
	Code   string
}

// Routes lists the routes of a component and its descendants, sorted by
// interface id.
func (x *Index) Routes(comp string) []Route {
	var out []Route
	var walk func(c string, seen map[string]bool)
	walk = func(c string, seen map[string]bool) {
		if seen[c] {
			return
		}
		seen[c] = true
		for _, id := range x.ByComp[c] {
			if rt, ok := RouteOf(x.Interfaces[id]); ok {
				out = append(out, rt)
			}
		}
		for _, ch := range x.Children[c] {
			walk(ch, seen)
		}
	}
	walk(comp, map[string]bool{})
	sort.Slice(out, func(i, j int) bool { return out[i].Interface < out[j].Interface })
	return out
}

// Router returns a component's router spec, or the zero spec.
func (x *Index) Router(comp string) RouterSpec {
	if c, ok := x.Components[comp]; ok && c.Router != nil {
		return *c.Router
	}
	return RouterSpec{}
}

// ResolveRoute resolves a method and path (no query) against a component's
// routes: the most specific matching pattern wins (literal segments over
// parameters over rest parameters, then an explicit method over any), then
// the lower interface id.
func (x *Index) ResolveRoute(comp, method, reqPath string) RouteMatch {
	method = strings.ToUpper(method)
	if method == "" {
		method = "GET"
	}
	var best *Route
	var bestRank []int
	var bestParams map[string]string
	pathOnly := false
	for _, rt := range x.Routes(comp) {
		params, rank, ok := MatchPath(rt.Pattern, reqPath)
		if !ok {
			continue
		}
		if !rt.allows(method) {
			pathOnly = true
			continue
		}
		if len(rt.Methods) > 0 {
			rank = append(rank, 1)
		} else {
			rank = append(rank, 0)
		}
		if best == nil || rankLess(bestRank, rank) {
			r := rt
			best, bestRank, bestParams = &r, rank, params
		}
	}
	if best != nil {
		return RouteMatch{Interface: best.Interface, Pattern: best.Pattern, Params: bestParams}
	}
	spec := x.Router(comp)
	if spec.Fallback != "" {
		return RouteMatch{Interface: spec.Fallback, Fallback: true, Params: map[string]string{}}
	}
	if pathOnly {
		code := spec.MethodNotAllowed
		if code == "" {
			code = "method_not_allowed"
		}
		return RouteMatch{Status: 405, Code: code}
	}
	code := spec.NotFound
	if code == "" {
		code = "not_found"
	}
	return RouteMatch{Status: 404, Code: code}
}

// rankLess orders ranks segment by segment; a longer rank wins a tie.
func rankLess(a, b []int) bool {
	for i := 0; i < len(a) && i < len(b); i++ {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return len(a) < len(b)
}

// HostComponent finds the component a host addresses through its router's
// hosts: an exact name first, then the longest "*." wildcard, then the
// lower component id. A port is ignored.
func (x *Index) HostComponent(host string) (string, bool) {
	host = strings.ToLower(stripPort(host))
	best, bestLen := "", -1
	ids := make([]string, 0, len(x.Components))
	for id, c := range x.Components {
		if c.Router != nil && len(c.Router.Hosts) > 0 {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	for _, id := range ids {
		for _, h := range x.Components[id].Router.Hosts {
			h = strings.ToLower(stripPort(h))
			n := -1
			switch {
			case h == host:
				n = 1 << 20
			case strings.HasPrefix(h, "*.") && strings.HasSuffix(host, h[1:]):
				n = len(h)
			}
			if n > bestLen {
				best, bestLen = id, n
			}
		}
	}
	return best, bestLen >= 0
}

func stripPort(h string) string {
	if i := strings.LastIndex(h, ":"); i >= 0 && !strings.Contains(h[i:], "]") {
		return h[:i]
	}
	return h
}

// CleanPath is Go's ServeMux path cleaning: path.Clean, keeping a trailing
// slash.
func CleanPath(p string) string {
	if p == "" {
		return "/"
	}
	if p[0] != '/' {
		p = "/" + p
	}
	np := path.Clean(p)
	if p[len(p)-1] == '/' && np != "/" {
		np += "/"
	}
	return np
}

// ParamKey is the input key a path parameter fills: the parameter's name,
// or its snake_case form when the request schema declares only that one.
func ParamKey(name string, request map[string]any) string {
	props, _ := request["properties"].(map[string]any)
	if props == nil {
		return name
	}
	if _, ok := props[name]; ok {
		return name
	}
	if sn := snake(name); sn != name {
		if _, ok := props[sn]; ok {
			return sn
		}
	}
	return name
}

// HeaderKey is the input key a request header fills: lower case with
// dashes as underscores (X-Org-Id becomes x_org_id).
func HeaderKey(h string) string {
	return strings.ReplaceAll(strings.ToLower(h), "-", "_")
}

func snake(s string) string {
	var b strings.Builder
	for i, r := range s {
		if unicode.IsUpper(r) {
			if i > 0 {
				b.WriteByte('_')
			}
			b.WriteRune(unicode.ToLower(r))
			continue
		}
		if r == '-' {
			r = '_'
		}
		b.WriteRune(r)
	}
	return b.String()
}

// router checks a component's router spec.
func (v *validator) router(p string, c Component) {
	rs := c.Router
	if rs == nil {
		return
	}
	p += ".router"
	for i, h := range rs.Hosts {
		if strings.TrimSpace(h) == "" || strings.ContainsAny(h, "/ ") {
			v.errf(fmt.Sprintf("%s.hosts[%d]", p, i), "invalid host %q", h)
		} else if other, ok := v.x.HostComponent(h); ok && other != c.ID && !strings.HasPrefix(h, "*.") {
			v.warnf(fmt.Sprintf("%s.hosts[%d]", p, i), "host %q also addresses %q", h, other)
		}
	}
	if rs.Fallback != "" {
		v.interfaceRef(p+".fallback", rs.Fallback)
	}
	if rs.CleanPath != 0 && (rs.CleanPath < 300 || rs.CleanPath > 399) {
		v.errf(p+".clean_path", "clean_path must be a 3xx status")
	}
}

// route checks a call addressed by route.
func (v *validator) route(p string, s Step) {
	rc := s.Route
	p += ".call"
	if rc.MaxRedirects < 0 {
		v.errf(p+".max_redirects", "must not be negative")
	}
	if rc.MaxRedirects > 0 && !rc.FollowRedirects {
		v.errf(p+".max_redirects", "max_redirects goes with follow_redirects")
	}
	// A route call may stream (§15.3): stream: true with on_item, as for an
	// id call.
	v.rawTemplate(p+".headers", rc.Headers)
	v.rawTemplate(p+".body", rc.Body)
	dynamic := false
	for _, fld := range []struct{ name, val string }{{"host", rc.Host}, {"component", rc.Component}, {"method", rc.Method}, {"path", rc.Path}} {
		if src, ok := expr.ExprOf(fld.val); ok {
			v.expr(expr.Behavior, p+"."+fld.name, src)
			dynamic = true
		}
	}
	abs := strings.HasPrefix(rc.Path, "http://") || strings.HasPrefix(rc.Path, "https://")
	if (rc.Host != "") == (rc.Component != "") && !(abs && rc.Host == "" && rc.Component == "") {
		v.errf(p, "a route call names a host or a component (one of them)")
		return
	}
	if rc.Path == "" {
		v.errf(p+".path", "a route call needs a path")
		return
	}
	if dynamic {
		if len(s.Targets) == 0 {
			v.warnf(p, "a route call without targets cannot be followed by plans and graphs")
		}
		return
	}
	comp, host := rc.Component, rc.Host
	reqPath := rc.Path
	if abs {
		if u, err := url.Parse(rc.Path); err == nil {
			host, reqPath = u.Host, u.EscapedPath()
		}
	} else if !strings.HasPrefix(reqPath, "/") {
		v.errf(p+".path", "a path starts with /")
		return
	}
	reqPath, _, _ = strings.Cut(reqPath, "?")
	if comp != "" {
		if _, ok := v.x.Components[comp]; !ok {
			v.errf(p+".component", "unknown component %q", comp)
			return
		}
	} else {
		c, ok := v.x.HostComponent(host)
		if !ok {
			v.warnf(p+".host", "no component's router serves host %q: the call fails with unknown_host", host)
			return
		}
		comp = c
	}
	m := v.x.ResolveRoute(comp, rc.Method, reqPath)
	if len(s.Targets) == 0 {
		if m.Interface != "" {
			v.warnf(p, "add targets: [%s] so plans and graphs follow this route call", m.Interface)
		}
	}
}
