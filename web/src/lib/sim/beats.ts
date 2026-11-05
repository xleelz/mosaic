// The summary trace: a run's story as beats, derived from the data with no LLM
// (docs/ux-review-2026-11.md, Concept B). `set` and `note` events collapse, the call
// tree folds at each area crossing, and what's left is the beats: step starts, area
// crossings, choices, faults, errors, retries and shallow notes.
//
// Only type imports here: node --test runs this file with type stripping.

import type { SimEvent } from "../api/types";

export type BeatKind =
  /** step.start */
  | "step"
  /** A call that enters another area, or a top-level call. */
  | "crossing"
  /** Work resuming in an area after a call into another one returned. */
  | "back"
  | "choice"
  | "fault"
  | "error"
  | "retry"
  | "timeout"
  | "warning"
  | "note"
  /** Consecutive repeats of the same beats, folded into one. */
  | "loop";

export interface Beat {
  /** Its position in the summary. */
  id: number;
  kind: BeatKind;
  /** The event index it starts at: where the cursor goes. */
  at: number;
  /** The last event index it folds, inclusive. */
  end: number;
  /** The area it runs in. */
  area?: string;
  /** The area a crossing came from. */
  fromArea?: string;
  title: string;
  detail?: string;
  /** The interface it's about, when there's one. */
  iface?: string;
  /** How many identical beats this one stands for. */
  count: number;
  /** Calls folded into this beat, not counting its own. */
  calls: number;
  /** `set` and `note` events collapsed into this beat. */
  collapsed: number;
  /** Identifies what the beat is, not when: compare aligns on it. */
  signature: string;
}

export interface BeatOptions {
  /** The grouping key of a component. See areaResolver. */
  areaOf: (component: string) => string;
  /** A note this deep or shallower (0 is the entry call's behavior) is a beat. */
  noteDepth?: number;
  /** The longest repeating run of beats to fold. */
  maxLoop?: number;
}

const DEFAULT_NOTE_DEPTH = 1;
const DEFAULT_MAX_LOOP = 12;

/** Beats that are never folded into a loop: a reader is looking for exactly these. */
const LANDMARK: ReadonlySet<BeatKind> = new Set<BeatKind>(["step", "fault", "error", "timeout"]);

/**
 * The grouping key for components: the area when the model has areas, "Other" for a
 * component outside them, and the component itself when the model has none, so a model
 * without areas folds at component crossings.
 */
export function areaResolver(area: ReadonlyMap<string, string>): (component: string) => string {
  if (area.size === 0) return (c) => c;
  return (c) => area.get(c) ?? "Other";
}

function shortName(iface: string): string {
  const i = iface.indexOf(".");
  return i >= 0 ? iface.slice(i + 1) : iface;
}

function errorText(e: SimEvent): string {
  const err = e.error;
  if (!err) return "error";
  return `${err.status ? `${err.status} ` : ""}${err.code ?? "error"}`;
}

