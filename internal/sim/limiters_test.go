package sim_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 27: back pressure with limiters.
const limiterDoc = `
components:
  - {id: client}
  - {id: redis}
  - id: api
    limiters:
      - {id: per_ip, kind: fixed_window, key: "= input.x_peer_ip", limit: 5, period_ms: 3600000}
      - {id: bucket, kind: token_bucket, limit: 2, period_ms: 1000}
      - {id: charged, kind: token_bucket, limit: 2, period_ms: 1000, floor: -3}
      - {id: window, kind: fixed_window, limit: 1, period_ms: 1000}
      - {id: slide, kind: sliding_window, limit: 2, period_ms: 1000}
      - {id: slots, kind: concurrency, limit: 1, lease_ms: 500}
      - {id: cwait, kind: concurrency, limit: 1, lease_ms: 100000, on_limit: wait, max_wait_ms: 1000}
      - {id: held, kind: concurrency, key: "= input.org", limit: 1, lease_ms: 50}
      - {id: queued, kind: token_bucket, limit: 1, burst: 1, period_ms: 100, on_limit: wait, max_wait_ms: 150}
      - {id: shadow, kind: fixed_window, limit: 1, period_ms: 1000, enforce: false}
      - {id: open, kind: fixed_window, limit: null, period_ms: 1000}
      - {id: none, kind: fixed_window, limit: 0, period_ms: 1000}
      - {id: dyn, kind: fixed_window, limit: "= config.cap > 0 ? config.cap : null", period_ms: 1000}
      - id: slow
        kind: fixed_window
        limit: 1
        period_ms: 1000
        error: {code: slow_down, status: 503, retryable: false, message: "= 'retry in ' + string(error.data.retry_after_ms) + ' ms'"}
      - {id: idle, kind: fixed_window, limit: 1, period_ms: 100000000, idle_ttl_ms: 100}
  - id: gw
    limiters:
      - {id: loc, kind: fixed_window, limit: 1, period_ms: 100000}
      - {id: sh, kind: fixed_window, limit: 1, period_ms: 100000, scope: shared}
      - {id: sh_open, kind: fixed_window, limit: 1, period_ms: 100000, scope: shared, backend: redis.check, on_backend_error: fail_open}
      - {id: sh_closed, kind: fixed_window, limit: 1, period_ms: 100000, scope: shared, backend: redis.check, on_backend_error: fail_closed}
      - {id: sh_prop, kind: fixed_window, limit: 1, period_ms: 100000, scope: shared, backend: redis.check}
configs:
  - {id: cap, type: integer, value: 1}
interfaces:
  - {component: redis, name: check, latency_ms: 5}
  - component: api
    name: get
    latency_ms: 1
    request: {type: object, properties: {x_peer_ip: {type: string}}}
    errors: [{code: rate_limited, status: 429}]
    limits: [per_ip]
  - component: api
    name: slow
    latency_ms: 100
    errors: [{code: rate_limited}]
    limits: [slots]
  - component: api
    name: cq
    latency_ms: 100
    errors: [{code: rate_limited}]
    limits: [cwait]
  - component: api
    name: q
    latency_ms: 1
    errors: [{code: rate_limited}]
    limits: [queued]
  - component: api
    name: sh
    latency_ms: 1
    errors: [{code: rate_limited}]
    limits: [shadow]
  - component: api
    name: errs
    latency_ms: 0
    errors: [{code: slow_down}]
    limits: [slow]
  - component: api
    name: bucket
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: bucket, as: a1}}
      - {admit: {limiter: bucket}, as: a2}
      - {admit: {limiter: bucket, as: a3, on_error: continue}}
      - {wait: 500}
      - {admit: {limiter: bucket, as: a4}}
      - {return: {a1: "= vars.a1", a2: "= vars.a2", a3: "= vars.a3", a4: "= vars.a4"}}
  - component: api
    name: gate
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: charged, gate: true, as: g1}}
      - {charge: {limiter: charged, cost: 4}}
      - {admit: {limiter: charged, gate: true, as: g2, on_error: continue}}
      - {charge: {limiter: charged, cost: 10}}
      - {return: {g1: "= vars.g1", g2: "= vars.g2", tokens: "= limiters['api.charged'][''].tokens"}}
  - component: api
    name: window
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: window, as: w1}}
      - {admit: {limiter: window, as: w2, on_error: continue}}
      - {wait: "= vars.w2.retry_after_ms"}
      - {admit: {limiter: window, as: w3}}
      - {return: {w1: "= vars.w1", w2: "= vars.w2", w3: "= vars.w3"}}
  - component: api
    name: slide
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: slide, as: s1}}
      - {wait: 400}
      - {admit: {limiter: slide, as: s2}}
      - {admit: {limiter: slide, as: s3, on_error: continue}}
      - {wait: 600}
      - {admit: {limiter: slide, as: s4}}
      - {return: {s1: "= vars.s1", s2: "= vars.s2", s3: "= vars.s3", s4: "= vars.s4"}}
  - component: api
    name: hold
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: held, as: l, on_error: continue}}
      - {return: "= vars.l"}
  - component: api
    name: cycle
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: held, as: l1}}
      - {admit: {limiter: held, as: l2, on_error: continue}}
      - {release: {limiter: held, lease: "= vars.l1.lease"}}
      - {release: {limiter: held, lease: "nope"}}
      - {admit: {limiter: held, as: l3}}
      - {return: {l1: "= vars.l1", l2: "= vars.l2", l3: "= vars.l3"}}
  - component: api
    name: group
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiters: [window, none], as: g, on_error: continue}}
      - {return: "= vars.g"}
  - component: api
    name: misc
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: open, as: o}}
      - {admit: {limiter: dyn, as: d1}}
      - {admit: {limiter: dyn, as: d2, on_error: continue}}
      - {return: {o: "= vars.o", d1: "= vars.d1", d2: "= vars.d2"}}
  - component: api
    name: idle
    latency_ms: 0
    errors: [{code: rate_limited}]
    behavior:
      - {admit: {limiter: idle, as: i1}}
      - {wait: 50}
      - {admit: {limiter: idle, as: i2, on_error: continue}}
      - {wait: 200}
      - {admit: {limiter: idle, as: i3}}
      - {return: {i1: "= vars.i1", i2: "= vars.i2", i3: "= vars.i3"}}
  - component: api
    name: pick
    latency_ms: 0
    behavior:
      - choice: side
        options: {a: [{return: a}], b: [{return: b}]}
        default: a
  - {component: gw, name: loc, latency_ms: 0, errors: [{code: rate_limited}], limits: [loc]}
  - {component: gw, name: sh, latency_ms: 0, errors: [{code: rate_limited}], limits: [sh]}
  - {component: gw, name: open, latency_ms: 0, errors: [{code: rate_limited}], limits: [sh_open]}
  - {component: gw, name: closed, latency_ms: 0, errors: [{code: rate_limited}], limits: [sh_closed]}
  - {component: gw, name: prop, latency_ms: 0, errors: [{code: rate_limited}], limits: [sh_prop]}
flows:
  - {id: bucket, entry: {caller: client, interface: api.bucket}}
  - {id: gate, entry: {caller: client, interface: api.gate}}
  - {id: window, entry: {caller: client, interface: api.window}}
  - {id: slide, entry: {caller: client, interface: api.slide}}
  - {id: cycle, entry: {caller: client, interface: api.cycle, input: {org: o1}}}
  - {id: group, entry: {caller: client, interface: api.group}}
  - {id: misc, entry: {caller: client, interface: api.misc}}
  - {id: idle, entry: {caller: client, interface: api.idle}}
  - {id: open, entry: {caller: client, interface: gw.open}}
  - {id: closed, entry: {caller: client, interface: gw.closed}}
  - {id: prop, entry: {caller: client, interface: gw.prop}}
fixtures:
  - id: ip-seeded
    limiters: {api.per_ip: {10.0.0.8: {count: 5}}}
scenarios:
  - id: per-ip
    steps:
      - interface: api.get
        caller: client
        repeat: {count: 7}
        input: {x_peer_ip: "= pass <= 6 ? '10.0.0.1' : '10.0.0.2'"}
        as: burst
    expect:
      - "steps.burst.result.ok"
      - "limits['api.per_ip'] == {'admitted': 6, 'rejected': 1, 'shadow': 0, 'waited': 0}"
      - "limiters['api.per_ip']['10.0.0.1'].count == 5 && limiters['api.per_ip']['10.0.0.2'].count == 1"
      - "trace.filter(e, e.type == 'limit' && e.output.decision == 'reject').map(e, e.input.key) == ['10.0.0.1']"
      - "trace.filter(e, e.type == 'call.end' && e.error != null).map(e, e.error.data.retry_after_ms) == [3600000 - 5]"
  - id: per-ip-seeded
    fixtures: [ip-seeded]
    limiters: {api.per_ip: {10.0.0.9: {count: 4}}}
    steps:
      - {interface: api.get, caller: client, input: {x_peer_ip: 10.0.0.8}, as: s8}
      - {interface: api.get, caller: client, input: {x_peer_ip: 10.0.0.9}, as: s9}
      - {interface: api.get, caller: client, input: {x_peer_ip: 10.0.0.9}, as: s9b}
      - {interface: api.get, caller: client, input: {x_peer_ip: 10.0.0.7}, as: s7, limiters: {api.per_ip: {10.0.0.7: {count: 5}}}}
    expect:
      - "steps.s8.result.error.code == 'rate_limited' && steps.s8.result.error.data.limit == 5"
      - "steps.s9.result.ok && !steps.s9b.result.ok && !steps.s7.result.ok"
  - id: bucket
    flow: bucket
    expect:
      - "result.value.a1.ok && result.value.a1.remaining == 1 && result.value.a2.remaining == 0"
      - "!result.value.a3.ok && result.value.a3.decision == 'reject' && result.value.a3.retry_after_ms == 500"
      - "result.value.a3.error.code == 'rate_limited' && result.value.a3.error.status == 429 && result.value.a3.error.retryable"
      - "result.value.a4.ok && result.value.a4.remaining == 0"
  - id: gate-charge-floor
    flow: gate
    expect:
      - "result.value.g1.ok && result.value.g1.remaining == 2"
      - "!result.value.g2.ok && result.value.g2.remaining == -2"
      - "result.value.tokens == -3"
      - "trace.filter(e, e.type == 'limit').map(e, e.output.decision) == ['admit', 'charge', 'reject', 'charge']"
  - id: window-aligned
    flow: window
    clock: {epoch_ms: 1700000000300}
    expect:
      - "result.value.w1.ok && !result.value.w2.ok && result.value.w2.retry_after_ms == 700 && result.value.w3.ok"
      - "duration_ms == 700"
  - id: sliding
    flow: slide
    expect:
      - "result.value.s1.ok && result.value.s2.ok && !result.value.s3.ok && result.value.s3.retry_after_ms == 600 && result.value.s4.ok"
  - id: concurrency-auto-release
    steps:
      - {interface: api.slow, caller: client, await: false, as: a}
      - {interface: api.slow, caller: client, at_ms: 10, await: false, as: b}
      - {interface: api.slow, caller: client, at_ms: 200, as: c}
    expect:
      - "steps.a.result.ok && !steps.b.result.ok && steps.c.result.ok"
      - "steps.b.result.error.data.retry_after_ms == 490"
      - "size(limiters['api.slots'][''].leases) == 0"
      - "trace.filter(e, e.type == 'limit' && e.output.decision == 'release').size() == 2"
  - id: concurrency-lease-expiry
    steps:
      - {interface: api.hold, caller: client, input: {org: o1}, as: a}
      - {interface: api.hold, caller: client, input: {org: o1}, at_ms: 20, as: b}
      - {interface: api.hold, caller: client, input: {org: o2}, at_ms: 20, as: other}
      - {interface: api.hold, caller: client, input: {org: o1}, at_ms: 60, as: c}
    expect:
      - "steps.a.result.value.ok && steps.a.result.value.lease != null"
      - "!steps.b.result.value.ok && steps.b.result.value.retry_after_ms == 30"
      - "steps.other.result.value.ok && steps.c.result.value.ok"
      - "size(limiters['api.held']['o1'].leases) == 1"
  - id: release
    flow: cycle
    expect:
      - "result.value.l1.ok && !result.value.l2.ok && result.value.l3.ok"
      - "trace.filter(e, e.type == 'limit' && e.output.decision == 'release').size() == 1"
  - id: all-or-nothing
    flow: group
    expect:
      - "!result.value.ok && result.value.limiter == 'api.none' && result.value.retry_after_ms == null"
      - "result.value.decisions.map(d, d.decision) == ['admit', 'reject']"
      - "limiters['api.window'][''].count == 0"
      - "limits['api.window'].admitted == 0 && limits['api.none'].rejected == 1"
  - id: unlimited-and-dynamic
    flow: misc
    expect:
      - "result.value.o.decision == 'unlimited' && result.value.o.remaining == null"
      - "result.value.d1.ok && !result.value.d2.ok"
  - id: dynamic-unlimited
    flow: misc
    config: {cap: 0}
    expect: ["result.value.d2.decision == 'unlimited'"]
  - id: idle-ttl
    flow: idle
    expect: ["result.value.i1.ok && !result.value.i2.ok && result.value.i3.ok"]
  - id: wait-fifo
    steps:
      - {interface: api.q, caller: client, await: false, as: a}
      - {interface: api.q, caller: client, await: false, as: b}
      - {interface: api.q, caller: client, as: c}
    expect:
      - "steps.a.result.ok && steps.a.duration_ms == 1"
      - "steps.b.result.ok && steps.b.duration_ms == 101"
      - "!steps.c.result.ok && steps.c.duration_ms == 150"
      - "limits['api.queued'] == {'admitted': 2, 'rejected': 1, 'shadow': 0, 'waited': 2}"
      - "trace.filter(e, e.type == 'queue').map(e, e.wait_ms) == [100, 150]"
  - id: concurrency-wait-release
    steps:
      - {interface: api.cq, caller: client, await: false, as: a}
      - {interface: api.cq, caller: client, at_ms: 10, as: b}
    expect:
      - "steps.a.result.ok && steps.b.result.ok && steps.b.duration_ms == 190"
      - "trace.filter(e, e.type == 'queue').map(e, e.wait_ms) == [90]"
      - "trace.filter(e, e.type == 'limit').map(e, e.output.decision) == ['admit', 'wait', 'release', 'admit', 'release']"
  - id: shadow
    steps:
      - {interface: api.sh, caller: client, as: a}
      - {interface: api.sh, caller: client, as: b}
    expect:
      - "steps.a.result.ok && steps.b.result.ok"
      - "limits['api.shadow'] == {'admitted': 1, 'rejected': 0, 'shadow': 1, 'waited': 0}"
  - id: custom-error
    steps:
      - {interface: api.errs, caller: client}
      - {interface: api.errs, caller: client, as: b}
    expect:
      - "steps.b.result.error == {'code': 'slow_down', 'status': 503, 'retryable': false, 'message': 'retry in 1000 ms', 'data': {'limiter': 'api.slow', 'key': '', 'limit': 1, 'remaining': 0, 'retry_after_ms': 1000}}"
  - id: instance-scope
    topology: {gw: [a, b]}
    steps:
      - {interface: gw.loc, caller: client, on: a, as: a1}
      - {interface: gw.loc, caller: client, on: b, as: b1}
      - {interface: gw.loc, caller: client, on: a, as: a2}
    expect:
      - "steps.a1.result.ok && steps.b1.result.ok && !steps.a2.result.ok"
      - "limiters['gw@a.loc'][''].count == 1 && limiters['gw@b.loc'][''].count == 1"
  - id: shared-scope
    topology: {gw: [a, b]}
    steps:
      - {interface: gw.sh, caller: client, on: a, as: a1}
      - {interface: gw.sh, caller: client, on: b, as: b1}
    expect:
      - "steps.a1.result.ok && !steps.b1.result.ok && limiters['gw.sh'][''].count == 1"
  - id: restart-resets-instance
    topology: {gw: [a]}
    steps:
      - {interface: gw.loc, caller: client, on: a}
      - {interface: gw.sh, caller: client, on: a}
      - {restart: {component: gw, instance: a}}
      - {interface: gw.loc, caller: client, on: a, as: loc}
      - {interface: gw.sh, caller: client, on: a, as: sh}
    expect: ["steps.loc.result.ok && !steps.sh.result.ok"]
  - id: backend-ok
    flow: open
    expect:
      - "result.ok && duration_ms == 5 && calls['redis.check'] == 1"
      - "trace.exists(e, e.type == 'call.start' && e.interface == 'redis.check' && e.input == {'limiter': 'gw.sh_open', 'key': '', 'op': 'admit', 'cost': 1})"
  - id: backend-fail-open
    flow: open
    faults: [{target: redis.check, type: unavailable}]
    expect:
      - "result.ok && trace.exists(e, e.type == 'limit' && e.output.decision == 'fail_open')"
      - "limits['gw.sh_open'].admitted == 1 && !('gw.sh_open' in limiters)"
  - id: backend-fail-closed
    flow: closed
    faults: [{target: redis.check, type: unavailable}]
    expect:
      - "result.error.code == 'rate_limited' && trace.exists(e, e.type == 'limit' && e.output.decision == 'fail_closed')"
  - id: backend-propagate
    flow: prop
    faults: [{target: redis.check, type: error, code: redis_down}]
    expect: ["result.error.code == 'redis_down' && !trace.exists(e, e.type == 'limit')"]
  - id: pass-in-choices
    steps:
      - {interface: api.pick, caller: client, repeat: {count: 3}, choices: {api.pick.side: "= pass == 2 ? 'b' : 'a'"}, as: p}
    expect:
      - "trace.filter(e, e.type == 'choice').map(e, e.option) == ['a', 'b', 'a']"
`

