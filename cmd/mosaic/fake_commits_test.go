package main

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/pkg/api"
)

// Commit endpoints of the fake server (docs/DESIGN.md §10).

func (o *fakeOnt) revForSHA(sha string) int {
	n := 0
	for _, r := range o.revs {
		if r.rev.Source != nil && r.rev.Source.SHA == sha {
			n = r.rev.Number
		}
	}
	return n
}

func (o *fakeOnt) commitList() api.CommitList {
	out := api.CommitList{Repo: o.repo, Commits: []api.Commit{}}
	for _, c := range o.commits {
		c.Revision = o.revForSHA(c.SHA)
		if c.Revision > 0 {
			prev := map[ekey]json.RawMessage{}
			if c.Revision > 1 {
				prev = o.revs[c.Revision-2].ents
			}
			c.Changed = !sameEntities(prev, o.revs[c.Revision-1].ents)
		}
		out.Commits = append(out.Commits, c)
	}
	return out
}

func (f *fakeServer) importCommits(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	var req api.ImportCommits
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || len(req.Commits) == 0 {
		writeErr(w, 400, "bad_request", "commits are required", nil)
		return
	}
	o.repo = req.Repo
	for _, c := range req.Commits {
		found := false
		for i := range o.commits {
			if o.commits[i].SHA == c.SHA {
				if c.URL == "" {
					c.URL = o.commits[i].URL // like the store, keep a stored url
				}
				o.commits[i], found = c, true
			}
		}
		if !found {
			o.commits = append(o.commits, c)
		}
	}
	writeJSON(w, 200, o.commitList())
}

func (f *fakeServer) listCommits(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	writeJSON(w, 200, o.commitList())
}

func (f *fakeServer) getCommit(w http.ResponseWriter, r *http.Request, o *fakeOnt) {
	prefix := r.PathValue("sha")
	list := o.commitList()
	var match []api.Commit
	for _, c := range list.Commits {
		if strings.HasPrefix(c.SHA, prefix) {
			match = append(match, c)
		}
	}
	switch {
	case len(prefix) < 7:
		writeErr(w, 400, "bad_request", "prefix too short", nil)
		return
	case len(match) == 0:
		writeErr(w, 404, "not_found", "no commit "+prefix, nil)
		return
	case len(match) > 1:
		writeErr(w, 409, "conflict", "commit prefix "+prefix+" is ambiguous", nil)
		return
	}
	c := match[0]
	d := api.CommitDetail{Commit: c, After: c.Revision, Before: o.revForSHA(c.Parent), Changes: []api.Change{}}
	before, after := &model.Document{}, &model.Document{}
	if d.Before > 0 {
		before, _ = document(o.revs[d.Before-1].ents)
	}
	if d.After > 0 {
		after, _ = document(o.revs[d.After-1].ents)
	}
	d.Impact = model.ComputeImpact(before, after)
	writeJSON(w, 200, d)
}