export function deriveBeats(events: readonly SimEvent[], opts: BeatOptions): Beat[] {
  const { areaOf } = opts;
  const noteDepth = opts.noteDepth ?? DEFAULT_NOTE_DEPTH;
  const beats: Beat[] = [];
  const spanDepth = new Map<number, number>();
  const depthOf = (span: number | undefined) => (span ? (spanDepth.get(span) ?? 0) : 0);
  // The area execution returned to, when a call out of it just came back.
  let cur: Beat | undefined;
  // The area of the most recent structural beat or return: where folded calls count.
  let here: string | undefined;

  const add = (kind: BeatKind, i: number, fields: Partial<Beat> & { title: string; signature: string }) => {
    const prev = beats[beats.length - 1];
    // The same beat again, with nothing between but what it folds: one line, with a count.
    if (prev && prev.kind === kind && prev.signature === fields.signature) {
      prev.count++;
      prev.end = i;
      cur = prev;
      return;
    }
    const b: Beat = { id: beats.length, kind, at: i, end: i, count: 1, calls: 0, collapsed: 0, ...fields };
    beats.push(b);
    cur = b;
  };

  events.forEach((e, i) => {
    if (cur) cur.end = i;
    switch (e.type) {
      case "set":
        if (cur) cur.collapsed++;
        return;
      case "note": {
        const shallow = depthOf(e.span) <= noteDepth;
        if (shallow && (e.title || e.detail)) {
          const title = e.title || e.detail || "note";
          add("note", i, { title, detail: e.title ? e.detail : undefined, area: e.component ? areaOf(e.component) : undefined, signature: `note|${title}` });
        } else if (cur) cur.collapsed++;
        return;
      }
      case "step.start": {
        const key = e.key ?? "";
        add("step", i, { title: `Step ${key}`.trim(), detail: e.interface, iface: e.interface, signature: `step|${key}|${e.interface ?? ""}` });
        here = undefined;
        return;
      }
      case "step.end":
        if (e.ok === false || e.error) {
          const text = errorText(e);
          add("error", i, { title: `Step ${e.key ?? ""} failed: ${text}`, detail: e.error?.message, signature: `error|step|${e.error?.code ?? ""}` });
        }
        return;
      case "call.start": {
        if (e.span) spanDepth.set(e.span, e.parent ? depthOf(e.parent) + 1 : 0);
        const to = e.to ? areaOf(e.to) : "Other";
        const from = e.from ? areaOf(e.from) : undefined;
        const iface = e.interface ?? "";
        if (!e.parent || !from || from !== to) {
          add("crossing", i, { title: shortName(iface) || iface, iface, area: to, fromArea: e.parent ? from : undefined, signature: `crossing|${from ?? ""}|${to}|${iface}` });
          here = to;
        } else if (here !== to) {
          // Back in this area with more to do after a call out of it returned.
          add("back", i, { title: `Back in ${to}`, area: to, iface, detail: shortName(iface), signature: `back|${to}|${iface}` });
          here = to;
        } else if (cur) {
          cur.calls++;
        }
        return;
      }
      case "call.end": {
        if (e.ok === false || e.error) {
          const text = errorText(e);
          const code = e.error?.code ?? "";
          const prev = beats[beats.length - 1];
          // An error unwinding through its callers is one beat, however many frames it passes.
          if (prev?.kind === "error" && prev.signature === `error|${code}`) {
            prev.count++;
            prev.end = i;
          } else {
            add("error", i, {
              title: `${shortName(e.interface ?? "")} failed: ${text}`,
              detail: e.error?.message,
              iface: e.interface,
              area: e.to ? areaOf(e.to) : undefined,
              signature: `error|${code}`,
            });
          }
        }
        if (e.from) here = areaOf(e.from);
        return;
      }
      case "choice": {
        const name = (e.key ?? "").split(".").pop() ?? "";
        add("choice", i, { title: `${name} → ${e.option ?? ""}`, detail: e.origin, area: e.component ? areaOf(e.component) : undefined, signature: `choice|${e.key ?? ""}|${e.option ?? ""}` });
        return;
      }
      case "fault":
        add("fault", i, {
          // A fault's kind is often just "error": its message says which.
          title: `Fault on ${shortName(e.interface ?? "")}: ${e.message || e.fault || ""}`,
          detail: e.message ? e.fault : undefined,
          iface: e.interface,
          area: e.component ? areaOf(e.component) : undefined,
          signature: `fault|${e.interface ?? ""}|${e.fault ?? ""}`,
        });
        return;
      case "kill":
        add("fault", i, {
          title: `Killed ${e.component ?? ""}${e.instance ? `@${e.instance}` : ""}`,
          area: e.component ? areaOf(e.component) : undefined,
          signature: `kill|${e.component ?? ""}|${e.instance ?? ""}`,
        });
        return;
      case "retry":
        add("retry", i, {
          title: `Retry ${shortName(e.interface ?? "")}, attempt ${e.attempt ?? "?"}`,
          detail: e.message,
          iface: e.interface,
          area: e.component ? areaOf(e.component) : undefined,
          signature: `retry|${e.interface ?? ""}`,
        });
        return;
      case "timeout":
      case "deadline":
        add("timeout", i, {
          title: e.type === "timeout" ? `Timeout on ${shortName(e.interface ?? "")} after ${e.duration_ms ?? "?"} ms` : `Deadline exceeded${e.interface ? ` calling ${shortName(e.interface)}` : ""}`,
          detail: e.message,
          iface: e.interface,
          area: e.component ? areaOf(e.component) : undefined,
          signature: `${e.type}|${e.interface ?? ""}`,
        });
        return;
      case "parallel.end":
        if (e.error) {
          add("error", i, { title: `Join failed: ${e.error.code}`, detail: e.error.message, area: e.component ? areaOf(e.component) : undefined, signature: `error|join|${e.error.code}` });
        }
        return;
      case "put":
      case "receive":
        if (e.error) {
          add("error", i, { title: `${e.type} on ${e.key ?? ""} failed: ${e.error.code}`, detail: e.error.message, area: e.component ? areaOf(e.component) : undefined, signature: `error|${e.type}|${e.key ?? ""}|${e.error.code}` });
        }
        return;
      case "warning":
        add("warning", i, { title: e.message ?? "warning", signature: `warning|${e.message ?? ""}` });
        return;
      default:
        return;
    }
  });
  return foldLoops(beats, opts.maxLoop ?? DEFAULT_MAX_LOOP);
}

