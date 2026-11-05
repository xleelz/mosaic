// Comparing two runs: the first point their paths differ, and what each leaves different.
// Any two runs of any revisions, so Draft and Compare can reuse it.
//
// Only type imports here: node --test runs this file with type stripping.

import type { JsonObject, JsonValue, SimEvent } from "../api/types";
import type { Beat } from "./beats";

/** What an event is on a run's path, ignoring when it happened and what values it carried. */
export function pathSignature(e: SimEvent, depth: number): string | null {
  switch (e.type) {
    case "set":
    case "note":
      return null;
    case "call.start":
      return `call|${e.interface ?? ""}|${depth}|${e.attempt ?? 1}`;
    case "call.end":
      return `end|${e.interface ?? ""}|${depth}|${e.ok === false || e.error ? (e.error?.code ?? "error") : "ok"}`;
    case "fault":
      return `fault|${e.interface ?? ""}|${e.fault ?? ""}`;
    case "choice":
      return `choice|${e.key ?? ""}|${e.option ?? ""}`;
    case "retry":
      return `retry|${e.interface ?? ""}|${e.attempt ?? ""}`;
    case "step.start":
      return `step|${e.key ?? ""}`;
    case "step.end":
      return `stepend|${e.key ?? ""}|${e.ok === false || e.error ? (e.error?.code ?? "error") : "ok"}`;
    default:
      return `${e.type}|${e.interface ?? ""}|${e.key ?? ""}|${e.error?.code ?? ""}`;
  }
}

/** One run's path: each on-path event's index and signature. */
export function runPath(events: readonly SimEvent[]): { idx: number; sig: string }[] {
  const depth = new Map<number, number>();
  const out: { idx: number; sig: string }[] = [];
  events.forEach((e, i) => {
    if (e.type === "call.start" && e.span) depth.set(e.span, e.parent ? (depth.get(e.parent) ?? 0) + 1 : 0);
    const sig = pathSignature(e, e.span ? (depth.get(e.span) ?? 0) : 0);
    if (sig !== null) out.push({ idx: i, sig });
  });
  return out;
}

export interface Divergence {
  /** The event index in each run where they part; -1 where that run has simply ended. */
  a: number;
  b: number;
}

/** Where two runs' paths first differ, or null when they follow the same path. Seeds are fixed, so this is deterministic. */
export function firstDivergence(a: readonly SimEvent[], b: readonly SimEvent[]): Divergence | null {
  const pa = runPath(a);
  const pb = runPath(b);
  const n = Math.min(pa.length, pb.length);
  for (let i = 0; i < n; i++) {
    if (pa[i].sig !== pb[i].sig) return { a: pa[i].idx, b: pb[i].idx };
  }
  if (pa.length === pb.length) return null;
  return pa.length > n ? { a: pa[n].idx, b: -1 } : { a: -1, b: pb[n].idx };
}

export interface BeatRow {
  a?: Beat;
  b?: Beat;
  /** True for the first row at or after the divergence. */
  diverges: boolean;
  /** True when this row's beats match and precede the divergence. */
  same: boolean;
}

function holds(beat: Beat | undefined, idx: number): boolean {
  return !!beat && idx >= 0 && beat.at <= idx && idx <= beat.end;
}

/**
 * Two runs' beats, row by row: the shared prefix aligned, then each run's own beats from the
 * divergence on. A beat counts as shared only if it ends before the runs part.
 */
export function alignBeats(a: readonly Beat[], b: readonly Beat[], d: Divergence | null): BeatRow[] {
  const rows: BeatRow[] = [];
  let i = 0;
  const atDivergence = (x: Beat | undefined, y: Beat | undefined) => !!d && (holds(x, d.a) || holds(y, d.b));
  while (i < a.length && i < b.length && a[i].signature === b[i].signature && !atDivergence(a[i], b[i])) {
    rows.push({ a: a[i], b: b[i], diverges: false, same: true });
    i++;
  }
  const tail = Math.max(a.length, b.length);
  let first = true;
  for (let j = i; j < tail; j++) {
    rows.push({ a: a[j], b: b[j], diverges: first && (!!d || a[j]?.signature !== b[j]?.signature), same: false });
    first = false;
  }
  return rows;
}

export interface StateChange {
  /** "<component>.<path>" */
  path: string;
  before: JsonValue | undefined;
  after: JsonValue | undefined;
}

function plain(v: JsonValue | undefined): v is JsonObject {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function walk(before: JsonValue | undefined, after: JsonValue | undefined, path: string, out: StateChange[]) {
  if (plain(before) && plain(after)) {
    for (const k of new Set([...Object.keys(before), ...Object.keys(after)])) walk(before[k], after[k], path ? `${path}.${k}` : k, out);
    return;
  }
  if (JSON.stringify(before) !== JSON.stringify(after)) out.push({ path, before, after });
}

/** The leaves a run left different from where it started, sorted. */
export function stateChanges(initial: Record<string, JsonObject> | undefined, final: Record<string, JsonObject> | undefined): StateChange[] {
  const out: StateChange[] = [];
  const ini = initial ?? {};
  const fin = final ?? {};
  for (const c of new Set([...Object.keys(ini), ...Object.keys(fin)])) walk(ini[c] ?? {}, fin[c] ?? {}, c, out);
  return out.sort((x, y) => (x.path < y.path ? -1 : x.path > y.path ? 1 : 0));
}

/** The leaves whose final value differs between two runs, with each run's value. */
export function stateDifferences(a: Record<string, JsonObject> | undefined, b: Record<string, JsonObject> | undefined): StateChange[] {
  return stateChanges(a, b);
}
