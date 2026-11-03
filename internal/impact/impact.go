// Package impact refines model.ComputeImpact with simulation traces.
//
// model.ComputeImpact finds affected flows from a flow's static reach: every
// call, emit and declared dynamic target on every branch. On a real model
// that closure is most of the system (one transport with a dozen dynamic
// route targets puts every flow through it in reach of everything), so it
// reports noise. Compute instead uses a flow's exercised reach: the
// interfaces its scenarios actually call when simulated, async emitted calls
// included, expanded like the static reach to their components, ancestors
// and referenced schemas. It lives here, not in model, because internal/sim
// imports internal/model.
package impact

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"runtime"
	"sort"
	"sync"

	"github.com/xleelz/mosaic/internal/model"
	"github.com/xleelz/mosaic/internal/sim"
)

// Basis values of model.FlowImpact.
const (
	BasisTraces = "traces"
	BasisStatic = "static"
)

// DefaultCacheSize bounds the documents a Cache keeps.
const DefaultCacheSize = 64

var defaultCache = NewCache(DefaultCacheSize)

// Compute is ComputeImpact with affected flows found from exercised reach,
// using a process-wide cache keyed by document content hash.
func Compute(before, after *model.Document) *model.Impact {
	return defaultCache.Compute(before, "", after, "")
}

// Cache memoizes each document's exercised reach. Documents are identified by
// a caller's key (an immutable revision, say "<ontology>@<n>") or, when the
// key is empty, by the hash of their JSON. It is safe for concurrent use.
type Cache struct {
	mu    sync.Mutex
	max   int
	docs  map[string]*docReach
	order []string // insertion order, for eviction
}

// NewCache returns a cache holding at most max documents (DefaultCacheSize
// when max <= 0).
func NewCache(max int) *Cache {
	if max <= 0 {
		max = DefaultCacheSize
	}
	return &Cache{max: max, docs: map[string]*docReach{}}
}

// Compute compares before and after with model.ComputeImpact, then recomputes
// FlowsAffected: an unchanged flow present in both is affected when a changed
// entity lies in its exercised reach in before or in after. Each document's
// reach comes from running the flow's scenarios against that document. A
// flow with no runnable scenarios in a document uses its static reach there,
// and its Basis is "static"; otherwise it is "traces". Keys may be empty.
func (c *Cache) Compute(before *model.Document, beforeKey string, after *model.Document, afterKey string) *model.Impact {
	imp := model.ComputeImpact(before, after)
	changed := changedKeys(imp)
	if len(changed) == 0 {
		return imp
	}
	b, a := c.reach(before, beforeKey), c.reach(after, afterKey)
	changedFlows := map[string]bool{}
	for _, id := range append(append(append([]string{}, imp.Flows.Added...), imp.Flows.Removed...), imp.Flows.Modified...) {
		changedFlows[id] = true
	}
	var flows []string
	for _, id := range a.flowIDs {
		if !changedFlows[id] && b.idx.FlowEntry(id) != nil {
			flows = append(flows, id)
		}
	}
	warm([]*docReach{b, a}, flows)
	out := []model.FlowImpact{}
	for _, id := range flows {
		reasons := map[string]bool{}
		basis := BasisTraces
		for _, side := range []*docReach{b, a} {
			keys, traced := side.flowReach(id)
			if !traced {
				basis = BasisStatic
			}
			for k := range keys {
				if changed[k] {
					reasons[k] = true
				}
			}
		}
		if len(reasons) > 0 {
			out = append(out, model.FlowImpact{Flow: id, Reasons: sortedKeys(reasons), Basis: basis})
		}
	}
	imp.FlowsAffected = out
	return imp
}

// warm computes the reach of every flow on every side, in parallel.
func warm(sides []*docReach, flows []string) {
	type job struct {
		side *docReach
		flow string
	}
	jobs := make(chan job)
	var wg sync.WaitGroup
	for range min(runtime.GOMAXPROCS(0), len(flows)*len(sides)) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range jobs {
				j.side.flowReach(j.flow)
			}
		}()
	}
	for _, f := range flows {
		for _, s := range sides {
			jobs <- job{s, f}
		}
	}
	close(jobs)
	wg.Wait()
}

func changedKeys(imp *model.Impact) map[string]bool {
	out := map[string]bool{}
	for kind, set := range map[string]model.ImpactSet{
		model.KindComponent: imp.Components, model.KindInterface: imp.Interfaces, model.KindLink: imp.Links,
		model.KindSchema: imp.Schemas, model.KindFlow: imp.Flows, model.KindScenario: imp.Scenarios,
	} {
		for _, l := range [][]string{set.Added, set.Removed, set.Modified} {
			for _, id := range l {
				out[kind+":"+id] = true
			}
		}
	}
	return out
}

