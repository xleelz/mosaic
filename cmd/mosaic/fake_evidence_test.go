package main

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/xleelz/mosaic/pkg/api"
)

// Evidence endpoints of the fake server. Validation is the real wire type's.

func (o *fakeOnt) evidenceRev(sel string) (int, bool) {
	switch sel {
	case "", "draft":
		return 0, true
	case "latest":
		return len(o.revs), len(o.revs) > 0
	}
	n, err := strconv.Atoi(sel)
	return n, err == nil && n >= 1 && n <= len(o.revs)
}

func (f *fakeServer) putEvidence(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	sel := r.URL.Query().Get("rev")
	if sel == "" {
		sel = "latest"
	}
	n, ok := o.evidenceRev(sel)
	if !ok {
		writeErr(w, 404, "not_found", "no such revision", nil)
		return
	}
	if n == 0 {
		writeErr(w, 400, "bad_request", "evidence is stored on a revision", nil)
		return
	}
	var in api.Evidence
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeErr(w, 400, "bad_request", err.Error(), nil)
		return
	}
	in.Normalize(n)
	if issues := in.Validate(n); len(issues) > 0 {
		writeErr(w, 422, "invalid", "the evidence does not validate", issues)
		return
	}
	if o.evidence == nil {
		o.evidence = map[int]api.Evidence{}
	}
	o.evidence[n] = in
	writeJSON(w, 200, in)
}

func (f *fakeServer) getEvidence(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	n, ok := o.evidenceRev(r.URL.Query().Get("rev"))
	if !ok {
		writeErr(w, 404, "not_found", "no such revision", nil)
		return
	}
	from := n
	if n == 0 {
		from = len(o.revs)
	}
	for ; from >= 1; from-- {
		if ev, ok := o.evidence[from]; ok {
			ev.Revision = n
			writeJSON(w, 200, ev)
			return
		}
	}
	writeErr(w, 404, "not_found", "no evidence", nil)
}
