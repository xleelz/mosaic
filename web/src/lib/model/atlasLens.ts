// What the Atlas lenses and trust marks put on a view's boxes. The layout never depends on any of
// this, so spatial memory holds when the lens changes.
//
// Only type imports (and sibling .ts files) here: node --test runs this file with type stripping.

import type { EvidenceMechanism, Flow, MechanismFidelity, Scenario } from "../api/types";
import type { DocIndex } from "./docindex";
import type { AtlasBox, AtlasEdge, AtlasModel, AtlasView } from "./atlas";
import { flowReach, type CallIndex } from "./atlasFlows.ts";
import { OTHER_AREA } from "./atlas.ts";

export type Lens = "area" | "failure" | "flow" | "data";
export const LENSES: { value: Lens; label: string; meaning: string }[] = [
  { value: "area", label: "Area", meaning: "Color is the area. Thickness is the call count." },
  { value: "failure", label: "Failure", meaning: "Tint counts scenarios that inject a fault here. Click a box to list them." },
  { value: "flow", label: "Flow", meaning: "Lit boxes could be reached by the chosen flow (static)." },
  { value: "data", label: "Data", meaning: "Lit boxes hold state. Arrows run from who writes it. Click a box to list them." },
];

export function parseLens(v: string | null | undefined): Lens {
  return v === "failure" || v === "flow" || v === "data" ? v : "area";
}

export type Counts = Record<MechanismFidelity, number> & { total: number };

function count(items: readonly EvidenceMechanism[]): Counts {
  const c: Counts = { modeled: 0, partial: 0, shell: 0, absent: 0, total: items.length };
  for (const m of items) c[m.fidelity]++;
  return c;
}

export interface AreaMechanisms {
  items: EvidenceMechanism[];
  counts: Counts;
  absent: EvidenceMechanism[];
}

export interface MechanismPlacement {
  byArea: Map<string, AreaMechanisms>;
  /** Mechanisms that no route could place on an area. Nothing is dropped. */
  unplaced: EvidenceMechanism[];
}

function majority(tally: ReadonlyMap<string, number>): string | undefined {
  let best: string | undefined;
  let most = 0;
  for (const [k, n] of tally) {
    if (n > most || (n === most && best !== undefined && k < best)) {
      best = k;
      most = n;
    }
  }
  return best;
}

/**
 * Puts each mechanism on a component area. The list's own area, where the model has one of that
 * name. Otherwise the area most of its interfaces live in. An absent mechanism has no interfaces,
 * so it goes where most of its list's placed mechanisms went. What's left stays unplaced.
 */
export function placeMechanisms(m: AtlasModel, idx: DocIndex, items: readonly EvidenceMechanism[]): MechanismPlacement {
  const areaOfIface = (iface: string): string | undefined => {
    const c = idx.interfacesById.get(iface)?.component;
    if (!c) return undefined;
    const a = idx.area.get(c) ?? OTHER_AREA;
    return m.areaByKey.has(a) ? a : undefined;
  };
  const direct = (mech: EvidenceMechanism): string | undefined => {
    if (m.areaByKey.has(mech.area)) return mech.area;
    const tally = new Map<string, number>();
    for (const i of mech.interfaces) {
      const a = areaOfIface(i);
      if (a) tally.set(a, (tally.get(a) ?? 0) + 1);
    }
    return majority(tally);
  };
  const listTally = new Map<string, Map<string, number>>();
  const placed = new Map<EvidenceMechanism, string>();
  for (const mech of items) {
    const a = direct(mech);
    if (!a) continue;
    placed.set(mech, a);
    let t = listTally.get(mech.area);
    if (!t) listTally.set(mech.area, (t = new Map()));
    t.set(a, (t.get(a) ?? 0) + 1);
  }
  const lists = new Map<string, EvidenceMechanism[]>();
  const unplaced: EvidenceMechanism[] = [];
  for (const mech of items) {
    const tally = listTally.get(mech.area);
    const a = placed.get(mech) ?? (tally ? majority(tally) : undefined);
    if (!a) {
      unplaced.push(mech);
      continue;
    }
    const l = lists.get(a);
    if (l) l.push(mech);
    else lists.set(a, [mech]);
  }
  const byArea = new Map<string, AreaMechanisms>();
  for (const [a, list] of lists) byArea.set(a, { items: list, counts: count(list), absent: list.filter((x) => x.fidelity === "absent") });
  return { byArea, unplaced };
}

