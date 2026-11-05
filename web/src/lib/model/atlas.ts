// Atlas: the area-first map (docs/ux-plan-2026-11.md, review Concept A). Everything here is pure:
// which component belongs to which area, which boxes a view draws, how a view stays at or under
// about 40 boxes, and which connections are strong enough to draw.
//
// A "place" is an area, or one of the two actor groups drawn on the edge of the map. Places
// partition the components. Inside a place, the hierarchy is the parent tree cut at place
// boundaries: a member owned by another area is a root of that area, not a child here.
//
// Only type imports (and sibling .ts files) here: node --test runs this file with type stripping.

import type { Document, Graph, GraphNode } from "../api/types";
import { CATEGORICAL, OTHER_COLOR } from "./colors.ts";
import { buildCallIndex, flowsByComponent, type CallIndex } from "./atlasFlows.ts";
import type { DocIndex } from "./docindex";

/** Models under this size keep the compound map, which is the best view for them. */
export const ATLAS_MIN_COMPONENTS = 120;
/** No view draws more boxes than this. */
export const MAX_BOXES = 40;
/** Actors drawn per edge of the opening view, before "and N more". */
export const MAX_ACTORS = 6;
/** Stubs drawn per side of an entered view, before "and N more". */
export const MAX_STUBS = 6;
/** The area of a component with none. The sidebar's "by area" uses the same name. */
export const OTHER_AREA = "Other";
export const ENTRY_PLACE = "@entry";
export const EXTERNAL_PLACE = "@external";
/** A top-level part this small, next to a part at least BIG_ROOT large, is a stray: it goes under "other". */
export const SMALL_ROOT = 2;
export const BIG_ROOT = 10;

export function isActorPlace(place: string): boolean {
  return place === ENTRY_PLACE || place === EXTERNAL_PLACE;
}

export interface AtlasArea {
  key: string;
  /** What the area does: the summary of its largest part, cut to a sentence. */
  role: string;
  parts: number;
  flows: number;
  color: string;
  /** The components of the area, its roots first. */
  components: string[];
}

export interface AtlasPair {
  from: string;
  to: string;
  /** Call count: the distinct interfaces called, or one for a call with none listed. */
  weight: number;
  emits: boolean;
}

export interface AtlasModel {
  graph: Graph;
  nodes: Map<string, GraphNode>;
  areas: AtlasArea[];
  areaByKey: Map<string, AtlasArea>;
  /** Component id -> its place. Every component has exactly one. */
  placeOf: Map<string, string>;
  /** Component id -> its parent, when that parent is in the same place. */
  inParent: Map<string, string | undefined>;
  /** Component id -> its children in the same place. */
  kids: Map<string, string[]>;
  /** Place -> its root components, largest first. */
  roots: Map<string, string[]>;
  /** Component id -> itself plus its descendants in the same place. */
  size: Map<string, number>;
  degree: Map<string, number>;
  pairs: AtlasPair[];
  calls: CallIndex;
  /** Component id -> flows that could reach it (indexes into the document's flows). */
  flowsOf: Map<string, number[]>;
  /** Top-level parts grouped under "other", so a stray doesn't weigh the same as a whole area. */
  strays: string[];
}

/** True when the Map should open on areas: enough components, and an area on most of them. */
export function atlasEligible(idx: DocIndex): boolean {
  const total = idx.componentsById.size;
  if (total < ATLAS_MIN_COMPONENTS) return false;
  return new Set(idx.area.values()).size >= 2 && idx.area.size * 2 >= total;
}

function firstSentence(s: string | undefined, max = 110): string {
  const t = (s ?? "").replace(/\s+/g, " ").trim();
  if (!t) return "";
  const m = /^.+?[.;:](\s|$)/.exec(t);
  const one = (m ? m[0] : t).trim().replace(/[.;:]$/, "");
  return one.length > max ? `${one.slice(0, max - 1).trimEnd()}…` : one;
}

/** The largest areas get the validated hues; the rest stay grey, and every box carries its name. */
function assignColors(keys: string[]): Map<string, string> {
  const out = new Map<string, string>();
  let n = 0;
  for (const k of keys) out.set(k, k !== OTHER_AREA && n < CATEGORICAL.length ? CATEGORICAL[n++] : OTHER_COLOR);
  return out;
}