func TestLimiters(t *testing.T) {
	doc := langDoc(t, limiterDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}

// TestLimiterPerIP checks the per-IP fixed window in detail: the 6th
// request from one IP fails with 429 and data, another IP passes.
func TestLimiterPerIP(t *testing.T) {
	doc := langDoc(t, limiterDoc)
	res := passes(t, doc, sim.Request{Scenario: "per-ip"})
	var ends []sim.Event
	for _, e := range res.Trace {
		if e.Type == "call.end" {
			ends = append(ends, e)
		}
	}
	if len(ends) != 7 {
		t.Fatalf("got %d calls, want 7", len(ends))
	}
	for i, e := range ends {
		if ok := *e.OK; ok != (i != 5) {
			t.Errorf("pass %d: ok %v", i+1, ok)
		}
	}
	e := ends[5].Error
	if e == nil || e.Code != "rate_limited" || e.Status != 429 || !e.Retryable {
		t.Fatalf("pass 6 error: %+v", e)
	}
	data, _ := json.Marshal(e.Data)
	if string(data) != `{"key":"10.0.0.1","limit":5,"limiter":"api.per_ip","remaining":0,"retry_after_ms":3599995}` {
		t.Errorf("data: %s", data)
	}
	if got := res.Summary.Limits["api.per_ip"]; got != (sim.LimitCount{Admitted: 6, Rejected: 1}) {
		t.Errorf("summary limits: %+v", got)
	}
	for _, ev := range res.Trace {
		if ev.Type == "limit" && (ev.Interface != "api.get" || ev.Key != "api.per_ip" || ev.From != "client") {
			t.Errorf("limit event: %+v", ev)
		}
	}
}

// TestLimiterAdditive checks that a document without limiters has no
// limits in its summary.
func TestLimiterAdditive(t *testing.T) {
	doc := langDoc(t, storeFaultDoc)
	res := passes(t, doc, sim.Request{Scenario: "transfer"})
	b, _ := json.Marshal(res.Summary)
	if strings.Contains(string(b), `"limits"`) {
		t.Errorf("summary carries limits: %s", b)
	}
}

func TestLimiterValidation(t *testing.T) {
	bad := map[string]string{
		"fixed_window needs period_ms": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1}]}]`,
		"concurrency needs lease_ms": `
