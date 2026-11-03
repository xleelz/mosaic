package main

import (
	"bytes"
	"regexp"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// TestStateFlag: --state prints each run scenario's final state, one line
// per state key in sorted order (DESIGN §13.1 item 12).
func TestStateFlag(t *testing.T) {
	doc, err := model.ParseDocument([]byte(traceDoc))
	if err != nil {
		t.Fatal(err)
	}
	var b bytes.Buffer
	runAll(&b, doc, nil, runOpts{Only: regexp.MustCompile("^put-then-read$"), Quiet: true, State: true})
	want := "    state: 4 keys\n      coord: {}\n      node@n1: {\"n\":1}\n      node@n2: {}\n      node@n3: {}\n"
	if !bytes.Contains(b.Bytes(), []byte(want)) {
		t.Errorf("output lacks %q:\n%s", want, b.String())
	}
	b.Reset()
	runAll(&b, doc, nil, runOpts{Only: regexp.MustCompile("^put-then-read$"), Quiet: true})
	if bytes.Contains(b.Bytes(), []byte("state:")) {
		t.Errorf("state printed without --state:\n%s", b.String())
	}
}