/**
 * Folds runs of the same few beats, repeating back to back, into one "loop" beat. A busy
 * loop or a per-item walk otherwise becomes hundreds of lines that say the same thing.
 */
export function foldLoops(beats: Beat[], maxLoop: number = DEFAULT_MAX_LOOP): Beat[] {
  const out: Beat[] = [];
  let i = 0;
  while (i < beats.length) {
    let bestLen = 0;
    let bestReps = 1;
    for (let len = 1; len <= maxLoop && i + 2 * len <= beats.length; len++) {
      let foldable = true;
      for (let k = 0; k < len && foldable; k++) foldable = !LANDMARK.has(beats[i + k].kind);
      if (!foldable) break;
      let reps = 1;
      while (i + (reps + 1) * len <= beats.length) {
        let same = true;
        for (let k = 0; k < len && same; k++) same = beats[i + k].signature === beats[i + reps * len + k].signature;
        if (!same) break;
        reps++;
      }
      // The fold that hides the most lines wins; a tie goes to the shorter loop.
      if (reps > 1 && (reps - 1) * len > (bestReps - 1) * bestLen) {
        bestLen = len;
        bestReps = reps;
      }
    }
    if (bestReps < 2) {
      out.push(beats[i]);
      i++;
      continue;
    }
    const covered = beats.slice(i, i + bestLen * bestReps);
    const first = covered.slice(0, bestLen);
    const titles = first.map((b) => b.title);
    const shown = titles.slice(0, 3).join(", ");
    out.push({
      id: 0,
      kind: "loop",
      at: covered[0].at,
      end: covered[covered.length - 1].end,
      area: first[0].area,
      title: `Repeats ${bestReps} times: ${shown}${titles.length > 3 ? ` and ${titles.length - 3} more` : ""}`,
      iface: first[0].iface,
      count: bestReps,
      calls: covered.reduce((n, b) => n + b.calls + b.count, 0) - bestReps,
      collapsed: covered.reduce((n, b) => n + b.collapsed, 0),
      signature: `loop|${first.map((b) => b.signature).join(",")}`,
    });
    i += bestLen * bestReps;
  }
  out.forEach((b, k) => {
    b.id = k;
    b.end = k + 1 < out.length ? out[k + 1].at - 1 : b.end;
  });
  return out;
}