components: [{id: a, limiters: [{id: l, kind: concurrency, limit: 1}]}]`,
		"backend goes with scope: shared": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1, backend: a.b}]}]
interfaces: [{component: a, name: b}]`,
		"kind is one of": `
components: [{id: a, limiters: [{id: l, kind: leaky, limit: 1}]}]`,
		"limit is required": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, period_ms: 1}]}]`,
		"duplicate limiter id": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1}, {id: l, kind: fixed_window, limit: 1, period_ms: 1}]}]`,
		"unknown limiter \"nope\"": `
components: [{id: a}]
interfaces: [{component: a, name: b, limits: [nope]}]`,
		"not one of a.b's declared errors": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1}]}]
interfaces: [{component: a, name: b, limits: [l]}]`,
		"slow_down\", which is not one of": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1, error: {code: slow_down}}]}]
interfaces: [{component: a, name: b, errors: [{code: rate_limited}], behavior: [{admit: {limiter: a.l}}]}]`,
		"release goes with a concurrency limiter": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1}]}]
interfaces: [{component: a, name: b, errors: [{code: rate_limited}], behavior: [{release: {limiter: l}}]}]`,
		"charge goes with token_bucket": `
components: [{id: a, limiters: [{id: l, kind: concurrency, limit: 1, lease_ms: 1}]}]
interfaces: [{component: a, name: b, errors: [{code: rate_limited}], behavior: [{charge: {limiter: l}}]}]`,
		"invalid expression": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, key: "= input.(", limit: 1, period_ms: 1}]}]`,
		"unknown limiter \"a.zz\"": `
components: [{id: a}]
fixtures: [{id: f, limiters: {a.zz: {k: {count: 1}}}}]`,
		"a seed sets tokens, count, leases or updated_ms": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1}]}]