export function buildAtlas(doc: Document, graph: Graph, idx: DocIndex): AtlasModel {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
  const parentOf = new Map<string, string | undefined>();
  for (const n of graph.nodes) parentOf.set(n.id, n.parent && n.parent !== n.id && nodes.has(n.parent) ? n.parent : undefined);
  // A parent cycle has no root: cut it where it's found.
  for (const n of graph.nodes) {
    const seen = new Set([n.id]);
    for (let cur = parentOf.get(n.id); cur; cur = parentOf.get(cur)) {
      if (seen.has(cur)) {
        parentOf.set(n.id, undefined);
        break;
      }
      seen.add(cur);
    }
  }

  // A flow's caller with nothing of its own to call is an actor, whatever its kind says.
  const callers = new Set<string>();
  for (const f of doc.flows ?? []) if (f.entry?.caller) callers.add(f.entry.caller);
  const hasKids = new Set<string>();
  for (const p of parentOf.values()) if (p) hasKids.add(p);

  const placeOf = new Map<string, string>();
  const placeFor = (id: string): string => {
    const known = placeOf.get(id);
    if (known) return known;
    const n = nodes.get(id)!;
    const p = parentOf.get(id);
    const parentPlace = p ? placeFor(p) : undefined;
    let place: string;
    if (parentPlace && isActorPlace(parentPlace)) place = parentPlace;
    else if (n.kind === "client") place = ENTRY_PLACE;
    else if (n.kind === "external") place = EXTERNAL_PLACE;
    else if (callers.has(id) && !p && !hasKids.has(id) && n.interfaces.length === 0) place = ENTRY_PLACE;
    else place = idx.area.get(id) ?? OTHER_AREA;
    placeOf.set(id, place);
    return place;
  };
  for (const n of graph.nodes) placeFor(n.id);

  const inParent = new Map<string, string | undefined>();
  const kids = new Map<string, string[]>();
  const rootLists = new Map<string, string[]>();
  for (const n of graph.nodes) {
    const p = parentOf.get(n.id);
    const place = placeOf.get(n.id)!;
    const local = p && placeOf.get(p) === place ? p : undefined;
    inParent.set(n.id, local);
    const list = local ? kids.get(local) : rootLists.get(place);
    if (list) list.push(n.id);
    else if (local) kids.set(local, [n.id]);
    else rootLists.set(place, [n.id]);
  }

  const size = new Map<string, number>();
  const sizeOf = (id: string): number => {
    const known = size.get(id);
    if (known !== undefined) return known;
    let total = 1;
    for (const k of kids.get(id) ?? []) total += sizeOf(k);
    size.set(id, total);
    return total;
  };
  for (const n of graph.nodes) sizeOf(n.id);

  // Call pairs, merged. A call between a container and its own member says nothing about the map.
  const isAncestorOf = (a: string, b: string) => {
    for (let cur = parentOf.get(b); cur; cur = parentOf.get(cur)) if (cur === a) return true;
    return false;
  };
  const merged = new Map<string, { from: string; to: string; ifaces: Set<string>; bare: number; emits: boolean; calls: boolean }>();
  for (const e of graph.edges) {
    if (e.from === e.to || !nodes.has(e.from) || !nodes.has(e.to)) continue;
    if (isAncestorOf(e.from, e.to) || isAncestorOf(e.to, e.from)) continue;
    const key = `${e.from}\u0000${e.to}`;
    let m = merged.get(key);
    if (!m) {
      m = { from: e.from, to: e.to, ifaces: new Set(), bare: 0, emits: false, calls: false };
      merged.set(key, m);
    }
    if (e.interfaces?.length) for (const i of e.interfaces) m.ifaces.add(i);
    else m.bare++;
    if (e.kind === "emits") m.emits = true;
    else m.calls = true;
  }
  const pairs: AtlasPair[] = [];
  const degree = new Map<string, number>();
  for (const m of merged.values()) {
    const weight = m.ifaces.size + m.bare;
    pairs.push({ from: m.from, to: m.to, weight, emits: m.emits && !m.calls });
    degree.set(m.from, (degree.get(m.from) ?? 0) + weight);
    degree.set(m.to, (degree.get(m.to) ?? 0) + weight);
  }

  const label = (id: string) => nodes.get(id)?.name || id;
  const heavier = (a: string, b: string) =>
    size.get(b)! - size.get(a)! || (degree.get(b) ?? 0) - (degree.get(a) ?? 0) || (label(a) < label(b) ? -1 : label(a) > label(b) ? 1 : 0);
  for (const l of kids.values()) l.sort(heavier);
  for (const l of rootLists.values()) l.sort(heavier);

  const calls = buildCallIndex(doc, idx);
  const flowsOf = flowsByComponent(doc, calls, idx);

  // Areas, largest first, "other" last.
  const areaKeys = Array.from(rootLists.keys()).filter((k) => !isActorPlace(k));
  const placeTotal = (k: string) => rootLists.get(k)!.reduce((s, r) => s + size.get(r)!, 0);
  areaKeys.sort((a, b) => (a === OTHER_AREA ? 1 : b === OTHER_AREA ? -1 : placeTotal(b) - placeTotal(a) || (a < b ? -1 : 1)));
  const colors = assignColors(areaKeys);
  const collect = (id: string, into: string[]) => {
    into.push(id);
    for (const k of kids.get(id) ?? []) collect(k, into);
  };
  const areas: AtlasArea[] = areaKeys.map((key) => {
    const components: string[] = [];
    for (const r of rootLists.get(key)!) collect(r, components);
    const flows = new Set<number>();
    for (const c of components) for (const f of flowsOf.get(c) ?? []) flows.add(f);
    const roots = rootLists.get(key)!;
    const withSummary = roots.find((r) => nodes.get(r)?.summary);
    const role =
      key === OTHER_AREA
        ? "Parts the model doesn't place in an area"
        : firstSentence(withSummary ? nodes.get(withSummary)?.summary : undefined) || roots.slice(0, 3).map(label).join(", ");
    return { key, role, parts: components.length, flows: flows.size, color: colors.get(key)!, components };
  });

  const model: AtlasModel = {
    graph,
    nodes,
    areas,
    areaByKey: new Map(areas.map((a) => [a.key, a])),
    placeOf,
    inParent,
    kids,
    roots: rootLists,
    size,
    degree,
    pairs,
    calls,
    flowsOf,
    strays: [],
  };
  for (const a of areas) model.strays.push(...smallRoots(model, a.key));
  return model;
}