// reach returns the cached reach of doc, creating it when absent.
func (c *Cache) reach(doc *model.Document, key string) *docReach {
	if key == "" {
		key = hashDoc(doc)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if r, ok := c.docs[key]; ok {
		return r
	}
	r := newDocReach(doc)
	if len(c.order) >= c.max {
		delete(c.docs, c.order[0])
		c.order = c.order[1:]
	}
	c.docs[key] = r
	c.order = append(c.order, key)
	return r
}

func hashDoc(doc *model.Document) string {
	if doc == nil {
		return "nil"
	}
	b, err := json.Marshal(doc)
	if err != nil {
		return "unhashable" // not cached usefully, but still correct for this call
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

// docReach is one document's reach, computed per flow on first use.
type docReach struct {
	doc       *model.Document
	idx       *model.ReachIndex
	flowIDs   []string            // sorted, unique
	scenarios map[string][]string // flow -> scenario ids, in document order, grouped by Scenario.GroupFlow
	callers   map[string][]string // scenario -> the callers of its steps (multi-step scenarios)

	mu    sync.Mutex
	flows map[string]*flowReach
}

type flowReach struct {
	once   sync.Once
	keys   map[string]bool
	traced bool
}

func newDocReach(doc *model.Document) *docReach {
	r := &docReach{doc: doc, idx: model.NewReachIndex(doc), scenarios: map[string][]string{}, callers: map[string][]string{},
		flows: map[string]*flowReach{}}
	if doc == nil {
		return r
	}
	// sim.Run normalizes interfaces in place; doing it once here makes the
	// concurrent runs in warm read-only.
	for i := range doc.Interfaces {
		doc.Interfaces[i].Normalize()
	}
	seen := map[string]bool{}
	for _, f := range doc.Flows {
		if !seen[f.ID] {
			seen[f.ID] = true
			r.flowIDs = append(r.flowIDs, f.ID)
		}
	}
	sort.Strings(r.flowIDs)
	flowCaller := map[string]string{}
	for _, f := range doc.Flows {
		if _, ok := flowCaller[f.ID]; !ok && f.Entry != nil {
			flowCaller[f.ID] = f.Entry.Caller
		}
	}
	seenSc := map[string]bool{}
	for i := range doc.Scenarios {
		sc := &doc.Scenarios[i]
		if seenSc[sc.ID] {
			continue
		}
		seenSc[sc.ID] = true
		// A multi-step scenario is grouped under its flow, or else its
		// first step's flow (§11.7); every interface its steps call counts
		// toward that flow's traced reach, and so do their callers.
		g := sc.GroupFlow()
		r.scenarios[g] = append(r.scenarios[g], sc.ID)
		for _, st := range sc.Steps {
			c := st.Caller
			if st.Flow != "" {
				c = flowCaller[st.Flow]
			}
			if c != "" {
				r.callers[sc.ID] = append(r.callers[sc.ID], c)
			}
		}
	}
	return r
}

// flowReach returns the entity keys in a flow's reach and whether they come
// from traces (false: the static reach).
func (r *docReach) flowReach(flow string) (map[string]bool, bool) {
	r.mu.Lock()
	fr, ok := r.flows[flow]
	if !ok {
		fr = &flowReach{}
		r.flows[flow] = fr
	}
	r.mu.Unlock()
	fr.once.Do(func() { fr.keys, fr.traced = r.compute(flow) })
	return fr.keys, fr.traced
}

func (r *docReach) compute(flow string) (map[string]bool, bool) {
	keys := map[string]bool{}
	add := func(k string) { keys[k] = true }
	entry := r.idx.FlowEntry(flow)
	if entry == nil {
		return keys, false
	}
	called := map[string]bool{}
	callers := map[string]bool{}
	ran := false
	for _, sc := range r.scenarios[flow] {
		trace, ok := runTrace(r.doc, sc)
		if !ok {
			continue
		}
		ran = true
		for _, c := range r.callers[sc] {
			callers[c] = true
		}
		for _, e := range trace {
			if e.Type == "call.start" && e.Interface != "" {
				called[e.Interface] = true
			}
		}
	}
	if !ran {
		r.idx.StaticReach(flow, add)
		return keys, false
	}
	r.idx.Expand(entry.Caller, sortedKeys(called), false, add)
	for _, c := range sortedKeys(callers) {
		r.idx.Expand(c, nil, false, add)
	}
	return keys, true
}

// runTrace simulates one scenario. An aborted run still yields the calls it
// made; a request that cannot run (or a panic) yields nothing.
func runTrace(doc *model.Document, scenario string) (trace []sim.Event, ok bool) {
	defer func() {
		if recover() != nil {
			trace, ok = nil, false
		}
	}()
	res, err := sim.Run(doc, sim.Request{Scenario: scenario})
	if err != nil || res == nil {
		return nil, false
	}
	return res.Trace, true
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
