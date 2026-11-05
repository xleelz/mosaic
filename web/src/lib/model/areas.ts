// The area of anything in a model, for the views that group by it. A component's
// area is what the "by area" sidebar uses (DocIndex.area). Most models only tag
// some components, and some tag none, so the top-level component stands in: a
// view can always say where a thing sits. Other things take the area of a
// component they belong to.
//
// Only type imports beyond docindex: node --test runs this with type stripping.

import type { Config, Document, Flow, JsonValue } from "../api/types";
import { citationIndex } from "./citations.ts";
import { nameOf, type DocIndex } from "./docindex.ts";

/** Things no one component owns (schemas, world setups, and anything unresolved). */
export const SHARED = "shared";

export function componentArea(idx: DocIndex, id: string): string | undefined {
  const area = idx.area.get(id);
  if (area) return area;
  const top = idx.topLevel.get(id);
  return top ? nameOf(idx, top) : undefined;
}

function attribute(v: JsonValue | undefined): string | undefined {
  return typeof v === "string" && v.trim() ? v.trim() : undefined;
}

/**
 * A config's area: its own attribute, or else the component that cites the same
 * file (most configs are read where they matter), or else shared.
 */
export function configArea(doc: Document, idx: DocIndex, c: Pick<Config, "attributes" | "sources">): string {
  const own = attribute(c.attributes?.area) ?? attribute(c.attributes?.owner);
  if (own) return own;
  const index = citationIndex(doc);
  for (const s of c.sources ?? []) {
    for (const cite of index.get(s.path) ?? []) {
      if (!cite.component) continue;
      const a = componentArea(idx, cite.component);
      if (a) return a;
    }
  }
  return SHARED;
}

export function flowArea(idx: DocIndex, flow: Flow): string | undefined {
  const e = flow.entry;
  if (!e) return undefined;
  const iface = idx.interfacesById.get(e.interface);
  const target = iface?.component ?? (e.interface.includes(".") ? e.interface.slice(0, e.interface.indexOf(".")) : undefined);
  return (target && componentArea(idx, target)) || (e.caller && componentArea(idx, e.caller)) || undefined;
}
