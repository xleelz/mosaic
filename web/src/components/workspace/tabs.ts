// The workspace's tabs (docs/ux-plan-2026-11.md): Overview Map Flows Runs | Evidence History.
// Every older route keeps working and belongs to one tab. No runtime imports: node --test runs this.

export interface WorkspaceLink {
  /** The route under /o/<id>; "" is Overview. */
  sub: string;
  label: string;
}

export interface WorkspaceTab extends WorkspaceLink {
  /** Every route segment that lights this tab. */
  routes: readonly string[];
  /** Pages inside this tab, linked from the end of the tab bar while the tab is active. */
  pages?: readonly WorkspaceLink[];
}

const MAP_PAGES: readonly WorkspaceLink[] = [
  { sub: "map", label: "Map" },
  { sub: "world", label: "Configs & world setup" },
];
const HISTORY_PAGES: readonly WorkspaceLink[] = [
  { sub: "revisions", label: "Revisions" },
  { sub: "commits", label: "Commits" },
];

/** Groups, divided in the tab bar. The third, empty for now, is the slot for Drafts (pillar 2). */
export const TAB_GROUPS: readonly (readonly WorkspaceTab[])[] = [
  [
    { sub: "", label: "Overview", routes: [""] },
    { sub: "map", label: "Map", routes: ["map", "world"], pages: MAP_PAGES },
    { sub: "flows", label: "Flows", routes: ["flows"] },
    // Simulate holds the form and the recent runs; a run's own page sits under this tab too.
    { sub: "simulate", label: "Runs", routes: ["simulate", "runs"] },
  ],
  [
    { sub: "evidence", label: "Evidence", routes: ["evidence", "tests", "explore"] },
    { sub: "revisions", label: "History", routes: ["revisions", "commits"], pages: HISTORY_PAGES },
  ],
  [],
];

/** Pages that search can open besides the tabs and their pages. Evidence draws its own section links. */
export const OTHER_PAGES: readonly (WorkspaceLink & { tab: string })[] = [
  { sub: "evidence/tests", label: "Self-checks", tab: "Evidence" },
  { sub: "evidence/race-search", label: "Race search", tab: "Evidence" },
];

/** The first path segment under /o/<id>. */
export function routeSegment(pathname: string, base: string): string {
  return pathname.replace(base, "").replace(/^\//, "").split("/")[0] ?? "";
}

export function activeTab(segment: string): WorkspaceTab | undefined {
  for (const group of TAB_GROUPS) {
    for (const t of group) if (t.routes.includes(segment)) return t;
  }
  return undefined;
}

/**
 * Query parameters that used to mean the map when it was the default route. A link to /o/<id>
 * with one of these still opens the map, not Overview.
 */
export const MAP_PARAMS: readonly string[] = ["c", "i", "zoom", "fixture", "commit", "before", "after", "view"];

/** True when a query at /o/<id> is an older link to the map. */
export function isMapQuery(keys: Iterable<string>): boolean {
  for (const k of keys) if (MAP_PARAMS.includes(k)) return true;
  return false;
}
