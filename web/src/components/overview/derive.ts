// What Overview says, derived from the document. None of it is hand-picked, so the page says so.
//
// Runtime imports carry the .ts extension: node --test runs this file with type stripping.

import type { Document, EvidenceMechanism, Flow, Interface } from "../../lib/api/types";
import { OTHER, flowSectionKeys, type DocIndex } from "../../lib/model/docindex.ts";
import { countFidelity, emptyCounts, type FidelityCounts } from "../trust/fidelity.ts";

export interface EntryPoint {
  id: string;
  name: string;
  kind?: string;
  /** Flows that enter here. */
  flows: number;
}

const OUTSIDE_KINDS = new Set(["client", "external"]);

function isOutside(kind: string | undefined): boolean {
  return OUTSIDE_KINDS.has((kind ?? "").toLowerCase());
}

function entryTarget(flow: Flow, idx: DocIndex): string | undefined {
  const e = flow.entry;
  if (!e) return undefined;
  const iface: Interface | undefined = idx.interfacesById.get(e.interface);
  const target = iface?.component ?? (e.interface.includes(".") ? e.interface.slice(0, e.interface.indexOf(".")) : undefined);
  return target && idx.componentsById.has(target) ? target : undefined;
}

/**
 * Where a request comes into the system: components of kind client or external that start a flow
 * or are declared, and the component a flow enters when its caller is inside the system.
 * Dependencies are the external components no flow starts from.
 */
export function entryPoints(doc: Document, idx: DocIndex): { entries: EntryPoint[]; dependencies: EntryPoint[] } {
  const flows = new Map<string, number>();
  for (const f of doc.flows ?? []) {
    const caller = f.entry?.caller ? idx.componentsById.get(f.entry.caller) : undefined;
    const at = caller && isOutside(caller.kind) ? caller.id : entryTarget(f, idx);
    if (at) flows.set(at, (flows.get(at) ?? 0) + 1);
  }
  const point = (id: string): EntryPoint => {
    const c = idx.componentsById.get(id);
    return { id, name: c?.name || id, kind: c?.kind, flows: flows.get(id) ?? 0 };
  };
  const entries = Array.from(flows.keys()).map(point);
  const dependencies: EntryPoint[] = [];
  for (const c of doc.components ?? []) {
    if (flows.has(c.id)) continue;
    const kind = (c.kind ?? "").toLowerCase();
    if (kind === "client") entries.push(point(c.id));
    else if (kind === "external") dependencies.push(point(c.id));
  }
  entries.sort((a, b) => b.flows - a.flows || a.name.localeCompare(b.name));
  dependencies.sort((a, b) => a.name.localeCompare(b.name));
  return { entries, dependencies };
}

export interface AreaRow {
  area: string;
  components: number;
  flows: number;
  mechanisms: FidelityCounts;
}

export interface AreaRollup {
  rows: AreaRow[];
  /** Mechanisms that attach to no area here: their list's area and their interfaces both miss. */
  unplaced: FidelityCounts;
}

/** The area a mechanism attaches to: its own, when components use it, else the most common among its interfaces' components. */
export function mechanismArea(m: Pick<EvidenceMechanism, "area" | "interfaces">, idx: DocIndex, known: ReadonlySet<string>): string | undefined {
  if (known.has(m.area)) return m.area;
  const tally = new Map<string, number>();
  for (const i of m.interfaces) {
    const comp = idx.interfacesById.get(i)?.component;
    const a = comp ? idx.area.get(comp) : undefined;
    if (a) tally.set(a, (tally.get(a) ?? 0) + 1);
  }
  let best: string | undefined;
  for (const [a, n] of tally) if (best === undefined || n > tally.get(best)! || (n === tally.get(best)! && a < best)) best = a;
  return best;
}

/** Areas with their counts, largest first. Empty when no component has an area. */
export function areaRollup(doc: Document, idx: DocIndex, mechanisms: readonly EvidenceMechanism[]): AreaRollup {
  if (idx.area.size === 0) return { rows: [], unplaced: countFidelity(mechanisms) };
  const rows = new Map<string, AreaRow>();
  const row = (area: string) => {
    let r = rows.get(area);
    if (!r) {
      r = { area, components: 0, flows: 0, mechanisms: emptyCounts() };
      rows.set(area, r);
    }
    return r;
  };
  for (const c of idx.componentsById.values()) row(idx.area.get(c.id) ?? OTHER).components++;
  for (const f of doc.flows ?? []) for (const k of flowSectionKeys(f, idx, "area")) row(k).flows++;
  const known = new Set(idx.area.values());
  const unplaced = emptyCounts();
  for (const m of mechanisms) {
    const a = mechanismArea(m, idx, known);
    const c = a ? row(a).mechanisms : unplaced;
    c[m.fidelity]++;
    c.total++;
  }
  const list = Array.from(rows.values()).sort((a, b) => {
    if ((a.area === OTHER) !== (b.area === OTHER)) return a.area === OTHER ? 1 : -1;
    return b.components - a.components || a.area.localeCompare(b.area);
  });
  return { rows: list, unplaced };
}

export interface ComponentRowLite {
  id: string;
  name: string;
  kind?: string;
  members: number;
}

/** For a model with no areas: its top-level components, those holding the most first. */
export function topLevelRows(idx: DocIndex, members: ReadonlyMap<string, number>): ComponentRowLite[] {
  return (idx.childrenByParent.get("") ?? [])
    .map((c) => ({ id: c.id, name: c.name || c.id, kind: c.kind, members: members.get(c.id) ?? 0 }))
    .sort((a, b) => b.members - a.members || a.name.localeCompare(b.name));
}
