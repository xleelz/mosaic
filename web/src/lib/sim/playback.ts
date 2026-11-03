// Pure helpers that turn a SimulationRun trace into what playback needs:
// spans, lifelines, and the ctx/state/vars as of every cursor position
// (replayed from summary.initial_state by applying `set` events).

import type { JsonObject, JsonValue, SimEvent, SimulationRun } from "@/lib/api/types";
import { isPlainObject, jsonEqual } from "@/lib/model/format";

export interface SpanInfo {
  span: number;
  parent: number;
  call: number;
  /** Caller lane: a component, or "<component>@<instance>" (§11.1). */
  from: string;
  /** Callee lane. */
  to: string;
  iface: string;
  attempt: number;
  async: boolean;
  startIdx: number;
  /** Index of the span's call.end, or -1 if it never ended (aborted run). */
  endIdx: number;
  /** Nesting depth on the callee lifeline (0 = outermost activation). */
  depth: number;
  ok?: boolean;
  late?: boolean;
}

export interface Snapshot {
  ctx: JsonObject;
  state: Record<string, JsonObject>;
  /** Behavior-local vars by span. */
  vars: Record<number, JsonObject>;
}

/**
 * The lanes an event is drawn on: from/to for arrows, at for single-lane marks.
 * A `timeout` or `deadline` is a mark at the caller (`at`) with `to` naming
 * the callee it gave up on or could not call (§13.1 item 11).
 */
export interface EventLanes {
  from?: string;
  to?: string;
  at?: string;
}

/** A `parallel` step: parallel.start .. parallel.end and the rows of each branch (§11.2). */
export interface ParallelGroup {
  startIdx: number;
  /** -1 if the run ended first. */
  endIdx: number;
  lane: string;
  /** Nesting depth among parallel groups (0 = outermost). */
  depth: number;
  branches: Map<number, { first: number; last: number }>;
}

/** A multi-step scenario step: step.start .. step.end (§11.7). */
export interface StepMark {
  key: string;
  startIdx: number;
  endIdx: number;
}

export interface Playback {
  run: SimulationRun;
  events: SimEvent[];
  /** Lanes: components, or "<component>@<instance>" when events carry instances; one component's lanes are adjacent. */
  lifelines: string[];
  /** lanes[i] is where events[i] is drawn. */
  lanes: EventLanes[];
  parallels: ParallelGroup[];
  /** For each event index, the parallel group its `branch` belongs to (-1 = none). */
  branchGroup: number[];
  /** For a publish event index, the subscriber call.start / emit indices that follow it. */
  fanout: Map<number, number[]>;
  steps: StepMark[];
  spans: Map<number, SpanInfo>;
  /** snapshots[i] is the state after applying events[0..i]. */
  snapshots: Snapshot[];
  initial: Snapshot;
  /** For each event index, the span whose behavior it belongs to (0 = none). */
  frameSpan: number[];
}

/** A lifeline key for a call target; unknown interfaces get a phantom lifeline. */
export function targetOf(e: SimEvent): string {
  if (e.to) return e.to;
  return `?${e.interface ?? "unknown"}`;
}

/** "<component>@<instance>", or the component for the unnamed instance. */
export function laneKey(component: string, instance?: string): string {
  return instance ? `${component}@${instance}` : component;
}

/** The component of a lane key. */
export function laneComponent(lane: string): string {
  const i = lane.indexOf("@");
  return i > 0 ? lane.slice(0, i) : lane;
}

/** The instance of a lane key ("" for none). */
export function laneInstance(lane: string): string {
  const i = lane.indexOf("@");
  return i > 0 ? lane.slice(i + 1) : "";
}

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * The segments a `set` event writes. A store write carries `table` and `key`
 * (the raw row key, which may hold dots), so it is ["state", table, key]
 * (§13.1 item 11). Otherwise the path is split on dots.
 */
export function setSegs(e: SimEvent): string[] | null {
  if (e.table && e.key !== undefined) return ["state", e.table, e.key];
  return e.path ? setPathSegs(e.path) : null;
}

/**
 * The segments of a `set` event's path, for runs from before store sets
 * carried `table` and `key`. A behavior's set path is the root followed by
 * identifiers, but a store write's is "state.<table>.<row key>", and a row key
 * may itself hold dots ("file:///a.ts"). So when a segment after the root is
 * not an identifier, everything after the table is one key.
 */
