// Categorical color for map identity (layer or kind), from the dataviz
// reference palette's dark steps. Validated with validate_palette.js against
// the panel surface #11181f: all checks pass (worst adjacent CVD ΔE 8.4,
// normal-vision ΔE 19.3, every slot >= 3:1). Hues are assigned in fixed slot
// order to the group names sorted by code point ("unspecified" last), never
// cycled; a ninth group and beyond fold into "other" gray. Sorting makes the
// assignment depend only on the set of names in the ontology, not on the order
// a data source returns nodes in, so the live server (nodes sorted by id) and
// the fixtures (document order) color the same ontology identically. Labels
// and legends always carry the group name, so identity never rests on color
// alone.

export const CATEGORICAL = [
  "#3987e5", // blue
  "#d95926", // orange
  "#199e70", // aqua
  "#c98500", // yellow
  "#d55181", // magenta
  "#008300", // green
  "#9085e9", // violet
  "#e66767", // red
] as const;

export const OTHER_COLOR = "#5f6d78";

export interface ColorScale {
  color(group: string | undefined): string;
  entries: { group: string; color: string }[];
}

const UNSPECIFIED = "unspecified";

/** Code-point order, independent of locale. */
export function compareStable(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function categoricalScale(groups: (string | undefined)[]): ColorScale {
  const set = new Set(groups.map((g) => g || UNSPECIFIED));
  const order = [...set].sort((a, b) => (a === UNSPECIFIED ? 1 : b === UNSPECIFIED ? -1 : compareStable(a, b)));
  const map = new Map<string, string>();
  order.forEach((g, i) => map.set(g, i < CATEGORICAL.length ? CATEGORICAL[i] : OTHER_COLOR));
  const entries = order.slice(0, CATEGORICAL.length).map((g) => ({ group: g, color: map.get(g)! }));
  if (order.length > CATEGORICAL.length) entries.push({ group: "other", color: OTHER_COLOR });
  return {
    color: (g) => map.get(g || UNSPECIFIED) ?? OTHER_COLOR,
    entries,
  };
}

// Status colors (reserved meaning; always shipped with an icon and a label).
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
} as const;