/** The index of the beat holding an event, or -1 before the first. */
export function beatIndexAt(beats: readonly Beat[], eventIdx: number): number {
  let lo = 0;
  let hi = beats.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (beats[mid].at <= eventIdx) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

export interface BeatSpan {
  span: number;
  /** The event index of its call.start. */
  idx: number;
  iface: string;
  /** Nesting relative to the beat's shallowest span. */
  indent: number;
  from?: string;
  to?: string;
  ok?: boolean;
  attempt: number;
}

/**
 * The spans a beat touches, in order: those that start inside it, and those it only finishes or
 * reports on. A fault or an error happens inside a call that started in an earlier beat.
 */
export function spansInBeat(events: readonly SimEvent[], beat: Pick<Beat, "at" | "end">): BeatSpan[] {
  const end = Math.min(beat.end, events.length - 1);
  const touched = new Set<number>();
  for (let i = beat.at; i <= end; i++) {
    const span = events[i].span;
    if (span) touched.add(span);
  }
  const out: BeatSpan[] = [];
  const pos = new Map<number, number>();
  const level = new Map<number, number>();
  for (let i = 0; i <= end; i++) {
    const e = events[i];
    if (e.type === "call.start" && e.span && touched.has(e.span)) {
      const indent = e.parent && level.has(e.parent) ? level.get(e.parent)! + 1 : 0;
      level.set(e.span, indent);
      pos.set(e.span, out.length);
      out.push({ span: e.span, idx: i, iface: e.interface ?? "", indent, from: e.from, to: e.to, attempt: e.attempt ?? 1 });
    } else if (e.type === "call.end" && e.span && pos.has(e.span)) {
      out[pos.get(e.span)!].ok = e.ok !== false && !e.error;
    }
  }
  return out;
}

export type WeakFidelity = "partial" | "shell" | "absent";

const WEAK_RANK: Record<WeakFidelity, number> = { shell: 0, absent: 1, partial: 2 };

/** The worst of two fidelity marks. */
export function worseFidelity(a: WeakFidelity | undefined, b: WeakFidelity): WeakFidelity {
  return a === undefined || WEAK_RANK[b] < WEAK_RANK[a] ? b : a;
}

/** interface -> its worst fidelity, from the mechanisms a run passed through that aren't fully modeled. */
export function weakByInterface(mechanisms: readonly { fidelity: string; interfaces: readonly string[] }[]): Map<string, WeakFidelity> {
  const out = new Map<string, WeakFidelity>();
  for (const m of mechanisms) {
    if (m.fidelity !== "partial" && m.fidelity !== "shell" && m.fidelity !== "absent") continue;
    for (const i of m.interfaces) out.set(i, worseFidelity(out.get(i), m.fidelity));
  }
  return out;
}

/** The worst fidelity of the calls made inside each beat, by beat id. */
export function weakBeats(events: readonly SimEvent[], beats: readonly Beat[], weak: ReadonlyMap<string, WeakFidelity>): Map<number, WeakFidelity> {
  const out = new Map<number, WeakFidelity>();
  if (weak.size === 0) return out;
  for (const b of beats) {
    let worst: WeakFidelity | undefined;
    for (let i = b.at; i <= b.end && i < events.length; i++) {
      const e = events[i];
      if (e.type !== "call.start" || !e.interface) continue;
      const f = weak.get(e.interface);
      if (f) worst = worseFidelity(worst, f);
    }
    if (worst) out.set(b.id, worst);
  }
  return out;
}

/** The interfaces a run called. */
export function calledInterfaces(events: readonly SimEvent[]): Set<string> {
  const out = new Set<string>();
  for (const e of events) if (e.type === "call.start" && e.interface) out.add(e.interface);
  return out;
}

export interface Jumps {
  firstFault: number;
  firstError: number;
  /** How many events are errors. */
  errors: number;
  /** Event indices that change component state, ascending. */
  stateChanges: number[];
}

function isError(e: SimEvent): boolean {
  switch (e.type) {
    case "call.end":
      return e.ok === false || !!e.error;
    case "step.end":
    case "parallel.end":
    case "put":
    case "receive":
      return e.ok === false || !!e.error;
    case "deadline":
    case "timeout":
      return true;
    default:
      return false;
  }
}

/** A `set` that writes component state, rather than ctx or a behavior's vars. */
export function isStateWrite(e: SimEvent): boolean {
  if (e.type !== "set") return false;
  if (e.table) return true;
  return e.scope === "state" || (e.path ?? "").startsWith("state.");
}

/** Where the jump tiles and keys go; -1 when a run has none. */
export function jumpTargets(events: readonly SimEvent[]): Jumps {
  let firstFault = -1;
  let firstError = -1;
  let errors = 0;
  const stateChanges: number[] = [];
  events.forEach((e, i) => {
    if (firstFault < 0 && (e.type === "fault" || e.type === "kill")) firstFault = i;
    if (isError(e)) {
      errors++;
      if (firstError < 0) firstError = i;
    }
    if (isStateWrite(e)) stateChanges.push(i);
  });
  return { firstFault, firstError, errors, stateChanges };
}

/** The first state change after the cursor, or -1. */
export function nextStateChange(jumps: Pick<Jumps, "stateChanges">, cursor: number): number {
  const list = jumps.stateChanges;
  let lo = 0;
  let hi = list.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid] > cursor) hi = mid;
    else lo = mid + 1;
  }
  return lo < list.length ? list[lo] : -1;
}

/** Where a run opens: on its first fault, else its first error, else the first event. */
export function openingCursor(jumps: Pick<Jumps, "firstFault" | "firstError">): number {
  if (jumps.firstFault >= 0) return jumps.firstFault;
  if (jumps.firstError >= 0) return jumps.firstError;
  return 0;
}

/** `set` and `note`: the events the sequence hides above NOISE_ABOVE events. */
export function isNoise(e: SimEvent): boolean {
  return e.type === "set" || e.type === "note";
}

export const NOISE_ABOVE = 300;

/** The next event to stop on in a direction, skipping `set` and `note` when hidden. */
export function stepTarget(events: readonly SimEvent[], cursor: number, dir: 1 | -1, skipNoise: boolean, by = 1): number {
  const last = events.length - 1;
  let i = cursor;
  for (let n = 0; n < by; n++) {
    let j = i + dir;
    while (skipNoise && j >= 0 && j <= last && isNoise(events[j])) j += dir;
    if (j < 0 || j > last) break;
    i = j;
  }
  return i;
}