/** Top-level parts of an area that are small next to its large ones. */
export function smallRoots(m: AtlasModel, place: string): string[] {
  const roots = m.roots.get(place) ?? [];
  if (roots.length < 2 || (m.size.get(roots[0]) ?? 0) < BIG_ROOT) return [];
  return roots.filter((r) => m.size.get(r)! <= SMALL_ROOT);
}

// ---- Scopes -------------------------------------------------------------

/** Where a view is. An empty place is the opening view of the whole model. */
export interface AtlasScope {
  place?: string;
  /** Inside this component. Absent: the place's top level. */
  parent?: string;
  /** Only the items of this role (a component kind). */
  role?: string;
  /** Only the small top-level parts, grouped under "other". */
  rest?: boolean;
}

export const ROOT_SCOPE: AtlasScope = {};

export function scopeKey(s: AtlasScope): string {
  return [s.place ?? "", s.parent ?? "", s.role ?? "", s.rest ? "rest" : ""].join("\u0000");
}

export function sameScope(a: AtlasScope, b: AtlasScope): boolean {
  return scopeKey(a) === scopeKey(b);
}

/** The view a component is drawn in directly. Actors are on the opening view's edge. */
export function scopeFor(m: AtlasModel, id: string): AtlasScope {
  const place = m.placeOf.get(id);
  if (!place) return ROOT_SCOPE;
  const parent = m.inParent.get(id);
  if (parent) return { place, parent };
  if (isActorPlace(place)) return ROOT_SCOPE;
  if (smallRoots(m, place).includes(id)) return { place, rest: true };
  return { place };
}

/** Reads a scope from URL values, falling back to the nearest one that still exists. */
export function parseScope(m: AtlasModel, v: { area?: string | null; in?: string | null; role?: string | null; rest?: string | null }): AtlasScope {
  const place = v.area ?? undefined;
  if (!place || !(m.roots.has(place))) return ROOT_SCOPE;
  const parent = v.in && m.placeOf.get(v.in) === place && (m.kids.get(v.in)?.length ?? 0) > 0 ? v.in : undefined;
  const s: AtlasScope = { place };
  if (parent) s.parent = parent;
  if (v.role) s.role = v.role;
  if (v.rest && !parent) s.rest = true;
  return s;
}

