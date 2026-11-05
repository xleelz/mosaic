// A semantic summary of the change between two versions of a model: per area
// first, then entities, with the JSON left for last. It takes any (base, head)
// pair's changes and impact, so a revision diff, a draft against current and a
// candidate against a candidate all read the same. Pure, so `pnpm test` can run it.

import type { Change, Document, Flow, FlowImpact, JsonValue } from "../api/types";
import { SHARED, componentArea, configArea, flowArea } from "./areas.ts";
import type { DocIndex } from "./docindex.ts";

export type ChangeGroup = "added" | "changed" | "removed";

export function changeGroup(c: Change): ChangeGroup {
  return c.change === "added" ? "added" : c.change === "removed" ? "removed" : "changed";
}

/** Order-independent JSON, leaving out any key `skip` matches, at every depth. */
function canonical(v: unknown, skip?: (key: string) => boolean): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v) ?? "";
  if (Array.isArray(v)) return `[${v.map((x) => canonical(x, skip)).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o)
    .filter((k) => o[k] !== undefined && !skip?.(k))
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonical(o[k], skip)}`)
    .join(",")}}`;
}

/** The top-level fields a modified entity changed, sorted. Empty unless both sides are objects. */
export function changedFields(c: Pick<Change, "before" | "after">): string[] {
  const a = c.before;
  const b = c.after;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) || Array.isArray(b)) return [];
  const x = a as Record<string, JsonValue>;
  const y = b as Record<string, JsonValue>;
  return Array.from(new Set([...Object.keys(x), ...Object.keys(y)]))
    .filter((k) => canonical(x[k]) !== canonical(y[k]))
    .sort();
}

const isCitation = (k: string) => k === "source" || k === "sources";

/** Nothing but citations changed: the evidence moved, and the model didn't. */
export function citationsOnly(c: Change): boolean {
  if (c.change !== "modified" || c.before === undefined || c.after === undefined) return false;
  return canonical(c.before, isCitation) === canonical(c.after, isCitation);
}

/** An entity's display name from its JSON, when it has one distinct from its id. */
export function changeName(c: Change): string | undefined {
  const side = (c.after ?? c.before) as { name?: unknown; title?: unknown } | undefined;
  const n = side && typeof side === "object" ? (side.name ?? side.title) : undefined;
  // An interface's id already ends in its name.
  return typeof n === "string" && n && n !== c.id && !c.id.endsWith(`.${n}`) ? n : undefined;
}

export interface AreaSummary {
  area: string;
  added: number;
  changed: number;
  removed: number;
  /** Modified entities where only citations moved; counted here and not in `changed`. */
  citations: number;
  /** Unchanged flows that reach something changed in this area. */
  flowsAffected: number;
  /** Changed entities per kind. */
  kinds: Record<string, number>;
  changes: Change[];
}

export interface DiffSummary {
  total: number;
  added: number;
  changed: number;
  removed: number;
  citations: number;
  /** Each flow once, though it can reach changes in several areas. */
  flowsAffected: number;
  /** How the affected flows were found: scenario runs, or the static call graph. */
  flowsExercised: number;
  flowsStatic: number;
  /** Largest first; shared things last. */
  areas: AreaSummary[];
}

function emptyArea(area: string): AreaSummary {
  return { area, added: 0, changed: 0, removed: 0, citations: 0, flowsAffected: 0, kinds: {}, changes: [] };
}

export function summarizeDiff(changes: Change[], flowsAffected: Pick<FlowImpact, "flow" | "reasons" | "basis">[], areaOf: (c: Change) => string): DiffSummary {
  const areas = new Map<string, AreaSummary>();
  const entityArea = new Map<string, string>();
  const s: DiffSummary = { total: changes.length, added: 0, changed: 0, removed: 0, citations: 0, flowsAffected: flowsAffected.length, flowsExercised: 0, flowsStatic: 0, areas: [] };
  for (const c of changes) {
    const area = areaOf(c);
    entityArea.set(`${c.kind}:${c.id}`, area);
    let a = areas.get(area);
    if (!a) areas.set(area, (a = emptyArea(area)));
    a.changes.push(c);
    a.kinds[c.kind] = (a.kinds[c.kind] ?? 0) + 1;
    if (citationsOnly(c)) {
      a.citations++;
      s.citations++;
    } else {
      const g = changeGroup(c);
      a[g]++;
      s[g]++;
    }
  }
  for (const f of flowsAffected) {
    if (f.basis === "traces") s.flowsExercised++;
    else if (f.basis === "static") s.flowsStatic++;
    const hit = new Set<string>();
    for (const r of f.reasons) {
      const area = entityArea.get(r);
      if (area) hit.add(area);
    }
    for (const area of hit) areas.get(area)!.flowsAffected++;
  }
  s.areas = Array.from(areas.values()).sort((a, b) => {
    if ((a.area === SHARED) !== (b.area === SHARED)) return a.area === SHARED ? 1 : -1;
    return b.changes.length - a.changes.length || a.area.localeCompare(b.area);
  });
  return s;
}

/**
 * Finds a change's area from the head document, and from the change's own JSON
 * for what the head no longer has, so a removed entity still lands somewhere
 * without loading the base document as well.
 */
export function changeAreaResolver(doc: Document, idx: DocIndex): (c: Change) => string {
  const ofComponent = (id: unknown) => (typeof id === "string" ? componentArea(idx, id) : undefined);
  const flowOf = (id: unknown) => {
    const flow = typeof id === "string" ? idx.flowsById.get(id) : undefined;
    return flow ? flowArea(idx, flow) : undefined;
  };
  return (c) => {
    const e = (c.after ?? c.before ?? {}) as Record<string, JsonValue> & { steps?: { flow?: string }[]; attributes?: Record<string, JsonValue> };
    switch (c.kind) {
      case "component": {
        const own = e.attributes?.area ?? e.attributes?.owner;
        return ofComponent(c.id) ?? (typeof own === "string" && own ? own : undefined) ?? ofComponent(e.parent) ?? SHARED;
      }
      case "interface":
        return ofComponent(e.component) ?? ofComponent(c.id.split(".")[0]) ?? SHARED;
      case "link":
        return ofComponent(e.from) ?? ofComponent(e.to) ?? SHARED;
      case "flow":
        return (idx.flowsById.has(c.id) ? flowOf(c.id) : flowArea(idx, e as unknown as Flow)) ?? SHARED;
      case "scenario":
        return flowOf(e.flow) ?? flowOf(e.steps?.[0]?.flow) ?? SHARED;
      case "config":
        return configArea(doc, idx, e);
      default:
        return SHARED;
    }
  };
}

/** Kinds in reading order: what the system is and does first, its schemas after. */
export const KIND_ORDER = ["component", "interface", "link", "flow", "scenario", "config", "fixture", "schema"];

export type EntityRow = { type: "kind"; key: string; kind: string; count: number } | { type: "change"; key: string; change: Change };

export interface EntityFilter {
  /** Only this area's changes; null for all. */
  area: AreaSummary | null;
  query: string;
  /** Leave out changes where only citations moved. */
  hideCitations: boolean;
}

/** The entity list under the summary: headed by kind, added first inside a kind, then by id. */
export function entityRows(all: Change[], f: EntityFilter): EntityRow[] {
  const words = f.query.toLowerCase().split(/\s+/).filter(Boolean);
  const list = (f.area ? f.area.changes : all).filter((c) => {
    if (f.hideCitations && citationsOnly(c)) return false;
    if (!words.length) return true;
    const hay = `${c.kind} ${c.id} ${changeName(c) ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
  const byKind = new Map<string, Change[]>();
  for (const c of list) {
    const l = byKind.get(c.kind);
    if (l) l.push(c);
    else byKind.set(c.kind, [c]);
  }
  const rank = (k: string) => {
    const i = KIND_ORDER.indexOf(k);
    return i < 0 ? KIND_ORDER.length : i;
  };
  const order: Record<ChangeGroup, number> = { added: 0, changed: 1, removed: 2 };
  const rows: EntityRow[] = [];
  for (const kind of Array.from(byKind.keys()).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))) {
    const l = byKind.get(kind)!;
    l.sort((a, b) => order[changeGroup(a)] - order[changeGroup(b)] || a.id.localeCompare(b.id));
    rows.push({ type: "kind", key: `kind:${kind}`, kind, count: l.length });
    for (const change of l) rows.push({ type: "change", key: `${change.kind}:${change.id}`, change });
  }
  return rows;
}

/** "233 scenarios, 181 interfaces, 41 components", largest first. */
export function kindsLine(kinds: Record<string, number>, max = 3): string {
  const parts = Object.entries(kinds)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([k, n]) => `${n} ${n === 1 ? k : k === "schema" ? "schemas" : `${k}s`}`);
  return parts.length > max ? `${parts.slice(0, max).join(", ")}, and ${parts.length - max} more ${parts.length - max === 1 ? "kind" : "kinds"}` : parts.join(", ");
}