export function setPathSegs(path: string): string[] {
  const segs = path.split(".");
  if (segs.length > 3 && segs.slice(1).some((s) => !IDENT.test(s))) return [segs[0], segs[1], segs.slice(2).join(".")];
  return segs;
}

function setIn(root: JsonObject, segs: string[], value: JsonValue): JsonObject {
  if (segs.length === 0) return root;
  const [head, ...rest] = segs;
  const out: JsonObject = { ...root };
  if (rest.length === 0) {
    out[head] = value;
  } else {
    const child = root[head];
    out[head] = setIn(isPlainObject(child) ? child : {}, rest, value);
  }
  return out;
}

export function buildPlayback(run: SimulationRun): Playback {
  const events = run.trace ?? [];
  const spans = new Map<number, SpanInfo>();
  const seen: string[] = [];
  const addLife = (c: string | undefined) => {
    if (c && !seen.includes(c)) seen.push(c);
  };
  const lanes: EventLanes[] = [];

  // Callee activation depth: count of open spans on the same lifeline.
  const openOn = new Map<string, number>();
  const frameSpan: number[] = [];
  // The lane of the behavior an event runs in: its span's callee, if the component matches.
  const frameLane = (span: number | undefined, component: string | undefined): string | undefined => {
    const s = span ? spans.get(span) : undefined;
    if (s && (!component || laneComponent(s.to) === component)) return s.to;
    return undefined;
  };
  // A component's lane: its own instance, or the enclosing behavior's lane.
  const at = (e: SimEvent, component: string | undefined): string | undefined => {
    if (!component) return frameLane(e.span, undefined);
    if (e.instance) return laneKey(component, e.instance);
    return frameLane(e.span, component) ?? component;
  };

  events.forEach((e, i) => {
    let l: EventLanes;
    if (e.type === "call.start") {
      // `instance` is the callee's; the caller runs where its parent span's callee runs.
      const to = laneKey(targetOf(e), e.instance);
      const from = frameLane(e.parent, e.from) ?? e.from ?? "";
      l = { from, to };
      if (e.span) {
        const depth = openOn.get(to) ?? 0;
        openOn.set(to, depth + 1);
        spans.set(e.span, {
          span: e.span,
          parent: e.parent ?? 0,
          call: e.call ?? 0,
          from,
          to,
          iface: e.interface ?? "",
          attempt: e.attempt ?? 1,
          async: !!e.async,
          startIdx: i,
          endIdx: -1,
          depth,
        });
      }
    } else if (e.type === "call.end") {
      const s = e.span ? spans.get(e.span) : undefined;
      l = s ? { from: s.from, to: s.to } : { from: e.from ?? "", to: laneKey(targetOf(e), e.instance) };
      if (s) {
        s.endIdx = i;
        s.ok = e.ok;
        s.late = e.late;
        openOn.set(s.to, Math.max(0, (openOn.get(s.to) ?? 1) - 1));
      }
    } else if (e.type === "emit") {
      l = { from: frameLane(e.span, e.from) ?? e.from ?? e.component, to: laneKey(e.to || `?${e.interface}`, e.instance) };
    } else if (e.type === "step.start" || e.type === "step.end") {
      // Step marks span the whole diagram, so they claim no lane. (Their `instance`
      // is the step's target, not the caller's: an `at` lane would invent "caller@instance".)
      l = {};
    } else if (e.type === "timeout" || e.type === "deadline") {
      // These describe the caller (§13.1 item 11): `component` and `instance`
      // are the caller's and `to` is the callee. A timeout's span is the call
      // it gave up on; a deadline's is the caller's own frame. Old runs put the
      // callee's instance here, so the span's lanes win when there is one.
      const s = e.type === "timeout" && e.span ? spans.get(e.span) : undefined;
      const caller =
        s?.from ?? frameLane(e.span, e.component) ?? (e.component ? laneKey(e.component, e.instance) : undefined);
      let callee = s?.to;
      if (!callee && e.to) callee = seen.includes(e.to) ? e.to : (seen.find((c) => laneComponent(c) === e.to) ?? e.to);
      l = { at: caller };
      if (callee && callee !== caller) l.to = callee;
    } else {
      l = { at: at(e, e.component) };
    }
    if (l.from !== undefined) addLife(l.from);
    if (l.to !== undefined) addLife(l.to);
    if (l.at !== undefined) addLife(l.at);
    lanes.push(l);
    frameSpan.push(e.span ?? 0);
  });

  // Keep one component's instance lanes together, in order of first appearance.
  const order = new Map<string, number>();
  seen.forEach((c) => {
    const k = laneComponent(c);
    if (!order.has(k)) order.set(k, order.size);
  });
  const lifelines = seen
    .map((c, i) => ({ c, i }))
    .sort((a, b) => order.get(laneComponent(a.c))! - order.get(laneComponent(b.c))! || a.i - b.i)
    .map((x) => x.c);

  // Parallel groups, branch membership, step marks and publish fan-out.
  const parallels: ParallelGroup[] = [];
  const branchGroup: number[] = [];
  const stack: number[] = [];
  const steps: StepMark[] = [];
  const fanout = new Map<number, number[]>();
  events.forEach((e, i) => {
    if (e.type === "parallel.start") {
      parallels.push({ startIdx: i, endIdx: -1, lane: lanes[i].at ?? "", depth: stack.length, branches: new Map() });
      stack.push(parallels.length - 1);
    } else if (e.type === "parallel.end") {
      const g = stack.pop();
      if (g !== undefined) parallels[g].endIdx = i;
    } else if (e.type === "step.start") {
      steps.push({ key: e.key ?? String(steps.length), startIdx: i, endIdx: -1 });
    } else if (e.type === "step.end") {
      const m = steps[steps.length - 1];
      if (m && m.endIdx < 0) m.endIdx = i;
    }
    let g = -1;
    if (e.branch !== undefined && e.type !== "parallel.start" && e.type !== "parallel.end") {
      // The innermost open group, else (late branch events) the last group closed.
      g = stack.length ? stack[stack.length - 1] : parallels.length - 1;
      if (g >= 0) {
        const b = parallels[g].branches.get(e.branch);
        if (b) b.last = i;
        else parallels[g].branches.set(e.branch, { first: i, last: i });
      }
    }
    branchGroup.push(g);
    if (e.type === "publish") {
      // Subscribers: the calls and emits the publishing behavior makes next.
      const frame = e.span ?? 0;
      const subs: number[] = [];
      for (let j = i + 1; j < events.length && subs.length < 64; j++) {
        const x = events[j];
        if (x.type === "call.start" && (x.parent ?? 0) === frame) subs.push(j);
        else if (x.type === "emit" && (x.span ?? 0) === frame) subs.push(j);
        else if ((x.span ?? 0) === frame && x.type !== "queue" && x.type !== "fault" && x.type !== "retry") break;
      }
      fanout.set(i, subs);
    }
  });

  const initial: Snapshot = {
    ctx: {},
    state: structuredClone(run.summary.initial_state ?? {}),
    vars: {},
  };
  const snapshots: Snapshot[] = [];
  let cur = initial;
  events.forEach((e, i) => {
    const segs = e.type === "set" ? setSegs(e) : null;
    if (segs) {
      const scope = segs[0];
      const rest = segs.slice(1);
      const value: JsonValue = e.new === undefined ? null : e.new;
      if (scope === "ctx") {
        cur = { ...cur, ctx: setIn(cur.ctx, rest, value) };
      } else if (scope === "state" && e.component) {
        const key = stateKey(e, lanes[i].at);
        cur = {
          ...cur,
          state: { ...cur.state, [key]: setIn(cur.state[key] ?? {}, rest, value) },
        };
      } else if (scope === "vars" && e.span) {
        cur = { ...cur, vars: { ...cur.vars, [e.span]: setIn(cur.vars[e.span] ?? {}, rest, value) } };
      }
    }
    snapshots.push(cur);
  });
  return { run, events, lifelines, lanes, parallels, branchGroup, fanout, steps, spans, snapshots, initial, frameSpan };
}

