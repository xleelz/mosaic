package model

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"
)

// Hierarchical ontologies (docs/DESIGN.md §14): levels, refinements and
// imports, their validation, and the composition of a parent with its
// refinements for a mixed-resolution run.

// Levels (§14.2). A document without a level is at LevelSystem.
const (
	LevelSystem  = "system"
	LevelService = "service"
	LevelLogic   = "logic"
	LevelRuntime = "runtime"
	LevelMachine = "machine"
)

// Levels lists the level labels, outermost first.
var Levels = []string{LevelSystem, LevelService, LevelLogic, LevelRuntime, LevelMachine}

// Resolutions (§14.5): how a run treats a component.
const (
	ResolutionBlackBox = "black_box" // the default: the component's contract and latency
	ResolutionRefined  = "refined"   // the component's child ontology, namespaced under its path
)

// OntologyRef names another ontology document, at a revision when given.
type OntologyRef struct {
	Ontology string `json:"ontology"`
	Revision string `json:"revision,omitempty"`
}

// RefinesRef is a refinement's link to its parent: the parent ontology,
// the component refined, and the parent revision refined.
type RefinesRef struct {
	Ontology  string `json:"ontology"`
	Component string `json:"component"`
	Revision  string `json:"revision,omitempty"`
}

// ImportRef imports a substrate ontology (§14.6). Its entities keep their
// ids, under the As prefix when one is given: components and links as
// "<as>/<id>", schemas as "<as>.<id>".
type ImportRef struct {
	Ontology string `json:"ontology"`
	Revision string `json:"revision,omitempty"`
	As       string `json:"as,omitempty"`
}

// LatencySource records where an interface's latency_ms comes from
// (§14.3): a refinement's measurement ("<ontology>@<rev>") or a value an
// operator pinned, with the reason. Exactly one is set.
type LatencySource struct {
	Refined string `json:"refined,omitempty"`
	Pinned  string `json:"pinned,omitempty"`
}

// ValidPathID reports whether s is a slug or a "/"-separated path of slugs,
// the form of a component namespaced under a refined component (§14.5).
func ValidPathID(s string) bool {
	if s == "" || len(s) > 512 {
		return false
	}
	for _, seg := range strings.Split(s, "/") {
		if !ValidID(seg) {
			return false
		}
	}
	return true
}

// isBoundary reports whether a component is marked attributes.boundary: a
// stub of an entity another document owns.
func isBoundary(c *Component) bool {
	b, _ := c.Attributes["boundary"].(bool)
	return b
}

// lastSeg is the last segment of a component path.
func lastSeg(path string) string {
	if i := strings.LastIndex(path, "/"); i >= 0 {
		return path[i+1:]
	}
	return path
}

// implementsTarget checks an implements value against the refined
// component path and returns the parent interface id it names there. The
// value's component may be the path itself or its last segment (a nested
// refinement names the component as its own parent ontology does).
func implementsTarget(impl, path string) (string, error) {
	comp, name, ok := strings.Cut(impl, ".")
	if !ok || comp == "" || name == "" {
		return "", fmt.Errorf("implements %q must be \"<parent component>.<interface>\"", impl)
	}
	if comp != path && comp != lastSeg(path) {
		return "", fmt.Errorf("implements %q targets component %q, not the refined component %q", impl, comp, path)
	}
	return path + "." + name, nil
}

// BoundaryInterfaces lists, sorted, the interfaces a document exposes at its
// boundary: those of components not marked attributes.boundary that no
// behavior in the document calls, emits to, publishes to, routes to or
// subscribes to a topic for, plus every interface that declares implements.
// In a refinement (§14.3) each must declare implements.
func BoundaryInterfaces(d *Document) []string {
	x := NewIndex(d)
	used := map[string]bool{}
	routed := map[string]bool{}
	for i := range d.Interfaces {
		walkStepPtrs(d.Interfaces[i].Behavior, func(s *Step) {
			if s.Call != "" {
				used[s.Call] = true
			}
			for _, t := range s.Targets {
				used[t] = true
			}
			if s.Emit != "" {
				used[s.Emit] = true
			}
			if s.Publish != "" {
				for _, id := range x.Subscribers[s.Publish] {
					used[id] = true
				}
				used[s.Publish] = true
			}
			if s.Route != nil && s.Route.Component != "" {
				routed[s.Route.Component] = true
			}
		})
	}
	var out []string
	for i := range d.Interfaces {
		f := &d.Interfaces[i]
		f.Normalize()
		if f.Implements != "" {
			out = append(out, f.ID)
			continue
		}
		c, ok := x.Components[f.Component]
		if ok && isBoundary(c) || used[f.ID] || len(f.Subscribe) > 0 || routed[f.Component] {
			continue
		}
		out = append(out, f.ID)
	}
	sort.Strings(out)
	return out
}