/** URL values for a scope. Undefined clears the value. */
export function scopeParams(s: AtlasScope): Record<"area" | "in" | "role" | "rest", string | undefined> {
  return { area: s.place, in: s.parent, role: s.role, rest: s.rest ? "1" : undefined };
}

export function placeLabel(place: string): string {
  if (place === ENTRY_PLACE) return "Entry";
  if (place === EXTERNAL_PLACE) return "External";
  return place === OTHER_AREA ? "other" : place;
}

// ---- Views --------------------------------------------------------------

export type BoxType = "area" | "component" | "self" | "group" | "more" | "stub" | "actor";

export interface MoreItem {
  label: string;
  detail?: string;
  component?: string;
  scope?: AtlasScope;
}

export interface AtlasBox {
  id: string;
  type: BoxType;
  label: string;
  /** Role, or a component's kind. */
  detail?: string;
  /** The component this box is, when it's one. */
  component?: string;
  /** The place, for its color. */
  place?: string;
  parts: number;
  flows: number;
  /** Every component this box stands for. */
  members: string[];
  /** Largest members, for a group's preview, and how many aren't named. */
  preview?: string[];
  previewMore?: number;
  /** The view this box opens. */
  enter?: AtlasScope;
  /** The list behind "and 38 more". */
  more?: MoreItem[];
  /** Which edge of the map this box belongs on. */
  edge?: "start" | "end";
  stateful?: boolean;
}

export interface AtlasEdge {
  id: string;
  from: string;
  to: string;
  /** Call count over every component pair this edge merges. */
  weight: number;
  emits: boolean;
  /** Drawn by default. The rest appear on hover, or with "all connections". */
  strong: boolean;
}

export interface Crumb {
  label: string;
  scope: AtlasScope;
}

export interface AtlasView {
  scope: AtlasScope;
  boxes: AtlasBox[];
  edges: AtlasEdge[];
  crumbs: Crumb[];
  /** Component id -> the box standing for it in this view; absent when the view doesn't show it. */
  repOf: Map<string, string>;
  /** The stub standing for a component outside this view, on the side a call to or from it lands. */
  stubFor: (id: string, side: "in" | "out") => string | undefined;
}

function labelOf(m: AtlasModel, id: string): string {
  return m.nodes.get(id)?.name || id;
}

function descend(m: AtlasModel, id: string, into: string[] = []): string[] {
  into.push(id);
  for (const k of m.kids.get(id) ?? []) descend(m, k, into);
  return into;
}

