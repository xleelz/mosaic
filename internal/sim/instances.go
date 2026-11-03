package sim

import (
	"fmt"

	"github.com/xleelz/mosaic/internal/expr"
	"github.com/xleelz/mosaic/internal/model"
)

// groupInfo is a component's instance group (§11.1): the component whose
// topology entry governs it and that entry's instances. ok is false for a
// component with no group, which has one unnamed instance ("").
type groupInfo struct {
	group     string
	instances []string
	ok        bool
}

// groupOf returns the instance group of a component. A topology entry with
// no instances counts as no entry.
func (r *run) groupOf(comp string) groupInfo {
	if len(r.topology) == 0 {
		return groupInfo{}
	}
	if g, ok := r.groups[comp]; ok {
		return g
	}
	g, inst, ok := r.x.InstanceGroup(r.topology, comp)
	gi := groupInfo{group: g, instances: inst, ok: ok && len(inst) > 0}
	r.groups[comp] = gi
	return gi
}

// instancesOf lists a component's instances: its group's, or the single
// unnamed one.
func (r *run) instancesOf(comp string) []string {
	if g := r.groupOf(comp); g.ok {
		return g.instances
	}
	return []string{""}
}

// targetInstance picks the instance a call, emit or publish delivery from
// caller runs on (§11.1). on is an instance name or "=cel" evaluated in env
// over act; bad reports an on that names no instance of the callee.
func (r *run) targetInstance(callerComp, callerInst, callee, on string, env *expr.Env, act map[string]any) (inst string, bad bool, err error) {
	f, known := r.x.Interfaces[callee]
	if !known {
		return "", false, nil
	}
	g := r.groupOf(f.Component)
	if on != "" {
		name, err := evalOn(on, env, act)
		if err != nil {
			return "", false, err
		}
		if !g.ok {
			return name, name != "", nil
		}
		return name, !containsStr(g.instances, name), nil
	}
	if !g.ok {
		return "", false, nil
	}
	if cg := r.groupOf(callerComp); cg.ok && cg.group == g.group && containsStr(g.instances, callerInst) {
		return callerInst, false, nil
	}
	if len(g.instances) > 1 {
		r.warn(fmt.Sprintf("%s runs on %s, the first of the %d instances of %s; set on to choose", callee, g.instances[0], len(g.instances), g.group))
	}
	return g.instances[0], false, nil
}

// entryInstance picks the instance an entry call runs on: on when given,
// else the first instance of the entry component's group.
func (r *run) entryInstance(entry *model.Interface, on string, env *expr.Env, act map[string]any) (string, bool, error) {
	g := r.groupOf(entry.Component)
	if on == "" {
		if g.ok {
			return g.instances[0], false, nil
		}
		return "", false, nil
	}
	name, err := evalOn(on, env, act)
	if err != nil {
		return "", false, err
	}
	if !g.ok {
		return name, name != "", nil
	}
	return name, !containsStr(g.instances, name), nil
}

func evalOn(on string, env *expr.Env, act map[string]any) (string, error) {
	src, isExpr := expr.ExprOf(on)
	if !isExpr {
		return on, nil
	}
	v, err := env.Eval(src, act)
	if err != nil {
		return "", err
	}
	s, ok := v.(string)
	if !ok {
		return "", fmt.Errorf("%s must give an instance name, got %T", on, v)
	}
	return s, nil
}