// walkStepPtrs calls fn on every step, nested steps included.
func walkStepPtrs(steps []Step, fn func(*Step)) {
	for i := range steps {
		s := &steps[i]
		fn(s)
		walkStepPtrs(s.Then, fn)
		walkStepPtrs(s.Else, fn)
		for _, k := range sortedKeys(s.Options) {
			walkStepPtrs(s.Options[k], fn)
		}
		walkStepPtrs(s.Steps, fn)
		for _, b := range s.Branches {
			walkStepPtrs(b, fn)
		}
		walkStepPtrs(s.OnLate, fn)
		walkStepPtrs(s.OnItem, fn)
		if s.OnError != nil {
			walkStepPtrs(s.OnError.Steps, fn)
		}
		if s.Admit != nil && s.Admit.OnError != nil {
			walkStepPtrs(s.Admit.OnError.Steps, fn)
		}
	}
}

// hierarchy validates the §14 fields of a document (§14.11).
func (v *validator) hierarchy() {
	d := v.x.Doc
	if d.Level != "" && !contains(Levels, d.Level) {
		v.errf("level", "unknown level %q (want %s)", d.Level, strings.Join(Levels, ", "))
	}
	if r := d.Refines; r != nil {
		if r.Ontology == "" {
			v.errf("refines.ontology", "ontology is required")
		}
		if !ValidPathID(r.Component) {
			v.errf("refines.component", "invalid component %q", r.Component)
		}
	}
	as := map[string]bool{}
	for i, im := range d.Imports {
		p := fmt.Sprintf("imports[%d]", i)
		if im.Ontology == "" {
			v.errf(p+".ontology", "ontology is required")
		}
		if im.As != "" {
			if !ValidID(im.As) {
				v.errf(p+".as", "invalid prefix %q: use [a-z0-9][a-z0-9_-]{0,63}", im.As)
			} else if as[im.As] {
				v.errf(p+".as", "duplicate prefix %q", im.As)
			}
			as[im.As] = true
		}
	}
	for _, c := range d.Components {
		for j, rb := range c.RefinedBy {
			if rb.Ontology == "" {
				v.errf(fmt.Sprintf("components[%s].refined_by[%d].ontology", c.ID, j), "ontology is required")
			}
		}
	}
	implemented := map[string]string{}
	for i := range d.Interfaces {
		f := &d.Interfaces[i]
		p := "interfaces[" + f.ID + "]"
		if ls := f.LatencySource; ls != nil {
			switch {
			case (ls.Refined == "") == (ls.Pinned == ""):
				v.errf(p+".latency_source", "give exactly one of refined and pinned")
			case ls.Refined != "":
				ont, rev, ok := strings.Cut(ls.Refined, "@")
				if !ok || ont == "" || rev == "" {
					v.errf(p+".latency_source.refined", "must be \"<ontology>@<rev>\", got %q", ls.Refined)
				}
			}
		}
		if f.Implements == "" {
			continue
		}
		if d.Refines == nil {
			// A composed document keeps implements, naming the shell its
			// interface sits under.
			if t, ok := v.x.Interfaces[f.Implements]; !ok || !v.ancestor(t.Component, f.Component) {
				v.errf(p+".implements", "implements needs the document's refines")
			}
			continue
		}
		target, err := implementsTarget(f.Implements, d.Refines.Component)
		if err != nil {
			v.errf(p+".implements", "%v", err)
			continue
		}
		if prev, dup := implemented[target]; dup {
			v.errf(p+".implements", "%q is already implemented by %s", f.Implements, prev)
		}
		implemented[target] = f.ID
		// The parent is loaded alongside (merged into this document): the
		// target must resolve there.
		if _, loaded := v.x.Components[d.Refines.Component]; loaded {
			if _, ok := v.x.Interfaces[target]; !ok {
				v.errf(p+".implements", "unknown parent interface %q", target)
			}
		}
	}
	if d.Refines != nil {
		for _, id := range BoundaryInterfaces(d) {
			if f := v.x.Interfaces[id]; f != nil && f.Implements == "" {
				// The refined component itself, loaded alongside, is the
				// parent's, not a boundary of the child.
				if f.Component == d.Refines.Component {
					continue
				}
				v.errf("interfaces["+id+"].implements", "a refinement's boundary interface must declare implements: <%s.interface>", d.Refines.Component)
			}
		}
	}
}

// ancestor reports whether anc is a proper ancestor of comp by parent.
func (v *validator) ancestor(anc, comp string) bool {
	seen := map[string]bool{}
	for c := v.x.Components[comp]; c != nil && !seen[c.ID]; c = v.x.Components[c.Parent] {
		seen[c.ID] = true
		if c.Parent == anc {
			return true
		}
	}
	return false
}