function flowCount(m: AtlasModel, ids: readonly string[]): number {
  const s = new Set<number>();
  for (const c of ids) for (const f of m.flowsOf.get(c) ?? []) s.add(f);
  return s.size;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function componentBox(m: AtlasModel, id: string, place: string): AtlasBox {
  const n = m.nodes.get(id);
  const members = descend(m, id);
  const kids = m.kids.get(id) ?? [];
  return {
    id: `c:${id}`,
    type: "component",
    label: labelOf(m, id),
    detail: n?.kind || "component",
    component: id,
    place,
    parts: members.length,
    flows: flowCount(m, members),
    members,
    preview: kids.slice(0, 3).map((k) => labelOf(m, k)),
    previewMore: Math.max(0, kids.length - 3),
    enter: kids.length ? { place, parent: id } : undefined,
    stateful: n?.stateful,
  };
}

function moreItems(m: AtlasModel, ids: readonly string[]): MoreItem[] {
  return ids.map((id) => {
    const n = m.nodes.get(id);
    const s = m.size.get(id) ?? 1;
    return { label: labelOf(m, id), detail: `${n?.kind || "component"}${s > 1 ? ` · ${plural(s, "part")}` : ""}`, component: id };
  });
}

function moreBox(m: AtlasModel, id: string, ids: readonly string[], place: string | undefined, enter?: AtlasScope): AtlasBox {
  const members = ids.flatMap((c) => descend(m, c));
  return {
    id,
    type: "more",
    label: `and ${ids.length} more`,
    detail: plural(members.length, "part"),
    place,
    parts: members.length,
    flows: flowCount(m, members),
    members,
    more: enter ? undefined : moreItems(m, ids),
    enter,
  };
}

function groupBox(m: AtlasModel, id: string, label: string, detail: string, ids: readonly string[], place: string, enter: AtlasScope): AtlasBox {
  const members = ids.flatMap((c) => descend(m, c));
  return {
    id,
    type: "group",
    label,
    detail,
    place,
    parts: members.length,
    flows: flowCount(m, members),
    members,
    preview: ids.slice(0, 3).map((c) => labelOf(m, c)),
    previewMore: Math.max(0, ids.length - 3),
    enter,
  };
}

/**
 * Fits a scope's items into a budget of boxes. Parts that hold others keep a box, up to half the
 * budget, since that's the next parent to open. The rest group by role. When roles can't help
 * (one role, or already inside one), the heaviest items keep their box and the rest become
 * "and 38 more". A pinned item always keeps its box, so a selection never gets lost.
 */
export function fitItems(m: AtlasModel, scope: AtlasScope, items: readonly string[], budget: number, pin: ReadonlySet<string>): AtlasBox[] {
  const place = scope.place!;
  const roomy = Math.max(budget, 2);
  if (items.length <= roomy) return items.map((id) => componentBox(m, id, place));

  const pinned = items.filter((id) => pin.has(id));
  const free = items.filter((id) => !pin.has(id));
  const cut = (room: number, list: readonly string[]): AtlasBox[] => {
    const keep = Math.max(0, room - 1);
    const out = list.slice(0, keep).map((id) => componentBox(m, id, place));
    const rest = list.slice(keep);
    if (rest.length === 1) out.push(componentBox(m, rest[0], place));
    else if (rest.length > 1) out.push(moreBox(m, `more:${scopeKey(scope)}`, rest, place));
    return out;
  };
  const first = pinned.map((id) => componentBox(m, id, place));
  const room = roomy - pinned.length;
  if (scope.role) return [...first, ...cut(room, free)];

  const kindOf = (id: string) => m.nodes.get(id)?.kind || "component";
  const parents = free.filter((id) => (m.kids.get(id)?.length ?? 0) > 0).slice(0, Math.floor(room / 2));
  const keepers = new Set(parents);
  const byRole = new Map<string, string[]>();
  for (const id of free) {
    if (keepers.has(id)) continue;
    const k = kindOf(id);
    const l = byRole.get(k);
    if (l) l.push(id);
    else byRole.set(k, [id]);
  }
  // One role left, and it's the whole scope: grouping would only add a click.
  if (byRole.size <= 1 && parents.length === 0) return [...first, ...cut(room, free)];

  const left = room - parents.length;
  const roles = Array.from(byRole.entries()).sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1));
  const boxes: AtlasBox[] = [...first, ...parents.map((id) => componentBox(m, id, place))];
  const shown = roles.length > left ? roles.slice(0, Math.max(0, left - 1)) : roles;
  for (const [kind, ids] of shown) {
    if (ids.length === 1) boxes.push(componentBox(m, ids[0], place));
    else boxes.push(groupBox(m, `role:${kind}`, `${kind} (${ids.length})`, "grouped by role", ids, place, { ...scope, role: kind }));
  }
  const rest = roles.slice(shown.length).flatMap(([, ids]) => ids);
  if (rest.length) boxes.push(moreBox(m, `more:${scopeKey(scope)}`, rest, place));
  return boxes;
}

function scopeItems(m: AtlasModel, scope: AtlasScope): string[] {
  const place = scope.place!;
  let items = scope.parent ? (m.kids.get(scope.parent) ?? []) : (m.roots.get(place) ?? []);
  if (!scope.parent) {
    const small = new Set(smallRoots(m, place));
    if (scope.rest) items = items.filter((r) => small.has(r));
    else if (small.size) items = items.filter((r) => !small.has(r));
  }
  if (scope.role) items = items.filter((id) => (m.nodes.get(id)?.kind || "component") === scope.role);
  return items;
}

function crumbsFor(m: AtlasModel, scope: AtlasScope): Crumb[] {
  const out: Crumb[] = [{ label: "Map", scope: ROOT_SCOPE }];
  if (!scope.place) return out;
  out.push({ label: placeLabel(scope.place), scope: { place: scope.place } });
  if (scope.rest) out.push({ label: "other", scope: { place: scope.place, rest: true } });
  const chain: string[] = [];
  for (let cur = scope.parent; cur; cur = m.inParent.get(cur)) chain.unshift(cur);
  for (const id of chain) out.push({ label: labelOf(m, id), scope: { place: scope.place, parent: id } });
  if (scope.role) out.push({ label: scope.role, scope });
  return out;
}

