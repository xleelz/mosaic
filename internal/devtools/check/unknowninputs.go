package main

// The unknown-inputs lint (DESIGN §15.2): scenario, scenario-step and flow
// entry input keys that the target interface's request schema doesn't
// declare, at any depth. The simulator completes a request from the schema's
// fake defaults, so a misspelled or stale key (a caller still sending an old
// shape) is silently ignored while the faked field stands in for it.

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// unknownInputs walks literal inputs against request schema shapes.
type unknownInputs struct {
	x       *model.Index
	resolve func(string) (any, bool)
	shapes  map[string]*shape
	r       *integrityReport
	sc      shareCounter
}

func (u *unknownInputs) reqShape(id string) *shape {
	if s, ok := u.shapes[id]; ok {
		return s
	}
	var s *shape
	if i := u.x.Interfaces[id]; i != nil && i.Request != nil {
		s = buildShape(asJSON(i.Request), u.resolve, 0)
	}
	u.shapes[id] = s
	return s
}

// inputMarker reports an input marker ({$absent}, {$null}, {$bytes},
// {$bigint}, ...): a single key starting with "$" stands for a value.
func inputMarker(m map[string]any) bool {
	if len(m) != 1 {
		return false
	}
	for k := range m {
		return strings.HasPrefix(k, "$")
	}
	return false
}

// checkable reports whether a shape lists the keys an object may have: an
// object schema with properties, closed to others.
func checkable(s *shape) bool {
	return s != nil && !s.Complex && !s.Open && len(s.Names) > 0 && s.isObject()
}

// declared returns the declared name k matches exactly, or, with alias (a
// route interface's top-level keys), as a route-header alias: X-Org-Id for
// x_org_id, the key a route fills from the header.
func declared(s *shape, k string, alias bool) (string, bool) {
	for _, d := range s.Names {
		if d == k {
			return d, true
		}
	}
	if !alias {
		return "", false
	}
	hk := model.HeaderKey(k)
	for _, d := range s.Names {
		if d == hk || model.HeaderKey(d) == hk {
			return d, true
		}
	}
	return "", false
}

func (u *unknownInputs) walk(frag, subject, target, path string, v any, s *shape, depth int, route bool) {
	if depth > 16 || s == nil {
		return
	}
	switch t := v.(type) {
	case map[string]any:
		if inputMarker(t) || !checkable(s) {
			return
		}
		for _, k := range sortedKeys(t) {
			if strings.HasPrefix(k, "$") || headerAlias(k) {
				continue
			}
			kp := path + "." + k
			d, ok := declared(s, k, route && depth == 0)
			u.sc.add(frag, !ok)
			if ok {
				u.walk(frag, subject, target, kp, t[k], s.Props[normName(d)], depth+1, false)
				continue
			}
			why := fmt.Sprintf("%s: %s's request schema doesn't declare %q", kp, target, k)
			if d := s.Names[normName(k)]; d != "" {
				why += fmt.Sprintf(" (it declares %q)", d)
			} else {
				names := make([]string, 0, len(s.Names))
				for _, n := range s.Names {
					names = append(names, n)
				}
				sort.Strings(names)
				if len(names) > 8 {
					names = append(names[:8], "...")
				}
				why += " (declares " + strings.Join(names, ", ") + ")"
			}
			u.r.Findings = append(u.r.Findings, integrityFinding{"", frag, subject, why + "; a faked default stands in for the field it meant"})
		}
	case []any:
		if s.Items == nil {
			return
		}
		for i, x := range t {
			u.walk(frag, subject, target, fmt.Sprintf("%s[%d]", path, i), x, s.Items, depth+1, false)
		}
	}
}

func (u *unknownInputs) input(frag, subject, target string, raw json.RawMessage) {
	if len(raw) == 0 || target == "" {
		return
	}
	var v any
	if json.Unmarshal(raw, &v) != nil {
		return
	}
	_, route := model.RouteOf(u.x.Interfaces[target])
	u.walk(frag, subject, target, "input", v, u.reqShape(target), 0, route)
}

// lintUnknownInputs lists the input keys of scenarios (without steps: their
// flow's entry), scenario steps and flow entries that the target's request
// schema doesn't declare. Keys of an open or free-form object, x_* header
// aliases, route-header spellings of a declared key, "$" markers and "="
// expressions aren't checked. The share is over the input keys checked.
func lintUnknownInputs(doc *model.Document, origins map[string]string) *integrityReport {
	x := indexed(doc)
	u := &unknownInputs{x: x, shapes: map[string]*shape{}, sc: shareCounter{},
		r:       &integrityReport{Lint: "unknown-inputs", Unit: "input keys"},
		resolve: func(r string) (any, bool) { s, ok := x.ResolveSchema(r); return s, ok }}
	entry := func(flow string) string {
		if f, ok := x.Flows[flow]; ok && f.Entry != nil {
			return f.Entry.Interface
		}
		return ""
	}
	for _, f := range doc.Flows {
		if f.Entry != nil {
			u.input(origins[model.KindFlow+"/"+f.ID], "flow "+f.ID+" entry", f.Entry.Interface, f.Entry.Input)
		}
	}
	for _, sc := range doc.Scenarios {
		frag := origins[model.KindScenario+"/"+sc.ID]
		if len(sc.Steps) == 0 {
			u.input(frag, "scenario "+sc.ID, entry(sc.Flow), sc.Input)
		}
		for i, st := range sc.Steps {
			if st.IsControl() {
				continue
			}
			target := st.Interface
			if target == "" {
				target = entry(st.Flow)
			}
			u.input(frag, fmt.Sprintf("scenario %s step %d", sc.ID, i), target, st.Input)
		}
	}
	u.r.finish(u.sc)
	return u.r
}