// resolution validates a scenario's resolution.
func (v *validator) resolution(p string, res map[string]string) {
	for _, k := range sortedKeys(res) {
		if r := res[k]; r != ResolutionBlackBox && r != ResolutionRefined {
			v.errf(p+".resolution."+k, "resolution must be black_box or refined, got %q", r)
		}
		if !ValidPathID(k) {
			v.errf(p+".resolution."+k, "invalid component path %q", k)
			continue
		}
		top, _, _ := strings.Cut(k, "/")
		if _, ok := v.x.Components[top]; !ok {
			v.errf(p+".resolution."+k, "unknown component %q", top)
		}
	}
}

// ValidateRefinement checks a child against its parent loaded alongside
// (§14.11): the child refines a component of the parent, every implements
// target resolves to an interface of that component, and no parent
// interface is implemented twice. Parent interfaces of the component left
// unimplemented are warnings.
func ValidateRefinement(parent, child *Document) []Issue {
	var issues []Issue
	errf := func(path, format string, a ...any) {
		issues = append(issues, Issue{Path: path, Message: fmt.Sprintf(format, a...), Severity: SeverityError})
	}
	if child.Refines == nil {
		errf("refines", "the child declares no refines")
		return issues
	}
	comp := child.Refines.Component
	px := NewIndex(parent)
	if _, ok := px.Components[comp]; !ok {
		errf("refines.component", "the parent has no component %q", comp)
		return issues
	}
	done := map[string]string{}
	for i := range child.Interfaces {
		f := &child.Interfaces[i]
		f.Normalize()
		if f.Implements == "" {
			continue
		}
		p := "interfaces[" + f.ID + "].implements"
		target, err := implementsTarget(f.Implements, comp)
		if err != nil {
			errf(p, "%v", err)
			continue
		}
		if _, ok := px.Interfaces[target]; !ok {
			errf(p, "unknown parent interface %q", target)
			continue
		}
		if prev, dup := done[target]; dup {
			errf(p, "%q is already implemented by %s", target, prev)
		}
		done[target] = f.ID
	}
	for _, id := range px.ByComp[comp] {
		if _, ok := done[id]; !ok {
			issues = append(issues, Issue{Path: "refines.component", Message: fmt.Sprintf("parent interface %q has no implementation in the child; it stays a black box", id), Severity: SeverityWarning})
		}
	}
	return issues
}

// ImplementsPairs returns the (parent interface id, child interface id)
// pairs of a refinement, sorted by parent interface id. It fails when the
// child does not refine a component of the parent or an implements target
// does not resolve.
func ImplementsPairs(parent *Document, child *Document) ([][2]string, error) {
	for _, is := range ValidateRefinement(parent, child) {
		if is.Severity == SeverityError {
			return nil, fmt.Errorf("%s: %s", is.Path, is.Message)
		}
	}
	comp := child.Refines.Component
	var out [][2]string
	for i := range child.Interfaces {
		f := child.Interfaces[i]
		f.Normalize()
		if f.Implements == "" {
			continue
		}
		target, _ := implementsTarget(f.Implements, comp)
		out = append(out, [2]string{target, f.ID})
	}
	sort.Slice(out, func(a, b int) bool { return out[a][0] < out[b][0] })
	return out, nil
}

// CollectRefinements flattens a document's loaded refinements, and theirs
// recursively, into one map keyed by full component path ("engine",
// "engine/scheduler").
func CollectRefinements(d *Document) map[string]*Document {
	out := map[string]*Document{}
	var walk func(prefix string, d *Document, depth int)
	walk = func(prefix string, d *Document, depth int) {
		if depth > 16 {
			return
		}
		for k, c := range d.Refinements {
			if c == nil {
				continue
			}
			out[prefix+k] = c
			walk(prefix+k+"/", c, depth+1)
		}
	}
	walk("", d, 0)
	return out
}

// HasRefined reports whether a resolution refines any component.
func HasRefined(resolution map[string]string) bool {
	for _, r := range resolution {
		if r == ResolutionRefined {
			return true
		}
	}
	return false
}

