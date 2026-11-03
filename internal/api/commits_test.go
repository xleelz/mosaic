package api_test

import (
	"strings"
	"testing"
	"time"

	"github.com/xleelz/mosaic/internal/model"
	wire "github.com/xleelz/mosaic/pkg/api"
)

func hash(prefix string) string { return prefix + strings.Repeat("0", 40-len(prefix)) }

func TestCommitsAndImpact(t *testing.T) {
	id := "commits-api"
	newOntology(t, id, true)
	base := "/v1/ontologies/" + id
	t0 := time.Date(2026, 3, 1, 9, 0, 0, 0, time.UTC)
	c1, c2, c3, c4 := hash("abcdef01"), hash("abcdef02"), hash("1234567"), hash("fedcba9")

	list := decode[wire.CommitList](t, call(t, "POST", base+"/commits", wire.ImportCommits{Repo: "/repo", Commits: []wire.Commit{
		{SHA: c1, Subject: "one", Date: t0, Files: []string{"gw/main.go"}},
		{SHA: c2, Parent: c1, Subject: "two", Date: t0.Add(time.Minute), Files: []string{"gw/route.go"}, URL: "https://git.example/" + c2},
		{SHA: c3, Parent: c2, Subject: "three", Date: t0.Add(2 * time.Minute), Files: []string{"README.md"}},
		{SHA: c4, Parent: c3, Subject: "four", Date: t0.Add(3 * time.Minute)},
	}}, 200))
	if list.Repo != "/repo" || len(list.Commits) != 4 || list.Commits[0].Revision != 0 {
		t.Fatalf("imported = %+v", list)
	}
	if e := errCode(t, call(t, "POST", base+"/commits", `{"repo":"r","commits":[{"sha":"nothex"}]}`, 400)); e.Code != "bad_request" {
		t.Fatalf("bad sha: %+v", e)
	}

	src := func(sha, parent string) *wire.CommitSource {
		return &wire.CommitSource{Repo: "/repo", SHA: sha, Parent: parent, Subject: "s", URL: "https://example.com/" + sha}
	}
	r1 := decode[wire.Revision](t, call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "one", Source: src(c1, "")}, 201))
	if r1.Source == nil || r1.Source.SHA != c1 || r1.Source.URL == "" {
		t.Fatalf("r1 = %+v", r1)
	}
	call(t, "PATCH", base+"/components/throttle", `{"name":"Throttle v2"}`, 200)
	call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "two", Source: src(c2, c1)}, 201)
	if e := errCode(t, call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "three", Source: src(c3, c2)}, 409)); e.Code != "conflict" {
		t.Fatalf("unchanged: %+v", e)
	}
	r3 := decode[wire.Revision](t, call(t, "POST", base+"/revisions", wire.CreateRevision{Message: "three", Source: src(c3, c2), AllowEmpty: true}, 201))
	if r3.Number != 3 {
		t.Fatalf("r3 = %+v", r3)
	}
	got := decode[wire.Revision](t, call(t, "GET", base+"/revisions/2", nil, 200))
	if got.Source == nil || got.Source.SHA != c2 || got.Source.Parent != c1 || got.Message != "two" {
		t.Fatalf("revision 2 = %+v", got)
	}
	revs := decode[wire.RevisionList](t, call(t, "GET", base+"/revisions", nil, 200))
	if len(revs.Revisions) != 3 || revs.Revisions[2].Source == nil || revs.Revisions[2].Source.SHA != c3 {
		t.Fatalf("revisions = %+v", revs)
	}

	list = decode[wire.CommitList](t, call(t, "GET", base+"/commits", nil, 200))
	want := []struct {
		sha     string
		rev     int
		changed bool
	}{{c1, 1, true}, {c2, 2, true}, {c3, 3, false}, {c4, 0, false}}
	for i, w := range want {
		c := list.Commits[i]
		if c.SHA != w.sha || c.Revision != w.rev || c.Changed != w.changed || (c.URL != "") != (w.sha == c2) {
			t.Fatalf("commit %d = %+v, want %+v", i, c, w)
		}
	}

	d := decode[wire.CommitDetail](t, call(t, "GET", base+"/commits/"+c2[:8], nil, 200))
	if d.Commit.SHA != c2 || d.Commit.URL != "https://git.example/"+c2 || d.Before != 1 || d.After != 2 || d.Impact == nil {
		t.Fatalf("c2 detail = %+v", d)
	}
	if len(d.Changes) != 1 || d.Changes[0].Kind != model.KindComponent || d.Changes[0].ID != "throttle" || d.Changes[0].Change != "modified" {
		t.Fatalf("c2 changes = %+v", d.Changes)
	}
	d = decode[wire.CommitDetail](t, call(t, "GET", base+"/commits/"+c3, nil, 200))
	if d.Before != 2 || d.After != 3 || len(d.Changes) != 0 {
		t.Fatalf("c3 detail = %+v", d)
	}
	// c4 has no revision: before falls back to the nearest earlier one.
	d = decode[wire.CommitDetail](t, call(t, "GET", base+"/commits/"+c4[:7], nil, 200))
	if d.Before != 3 || d.After != 0 || len(d.Changes) != 0 || d.Impact == nil {
		t.Fatalf("c4 detail = %+v", d)
	}
	if e := errCode(t, call(t, "GET", base+"/commits/abcdef0", nil, 409)); e.Code != "conflict" {
		t.Fatalf("ambiguous: %+v", e)
	}
	call(t, "GET", base+"/commits/abc", nil, 400)
	call(t, "GET", base+"/commits/0000000", nil, 404)
	call(t, "GET", "/v1/ontologies/nope/commits", nil, 404)

	im := decode[model.Impact](t, call(t, "GET", base+"/impact?from=1&to=2", nil, 200))
	_ = im                                   // the shape is model.Impact; its contents belong to model.ComputeImpact's tests
	call(t, "GET", base+"/impact", nil, 200) // latest to draft
	call(t, "GET", base+"/impact?from=base&to=latest", nil, 200)
	call(t, "GET", base+"/impact?from=7", nil, 404)
	call(t, "GET", base+"/impact?to=x", nil, 400)

	call(t, "DELETE", base, nil, 204)
	newOntology(t, id, false)
	if list := decode[wire.CommitList](t, call(t, "GET", base+"/commits", nil, 200)); len(list.Commits) != 0 {
		t.Fatalf("commits survived delete: %+v", list)
	}
}
