// Indexes over a document, built once per document object, and the pure
// grouping helpers the Flows tab and the component browser use. Large
// ontologies hold hundreds of components and thousands of scenarios, so
// lookups go through maps instead of `find` and `filter` scans.
//
// Only type imports here: node --test runs this file with type stripping.

import type { Component, Document, Flow, Interface, Scenario } from "../api/types";

export interface DocIndex {
  componentsById: Map<string, Component>;
  interfacesById: Map<string, Interface>;
  /** Interfaces of each component, in document order. */
  interfacesByComponent: Map<string, Interface[]>;
  flowsById: Map<string, Flow>;
  scenariosById: Map<string, Scenario>;
  /** Scenarios grouped under their flow (see scenarioFlow), in document order. */
  scenariosByFlow: Map<string, Scenario[]>;
  /** Members of each component, sorted by id. Top-level components are under "". */
  childrenByParent: Map<string, Component[]>;
  /** The top-level ancestor of each component (itself when it has no known parent). */
  topLevel: Map<string, string>;
  /** attributes.area, else attributes.owner, of the component or its nearest ancestor that has one. */
  area: Map<string, string>;
}

const ROOT = "";

function byId(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function interfaceId(i: Interface): string {
  return i.id || `${i.component}.${i.name}`;
}

function flowOfScenario(s: Scenario): string {
  return s.flow || s.steps?.[0]?.flow || "";
}

function ownArea(c: Component | undefined): string | undefined {
  const a = c?.attributes;
  if (!a) return undefined;
  for (const k of ["area", "owner"]) {
    const v = a[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return undefined;
}

function push<K, V>(m: Map<K, V[]>, k: K, v: V) {
  const l = m.get(k);
  if (l) l.push(v);
  else m.set(k, [v]);
}

export function buildDocIndex(doc: Document): DocIndex {
  const componentsById = new Map<string, Component>();
  for (const c of doc.components ?? []) componentsById.set(c.id, c);

  const interfacesById = new Map<string, Interface>();
  const interfacesByComponent = new Map<string, Interface[]>();
  for (const i of doc.interfaces ?? []) {
    interfacesById.set(interfaceId(i), i);
    push(interfacesByComponent, i.component, i);
  }

  const flowsById = new Map<string, Flow>();
  for (const f of doc.flows ?? []) flowsById.set(f.id, f);

  const scenariosById = new Map<string, Scenario>();
  const scenariosByFlow = new Map<string, Scenario[]>();
  for (const s of doc.scenarios ?? []) {
    scenariosById.set(s.id, s);
    push(scenariosByFlow, flowOfScenario(s), s);
  }

  const childrenByParent = new Map<string, Component[]>();
  for (const c of componentsById.values()) {
    const p = c.parent && c.parent !== c.id && componentsById.has(c.parent) ? c.parent : ROOT;
    push(childrenByParent, p, c);
  }
  for (const l of childrenByParent.values()) l.sort(byId);

  // Walk down from the roots so every component is visited once; a parent
  // cycle (no root) falls back to the component itself.
  const topLevel = new Map<string, string>();
  const area = new Map<string, string>();
  const walk = (c: Component, top: string, inherited: string | undefined) => {
    if (topLevel.has(c.id)) return;
    topLevel.set(c.id, top);
    const a = ownArea(c) ?? inherited;
    if (a) area.set(c.id, a);
    for (const k of childrenByParent.get(c.id) ?? []) walk(k, top, a);
  };
  for (const c of childrenByParent.get(ROOT) ?? []) walk(c, c.id, undefined);
  for (const c of componentsById.values()) if (!topLevel.has(c.id)) walk(c, c.id, undefined);

  return { componentsById, interfacesById, interfacesByComponent, flowsById, scenariosById, scenariosByFlow, childrenByParent, topLevel, area };
}

const cache = new WeakMap<Document, DocIndex>();

/** The index of a document, built on first use and shared by every caller holding the same document. */
export function docIndex(doc: Document): DocIndex {
  let idx = cache.get(doc);
  if (!idx) {
    idx = buildDocIndex(doc);
    cache.set(doc, idx);
  }
  return idx;
}

/** A component's display name, or its id. */
export function nameOf(idx: DocIndex, id: string): string {
  return idx.componentsById.get(id)?.name || id;
}

// ---- Flow sections ------------------------------------------------------

export type FlowGrouping = "feature" | "area" | "parent";

export const FLOW_GROUPINGS: { value: FlowGrouping; label: string }[] = [
  { value: "feature", label: "Feature tag" },
  { value: "area", label: "Area / owner" },
  { value: "parent", label: "Top-level component" },
];

export interface FlowGroup {
  /** Stable key for the URL (?section=). */
  key: string;
  label: string;
  flows: Flow[];
}

export const OTHER = "Other";
const FEATURE = "feature:";

/** The flow's feature tags without the prefix. */
export function featureTags(flow: Flow): string[] {
  return (flow.tags ?? []).filter((t) => t.startsWith(FEATURE) && t.length > FEATURE.length).map((t) => t.slice(FEATURE.length));
}

/**
 * The component a flow enters: the entry interface's component, else the
 * caller. Callers are often external actors shared by many flows, so the
 * entered component tells flows apart better.
 */
export function entryComponents(flow: Flow, idx: DocIndex): string[] {
  const e = flow.entry;
  if (!e) return [];
  const out: string[] = [];
  const iface = idx.interfacesById.get(e.interface);
  const target = iface?.component ?? (e.interface.includes(".") ? e.interface.slice(0, e.interface.indexOf(".")) : undefined);
  if (target && idx.componentsById.has(target)) out.push(target);
  if (e.caller && idx.componentsById.has(e.caller) && e.caller !== target) out.push(e.caller);
  return out;
}

/** The section keys of one flow under a grouping (a flow with several feature tags is in several sections). */
export function flowSectionKeys(flow: Flow, idx: DocIndex, by: FlowGrouping): string[] {
  if (by === "feature") {
    const f = featureTags(flow);
    return f.length ? f : [OTHER];
  }
  const comps = entryComponents(flow, idx);
  if (by === "area") {
    for (const c of comps) {
      const a = idx.area.get(c);
      if (a) return [a];
    }
    return [OTHER];
  }
  const top = comps.length ? idx.topLevel.get(comps[0]) : undefined;
  return [top ?? OTHER];
}

/** Flows split into sections, largest first, then by name; "Other" always last. Flows keep document order inside a section. */
export function groupFlows(flows: Flow[], idx: DocIndex, by: FlowGrouping): FlowGroup[] {
  const m = new Map<string, Flow[]>();
  for (const f of flows) for (const k of flowSectionKeys(f, idx, by)) push(m, k, f);
  const label = (k: string) => (by === "parent" && k !== OTHER ? nameOf(idx, k) : k);
  return Array.from(m.entries())
    .map(([key, fl]) => ({ key, label: label(key), flows: fl }))
    .sort((a, b) => {
      if ((a.key === OTHER) !== (b.key === OTHER)) return a.key === OTHER ? 1 : -1;
      return b.flows.length - a.flows.length || a.label.localeCompare(b.label);
    });
}

/** Feature tags when most flows have one; else area when most entry components have one; else the top-level component. */
export function defaultFlowGrouping(flows: Flow[], idx: DocIndex): FlowGrouping {
  if (flows.length === 0) return "feature";
  const half = flows.length / 2;
  if (flows.filter((f) => featureTags(f).length > 0).length > half) return "feature";
  if (flows.filter((f) => flowSectionKeys(f, idx, "area")[0] !== OTHER).length > half) return "area";
  return "parent";
}

/** True when the flow's name, id or a tag contains every word of the query (case-insensitive). */
export function flowMatches(flow: Flow, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = [flow.id, flow.name ?? "", ...(flow.tags ?? [])].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

// ---- Component browser ----------------------------------------------------

export type ComponentGrouping = "tree" | "area";

export interface ComponentRow {
  /** Unique row key. */
  key: string;
  /** A component id, or null for a group heading. */
  id: string | null;
  label: string;
  depth: number;
  /** Members (tree) or items (group) under this row, counting all descendants. */
  count: number;
  expandable: boolean;
  expanded: boolean;
  /** Matches the filter itself (as opposed to being shown as an ancestor of a match). */
  match: boolean;
}

function componentMatches(c: Component, words: string[]): boolean {
  if (!words.length) return true;
  const hay = `${c.id} ${c.name ?? ""} ${c.kind ?? ""} ${(c.tags ?? []).join(" ")}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** Descendant counts per component (members of members included). */
export function descendantCounts(idx: DocIndex): Map<string, number> {
  const out = new Map<string, number>();
  const count = (id: string, seen: Set<string>): number => {
    const have = out.get(id);
    if (have !== undefined) return have;
    if (seen.has(id)) return 0;
    seen.add(id);
    let n = 0;
    for (const k of idx.childrenByParent.get(id) ?? []) n += 1 + count(k.id, seen);
    out.set(id, n);
    return n;
  };
  for (const id of idx.componentsById.keys()) count(id, new Set());
  return out;
}

/**
 * The visible rows of the component browser. In tree mode components nest by
 * parent; in area mode they sit flat under their area (or owner) heading.
 * `expanded` holds open component ids, or "area:<name>" for area headings. A
 * non-empty filter shows every match with its ancestors open.
 */
export function componentRows(idx: DocIndex, by: ComponentGrouping, expanded: ReadonlySet<string>, filter: string, counts = descendantCounts(idx)): ComponentRow[] {
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  const filtering = words.length > 0;
  const rows: ComponentRow[] = [];
  const label = (c: Component) => c.name || c.id;

  if (by === "area") {
    const groups = new Map<string, Component[]>();
    for (const c of idx.componentsById.values()) if (componentMatches(c, words)) push(groups, idx.area.get(c.id) ?? OTHER, c);
    const keys = Array.from(groups.keys()).sort((a, b) => (a === OTHER ? 1 : b === OTHER ? -1 : a.localeCompare(b)));
    for (const k of keys) {
      const list = groups.get(k)!.sort((a, b) => label(a).localeCompare(label(b)));
      const open = filtering || expanded.has(`area:${k}`);
      rows.push({ key: `area:${k}`, id: null, label: k, depth: 0, count: list.length, expandable: true, expanded: open, match: false });
      if (open) for (const c of list) rows.push({ key: c.id, id: c.id, label: label(c), depth: 1, count: counts.get(c.id) ?? 0, expandable: false, expanded: false, match: filtering });
    }
    return rows;
  }

  // Tree: with a filter, keep matches and their ancestors.
  let keep: Set<string> | null = null;
  if (filtering) {
    keep = new Set();
    for (const c of idx.componentsById.values()) {
      if (!componentMatches(c, words)) continue;
      let cur: Component | undefined = c;
      while (cur && !keep.has(cur.id)) {
        keep.add(cur.id);
        cur = cur.parent ? idx.componentsById.get(cur.parent) : undefined;
      }
    }
  }
  const visit = (parent: string, depth: number, seen: Set<string>) => {
    const kids = (idx.childrenByParent.get(parent) ?? []).slice().sort((a, b) => label(a).localeCompare(label(b)));
    for (const c of kids) {
      if (keep && !keep.has(c.id)) continue;
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      const members = idx.childrenByParent.get(c.id)?.length ?? 0;
      const open = members > 0 && (filtering || expanded.has(c.id));
      rows.push({ key: c.id, id: c.id, label: label(c), depth, count: counts.get(c.id) ?? 0, expandable: members > 0, expanded: open, match: !filtering || componentMatches(c, words) });
      if (open) visit(c.id, depth + 1, seen);
    }
  };
  const seen = new Set<string>();
  visit(ROOT, 0, seen);
  // Components caught in a parent cycle have no root; list them at the top level.
  for (const c of idx.componentsById.values()) {
    if (seen.has(c.id) || (keep && !keep.has(c.id)) || !inParentCycle(idx, c.id)) continue;
    seen.add(c.id);
    rows.push({ key: c.id, id: c.id, label: label(c), depth: 0, count: counts.get(c.id) ?? 0, expandable: false, expanded: false, match: true });
  }
  return rows;
}

/** True when following parents from the component loops instead of reaching a top-level component. */
export function inParentCycle(idx: DocIndex, id: string): boolean {
  const seen = new Set<string>();
  let cur: string | undefined = id;
  while (cur) {
    if (seen.has(cur)) return true;
    seen.add(cur);
    const p: string | undefined = idx.componentsById.get(cur)?.parent;
    cur = p && p !== cur && idx.componentsById.has(p) ? p : undefined;
  }
  return false;
}

/** The ancestors of a component, nearest first. */
export function ancestors(idx: DocIndex, id: string): string[] {
  const out: string[] = [];
  const seen = new Set([id]);
  let cur = idx.componentsById.get(id)?.parent;
  while (cur && idx.componentsById.has(cur) && !seen.has(cur)) {
    out.push(cur);
    seen.add(cur);
    cur = idx.componentsById.get(cur)?.parent;
  }
  return out;
}
