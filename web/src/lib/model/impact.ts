// Entity diffs and impact computed in the browser. The fixture client uses
// these to answer /diff, /impact and /commits/{sha} the way mosaicd does
// (docs/DESIGN.md §10); the commit views use the helpers at the bottom to read
// an Impact.

import type { Change, Document, Impact, ImpactKind, ImpactSet, JsonValue, Plan } from "@/lib/api/types";

/** Entity kinds in document order, with their Impact key. */
export const ENTITY_KINDS: { kind: string; key: ImpactKind }[] = [
  { kind: "component", key: "components" },
  { kind: "interface", key: "interfaces" },
  { kind: "link", key: "links" },
  { kind: "schema", key: "schemas" },
  { kind: "flow", key: "flows" },
  { kind: "scenario", key: "scenarios" },
  { kind: "config", key: "configs" },
  { kind: "fixture", key: "fixtures" },
];

function canonical(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o)
    .filter((k) => o[k] !== undefined)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`)
    .join(",")}}`;
}

function entities(doc: Document | undefined, kind: string): Map<string, JsonValue> {
  const m = new Map<string, JsonValue>();
  if (!doc) return m;
  const list: unknown[] | undefined =
    kind === "component" ? doc.components
    : kind === "interface" ? doc.interfaces
    : kind === "link" ? doc.links
    : kind === "schema" ? doc.schemas
    : kind === "flow" ? doc.flows
    : kind === "scenario" ? doc.scenarios
    : kind === "config" ? doc.configs
    : doc.fixtures;
  for (const e of list ?? []) {
    const r = e as { id?: string; component?: string; name?: string };
    const id = kind === "interface" ? r.id || `${r.component}.${r.name}` : r.id;
    if (id) m.set(id, e as JsonValue);
  }
  return m;
}

/** Entity changes between two documents, in kind order then by id. */
export function diffDocuments(before: Document | undefined, after: Document | undefined): Change[] {
  const out: Change[] = [];
  for (const { kind } of ENTITY_KINDS) {
    const a = entities(before, kind);
    const b = entities(after, kind);
    const ids = Array.from(new Set([...a.keys(), ...b.keys()])).sort();
    for (const id of ids) {
      const x = a.get(id);
      const y = b.get(id);
      if (x === undefined) out.push({ kind, id, change: "added", after: y });
      else if (y === undefined) out.push({ kind, id, change: "removed", before: x });
      else if (canonical(x) !== canonical(y)) out.push({ kind, id, change: "modified", before: x, after: y });
    }
  }
  return out;
}

export function emptyImpact(): Impact {
  const set = (): ImpactSet => ({ added: [], removed: [], modified: [], cited: [] });
  return { components: set(), interfaces: set(), links: set(), schemas: set(), flows: set(), scenarios: set(), configs: set(), fixtures: set(), flows_affected: [] };
}

/**
 * Impact from a list of changes. Affected flows are flows whose own definition
 * didn't change but whose reach (plan interfaces and components, before or
 * after) contains a changed component or interface.
 */
export function impactOf(changes: Change[], plans: Map<string, Plan[]>): Impact {
  const imp = emptyImpact();
  const changed = new Set<string>();
  for (const c of changes) {
    const k = ENTITY_KINDS.find((e) => e.kind === c.kind);
    if (!k) continue;
    const set = imp[k.key];
    if (c.change === "added") set.added.push(c.id);
    else if (c.change === "removed") set.removed.push(c.id);
    else set.modified.push(c.id);
    changed.add(`${c.kind}:${c.id}`);
  }
  for (const [flow, ps] of plans) {
    if (changed.has(`flow:${flow}`)) continue;
    const reach = new Set<string>();
    for (const p of ps) {
      for (const i of p.interfaces ?? []) reach.add(`interface:${i}`);
      for (const c of p.components ?? []) reach.add(`component:${c}`);
    }
    const reasons = Array.from(reach).filter((r) => changed.has(r)).sort();
    // Plans are static reach, so mark it as such.
    if (reasons.length) imp.flows_affected.push({ flow, reasons, basis: "static" });
  }
  imp.flows_affected.sort((a, b) => (a.flow < b.flow ? -1 : 1));
  return imp;
}

// ---------------------------------------------------------------- reading

export type ChangeKind = "added" | "removed" | "modified";

/** The number of changed entities in a set. */
export function setSize(s: ImpactSet): number {
  return s.added.length + s.removed.length + s.modified.length;
}

export function impactTotal(imp: Impact): number {
  return ENTITY_KINDS.reduce((n, k) => n + setSize(imp[k.key]), 0);
}

/** Splits a "<kind>:<id>" reason. */
export function parseReason(r: string): { kind: string; id: string } {
  const i = r.indexOf(":");
  return i < 0 ? { kind: "", id: r } : { kind: r.slice(0, i), id: r.slice(i + 1) };
}
