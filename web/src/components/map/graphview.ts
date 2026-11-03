// Graph transforms for the map: collapsing containers, focusing a diff on the
// changed components and their neighbours, and the before/after union used by the diff views.

import type { Graph, GraphEdge, GraphNode, Impact } from "@/lib/api/types";
import { ifaceComponent } from "@/lib/model/format";
import type { ChangeKind } from "@/lib/model/impact";

export function parentMap(g: Graph): Map<string, string | undefined> {
  const ids = new Set(g.nodes.map((n) => n.id));
  return new Map(g.nodes.map((n) => [n.id, n.parent && ids.has(n.parent) && n.parent !== n.id ? n.parent : undefined]));
}

function chain(id: string, parentOf: Map<string, string | undefined>): string[] {
  const out: string[] = [];
  const seen = new Set([id]);
  let cur = parentOf.get(id);
  while (cur && !seen.has(cur)) {
    out.push(cur);
    seen.add(cur);
    cur = parentOf.get(cur);
  }
  return out;
}

/** Ids of nodes that have members. */
export function containers(g: Graph): Set<string> {
  const p = parentMap(g);
  return new Set(Array.from(p.values()).filter((v): v is string => !!v));
}

export interface Collapsed {
  graph: Graph;
  /** Collapsed container id -> the number of components hidden inside it. */
  hidden: Map<string, number>;
}

/**
 * Hides the members of every collapsed container. Edges to a hidden node are
 * moved to its outermost collapsed ancestor and merged; edges that end up
 * inside one collapsed container are dropped.
 */
export function collapseGraph(g: Graph, collapsed: Set<string>): Collapsed {
  const hidden = new Map<string, number>();
  if (collapsed.size === 0) return { graph: g, hidden };
  const parentOf = parentMap(g);
  const visibleAs = new Map<string, string>();
  for (const n of g.nodes) {
    const anc = chain(n.id, parentOf);
    let rep = n.id;
    for (const a of anc) if (collapsed.has(a)) rep = a; // outermost wins
    visibleAs.set(n.id, rep);
    if (rep !== n.id) hidden.set(rep, (hidden.get(rep) ?? 0) + 1);
  }
  const nodes: GraphNode[] = g.nodes.filter((n) => visibleAs.get(n.id) === n.id);
  const merged = new Map<string, GraphEdge>();
  for (const e of g.edges) {
    const from = visibleAs.get(e.from);
    const to = visibleAs.get(e.to);
    if (!from || !to || from === to) continue;
    if (from === e.from && to === e.to) {
      merged.set(e.id, e);
      continue;
    }
    const key = `${e.derived ? e.kind : "link"}:${from}->${to}`;
    const prev = merged.get(key);
    const ifaces = Array.from(new Set([...(prev?.interfaces ?? []), ...(e.interfaces ?? [])])).sort();
    merged.set(key, {
      id: key,
      from,
      to,
      kind: e.derived ? e.kind : prev?.kind ?? e.kind,
      derived: e.derived,
      label: e.derived ? `${ifaces.length} interface${ifaces.length === 1 ? "" : "s"}` : prev ? undefined : e.label,
      interfaces: ifaces,
    });
  }
  return { graph: { nodes, edges: Array.from(merged.values()) }, hidden };
}

export interface DiffStatus {
  nodes: Map<string, ChangeKind>;
  edges: Map<string, ChangeKind>;
  /** Component id -> interface ids that changed on it. */
  ifaces: Map<string, string[]>;
}

/** The union of two graphs: AFTER plus everything only in BEFORE, with per-node and per-edge status. */
export function unionDiff(before: Graph, after: Graph, impact: Impact | null): { graph: Graph; status: DiffStatus } {
  const bNodes = new Map(before.nodes.map((n) => [n.id, n]));
  const aNodes = new Map(after.nodes.map((n) => [n.id, n]));
  const nodes = [...after.nodes, ...before.nodes.filter((n) => !aNodes.has(n.id))].sort((x, y) => (x.id < y.id ? -1 : 1));
  const status = new Map<string, ChangeKind>();
  const ifaces = new Map<string, string[]>();
  const modified = new Set(impact?.components.modified ?? []);
  if (impact) {
    for (const k of ["added", "removed", "modified"] as const) {
      for (const i of impact.interfaces[k]) {
        const c = ifaceComponent(i);
        if (!ifaces.has(c)) ifaces.set(c, []);
        ifaces.get(c)!.push(i);
      }
    }
  }
  for (const n of nodes) {
    if (!bNodes.has(n.id)) status.set(n.id, "added");
    else if (!aNodes.has(n.id)) status.set(n.id, "removed");
    else if (modified.has(n.id) || ifaces.has(n.id)) status.set(n.id, "modified");
  }
  const bEdges = new Map(before.edges.map((e) => [e.id, e]));
  const aEdges = new Map(after.edges.map((e) => [e.id, e]));
  const edges = [...after.edges, ...before.edges.filter((e) => !aEdges.has(e.id))];
  const estatus = new Map<string, ChangeKind>();
  const sig = (e: GraphEdge) => `${e.kind}|${e.label ?? ""}|${(e.interfaces ?? []).join(",")}`;
  for (const e of edges) {
    const b = bEdges.get(e.id);
    const a = aEdges.get(e.id);
    if (!b) estatus.set(e.id, "added");
    else if (!a) estatus.set(e.id, "removed");
    else if (sig(a) !== sig(b)) estatus.set(e.id, "modified");
  }
  return { graph: { nodes, edges }, status: { nodes: status, edges: estatus, ifaces } };
}

