// Fixtures and topology (docs/DESIGN.md §11.1, §11.7): the extends chain of a
// fixture, the effective world of a list of fixtures, and the instance group
// each component belongs to under a topology.

import type { Clock, Document, Fixture, JsonObject, Topology } from "@/lib/api/types";
import { deepMerge, isPlainObject } from "./format";

export interface FixtureChain {
  /** Fixture ids in application order: each fixture's extends (recursively, in order) before itself. */
  order: string[];
  /** Ids that extend themselves, directly or not; the cycle is cut where it closes. */
  cycles: string[];
  /** Ids named by extends (or asked for) that aren't fixtures. */
  missing: string[];
}

/** Resolves the extends chains of `ids`, in order, cycle-safe. A fixture applies once. */
export function fixtureChain(doc: Document, ids: string[]): FixtureChain {
  const byId = new Map((doc.fixtures ?? []).map((f) => [f.id, f]));
  const out: FixtureChain = { order: [], cycles: [], missing: [] };
  const done = new Set<string>();
  const visiting = new Set<string>();
  const visit = (id: string) => {
    if (done.has(id)) return;
    if (visiting.has(id)) {
      if (!out.cycles.includes(id)) out.cycles.push(id);
      return;
    }
    const f = byId.get(id);
    if (!f) {
      if (!out.missing.includes(id)) out.missing.push(id);
      return;
    }
    visiting.add(id);
    for (const e of f.extends ?? []) visit(e);
    visiting.delete(id);
    done.add(id);
    out.order.push(id);
  };
  ids.forEach(visit);
  return out;
}

export interface World {
  topology: Topology;
  config: JsonObject;
  state: { [key: string]: JsonObject };
  clock?: Clock;
}

/** Applies fixtures in chain order: later topology entries and clocks replace, config and state deep-merge. */
export function effectiveWorld(doc: Document, ids: string[]): World & { chain: FixtureChain } {
  const chain = fixtureChain(doc, ids);
  const byId = new Map((doc.fixtures ?? []).map((f) => [f.id, f]));
  const w: World = { topology: {}, config: {}, state: {} };
  for (const id of chain.order) applyFixture(w, byId.get(id)!);
  return { ...w, chain };
}

function applyFixture(w: World, f: Fixture) {
  for (const [c, insts] of Object.entries(f.topology ?? {})) w.topology[c] = [...(insts ?? [])];
  const cfg = deepMerge(w.config, f.config);
  if (isPlainObject(cfg)) w.config = cfg;
  for (const [k, v] of Object.entries(f.state ?? {})) {
    const merged = deepMerge(w.state[k], v);
    if (isPlainObject(merged)) w.state[k] = merged;
  }
  if (f.clock) w.clock = { ...f.clock };
}

export interface InstanceGroup {
  /** The component whose topology entry names the instances. */
  owner: string;
  instances: string[];
}

/**
 * The instance group of each component that has one: its nearest ancestor (or
 * itself) with a topology entry. Components outside every group are absent.
 */
export function instanceGroups(doc: Document, topology: Topology): Map<string, InstanceGroup> {
  const parent = new Map(doc.components.map((c) => [c.id, c.parent ?? ""]));
  const out = new Map<string, InstanceGroup>();
  for (const c of doc.components) {
    const seen = new Set<string>();
    for (let cur = c.id; cur && !seen.has(cur); cur = parent.get(cur) ?? "") {
      seen.add(cur);
      if (topology[cur]) {
        out.set(c.id, { owner: cur, instances: topology[cur] });
        break;
      }
    }
  }
  return out;
}