/** The state key a `set` writes: "<component>@<instance>", or the component (§11.1). `lane` is the event's lane, when known. */
function stateKey(e: SimEvent, lane?: string): string {
  if (e.instance || !lane || laneComponent(lane) !== e.component) return laneKey(e.component ?? "", e.instance);
  return lane;
}

/**
 * The state keys this run read or wrote: those a `set` touched, those whose
 * final state (summary.state) differs from the initial state, those the
 * request seeded, and those of components that ran in the trace (a behavior
 * may read its own state without a trace event).
 */
export function touchedState(p: Playback): Set<string> {
  const out = new Set<string>();
  p.events.forEach((e, i) => {
    const c = changedAt(e, p.lanes[i]?.at);
    if (c?.scope === "state" && c.component) out.add(c.component);
  });
  const fin = p.run.summary.state ?? {};
  const init = p.run.summary.initial_state ?? {};
  for (const k of new Set([...Object.keys(fin), ...Object.keys(init)])) {
    if (!jsonEqual(fin[k] ?? null, init[k] ?? null)) out.add(k);
  }
  for (const k of Object.keys(p.run.request?.state ?? {})) out.add(k);
  const keys = new Set([...Object.keys(init), ...Object.keys(fin)]);
  for (const k of keys) {
    const comp = laneComponent(k);
    const inst = laneInstance(k);
    if (p.lifelines.some((l) => laneComponent(l) === comp && (!inst || !laneInstance(l) || l === k))) out.add(k);
  }
  return out;
}

