// Hierarchy helpers (docs/DESIGN.md §14.3, §14.11, §16.6).

import type { Component, Document, OntologyRef, Resolution } from "@/lib/api/types";
import { docIndex } from "./docindex";

/**
 * A refinement's revision as a client revision selector: "r3" and "3" are
 * revision 3; latest and draft pass through; none means latest (or the
 * draft when the child has no revision, see childRev).
 */
export function refRev(revision?: string): string | undefined {
  if (!revision) return undefined;
  const m = /^r?(\d+)$/.exec(revision.trim());
  return m ? m[1] : revision.trim();
}

/** The revision to read a child at, given its latest revision number (0 = none yet). */
export function childRev(ref: OntologyRef, latest: number | undefined): string {
  return refRev(ref.revision) ?? (latest === 0 ? "draft" : "latest");
}

/** Components with a refinement, in document order. */
export function refinedComponents(doc: Document): Component[] {
  return doc.components.filter((c) => (c.refined_by?.length ?? 0) > 0);
}

/** The first refinement of a component, which the store loads (§15.8). */
export function firstRefinement(doc: Document, component: string): OntologyRef | undefined {
  return docIndex(doc).componentsById.get(component)?.refined_by?.[0];
}

/** A scenario's resolution for a component (default black_box, §14.5). */
export function resolutionOf(res: { [component: string]: Resolution } | undefined, component: string): Resolution {
  return res?.[component] === "refined" ? "refined" : "black_box";
}
