package model

import (
	"regexp"
	"strconv"
	"strings"
)

// headerRead finds an expectation's reads of a response header (§13.1
// item 35): steps.<as>.result.value.headers[...], steps[i].result.value
// .headers[...] and result.value.headers[...], with the header as a
// quoted index or a field.
var headerRead = regexp.MustCompile(`(?:steps\.([A-Za-z_]\w*)\.|steps\[\s*(\d+)\s*\]\.|(^|[^.\w]))result\.value\.headers(?:\[\s*(?:'([^']*)'|"([^"]*)")\s*\]|\.([A-Za-z_]\w*))`)

// expectHeaders warns when expectation e of scenario s reads a response
// header that the response schema of the interface it reads doesn't
// declare. Only a schema whose headers property lists properties is
// checked; a free-form headers object declares every header.
func (v *validator) expectHeaders(p string, s *Scenario, e string) {
	for _, m := range headerRead.FindAllStringSubmatch(e, -1) {
		header := m[4] + m[5] + m[6]
		if header == "" {
			continue
		}
		iface := ""
		switch {
		case m[1] != "":
			for _, st := range s.Steps {
				if st.As == m[1] {
					iface = v.stepInterface(st)
				}
			}
		case m[2] != "":
			if i, err := strconv.Atoi(m[2]); err == nil && i < len(s.Steps) {
				iface = v.stepInterface(s.Steps[i])
			}
		case len(s.Steps) > 0:
			iface = v.stepInterface(s.Steps[len(s.Steps)-1])
		default:
			if f, ok := v.x.Flows[s.Flow]; ok && f.Entry != nil {
				iface = f.Entry.Interface
			}
		}
		f, ok := v.x.Interfaces[iface]
		if !ok {
			continue
		}
		if !declaresHeader(v.x, f.Response, header) {
			v.warnf(p, "reads header %q, which the response schema of %s doesn't declare", header, iface)
		}
	}
}

// stepInterface is the interface a scenario step calls, or "".
func (v *validator) stepInterface(st ScenarioStep) string {
	if st.Interface != "" {
		return st.Interface
	}
	if f, ok := v.x.Flows[st.Flow]; ok && f.Entry != nil {
		return f.Entry.Interface
	}
	return ""
}

// declaresHeader reports whether a response schema declares a header, or
// can't be told not to: a schema without top-level properties, or with a
// headers object that lists none, declares every header.
func declaresHeader(x *Index, ref any, header string) bool {
	s, ok := x.ResolveSchema(ref)
	if !ok {
		return true
	}
	props, ok := s["properties"].(map[string]any)
	if !ok {
		return true
	}
	hs, ok := x.ResolveSchema(props["headers"])
	if !ok {
		return false
	}
	hp, ok := hs["properties"].(map[string]any)
	if !ok || len(hp) == 0 {
		return true
	}
	for k := range hp {
		if strings.EqualFold(k, header) {
			return true
		}
	}
	return false
}