/** Box id -> the fidelity of the mechanisms that attach to its components through interfaces. */
export function boxFidelity(view: AtlasView, idx: DocIndex, items: readonly EvidenceMechanism[]): Map<string, Counts> {
  const perBox = new Map<string, EvidenceMechanism[]>();
  for (const mech of items) {
    const boxes = new Set<string>();
    for (const i of mech.interfaces) {
      const c = idx.interfacesById.get(i)?.component;
      const b = c ? view.repOf.get(c) : undefined;
      if (b) boxes.add(b);
    }
    for (const b of boxes) {
      const l = perBox.get(b);
      if (l) l.push(mech);
      else perBox.set(b, [mech]);
    }
  }
  return new Map(Array.from(perBox, ([b, l]) => [b, count(l)]));
}

// ---- Lens decoration ----------------------------------------------------

export interface LensDecor {
  /** Box id -> the number the lens shows. */
  counts: Map<string, number>;
  /** Boxes the lens lights. Null: it dims nothing. */
  lit: Set<string> | null;
  /** Connections the lens draws, whatever their strength; some may not be in the view's edges. */
  edges: AtlasEdge[];
}

/** The step of a five-step tint for a count: 0 for none, logarithmic above that. */
export function tintStep(n: number, heaviest: number): 0 | 1 | 2 | 3 | 4 {
  if (n <= 0 || heaviest <= 0) return 0;
  if (heaviest === 1) return 4;
  const t = Math.log(1 + n) / Math.log(1 + heaviest);
  return Math.min(4, Math.max(1, Math.ceil(t * 4))) as 1 | 2 | 3 | 4;
}

export function failureDecor(view: AtlasView, faults: ReadonlyMap<string, readonly Scenario[]>): LensDecor {
  const counts = new Map<string, number>();
  for (const b of view.boxes) {
    const n = faultsForBox(b, faults).length;
    if (n) counts.set(b.id, n);
  }
  return { counts, lit: null, edges: [] };
}

/** The distinct fault scenarios aimed at anything a box stands for. */
export function faultsForBox(box: AtlasBox, faults: ReadonlyMap<string, readonly Scenario[]>): Scenario[] {
  const out = new Map<string, Scenario>();
  for (const c of box.members) for (const s of faults.get(c) ?? []) out.set(s.id, s);
  return Array.from(out.values());
}

/** Connects component hops through the view's boxes and stubs. */
function hopEdges(view: AtlasView, hops: readonly { from: string; to: string }[]): AtlasEdge[] {
  const known = new Map(view.edges.map((e) => [e.id, e]));
  const out = new Map<string, AtlasEdge>();
  for (const h of hops) {
    const a = view.repOf.get(h.from);
    const b = view.repOf.get(h.to);
    const from = a ?? (b ? view.stubFor(h.from, "in") : undefined);
    const to = b ?? (a ? view.stubFor(h.to, "out") : undefined);
    if (!from || !to || from === to) continue;
    const id = `${from}->${to}`;
    out.set(id, known.get(id) ?? { id, from, to, weight: 1, emits: false, strong: true });
  }
  return Array.from(out.values());
}

export function flowDecor(view: AtlasView, flow: Flow, calls: CallIndex, idx: DocIndex): LensDecor {
  const reach = flowReach(flow, calls, idx);
  const lit = new Set<string>();
  const counts = new Map<string, number>();
  for (const b of view.boxes) {
    let n = 0;
    for (const c of b.members) if (reach.components.has(c)) n++;
    if (n) {
      lit.add(b.id);
      counts.set(b.id, n);
    }
  }
  const edges = hopEdges(view, reach.hops);
  for (const e of edges) {
    lit.add(e.from);
    lit.add(e.to);
  }
  return { counts, lit, edges };
}

export function dataDecor(view: AtlasView, m: AtlasModel, writers: ReadonlyMap<string, readonly string[]>): LensDecor {
  const counts = new Map<string, number>();
  const lit = new Set<string>();
  for (const b of view.boxes) {
    let n = 0;
    for (const c of b.members) if (m.nodes.get(c)?.stateful) n++;
    if (n) {
      counts.set(b.id, n);
      lit.add(b.id);
    }
  }
  const hops: { from: string; to: string }[] = [];
  for (const [state, list] of writers) for (const w of list) hops.push({ from: w, to: state });
  const edges = hopEdges(view, hops).filter((e) => lit.has(e.to) || e.to.startsWith("stub:"));
  for (const e of edges) {
    lit.add(e.from);
    lit.add(e.to);
  }
  return { counts, lit, edges };
}

export interface DataRow {
  component: string;
  writers: string[];
}

/** The stateful components a box stands for, and who writes each. */
export function dataForBox(box: AtlasBox, m: AtlasModel, writers: ReadonlyMap<string, readonly string[]>): DataRow[] {
  const out: DataRow[] = [];
  for (const c of box.members) if (m.nodes.get(c)?.stateful) out.push({ component: c, writers: [...(writers.get(c) ?? [])] });
  return out;
}