/** Components with more call partners than this are hubs (a shared datastore, say). */
export const HUB_DEGREE = 12;

export interface DiffFocusOptions {
  /** 0: changed components only; 1: plus their direct neighbours; 2: plus neighbours of those. */
  hops: number;
  /** Components whose neighbours were asked for explicitly; hubs included. */
  expand?: Iterable<string>;
}

export interface DiffFocus {
  graph: Graph;
  /** The changed components, or the ends of the changed edges when no component changed. */
  changed: string[];
  /** Hubs that were drawn but whose neighbours weren't pulled in. */
  hubs: string[];
}

/**
 * The part of a diff worth drawing: the changed components, their direct call
 * neighbours (a changed hub only brings in the neighbours on changed edges or
 * changed interfaces), more hops on request, and the ancestors of all of them.
 * Ancestors become containers that hold only the drawn members; a parent is
 * never expanded just because one of its children changed.
 */
export function focusDiff(g: Graph, status: DiffStatus, opts: DiffFocusOptions): DiffFocus {
  const parentOf = parentMap(g);
  const adj = new Map<string, Map<string, GraphEdge[]>>();
  const link = (a: string, b: string, e: GraphEdge) => {
    if (!adj.has(a)) adj.set(a, new Map());
    const m = adj.get(a)!;
    if (!m.has(b)) m.set(b, []);
    m.get(b)!.push(e);
  };
  for (const e of g.edges) {
    if (e.from === e.to || !parentOf.has(e.from) || !parentOf.has(e.to)) continue;
    // Container <-> member edges say nothing about who talks to whom outside.
    if (chain(e.to, parentOf).includes(e.from) || chain(e.from, parentOf).includes(e.to)) continue;
    link(e.from, e.to, e);
    link(e.to, e.from, e);
  }
  const degree = (id: string) => adj.get(id)?.size ?? 0;
  const changedIfaces = new Set(Array.from(status.ifaces.values()).flat());
  const relevant = (e: GraphEdge) => status.edges.has(e.id) || (e.interfaces ?? []).some((i) => changedIfaces.has(i));

  const ends = new Set<string>();
  for (const e of g.edges) if (status.edges.has(e.id) && parentOf.has(e.from) && parentOf.has(e.to)) ends.add(e.from).add(e.to);
  const seeds = status.nodes.size > 0 ? Array.from(status.nodes.keys()).filter((id) => parentOf.has(id)) : Array.from(ends);
  const keep = new Set<string>([...seeds, ...ends]);
  const hubs = new Set<string>();
  if (opts.hops >= 1) {
    for (const c of seeds) {
      const hub = degree(c) > HUB_DEGREE;
      if (hub) hubs.add(c);
      for (const [nb, es] of adj.get(c) ?? []) if (!hub || es.some(relevant)) keep.add(nb);
    }
  }
  let frontier = Array.from(keep);
  for (let hop = 2; hop <= opts.hops; hop++) {
    const next: string[] = [];
    for (const x of frontier) {
      if (degree(x) > HUB_DEGREE) {
        hubs.add(x);
        continue;
      }
      for (const nb of adj.get(x)?.keys() ?? []) if (!keep.has(nb)) {
        keep.add(nb);
        next.push(nb);
      }
    }
    frontier = next;
  }
  for (const x of opts.expand ?? []) {
    if (!parentOf.has(x)) continue;
    keep.add(x);
    hubs.delete(x);
    for (const nb of adj.get(x)?.keys() ?? []) keep.add(nb);
  }
  for (const id of Array.from(keep)) for (const a of chain(id, parentOf)) keep.add(a);
  return {
    graph: subgraph(g, keep),
    changed: seeds,
    hubs: Array.from(hubs).filter((h) => keep.has(h)).sort(),
  };
}

/** Container id -> the number of direct members it has in the graph. */
export function memberCounts(g: Graph): Map<string, number> {
  const out = new Map<string, number>();
  for (const p of parentMap(g).values()) if (p) out.set(p, (out.get(p) ?? 0) + 1);
  return out;
}

/** The subgraph made of the given node ids. */
export function subgraph(g: Graph, ids: Set<string>): Graph {
  return { nodes: g.nodes.filter((n) => ids.has(n.id)), edges: g.edges.filter((e) => ids.has(e.from) && ids.has(e.to)) };
}

export const DIFF_COLORS: Record<ChangeKind, string> = {
  added: "#0ca30c",
  modified: "#fab219",
  removed: "#d03b3b",
};