fixtures: [{id: f, limiters: {a.l: {k: {level: 1}}}}]`,
		"is shared: seed it as": `
components: [{id: a, limiters: [{id: l, kind: fixed_window, limit: 1, period_ms: 1, scope: shared}]}]
fixtures: [{id: f, limiters: {a@x.l: {k: {count: 1}}}}]`,
	}
	for want, src := range bad {
		doc, err := model.ParseDocument([]byte("schema_version: 1\n" + src))
		if err != nil {
			t.Fatalf("%s: %v", want, err)
		}
		found := false
		for _, is := range model.Validate(doc) {
			if is.Severity == model.SeverityError && strings.Contains(is.Message, want) {
				found = true
			}
		}
		if !found {
			t.Errorf("no error containing %q; got %+v", want, model.Validate(doc))
		}
	}
}

// TestLimiterRoundTrip checks that limiter declarations, limits, steps and
// seeds encode back to the same document.
func TestLimiterRoundTrip(t *testing.T) {
	doc := langDoc(t, limiterDoc)
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	again, err := model.ParseDocument(b)
	if err != nil {
		t.Fatal(err)
	}
	b2, _ := json.Marshal(again)
	if string(b) != string(b2) {
		t.Errorf("round trip differs")
	}
	for _, want := range []string{`"limits":["per_ip"]`, `"admit":{"limiter":"bucket","as":"a1"}`, `"limit":null`, `"limiters":{"api.per_ip"`} {
		if !strings.Contains(string(b), want) {
			t.Errorf("encoding lacks %s", want)
		}
	}
}
