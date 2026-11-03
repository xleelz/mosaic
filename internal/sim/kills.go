package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// Kills (§13.1 item 18) terminate a component instance at a virtual time:
// a kill fault {type: kill, target, instance, at_ms} or a kill step. The
// instance's tasks stop: a task whose work is a call into the instance
// unwinds to that call, recording call.end {code: killed} for every call
// it abandons, and the caller of the outermost one gets
// {code: peer-killed}; a parallel branch running inside such a call stops.
// Its queued deliveries are dropped, rendezvous it waits in fail for the
// other waiters with peer-killed, later calls to it fail with peer-killed,
// and its state is marked dead: true. A restart of the instance revives it.

// activeCall is a call in progress in a task.
type activeCall struct {
	comp, inst string
}

// scope is an instance of a component group: the components whose nearest
// topology entry is root's, on inst; for a component without instances,
// its subtree.
type scope struct {
	root, inst string
	topo       map[string][]string
}

// in reports whether a component instance belongs to the scope.
func (r *run) in(sc scope, comp, inst string) bool {
	grp, _, ok := r.x.InstanceGroup(sc.topo, comp)
	return ok && grp == sc.root && inst == sc.inst
}

// scopeOf resolves the instance group of comp on inst, as restart does.
// Without inst, it is the group's first instance.
func (r *run) scopeOf(comp, inst, p string) (scope, error) {
	if _, ok := r.x.Components[comp]; !ok {
		return scope{}, abortf("%s: unknown component %q", p, comp)
	}
	g := r.groupOf(comp)
	if inst == "" && g.ok {
		inst = g.instances[0]
	}
	if g.ok && !containsStr(g.instances, inst) {
		return scope{}, abortf("%s: %s has no instance %q", p, comp, inst)
	}
	if !g.ok && inst != "" {
		return scope{}, abortf("%s: %s has no instances, so instance %q does not exist", p, comp, inst)
	}
	if g.ok {
		return scope{root: g.group, inst: inst, topo: r.topology}, nil
	}
	topo := map[string][]string{}
	for c, l := range r.topology {
		topo[c] = l
	}
	topo[comp] = []string{""}
	return scope{root: comp, inst: "", topo: topo}, nil
}

func (sc scope) key() string { return sc.root + "@" + sc.inst }

// isDead reports whether a component instance has been killed and not
// restarted since.
func (r *run) isDead(comp, inst string) bool {
	for _, k := range sortedKeys(r.dead) {
		if r.in(r.dead[k], comp, inst) {
			return true
		}
	}
	return false
}

func peerKilledError(comp, inst string) *Error {
	where := comp
	if inst != "" {
		where += "@" + inst
	}
	return &Error{Code: "peer-killed", Retryable: true, Message: where + " was killed"}
}

func killedError(target string) *Error {
	return &Error{Code: "killed", Message: target + ": the instance was killed"}
}

// deathError is what waits on a task that was stopped get: peer-killed
// after a kill, canceled after a restart.
func deathError(t *task, target string) *Error {
	if t.death == "killed" {
		return &Error{Code: "peer-killed", Retryable: true, Message: target + " was killed"}
	}
	return &Error{Code: "canceled", Message: target + " was canceled by a restart"}
}

// killIn runs a behavior's kill step. Without an instance it kills the
// running instance when the component shares its group.
func (r *run) killIn(f *frame, k *model.Kill, p string) error {
	inst := k.Instance
	if src, ok := expr.ExprOf(inst); ok {
		v, err := expr.Behavior.Eval(src, r.act(f, 1))
		if err != nil {
			return abortf("%s.kill.instance: %v", p, err)
		}
		s, ok := v.(string)
		if !ok {
			return abortf("%s.kill.instance: must give an instance name, got %T", p, v)
		}
		inst = s
	} else if inst == "" {
		if g, fg := r.groupOf(k.Component), r.groupOf(f.comp); g.ok && fg.ok && g.group == fg.group {
			inst = f.inst
		}
	}
	return r.killInstance(k.Component, inst, f.comp, f.inst, f.span, p+".kill")
}

// killFault runs a kill fault at its time.
func (r *run) killFault(ft model.Fault, i int) error {
	comp := ft.Target
	if f, ok := r.x.Interfaces[comp]; ok {
		comp = f.Component
	}
	return r.killInstance(comp, ft.Instance, "", "", 0, fmt.Sprintf("faults[%d]", i))
}

// killInstance terminates comp's instance group on inst now (§13.1 item
// 18).
func (r *run) killInstance(comp, inst, fromComp, fromInst string, span int, p string) error {
	sc, err := r.scopeOf(comp, inst, p)
	if err != nil {
		return err
	}
	r.dead[sc.key()] = sc
	st := r.state(model.StateKey(comp, sc.inst))
	st["dead"] = true
	cur := r.s.cur
	var live []*task
	for _, t := range r.s.live {
		live = append(live, t)
	}
	sortTasks(live)
	failed, stopped := 0, 0
	for _, t := range live {
		if t.done || t.killed {
			continue
		}
		inside := false
		for _, ac := range t.via {
			inside = inside || (ac.comp != "" && r.in(sc, ac.comp, ac.inst))
		}
		if inside {
			// A branch of a parallel step that runs inside a call into the
			// instance stops.
			stopped++
			t.death = "killed"
			if t == cur {
				t.killed = true
			} else {
				r.kill(t)
			}
			continue
		}
		// The outermost call into the instance is where the task unwinds to.
		for i, ac := range t.calls {
			if ac.comp == "" || !r.in(sc, ac.comp, ac.inst) {
				continue
			}
			failed++
			if t.unwind == nil || i < callIndex(t, t.unwind) {
				t.unwind = ac
			}
			if t != cur {
				r.wakeAt(t, r.now, 0)
			}
			break
		}
	}
	dropped := r.dropDeliveries(func(t *timer) bool {
		f, ok := r.x.Interfaces[t.target]
		return ok && r.in(sc, f.Component, t.inst)
	})
	if err := r.ev(Event{Type: "kill", Span: span, Component: comp, Instance: sc.inst, From: fromComp,
		Output: map[string]any{"failed": int64(failed), "stopped": int64(stopped), "dropped": int64(dropped)}}); err != nil {
		return err
	}
	r.raiseExits(sc, "killed") // §17 item 14, exits.go
	if cur != nil {
		return cur.stopErr()
	}
	return nil
}

func callIndex(t *task, ac *activeCall) int {
	for i, x := range t.calls {
		if x == ac {
			return i
		}
	}
	return len(t.calls)
}