/** Merges the model's call pairs onto the boxes `ends` maps them to. */
function mergeEdges(m: AtlasModel, ends: (p: AtlasPair) => (string | undefined)[]): AtlasEdge[] {
  const out = new Map<string, AtlasEdge & { calls: boolean }>();
  for (const p of m.pairs) {
    const [from, to] = ends(p);
    if (!from || !to || from === to) continue;
    const id = `${from}->${to}`;
    const e = out.get(id);
    if (e) {
      e.weight += p.weight;
      if (!p.emits) e.calls = true;
    } else out.set(id, { id, from, to, weight: p.weight, emits: false, strong: false, calls: !p.emits });
  }
  return Array.from(out.values(), ({ calls, ...e }) => ({ ...e, emits: !calls }));
}

/** How many connections a view draws by default. */
export function edgeBudget(boxes: number): number {
  return Math.min(30, Math.max(8, boxes));
}

/**
 * Marks the connections drawn by default: the heaviest up to the budget, and each box's heaviest,
 * so no box looks unconnected when it isn't. Input order doesn't matter; ties break by id.
 */
export function thresholdEdges(edges: readonly AtlasEdge[], boxes: number): AtlasEdge[] {
  const sorted = [...edges].sort((a, b) => b.weight - a.weight || (a.id < b.id ? -1 : 1));
  const budget = edgeBudget(boxes);
  const strong = new Set(sorted.slice(0, budget).map((e) => e.id));
  const covered = new Set<string>();
  for (const e of sorted) {
    if (strong.has(e.id)) {
      covered.add(e.from);
      covered.add(e.to);
    }
  }
  for (const e of sorted) {
    if (covered.has(e.from) && covered.has(e.to)) continue;
    strong.add(e.id);
    covered.add(e.from);
    covered.add(e.to);
  }
  return sorted.map((e) => ({ ...e, strong: strong.has(e.id) }));
}

/** Stroke width for a call count: logarithmic, so one heavy pair doesn't flatten the rest. */
export function edgeWidth(weight: number, heaviest: number): number {
  if (heaviest <= 1) return 1.25;
  return 1.25 + (4.75 * Math.log(1 + Math.max(weight, 0))) / Math.log(1 + heaviest);
}

function rootView(m: AtlasModel, pin: ReadonlySet<string>, max: number): AtlasView {
  const boxes: AtlasBox[] = [];
  const repOf = new Map<string, string>();
  const claim = (b: AtlasBox) => {
    boxes.push(b);
    for (const c of b.members) repOf.set(c, b.id);
  };
  const actors = (place: string, edge: "start" | "end") => {
    const roots = m.roots.get(place) ?? [];
    const pinned = roots.filter((r) => pin.has(r));
    const free = roots.filter((r) => !pinned.includes(r));
    const list = roots.length <= MAX_ACTORS ? roots : [...pinned, ...free.slice(0, Math.max(0, MAX_ACTORS - 1 - pinned.length))];
    for (const id of list) claim({ ...componentBox(m, id, place), type: "actor", detail: placeLabel(place), edge });
    const shown = new Set(list);
    const rest = roots.filter((r) => !shown.has(r));
    if (rest.length) claim({ ...moreBox(m, `more:${place}`, rest, place, { place }), edge });
  };
  actors(ENTRY_PLACE, "start");
  actors(EXTERNAL_PLACE, "end");

  const room = max - boxes.length;
  const list = m.areas.length <= room ? m.areas : m.areas.slice(0, Math.max(0, room - 1));
  for (const a of list) {
    claim({
      id: `area:${a.key}`,
      type: "area",
      label: placeLabel(a.key),
      detail: a.role,
      place: a.key,
      parts: a.parts,
      flows: a.flows,
      members: a.components,
      enter: { place: a.key },
    });
  }
  if (list.length < m.areas.length) {
    const rest = m.areas.slice(list.length);
    const members = rest.flatMap((a) => a.components);
    claim({
      id: "more:areas",
      type: "more",
      label: `and ${rest.length} more`,
      detail: plural(members.length, "part"),
      parts: members.length,
      flows: flowCount(m, members),
      members,
      more: rest.map((a) => ({ label: placeLabel(a.key), detail: plural(a.parts, "part"), scope: { place: a.key } })),
    });
  }
  const edges = thresholdEdges(mergeEdges(m, (p) => [repOf.get(p.from), repOf.get(p.to)]), boxes.length);
  return { scope: ROOT_SCOPE, boxes, edges, crumbs: crumbsFor(m, ROOT_SCOPE), repOf, stubFor: () => undefined };
}