// ComposeRefinements returns one document in which each component named in
// resolution as "refined" is replaced by its child ontology (children[component]),
// rewired per DESIGN §14.11. Components not named, or named "black_box", are left as is.
//
// Rewiring, for a refined component at path P with child C:
//   - C's components become "P/<id>"; those without a parent in C get P as
//     their parent, so they share P's instance group. A C component marked
//     attributes.boundary resolves to the composed document's component of
//     the same id when one exists (looked up from P's scope outwards), and
//     is dropped; its interfaces the document lacks are added to it.
//   - Every reference inside C to its own components and interfaces is
//     rewritten (calls, targets, emits, publish topics and subscriptions
//     naming C interfaces, route components, kill and restart components,
//     limiter ids, links, router fallbacks). Dynamic "=cel" targets are
//     mapped through their declared targets (below).
//   - Each parent interface P.<name> that a C interface implements keeps its
//     id and becomes a zero-latency shell whose behavior calls the
//     implementing interface with the same input and returns its value; its
//     errors propagate unchanged. P loses its capacity, and the shell its
//     store and limits. Parent interfaces C does not implement stay black
//     boxes.
//   - C's flows and scenarios are dropped; its schemas and configs are added
//     unless the parent has the same id. C's fixtures marked
//     attributes.world (its deployment: topology, seed state, config), and
//     the fixtures they extend, come along as "P/<id>" with their keys
//     renamed, and every scenario applies the world fixtures first.
//   - A "=cel" call or emit target with declared targets is rewritten to
//     map the ids it computes through the same renaming.
//
// A nested path ("engine/scheduler") is composed after its ancestor, which
// must itself be refined. Documents carrying ImportDocs have their imports
// merged first.
func ComposeRefinements(parent *Document, children map[string]*Document, resolution map[string]string) (*Document, error) {
	doc := parent
	if len(parent.ImportDocs) > 0 {
		var err error
		if doc, err = MergeImports(parent, parent.ImportDocs); err != nil {
			return nil, err
		}
	}
	var refined []string
	for _, k := range sortedKeys(resolution) {
		switch resolution[k] {
		case ResolutionRefined:
			refined = append(refined, k)
		case ResolutionBlackBox, "":
		default:
			return nil, fmt.Errorf("resolution of %q must be black_box or refined, got %q", k, resolution[k])
		}
	}
	if len(refined) == 0 {
		return doc, nil
	}
	sort.SliceStable(refined, func(a, b int) bool {
		return strings.Count(refined[a], "/") < strings.Count(refined[b], "/")
	})
	for _, k := range refined {
		if i := strings.LastIndex(k, "/"); i >= 0 && resolution[k[:i]] != ResolutionRefined {
			return nil, fmt.Errorf("resolution refines %q but not its parent %q", k, k[:i])
		}
		child := children[k]
		if child == nil {
			return nil, fmt.Errorf("resolution refines %q but no refinement of it is loaded", k)
		}
		var err error
		if doc, err = composeOne(doc, k, child); err != nil {
			return nil, fmt.Errorf("refining %q: %w", k, err)
		}
	}
	return doc, nil
}

// CloneDocument deep-copies a document through its JSON encoding. The
// loaded Refinements and ImportDocs are shared, not copied.
func CloneDocument(d *Document) (*Document, error) {
	b, err := json.Marshal(d)
	if err != nil {
		return nil, err
	}
	var out Document
	if err := Decode(b, &out); err != nil {
		return nil, err
	}
	for i := range out.Interfaces {
		out.Interfaces[i].Normalize()
	}
	out.EnsureSlices()
	out.Refinements, out.ImportDocs = d.Refinements, d.ImportDocs
	return &out, nil
}

// renamer rewrites the references of entities moved into another document.
type renamer struct {
	comp  func(string) string // component id
	iface func(string) string // interface id
	topic func(string) string // publish topic or subscription
}

func (r renamer) limiter(ref string) string {
	if c, inst, id, ok := SplitLimiterID(ref); ok {
		return StateKey(r.comp(c), inst) + "." + id
	}
	return ref
}

