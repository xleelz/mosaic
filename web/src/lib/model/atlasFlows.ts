// Static reach over behaviors for the Atlas map: which interfaces a behavior could call, which
// components a flow could reach, which fault scenarios aim at a component, and who writes state.
// All of it is "could reach (static)": dynamic targets count when a literal names them, and
// nothing here says a run takes that path.
//
// Only type imports here: node --test runs this file with type stripping.

import type { Document, Flow, Scenario } from "../api/types";
import type { DocIndex } from "./docindex";

export interface CallIndex {
  /** Interface id -> the interfaces its behavior could call, emit to or publish to. */
  calls: Map<string, string[]>;
  /** Interfaces that write their component's state: a store write, or a `set` on state. */
  writes: Set<string>;
}

const WRITE_OPS = new Set(["put", "update", "delete", "incr"]);
/** Step keys holding data, not more steps. */
const DATA_KEYS = new Set(["input", "return", "fail", "set", "source", "value", "foreach", "parallel", "retry", "join", "token"]);

function isStateKey(k: string): boolean {
  return k.startsWith("state.") || k === "state" || /^=\s*'state/.test(k);
}

/** The interfaces a call target can resolve to: itself, or the quoted literals of a "=cel" expression. */
function resolveTargets(target: string, known: ReadonlyMap<string, unknown>): string[] {
  if (!target.startsWith("=")) return known.has(target) ? [target] : [];
  const out: string[] = [];
  for (const m of target.matchAll(/['"]([^'"]+)['"]/g)) if (known.has(m[1])) out.push(m[1]);
  return out;
}

function walkSteps(value: unknown, visit: (step: Record<string, unknown>) => void): void {
  if (Array.isArray(value)) {
    for (const v of value) walkSteps(v, visit);
    return;
  }
  if (!value || typeof value !== "object") return;
  const step = value as Record<string, unknown>;
  visit(step);
  for (const [k, v] of Object.entries(step)) if (!DATA_KEYS.has(k) && v && typeof v === "object") walkSteps(v, visit);
}

export function buildCallIndex(doc: Document, idx: DocIndex): CallIndex {
  const subscribers = new Map<string, string[]>();
  for (const [id, i] of idx.interfacesById) {
    for (const t of i.subscribe ?? []) {
      const l = subscribers.get(t);
      if (l) l.push(id);
      else subscribers.set(t, [id]);
    }
  }
  const calls = new Map<string, string[]>();
  const writes = new Set<string>();
  for (const [id, i] of idx.interfacesById) {
    const out = new Set<string>();
    if (i.store && WRITE_OPS.has(i.store.op)) writes.add(id);
    walkSteps(i.behavior, (s) => {
      if (typeof s.call === "string") for (const t of resolveTargets(s.call, idx.interfacesById)) out.add(t);
      if (Array.isArray(s.targets)) for (const t of s.targets) if (typeof t === "string" && idx.interfacesById.has(t)) out.add(t);
      if (typeof s.emit === "string") {
        for (const t of resolveTargets(s.emit, idx.interfacesById)) out.add(t);
        for (const t of subscribers.get(s.emit) ?? []) out.add(t);
      }
      if (typeof s.publish === "string") for (const t of subscribers.get(s.publish) ?? []) out.add(t);
      if (s.transact || s.put) writes.add(id);
      if (s.set && typeof s.set === "object" && Object.keys(s.set).some(isStateKey)) writes.add(id);
    });
    out.delete(id);
    if (out.size) calls.set(id, Array.from(out).sort());
  }
  return { calls, writes };
}

export interface FlowReach {
  /** Components the flow could reach, its caller included. */
  components: Set<string>;
  /** Component -> component hops it could take. */
  hops: { from: string; to: string }[];
}

/** What a flow could reach from its entry, plus any components its written steps name. */
export function flowReach(flow: Flow, calls: CallIndex, idx: DocIndex): FlowReach {
  const components = new Set<string>();
  const hops = new Map<string, { from: string; to: string }>();
  const hop = (from: string, to: string) => {
    if (from !== to) hops.set(`${from}\u0000${to}`, { from, to });
  };
  const entry = flow.entry?.interface;
  const caller = flow.entry?.caller;
  if (caller && idx.componentsById.has(caller)) components.add(caller);
  const start = entry ? idx.interfacesById.get(entry) : undefined;
  if (entry && start) {
    components.add(start.component);
    if (caller && idx.componentsById.has(caller)) hop(caller, start.component);
    const seen = new Set([entry]);
    const queue = [entry];
    while (queue.length) {
      const cur = queue.pop()!;
      const from = idx.interfacesById.get(cur)!.component;
      for (const next of calls.calls.get(cur) ?? []) {
        const to = idx.interfacesById.get(next)!.component;
        components.add(to);
        hop(from, to);
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
  }
  let prev: string | undefined;
  for (const s of flow.steps ?? []) {
    if (!idx.componentsById.has(s.component)) continue;
    components.add(s.component);
    if (prev) hop(prev, s.component);
    prev = s.component;
  }
  return { components, hops: Array.from(hops.values()) };
}

/** Component id -> the flows that could reach it, as indexes into doc.flows. */
export function flowsByComponent(doc: Document, calls: CallIndex, idx: DocIndex): Map<string, number[]> {
  const out = new Map<string, number[]>();
  (doc.flows ?? []).forEach((f, n) => {
    for (const c of flowReach(f, calls, idx).components) {
      const l = out.get(c);
      if (l) l.push(n);
      else out.set(c, [n]);
    }
  });
  return out;
}

/** The component a fault target lands on: a component id, or an interface id. */
export function faultComponent(target: string, idx: DocIndex): string | undefined {
  const i = idx.interfacesById.get(target);
  if (i) return i.component;
  if (idx.componentsById.has(target)) return target;
  const dot = target.indexOf(".");
  const c = dot > 0 ? target.slice(0, dot) : undefined;
  return c && idx.componentsById.has(c) ? c : undefined;
}

/** Component id -> the scenarios that inject a fault on it. */
export function faultScenarios(doc: Document, idx: DocIndex): Map<string, Scenario[]> {
  const out = new Map<string, Scenario[]>();
  for (const s of doc.scenarios ?? []) {
    const hit = new Set<string>();
    for (const f of s.faults ?? []) {
      const c = faultComponent(f.target, idx);
      if (c) hit.add(c);
    }
    for (const c of hit) {
      const l = out.get(c);
      if (l) l.push(s);
      else out.set(c, [s]);
    }
  }
  return out;
}

/** Stateful component id -> the components that write it: itself, and callers of a writing interface. */
export function stateWriters(stateful: Iterable<string>, calls: CallIndex, idx: DocIndex): Map<string, string[]> {
  const out = new Map<string, Set<string>>();
  for (const s of stateful) out.set(s, new Set());
  const writtenBy = (iface: string) => {
    const owner = idx.interfacesById.get(iface)?.component;
    return owner && out.has(owner) ? out.get(owner)! : null;
  };
  for (const iface of calls.writes) writtenBy(iface)?.add(idx.interfacesById.get(iface)!.component);
  for (const [from, targets] of calls.calls) {
    const caller = idx.interfacesById.get(from)?.component;
    if (!caller) continue;
    for (const t of targets) if (calls.writes.has(t)) writtenBy(t)?.add(caller);
  }
  return new Map(Array.from(out, ([k, v]) => [k, Array.from(v).sort()]));
}