export function snapshotAt(p: Playback, cursor: number): Snapshot {
  if (cursor < 0 || p.snapshots.length === 0) return p.initial;
  return p.snapshots[Math.min(cursor, p.snapshots.length - 1)];
}

/** Spans open (started, not yet ended) at the cursor, outermost first. */
export function openSpans(p: Playback, cursor: number): SpanInfo[] {
  const out: SpanInfo[] = [];
  p.spans.forEach((s) => {
    if (s.startIdx <= cursor && (s.endIdx === -1 || s.endIdx >= cursor)) out.push(s);
  });
  return out.sort((a, b) => a.startIdx - b.startIdx);
}

export interface ActiveEdge {
  from: string;
  to: string;
  /** request, response, error, emit, async, timeout */
  kind: "request" | "response" | "error" | "emit" | "async" | "timeout" | "late";
}

/** What the map highlights for an event. */
export function activeFor(e: SimEvent | undefined): { component?: string; edge?: ActiveEdge } {
  if (!e) return {};
  switch (e.type) {
    case "call.start":
      return {
        component: targetOf(e),
        edge: { from: e.from ?? "", to: targetOf(e), kind: e.async ? "async" : "request" },
      };
    case "call.end":
      return {
        component: e.from,
        edge: {
          from: targetOf(e),
          to: e.from ?? "",
          kind: e.late ? "late" : e.ok === false ? "error" : "response",
        },
      };
    case "emit":
      return { component: e.from, edge: { from: e.from ?? "", to: e.to || "", kind: "emit" } };
    case "timeout":
    case "deadline": {
      // The caller gave up on (or could not call) `to` (§13.1 item 11).
      const to = e.to || (e.interface ? e.interface.split(".")[0] : "");
      return { component: e.component, edge: to ? { from: e.component ?? "", to, kind: "timeout" } : undefined };
    }
    default:
      return { component: e.component };
  }
}

export type ChangedPath = { scope: "ctx" | "state" | "vars"; component?: string; span?: number; segs: string[] };

export function changedAt(e: SimEvent | undefined, lane?: string): ChangedPath | null {
  if (!e || e.type !== "set") return null;
  const segs = setSegs(e);
  if (!segs) return null;
  const scope = segs[0];
  if (scope !== "ctx" && scope !== "state" && scope !== "vars") return null;
  return { scope, component: scope === "state" ? stateKey(e, lane) : e.component, span: e.span, segs: segs.slice(1) };
}

/** What a `set` writes, for display: "state.<table>[<key>]" for a store row, else the path. */
export function setLabel(e: SimEvent): string {
  if (e.table && e.key !== undefined) return IDENT.test(e.key) ? `state.${e.table}.${e.key}` : `state.${e.table}[${JSON.stringify(e.key)}]`;
  return e.path ?? "";
}