// dynamic rewrites a "=cel" call or emit target so that the id it computes
// is renamed too: the step's declared targets (their original ids) map to
// their renamed ids, and any other value passes through unchanged. Without
// targets the expression is left as is.
func (r renamer) dynamic(v string, targets []string) string {
	src := strings.TrimSpace(strings.TrimPrefix(v, "="))
	var pairs []string
	seen := map[string]bool{}
	for _, t := range targets {
		if n := r.iface(t); n != t && !seen[t] && !strings.ContainsAny(t+n, `'\`) {
			seen[t] = true
			pairs = append(pairs, "'"+t+"': '"+n+"'")
		}
	}
	if len(pairs) == 0 || src == "" {
		return v
	}
	m := "{" + strings.Join(pairs, ", ") + "}"
	// The expression appears once, so renaming it again (an import inside
	// a refinement) grows it by one map, not threefold.
	return "= [" + src + "].map(t_, t_ in " + m + " ? " + m + "[t_] : t_)[0]"
}

func (r renamer) steps(steps []Step) {
	walkStepPtrs(steps, func(s *Step) {
		if s.Call != "" && !strings.HasPrefix(s.Call, "=") {
			s.Call = r.iface(s.Call)
		}
		if strings.HasPrefix(s.Call, "=") {
			s.Call = r.dynamic(s.Call, s.Targets)
		}
		if strings.HasPrefix(s.Emit, "=") {
			s.Emit = r.dynamic(s.Emit, s.Targets)
		}
		for i, t := range s.Targets {
			s.Targets[i] = r.iface(t)
		}
		if s.Route != nil && s.Route.Component != "" {
			s.Route.Component = r.comp(s.Route.Component)
		}
		if s.Emit != "" && !strings.HasPrefix(s.Emit, "=") {
			s.Emit = r.iface(s.Emit)
		}
		if s.Publish != "" && !strings.HasPrefix(s.Publish, "=") {
			s.Publish = r.topic(s.Publish)
		}
		if s.Kill != nil && !strings.HasPrefix(s.Kill.Component, "=") {
			s.Kill.Component = r.comp(s.Kill.Component)
		}
		if s.Restart != nil {
			if !strings.HasPrefix(s.Restart.Component, "=") {
				s.Restart.Component = r.comp(s.Restart.Component)
			}
			for i, k := range s.Restart.Keep {
				s.Restart.Keep[i] = r.comp(k)
			}
		}
		if s.Admit != nil {
			if s.Admit.Limiter != "" {
				s.Admit.Limiter = r.limiter(s.Admit.Limiter)
			}
			for i := range s.Admit.Limiters {
				s.Admit.Limiters[i].Limiter = r.limiter(s.Admit.Limiters[i].Limiter)
			}
		}
		if s.Charge != nil {
			s.Charge.Limiter = r.limiter(s.Charge.Limiter)
		}
		if s.Release != nil {
			s.Release.Limiter = r.limiter(s.Release.Limiter)
		}
	})
}

func (r renamer) renameComponent(c *Component) {
	c.ID = r.comp(c.ID)
	if c.Parent != "" {
		c.Parent = r.comp(c.Parent)
	}
	if c.Router != nil && c.Router.Fallback != "" {
		c.Router.Fallback = r.iface(c.Router.Fallback)
	}
}

func (r renamer) renameInterface(f *Interface) {
	f.Normalize()
	f.Component = r.comp(f.Component)
	f.ID = f.Component + "." + f.Name
	for i, t := range f.Subscribe {
		f.Subscribe[i] = r.topic(t)
	}
	for i := range f.Limits {
		f.Limits[i].Limiter = r.limiter(f.Limits[i].Limiter)
	}
	r.steps(f.Behavior)
}

func (r renamer) renameLink(l *Link) {
	l.From, l.To = r.endpoint(l.From), r.endpoint(l.To)
}

func (r renamer) endpoint(id string) string {
	if strings.Contains(id, ".") {
		return r.iface(id)
	}
	return r.comp(id)
}

// mapper builds the component and interface maps of a document moved under
// a renaming of its components.
func mapper(src *Document, compMap map[string]string) renamer {
	ifaces := map[string]bool{}
	for _, f := range src.Interfaces {
		f.Normalize()
		ifaces[f.ID] = true
	}
	comp := func(id string) string {
		if n, ok := compMap[id]; ok {
			return n
		}
		return id
	}
	iface := func(id string) string {
		c, n, ok := strings.Cut(id, ".")
		if !ok {
			return id
		}
		if _, known := compMap[c]; known {
			return comp(c) + "." + n
		}
		return id
	}
	topic := func(t string) string {
		if ifaces[t] {
			return iface(t)
		}
		return t
	}
	return renamer{comp: comp, iface: iface, topic: topic}
}

// composeOne replaces the component at path in doc by child.
func composeOne(doc *Document, path string, child *Document) (*Document, error) {
	out, err := CloneDocument(doc)
	if err != nil {
		return nil, err
	}
	out.Refinements, out.ImportDocs = nil, nil
	src := child
	if len(child.ImportDocs) > 0 {
		if src, err = MergeImports(child, child.ImportDocs); err != nil {
			return nil, err
		}
	}
	if src, err = CloneDocument(src); err != nil {
		return nil, err
	}
	x := NewIndex(out)
	shell, ok := x.Components[path]
	if !ok {
		return nil, fmt.Errorf("the document has no component %q", path)
	}
	if src.Refines != nil && src.Refines.Component != path && src.Refines.Component != lastSeg(path) {
		return nil, fmt.Errorf("the child refines %q, not %q", src.Refines.Component, path)
	}

	// Boundary stubs resolve to the composed document's entities, from the
	// refined component's scope outwards; everything else is namespaced.
	resolveUp := func(id string) (string, bool) {
		scope := path
		for {
			i := strings.LastIndex(scope, "/")
			if i < 0 {
				break
			}
			scope = scope[:i]
			if cand := scope + "/" + id; cand != path {
				if _, ok := x.Components[cand]; ok {
					return cand, true
				}
			}
		}
		if _, ok := x.Components[id]; ok && id != path {
			return id, true
		}
		return "", false
	}
	compMap := map[string]string{}
	stub := map[string]bool{}
	for i := range src.Components {
		c := &src.Components[i]
		if isBoundary(c) {
			if to, ok := resolveUp(c.ID); ok {
				compMap[c.ID], stub[c.ID] = to, true
				continue
			}
		}
		compMap[c.ID] = path + "/" + c.ID
	}
	rn := mapper(src, compMap)
	childComps := map[string]bool{}
	for _, c := range src.Components {
		childComps[c.ID] = true
	}

	// The contract: parent interface -> implementing child interface.
	impl := map[string]string{}
	for i := range src.Interfaces {
		f := &src.Interfaces[i]
		if f.Implements == "" {
			continue
		}
		target, err := implementsTarget(f.Implements, path)
		if err != nil {
			return nil, fmt.Errorf("interface %s: %w", f.ID, err)
		}
		if _, ok := x.Interfaces[target]; !ok {
			return nil, fmt.Errorf("interface %s implements unknown parent interface %q", f.ID, target)
		}
		if prev, dup := impl[target]; dup {
			return nil, fmt.Errorf("parent interface %q is implemented by both %s and %s", target, prev, f.ID)
		}
		impl[target] = rn.iface(f.ID)
	}

	for i := range src.Components {
		c := src.Components[i]
		if stub[c.ID] {
			continue
		}
		top := c.Parent == "" || !childComps[c.Parent]
		rn.renameComponent(&c)
		if top {
			c.Parent = path
		}
		if x.Components[c.ID] != nil {
			return nil, fmt.Errorf("component %q already exists", c.ID)
		}
		out.Components = append(out.Components, c)
	}
	for i := range src.Interfaces {
		f := src.Interfaces[i]
		f.Normalize()
		wasStub := stub[f.Component]
		rn.renameInterface(&f)
		if _, exists := x.Interfaces[f.ID]; exists {
			if wasStub {
				continue // the parent's own interface answers
			}
			return nil, fmt.Errorf("interface %q already exists", f.ID)
		}
		if f.Implements != "" {
			f.Implements, _ = implementsTarget(f.Implements, path)
			// The shell carries the route; the implementation must not
			// answer it a second time under a router.
			_, shellRouted := RouteOf(x.Interfaces[f.Implements])
			if _, routed := RouteOf(&f); routed && shellRouted {
				f.Attributes = copyWithout(f.Attributes, "path", "method")
			}
		}
		out.Interfaces = append(out.Interfaces, f)
	}
	for i := range src.Links {
		l := src.Links[i]
		rn.renameLink(&l)
		l.ID = path + "/" + l.ID
		out.Links = append(out.Links, l)
	}
	for _, s := range src.Schemas {
		if _, ok := x.Schemas[s.ID]; !ok {
			out.Schemas = append(out.Schemas, s)
		}
	}
	for _, c := range src.Configs {
		if _, ok := x.Configs[c.ID]; !ok {
			out.Configs = append(out.Configs, c)
		}
	}

	// The child's world: fixtures it marks attributes.world (its deployment:
	// topology, seed state, config) come along namespaced, and every
	// scenario of the composed document applies them before its own.
	// The fixtures they extend come along too, under the same prefix.
	srcFx := map[string]*Fixture{}
	for i := range src.Fixtures {
		srcFx[src.Fixtures[i].ID] = &src.Fixtures[i]
	}
	var world []string
	carried := map[string]bool{}
	var carry func(id string, depth int) error
	carry = func(id string, depth int) error {
		f := srcFx[id]
		if f == nil || carried[id] || depth > 16 {
			return nil
		}
		carried[id] = true
		fx := renameFixture(*f, rn, path)
		if x.Fixtures[fx.ID] != nil {
			return fmt.Errorf("fixture %q already exists", fx.ID)
		}
		out.Fixtures = append(out.Fixtures, fx)
		for _, e := range f.Extends {
			if err := carry(e, depth+1); err != nil {
				return err
			}
		}
		return nil
	}
	for i := range src.Fixtures {
		if w, _ := src.Fixtures[i].Attributes["world"].(bool); !w {
			continue
		}
		if err := carry(src.Fixtures[i].ID, 0); err != nil {
			return nil, err
		}
		world = append(world, path+"/"+src.Fixtures[i].ID)
	}
	if len(world) > 0 {
		for i := range out.Scenarios {
			sc := &out.Scenarios[i]
			sc.Fixtures = append(append([]string(nil), world...), sc.Fixtures...)
		}
	}

	// The shell: the refined component keeps its interfaces' ids, which now
	// forward to the implementations.
	for i := range out.Components {
		if out.Components[i].ID == shell.ID {
			out.Components[i].Capacity = nil
		}
	}
	for i := range out.Interfaces {
		f := &out.Interfaces[i]
		to, ok := impl[f.ID]
		if !ok {
			continue
		}
		f.LatencyMS, f.Store, f.Limits = &Latency{}, nil, nil // zero: the child's timing replaces the parent's
		f.LatencyByOutcome = nil
		f.StreamsWhen = "" // the new behavior has no yield of its own
		f.Behavior = []Step{
			{Call: to, Input: json.RawMessage(`"=input"`), As: "refined"},
			{Return: json.RawMessage(`"=vars.refined.value"`)},
		}
	}
	out.EnsureSlices()
	return out, nil
}

// renameFixture moves a child's world fixture under the refined component
// at path: its id and the fixtures it extends take the "<path>/" prefix, and
// its topology, state and limiter keys name the composed components.
func renameFixture(f Fixture, rn renamer, path string) Fixture {
	key := func(k string) string {
		c, inst := SplitStateKey(k)
		return StateKey(rn.comp(c), inst)
	}
	out := f
	out.ID = path + "/" + f.ID
	out.Extends = nil
	for _, e := range f.Extends {
		out.Extends = append(out.Extends, path+"/"+e)
	}
	if f.Topology != nil {
		out.Topology = map[string][]string{}
		for k, v := range f.Topology {
			out.Topology[rn.comp(k)] = v
		}
	}
	if f.State != nil {
		out.State = map[string]map[string]any{}
		for k, v := range f.State {
			out.State[key(k)] = v
		}
	}
	if f.Limiters != nil {
		out.Limiters = LimiterSeeds{}
		for k, v := range f.Limiters {
			out.Limiters[rn.limiter(k)] = v
		}
	}
	return out
}

func copyWithout(m map[string]any, keys ...string) map[string]any {
	out := map[string]any{}
	for k, v := range m {
		if !contains(keys, k) {
			out[k] = v
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// LoadImportFiles fills d.ImportDocs, recursively, for the imports that
// name a document file (§14.11 "imports resolve by path"): a relative path
// resolves against dir, the importing document's directory, else the
// working directory, and a directory to its single ontology document
// (resolveImportPath). read reads a file (os.ReadFile in callers). An import whose ontology is not a readable
// file is left unloaded (a store id, for a store-backed loader); it fails
// later, when the import is merged. Each file is parsed once.
func LoadImportFiles(d *Document, dir string, read func(string) ([]byte, error)) error {
	return loadImportFiles(d, dir, read, map[string]*Document{}, 0)
}

func loadImportFiles(d *Document, dir string, read func(string) ([]byte, error), cache map[string]*Document, depth int) error {
	if depth > 16 {
		return fmt.Errorf("imports nest too deep")
	}
	for _, im := range d.Imports {
		if d.ImportDocs[im.Ontology] != nil {
			continue
		}
		p, found, err := resolveImportPath(im.Ontology, dir)
		if err != nil {
			return err
		}
		if !found {
			continue
		}
		sub, ok := cache[p]
		if !ok {
			data, err := read(p)
			if err != nil {
				if errors.Is(err, fs.ErrNotExist) {
					continue
				}
				return fmt.Errorf("import %q: %w", im.Ontology, err)
			}
			if sub, err = ParseDocument(data); err != nil {
				return fmt.Errorf("import %q: %w", im.Ontology, err)
			}
			cache[p] = sub
			if err := loadImportFiles(sub, filepath.Dir(p), read, cache, depth+1); err != nil {
				return fmt.Errorf("import %q: %w", im.Ontology, err)
			}
		}
		if d.ImportDocs == nil {
			d.ImportDocs = map[string]*Document{}
		}
		d.ImportDocs[im.Ontology] = sub
	}
	return nil
}

// MergeImports returns doc with its imports merged in (§14.6, §14.11).
// imported maps each import's ontology reference to its loaded document.
// Imported components, interfaces and links keep their ids, under
// "<as>/" when the import gives as:, and schemas under "<as>.". A local
// entity of the same id wins, unless it is a boundary stub
// (attributes.boundary: true), which the import replaces. Imported
// configs are added unless the document has them, and imported fixtures
// (its worlds) under "<as>/" unless the document has them; imported flows
// and scenarios (the substrate's own tests) are not merged.
// Imports of imported documents that carry ImportDocs merge recursively.
func MergeImports(doc *Document, imported map[string]*Document) (*Document, error) {
	return mergeImports(doc, imported, 0)
}

func mergeImports(doc *Document, imported map[string]*Document, depth int) (*Document, error) {
	if depth > 16 {
		return nil, fmt.Errorf("imports nest too deep")
	}
	out, err := CloneDocument(doc)
	if err != nil {
		return nil, err
	}
	out.ImportDocs = nil
	for _, im := range doc.Imports {
		src := imported[im.Ontology]
		if src == nil {
			return nil, fmt.Errorf("import %q is not loaded", im.Ontology)
		}
		if len(src.ImportDocs) > 0 {
			if src, err = mergeImports(src, src.ImportDocs, depth+1); err != nil {
				return nil, fmt.Errorf("import %q: %w", im.Ontology, err)
			}
		}
		if src, err = CloneDocument(src); err != nil {
			return nil, err
		}
		if src, err = prefixImportConfigs(src, out, im.As); err != nil {
			return nil, fmt.Errorf("import %q: %w", im.Ontology, err)
		}
		if err := mergeOne(out, src, im.As); err != nil {
			return nil, fmt.Errorf("import %q: %w", im.Ontology, err)
		}
	}
	out.EnsureSlices()
	return out, nil
}

func mergeOne(out, src *Document, as string) error {
	compMap := map[string]string{}
	if as != "" {
		for _, c := range src.Components {
			compMap[c.ID] = as + "/" + c.ID
		}
	}
	rn := mapper(src, compMap)
	ifaces := map[string]bool{}
	for _, f := range src.Interfaces {
		f.Normalize()
		ifaces[f.ID] = true
	}
	rn.topic = importTopic(rn, ifaces, as) // §17 item 8
	schema := func(id string) string { return id }
	if as != "" {
		ids := map[string]bool{}
		for _, s := range src.Schemas {
			ids[s.ID] = true
		}
		schema = func(id string) string {
			if ids[id] {
				return as + "." + id
			}
			return id
		}
	}
	x := NewIndex(out)
	replaced := map[string]bool{} // local stub components the import replaces
	skipped := map[string]bool{}  // imported components a local one overrides
	for i := range src.Components {
		c := src.Components[i]
		rn.renameComponent(&c)
		if local, ok := x.Components[c.ID]; ok {
			if !isBoundary(local) {
				skipped[c.ID] = true
				continue
			}
			replaced[c.ID] = true
			*local = c
			continue
		}
		out.Components = append(out.Components, c)
	}
	for i := range src.Interfaces {
		f := src.Interfaces[i]
		rn.renameInterface(&f)
		f.Request, f.Response = renameSchemaRefs(f.Request, schema), renameSchemaRefs(f.Response, schema)
		if skipped[f.Component] {
			continue
		}
		if local, ok := x.Interfaces[f.ID]; ok {
			if replaced[f.Component] {
				*local = f
			}
			continue
		}
		out.Interfaces = append(out.Interfaces, f)
	}
	for i := range src.Links {
		l := src.Links[i]
		rn.renameLink(&l)
		if as != "" {
			l.ID = as + "/" + l.ID
		}
		if !hasLink(out, l.ID) {
			out.Links = append(out.Links, l)
		}
	}
	for _, s := range src.Schemas {
		s.ID = schema(s.ID)
		s.Schema, _ = renameSchemaRefs(s.Schema, schema).(map[string]any)
		if _, ok := x.Schemas[s.ID]; !ok {
			out.Schemas = append(out.Schemas, s)
		}
	}
	for _, c := range src.Configs {
		if _, ok := x.Configs[c.ID]; !ok {
			out.Configs = append(out.Configs, c)
		}
	}
	// The import's fixtures are its worlds: they come along under the
	// prefix, inert until a local fixture extends one (a refinement's
	// world, §14.12) or a run names it.
	for i := range src.Fixtures {
		fx := src.Fixtures[i]
		if as != "" {
			fx = renameFixture(fx, rn, as)
		}
		if _, ok := x.Fixtures[fx.ID]; !ok {
			out.Fixtures = append(out.Fixtures, fx)
		}
	}
	return nil
}

func hasLink(d *Document, id string) bool {
	for _, l := range d.Links {
		if l.ID == id {
			return true
		}
	}
	return false
}

// renameSchemaRefs rewrites schema references: a schema id string, and
// every "$ref" naming a schema id (or "#/schemas/<id>") inside a schema.
func renameSchemaRefs(v any, rename func(string) string) any {
	switch t := v.(type) {
	case string:
		if id, ok := strings.CutPrefix(t, "#/schemas/"); ok {
			return "#/schemas/" + rename(id)
		}
		return rename(t)
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, x := range t {
			if r, ok := x.(string); ok && k == "$ref" {
				out[k] = renameSchemaRefs(r, rename)
				continue
			}
			if _, isStr := x.(string); isStr {
				out[k] = x
				continue
			}
			out[k] = renameSchemaRefs(x, rename)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, x := range t {
			if _, isStr := x.(string); isStr {
				out[i] = x
				continue
			}
			out[i] = renameSchemaRefs(x, rename)
		}
		return out
	}
	return v
}