/**
 * The boxes of a scope: never more than `max`. Each neighbor outside an entered scope becomes a
 * labeled stub at the edge. `pin` lists components that must keep their own box.
 */
export function buildView(m: AtlasModel, scope: AtlasScope, opts: { pin?: Iterable<string>; max?: number } = {}): AtlasView {
  const max = opts.max ?? MAX_BOXES;
  const pin = new Set(opts.pin ?? []);
  if (!scope.place || !m.roots.has(scope.place)) return rootView(m, pin, max);
  const place = scope.place;
  // A level holding a single part is a click with nothing to decide: open it right here.
  let items = scopeItems(m, scope);
  const opened: string[] = [];
  if (!scope.role && !scope.rest) {
    while (items.length === 1 && (m.kids.get(items[0])?.length ?? 0) > 0) {
      opened.push(items[0]);
      items = m.kids.get(items[0])!;
    }
  }

  // Everything this view stands for.
  const inside = new Set<string>();
  for (const id of items) for (const c of descend(m, id)) inside.add(c);
  const strays = !scope.parent && !scope.rest && !scope.role ? smallRoots(m, place) : [];
  for (const id of strays) for (const c of descend(m, id)) inside.add(c);
  // A part that was opened still has its own interfaces, and still can be selected.
  const selves = [...(scope.parent && !scope.role ? [scope.parent] : []), ...opened].filter((id) => (m.nodes.get(id)?.interfaces.length ?? 0) > 0 || pin.has(id));
  for (const id of selves) inside.add(id);

  // The chain of parents the scope sits under, to name a same-area neighbor.
  const chain = new Set<string>();
  for (let cur = scope.parent; cur; cur = m.inParent.get(cur)) chain.add(cur);
  const neighbor = (id: string): { key: string; label: string; place: string; enter?: AtlasScope; component?: string } => {
    const p = m.placeOf.get(id)!;
    if (p !== place && !isActorPlace(p)) return { key: `area:${p}`, label: placeLabel(p), place: p, enter: { place: p } };
    let cur = id;
    for (let up = m.inParent.get(cur); up && !chain.has(up); up = m.inParent.get(cur)) cur = up;
    const hasKids = (m.kids.get(cur)?.length ?? 0) > 0;
    return {
      key: `c:${cur}`,
      label: labelOf(m, cur),
      place: p,
      enter: hasKids ? { place: p, parent: cur } : undefined,
      component: hasKids ? undefined : cur,
    };
  };

  // Stubs, heaviest first, each side capped.
  type Stub = { key: string; label: string; place: string; enter?: AtlasScope; component?: string; weight: number };
  const stubsIn = new Map<string, Stub>();
  const stubsOut = new Map<string, Stub>();
  const stubKeyOf = new Map<string, { key: string; label: string; place: string; enter?: AtlasScope; component?: string }>();
  const nb = (id: string) => {
    let n = stubKeyOf.get(id);
    if (!n) {
      n = neighbor(id);
      stubKeyOf.set(id, n);
    }
    return n;
  };
  for (const p of m.pairs) {
    const a = inside.has(p.from);
    const b = inside.has(p.to);
    if (a === b) continue;
    const n = nb(a ? p.to : p.from);
    const map = a ? stubsOut : stubsIn;
    const s = map.get(n.key);
    if (s) s.weight += p.weight;
    else map.set(n.key, { ...n, weight: p.weight });
  }
  const stubBoxes: AtlasBox[] = [];
  const stubRep = (side: "in" | "out", map: Map<string, Stub>): Map<string, string> => {
    const sorted = Array.from(map.values()).sort((a, b) => b.weight - a.weight || (a.label < b.label ? -1 : 1));
    const list = sorted.length <= MAX_STUBS ? sorted : sorted.slice(0, MAX_STUBS - 1);
    const rep = new Map<string, string>();
    const edge = side === "in" ? "start" : "end";
    for (const s of list) {
      const id = `stub:${side}:${s.key}`;
      rep.set(s.key, id);
      stubBoxes.push({
        id,
        type: "stub",
        label: side === "in" ? `from ${s.label}` : `to ${s.label}`,
        place: s.place,
        component: s.component,
        parts: 0,
        flows: 0,
        members: [],
        enter: s.enter,
        edge,
      });
    }
    const rest = sorted.slice(list.length);
    if (rest.length) {
      const id = `stub:${side}:more`;
      for (const s of rest) rep.set(s.key, id);
      stubBoxes.push({
        id,
        type: "stub",
        label: `and ${rest.length} more ${side === "in" ? "callers" : "callees"}`,
        parts: 0,
        flows: 0,
        members: [],
        more: rest.map((s) => ({ label: s.label, detail: plural(s.weight, "call"), scope: s.enter, component: s.component })),
        edge,
      });
    }
    return rep;
  };
  const inRep = stubRep("in", stubsIn);
  const outRep = stubRep("out", stubsOut);

  const boxes: AtlasBox[] = [];
  const repOf = new Map<string, string>();
  for (const self of selves) {
    const n = m.nodes.get(self);
    boxes.push({
      id: `self:${self}`,
      type: "self",
      label: labelOf(m, self),
      detail: `${n?.kind || "component"} · itself`,
      component: self,
      place,
      parts: 1,
      flows: flowCount(m, [self]),
      members: [self],
      stateful: n?.stateful,
    });
  }
  const budget = max - stubBoxes.length - boxes.length;

  // The top level of an area folds its strays under "other".
  const shownStrays = strays.filter((s) => pin.has(s));
  const folded = strays.filter((s) => !pin.has(s));
  const itemsHere = shownStrays.length ? [...items, ...shownStrays] : items;
  // A group's link has to name the level it was drawn on, including one opened above.
  const fitScope = opened.length ? { ...scope, parent: opened[opened.length - 1] } : scope;
  for (const b of fitItems(m, fitScope, itemsHere, budget - (folded.length ? 1 : 0), pin)) boxes.push(b);
  if (folded.length) boxes.push(groupBox(m, `other:${place}`, `other (${folded.length})`, "small parts of this area", folded, place, { place, rest: true }));
  for (const b of boxes) for (const c of b.members) repOf.set(c, b.id);
  for (const b of stubBoxes) boxes.push(b);

  const stubFor = (id: string, side: "in" | "out") => (side === "in" ? inRep : outRep).get(nb(id).key);
  const edges = thresholdEdges(
    mergeEdges(m, (p) => {
      const a = inside.has(p.from);
      const b = inside.has(p.to);
      if (a && b) return [repOf.get(p.from), repOf.get(p.to)];
      if (a) return [repOf.get(p.from), stubFor(p.to, "out")];
      if (b) return [stubFor(p.from, "in"), repOf.get(p.to)];
      return [undefined, undefined];
    }),
    boxes.length,
  );
  return { scope, boxes, edges, crumbs: crumbsFor(m, scope), repOf, stubFor };
}

/** Every view reachable from the opening one, by entering boxes. For checking the box rule. */
export function allScopes(m: AtlasModel): AtlasScope[] {
  const seen = new Map<string, AtlasScope>([[scopeKey(ROOT_SCOPE), ROOT_SCOPE]]);
  const queue: AtlasScope[] = [ROOT_SCOPE];
  while (queue.length) {
    const s = queue.pop()!;
    for (const b of buildView(m, s).boxes) {
      if (b.enter && !seen.has(scopeKey(b.enter))) {
        seen.set(scopeKey(b.enter), b.enter);
        queue.push(b.enter);
      }
    }
  }
  return Array.from(seen.values());
}

// ---- Filter -------------------------------------------------------------

/** Box id -> how many of the matching components it stands for. */
export function matchCounts(view: AtlasView, matches: ReadonlySet<string>): Map<string, number> {
  const out = new Map<string, number>();
  for (const b of view.boxes) {
    let n = 0;
    for (const c of b.members) if (matches.has(c)) n++;
    if (n) out.set(b.id, n);
  }
  return out;
}