/** A human label for an event, used by the timeline and the inspector. */
export function eventLabel(e: SimEvent): string {
  const iface = e.interface ?? "";
  switch (e.type) {
    case "call.start":
      return `${e.async ? "async " : ""}call ${iface}${(e.attempt ?? 1) > 1 ? ` (attempt ${e.attempt})` : ""}`;
    case "call.end":
      if (e.ok === false) return `${iface} failed: ${e.error?.code ?? "error"}${e.late ? " (late)" : ""}`;
      return `${iface} returned${e.late ? " late" : ""}`;
    case "note":
      return e.title || e.detail || "note";
    case "set":
      return `set ${setLabel(e)}`;
    case "choice":
      return `choice ${e.key} → ${e.option}`;
    case "fault":
      return `fault ${e.fault} on ${iface}`;
    case "retry":
      return `retry ${iface} (attempt ${e.attempt ?? "?"})`;
    case "timeout":
      return `timeout ${iface} after ${e.duration_ms ?? "?"} ms${e.to ? ` (gave up on ${e.to})` : ""}`;
    case "emit":
      return `emit ${iface}`;
    case "warning":
      return `warning: ${e.message ?? ""}`;
    case "queue":
      return `queued ${iface} for ${e.wait_ms ?? 0} ms`;
    case "publish":
      return `publish ${e.topic ?? iface}`;
    case "parallel.start": {
      const o = isPlainObject(e.output) ? e.output : {};
      return `parallel: ${o.branches ?? "?"} branches, need ${o.need ?? "?"}`;
    }
    case "parallel.end": {
      const o = isPlainObject(e.output) ? e.output : {};
      if (e.error) return `parallel failed: ${e.error.code} (${o.received ?? "?"}/${o.required ?? "?"})`;
      return `parallel joined: ${o.received ?? "?"}/${o.required ?? "?"}`;
    }
    case "step.start":
      return `step ${e.key ?? ""}${e.interface ? ` · ${e.interface}` : ""}`;
    case "step.end":
      return `step ${e.key ?? ""} ${e.ok === false || e.error ? "failed" : "done"}`;
    case "deadline":
      return `deadline exceeded${iface ? ` calling ${iface}` : ""}`;
    case "yield":
      return `yield #${e.index ?? 0}${iface ? ` from ${iface}` : ""}`;
    case "put":
      return e.error ? `put on ${e.key ?? ""} failed: ${e.error.code}` : `put on ${e.key ?? ""}${e.wait_ms ? ` after ${e.wait_ms} ms` : ""}`;
    case "receive":
      return e.error ? `receive on ${e.key ?? ""} failed: ${e.error.code}` : `receive from ${e.key ?? ""}${e.wait_ms ? ` after ${e.wait_ms} ms` : ""}`;
    case "kill":
      return `kill ${e.component ?? ""}${e.instance ? `@${e.instance}` : ""}`;
    default:
      return e.type;
  }
}

/** The status family of an event, for consistent icon + color across views. */
export type EventTone =
  | "call"
  | "ok"
  | "error"
  | "fault"
  | "retry"
  | "timeout"
  | "late"
  | "async"
  | "note"
  | "set"
  | "choice"
  | "warning"
  | "queue"
  | "parallel"
  | "step";

export function eventTone(e: SimEvent): EventTone {
  switch (e.type) {
    case "call.start":
      return e.async ? "async" : "call";
    case "call.end":
      if (e.late) return "late";
      return e.ok === false ? "error" : e.async ? "async" : "ok";
    case "fault":
      return "fault";
    case "retry":
      return "retry";
    case "timeout":
      return "timeout";
    case "emit":
      return "async";
    case "note":
      return "note";
    case "set":
      return "set";
    case "choice":
      return "choice";
    case "warning":
      return "warning";
    case "queue":
      return "queue";
    case "publish":
      return "async";
    case "parallel.start":
      return "parallel";
    case "parallel.end":
      return e.error ? "error" : "parallel";
    case "step.start":
      return "step";
    case "step.end":
      return e.ok === false || e.error ? "error" : "step";
    case "deadline":
      return "timeout";
    case "yield":
      return "async";
    case "put":
    case "receive":
      return e.error ? "error" : "queue";
    case "kill":
      return "error";
    default:
      return "note";
  }
}

export const TONE_ICON: Record<EventTone, string> = {
  call: "→",
  ok: "←",
  error: "✗",
  fault: "⚡",
  retry: "↻",
  timeout: "⏱",
  late: "⇠",
  async: "⇢",
  note: "✎",
  set: "≔",
  choice: "◆",
  warning: "⚠",
  queue: "⧗",
  parallel: "⫴",
  step: "▤",
};
