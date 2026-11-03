package main

import (
	"strings"
	"testing"
)

// DESIGN §17 item 7: fail steps inside receive on_error, other catch-style
// handlers and a parallel step's handler count as raising.
const unraisedHandlersDoc = `schema_version: 1
id: handlers
components:
  - {id: svc}
interfaces:
  - component: svc
    name: worker
    errors:
      - {code: queue_empty, status: 504}
      - {code: lost, status: 409}
      - {code: quorum_lost, status: 503}
      - {code: rethrown_timeout, status: 504}
      - {code: never_raised, status: 400}
    behavior:
      - receive: jobs
        as: job
        timeout_ms: 100
        on_error: [{fail: {code: queue_empty, status: 504}}]
      - put: results
        value: "= vars.job"
        capacity: 1
        timeout_ms: 50
        on_error:
          - if: "error.code == 'timeout'"
            then: [{fail: {code: lost, status: 409}}]
      - branches:
          - [{set: {vars.a: 1}}]
          - - receive: votes
              as: v
              timeout_ms: 20
              on_error: [{fail: {code: quorum_lost, status: 503}}]
        join: {need: all}
      - receive: more
        as: m
        timeout_ms: 10
        on_error: [{fail: "= error.code == 'timeout' ? 'rethrown_timeout' : 'x'"}]
`

func TestLintUnraisedFollowsHandlers(t *testing.T) {
	doc, origins := round4Fixture(t, unraisedHandlersDoc)
	r := lintUnraised(doc, origins)
	if got := strings.Join(subjects(r), ","); got != "svc.worker never_raised" {
		t.Fatalf("unraised %q:\n%+v", got, r.Findings)
	}
}
