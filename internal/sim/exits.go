package sim

import (
	"github.com/xleelz/mosaic/internal/model"
)

// Exit signals (DESIGN §17 item 14). When a component instance's group
// stops, by a kill (fault or step: reason "killed") or by a restart of a
// live instance (reason "restarted"), the simulator delivers the built-in
// signal "exit:<component>[@<instance>]" for every component of the group
// on that instance, in component order, carrying
// {component, instance, reason, at_us}. A blocking wait on it wakes, as a
// monitor blocked on a process sentinel does. Unlike other signals, an
// exit is remembered while the instance stays dead: a wait that starts
// after the kill returns at once. A restart forgets it. Nothing changes
// for a run that waits on no exit signal.

// exitSignal is the name of the exit signal of a component instance.
func exitSignal(comp, inst string) string {
	return "exit:" + model.StateKey(comp, inst)
}

// raiseExits delivers the exit signals of a scope's components. A kill
// remembers them until a restart.
func (r *run) raiseExits(sc scope, reason string) {
	for _, c := range sortedKeys(r.x.Components) {
		if !r.in(sc, c, sc.inst) {
			continue
		}
		name := exitSignal(c, sc.inst)
		data := map[string]any{"component": c, "instance": sc.inst, "reason": reason, "at_us": r.now}
		if reason == "killed" {
			r.exits[name] = data
		}
		r.deliverSignal(name, data)
	}
}

// forgetExits drops the remembered exits of a scope's components, when a
// restart revives it.
func (r *run) forgetExits(sc scope) {
	for _, c := range sortedKeys(r.x.Components) {
		if r.in(sc, c, sc.inst) {
			delete(r.exits, exitSignal(c, sc.inst))
		}
	}
}
