// Swimlanes by area: which lanes a run's lifelines draw on. 55 to 75 component lanes become
// 5 to 13 areas, each expandable to its components. A model with no areas keeps its lanes.
//
// Only type imports here: node --test runs this file with type stripping.

/** Above this many lifelines a model with areas starts grouped. */
export const GROUP_LANES_ABOVE = 12;

export interface DisplayLane {
  /** A lifeline key, or "area:<name>" for a collapsed area. */
  key: string;
  /** The lifelines drawn on it. */
  members: string[];
  /** The area, in a grouped view. */
  area?: string;
  /** True when this lane stands for a whole area. */
  collapsed: boolean;
}

export interface LaneView {
  lanes: DisplayLane[];
  /** lifeline -> index into lanes. */
  indexOf: Map<string, number>;
  grouped: boolean;
}

function component(lane: string): string {
  const i = lane.indexOf("@");
  return i > 0 ? lane.slice(0, i) : lane;
}

/** A component's lane area: undefined for a phantom "?iface" lane or a model with no areas. */
function laneArea(lane: string, area: ReadonlyMap<string, string>): string {
  return (lane.startsWith("?") ? undefined : area.get(component(lane))) ?? "Other";
}

/** The distinct areas the lifelines fall in, in lane order. Empty when the model has no areas. */
export function laneAreas(lifelines: readonly string[], area: ReadonlyMap<string, string>): string[] {
  if (area.size === 0) return [];
  const out: string[] = [];
  for (const l of lifelines) {
    const a = laneArea(l, area);
    if (!out.includes(a)) out.push(a);
  }
  return out;
}

/** Whether a run opens grouped: enough lanes to need it, and at least two areas to group into. */
export function groupsByDefault(lifelines: readonly string[], area: ReadonlyMap<string, string>): boolean {
  return lifelines.length > GROUP_LANES_ABOVE && laneAreas(lifelines, area).length >= 2;
}

/** The lanes to draw. An area in `expanded` draws its members; any other draws as one lane. */
export function buildLaneView(lifelines: readonly string[], area: ReadonlyMap<string, string>, group: boolean, expanded: ReadonlySet<string>): LaneView {
  const lanes: DisplayLane[] = [];
  const indexOf = new Map<string, number>();
  if (!group || area.size === 0) {
    lifelines.forEach((l, i) => {
      lanes.push({ key: l, members: [l], collapsed: false });
      indexOf.set(l, i);
    });
    return { lanes, indexOf, grouped: false };
  }
  const members = new Map<string, string[]>();
  for (const l of lifelines) {
    const a = laneArea(l, area);
    const list = members.get(a);
    if (list) list.push(l);
    else members.set(a, [l]);
  }
  for (const [a, list] of members) {
    if (expanded.has(a)) {
      for (const l of list) {
        indexOf.set(l, lanes.length);
        lanes.push({ key: l, members: [l], area: a, collapsed: false });
      }
    } else {
      for (const l of list) indexOf.set(l, lanes.length);
      lanes.push({ key: `area:${a}`, members: list, area: a, collapsed: true });
    }
  }
  return { lanes, indexOf, grouped: true };
}

/** Activation depth per span on the drawn lanes: spans that share a collapsed lane nest together. */
export function laneDepths(
  spans: Iterable<{ span: number; to: string; startIdx: number; endIdx: number }>,
  indexOf: ReadonlyMap<string, number>,
): Map<number, number> {
  const marks: { at: number; end: boolean; span: number; lane: number }[] = [];
  for (const s of spans) {
    const lane = indexOf.get(s.to) ?? -1;
    marks.push({ at: s.startIdx, end: false, span: s.span, lane });
    if (s.endIdx >= 0) marks.push({ at: s.endIdx, end: true, span: s.span, lane });
  }
  marks.sort((a, b) => a.at - b.at);
  const open = new Map<number, number>();
  const out = new Map<number, number>();
  for (const m of marks) {
    const n = open.get(m.lane) ?? 0;
    if (m.end) open.set(m.lane, Math.max(0, n - 1));
    else {
      out.set(m.span, n);
      open.set(m.lane, n + 1);
    }
  }
  return out;
}
