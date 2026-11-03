package model

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestMatchPath(t *testing.T) {
	cases := []struct {
		pattern, path string
		ok            bool
		params        map[string]string
	}{
		{"/v1", "/v1", true, map[string]string{}},
		{"/v1", "/v1/", false, nil},
		{"/v1/vms/{id}", "/v1/vms/a%2Fb", true, map[string]string{"id": "a/b"}},
		{"/v1/vms/{id}", "/v1/vms/", false, nil},
		{"/v1/vms/:id", "/v1/vms/x", true, map[string]string{"id": "x"}},
		{"/v1/endpoints/{id}/{path...}", "/v1/endpoints/e1/a/b", true, map[string]string{"id": "e1", "path": "a/b"}},
		{"/v1/endpoints/{id}/{path...}", "/v1/endpoints/e1/", true, map[string]string{"id": "e1", "path": ""}},
		{"/static/", "/static/a/b", true, map[string]string{}},
		{"/static/{$}", "/static/", true, map[string]string{}},
		{"/static/{$}", "/static/a", false, nil},
		{"/", "/anything", true, map[string]string{}},
	}
	for _, c := range cases {
		params, _, ok := MatchPath(c.pattern, c.path)
		if ok != c.ok {
			t.Errorf("%s ~ %s: ok %v, want %v", c.pattern, c.path, ok, c.ok)
			continue
		}
		if ok && len(params) != len(c.params) {
			t.Errorf("%s ~ %s: params %v, want %v", c.pattern, c.path, params, c.params)
		}
		for k, v := range c.params {
			if params[k] != v {
				t.Errorf("%s ~ %s: %s = %q, want %q", c.pattern, c.path, k, params[k], v)
			}
		}
	}
}

const routesModelDoc = `
schema_version: 1
components:
  - {id: cp, router: {hosts: [api.test]}}
  - {id: cp-a, parent: cp}
  - {id: cli}
interfaces:
  - {component: cp-a, name: any-root, attributes: {method: ANY, path: /}}
  - {component: cp-a, name: get-x, attributes: {method: GET, path: "/v1/x/{id}"}}
  - {component: cp-a, name: get-x-me, attributes: {method: GET, path: /v1/x/me}}
  - {component: cp-a, name: any-x, attributes: {method: ANY, path: "/v1/x/{id}"}}
  - {component: cp-a, name: go-style, attributes: {path: "DELETE /v1/y/{id}"}}
  - {component: cp-a, name: not-a-route, attributes: {method: ANY, path: "run.* hosts"}}
  - component: cli
    name: run
    behavior:
      - call: {host: api.test, method: GET, path: /v1/x/me, follow_redirects: true}
        targets: [cp-a.get-x-me]
`

func TestResolveRoute(t *testing.T) {
	d, err := ParseDocument([]byte(routesModelDoc))
	if err != nil {
		t.Fatal(err)
	}
	x := NewIndex(d)
	for _, c := range []struct{ method, path, want string }{
		{"GET", "/v1/x/me", "cp-a.get-x-me"},
		{"GET", "/v1/x/7", "cp-a.get-x"},
		{"head", "/v1/x/7", "cp-a.get-x"},
		{"POST", "/v1/x/7", "cp-a.any-x"},
		{"DELETE", "/v1/y/7", "cp-a.go-style"},
		{"GET", "/v1/y/7", "cp-a.any-root"},
	} {
		if m := x.ResolveRoute("cp", c.method, c.path); m.Interface != c.want {
			t.Errorf("%s %s: %+v, want %s", c.method, c.path, m, c.want)
		}
	}
	if _, ok := RouteOf(x.Interfaces["cp-a.not-a-route"]); ok {
		t.Error("a path that does not start with / is not a route")
	}
	if c, ok := x.HostComponent("API.test:8443"); !ok || c != "cp" {
		t.Errorf("host: %q %v", c, ok)
	}
	for _, is := range Validate(d) {
		if is.Severity == SeverityError {
			t.Errorf("%s: %s", is.Path, is.Message)
		}
	}
	// The route object survives a round trip under call.
	b, err := json.Marshal(d.Interfaces[len(d.Interfaces)-1].Behavior)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), `"call":{"host":"api.test","method":"GET","path":"/v1/x/me","follow_redirects":true}`) {
		t.Errorf("marshal: %s", b)
	}
	var back []Step
	if err := Decode(b, &back); err != nil || back[0].Route == nil || back[0].Route.Path != "/v1/x/me" || back[0].Call != "" {
		t.Errorf("round trip: %v %+v", err, back)
	}
}

func TestRouteValidation(t *testing.T) {
	src := `
schema_version: 1
components:
  - {id: cp, router: {clean_path: 200, fallback: cp.nope}}
  - {id: cli}
interfaces:
  - component: cli
    name: run
    behavior:
      - call: {host: a.test, component: cp, path: /x}
      - call: {component: cp, path: x}
      - call: {component: cp, path: /x, max_redirects: 2}
      - call: {component: ghost, path: /x}
`
	d, err := ParseDocument([]byte(src))
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, is := range Validate(d) {
		if is.Severity == SeverityError {
			got = append(got, is.Path+": "+is.Message)
		}
	}
	all := strings.Join(got, "\n")
	for _, want := range []string{"router.clean_path", "router.fallback", "behavior[0].call: a route call names a host or a component",
		"behavior[1].call.path", "behavior[2].call.max_redirects", "behavior[3].call.component"} {
		if !strings.Contains(all, want) {
			t.Errorf("missing %q in:\n%s", want, all)
		}
	}
	if _, err := ParseDocument([]byte(strings.Replace(src, "path: /x}\n      - call: {component: cp, path: x}", "path: /x, bogus: 1}\n      - call: {component: cp, path: x}", 1))); err == nil {
		t.Error("an unknown key in a route call must fail to decode")
	}
}
