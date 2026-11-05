// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { SimEvent, SimulationRun } from "../api/types.ts";
import {
  areaResolver,
  beatIndexAt,
  calledInterfaces,
  deriveBeats,
  jumpTargets,
  nextStateChange,
  openingCursor,
  spansInBeat,
  stepTarget,
  weakBeats,
  weakByInterface,
  worseFidelity,
  type Beat,
} from "./beats.ts";

function fixture(path: string): SimulationRun {
  return JSON.parse(readFileSync(new URL(`../../../fixtures/${path}`, import.meta.url), "utf8")) as SimulationRun;
}

const area = new Map([
  ["api", "serving"],
  ["router", "serving"],
  ["engine", "core"],
  ["sched", "core"],
  ["worker", "workers"],
]);
const areaOf = areaResolver(area);

let seq = 0;
function ev(type: string, fields: Partial<SimEvent> = {}): SimEvent {
  seq++;
  return { seq, t: seq, type, ...fields } as SimEvent;
}
function call(span: number, parent: number, from: string, to: string, name: string): SimEvent {
  return ev("call.start", { span, parent, call: span, component: from, from, to, interface: `${to}.${name}`, attempt: 1 });
}
function ret(span: number, parent: number, from: string, to: string, name: string): SimEvent {
  return ev("call.end", { span, parent, call: span, component: to, from, to, interface: `${to}.${name}`, attempt: 1, ok: true });
}
function failed(span: number, parent: number, from: string, to: string, name: string, code: string, status = 500): SimEvent {
  return ev("call.end", { span, parent, call: span, component: to, from, to, interface: `${to}.${name}`, attempt: 1, ok: false, error: { code, message: code, status } });
}
function set(span: number, component: string, path: string, scope = "state"): SimEvent {
  return ev("set", { span, component, scope, path, new: 1 });
}

/** A request through two areas, ending in a worker fault that unwinds to the entry. */
function faultedRun(): SimEvent[] {
  return [
    call(1, 0, "client", "api", "generate"),
    set(1, "api", "vars.p", "vars"),
    call(2, 1, "api", "router", "route"),
    ret(2, 1, "api", "router", "route"),
    call(3, 1, "api", "engine", "submit"),
    set(3, "engine", "state.queued"),
    ev("note", { span: 3, component: "engine", title: "Admission check" }),
    call(4, 3, "engine", "sched", "pick"),
    ev("note", { span: 4, component: "sched", title: "Too deep to tell" }),
    ev("choice", { span: 4, component: "sched", key: "sched.pick.has_work", option: "busy", origin: "expression" }),
    ret(4, 3, "engine", "sched", "pick"),
    call(5, 3, "engine", "worker", "execute"),
    ev("fault", { span: 5, call: 5, component: "worker", interface: "worker.execute", fault: "error", message: "device-error" }),
    failed(5, 3, "engine", "worker", "execute", "device-error"),
    failed(3, 1, "api", "engine", "submit", "device-error"),
    failed(1, 0, "client", "api", "generate", "device-error"),
  ];
}

test("collapses set and deep notes, keeps shallow notes, choices and faults", () => {
  const beats = deriveBeats(faultedRun(), { areaOf });
  const kinds = beats.map((b) => b.kind);
  assert.deepEqual(kinds, ["crossing", "crossing", "note", "choice", "crossing", "fault", "error"]);
  assert.equal(beats.some((b) => b.title === "Too deep to tell"), false);
  assert.equal(beats[1].collapsed, 1);
  assert.ok(beats.every((b) => !b.title.startsWith("set")));
});

test("folds calls inside one area into the beat they follow", () => {
  const beats = deriveBeats(faultedRun(), { areaOf });
  assert.equal(beats[0].title, "generate");
  assert.equal(beats[0].calls, 1, "the call to the router stays in the serving area");
  const spans = spansInBeat(faultedRun(), beats[0]);
  assert.deepEqual(spans.map((s) => s.iface), ["api.generate", "router.route"]);
  assert.deepEqual(spans.map((s) => s.indent), [0, 1]);
});

test("a fault or an error opens the spans it happened in, though they started earlier", () => {
  const events = faultedRun();
  const beats = deriveBeats(events, { areaOf });
  const fault = beats.find((b) => b.kind === "fault")!;
  assert.deepEqual(spansInBeat(events, fault).map((s) => s.iface), ["worker.execute"]);
  const error = beats.find((b) => b.kind === "error")!;
  const spans = spansInBeat(events, error);
  assert.deepEqual(spans.map((s) => s.iface), ["api.generate", "engine.submit", "worker.execute"]);
  assert.ok(spans.every((s) => s.ok === false));
  assert.deepEqual(spans.map((s) => s.indent), [0, 1, 2]);
});

test("an error unwinding through its callers is one beat", () => {
  const beats = deriveBeats(faultedRun(), { areaOf });
  const errors = beats.filter((b) => b.kind === "error");
  assert.equal(errors.length, 1);
  assert.equal(errors[0].count, 3);
  assert.equal(errors[0].title, "execute failed: 500 device-error");
  assert.equal(beats.find((b) => b.kind === "fault")?.title, "Fault on execute: device-error");
});

test("beats cover the trace with no gaps, and each event finds its beat", () => {
  const events = faultedRun();
  const beats = deriveBeats(events, { areaOf });
  for (let i = 1; i < beats.length; i++) assert.equal(beats[i].at, beats[i - 1].end + 1);
  assert.equal(beats[beats.length - 1].end, events.length - 1);
  assert.equal(beatIndexAt(beats, 0), 0);
  assert.equal(beats[beatIndexAt(beats, 12)].kind, "fault");
  assert.equal(beatIndexAt([], 3), -1);
});

test("a repeating walk folds into one loop beat, with its calls counted", () => {
  const events: SimEvent[] = [call(1, 0, "client", "engine", "loop")];
  let span = 2;
  for (let i = 0; i < 20; i++) {
    events.push(call(span, 1, "engine", "worker", "execute"), set(span, "worker", "state.n"), ret(span, 1, "engine", "worker", "execute"));
    span++;
    events.push(call(span, 1, "engine", "api", "publish"), ret(span, 1, "engine", "api", "publish"));
    span++;
  }
  const beats = deriveBeats(events, { areaOf });
  assert.equal(beats.length, 2);
  const loop = beats[1];
  assert.equal(loop.kind, "loop");
  assert.equal(loop.count, 20);
  assert.equal(loop.title, "Repeats 20 times: execute, publish");
  assert.equal(loop.collapsed, 20);
});

test("a fault is never folded away, even inside a repeating walk", () => {
  const events: SimEvent[] = [call(1, 0, "client", "engine", "loop")];
  let span = 2;
  for (let i = 0; i < 6; i++) {
    events.push(call(span, 1, "engine", "worker", "execute"));
    if (i === 3) events.push(ev("fault", { span, component: "worker", interface: "worker.execute", fault: "error", message: "x" }));
    events.push(ret(span, 1, "engine", "worker", "execute"));
    span++;
    events.push(call(span, 1, "engine", "api", "publish"), ret(span, 1, "engine", "api", "publish"));
    span++;
  }
  const beats = deriveBeats(events, { areaOf });
  assert.equal(beats.filter((b) => b.kind === "fault").length, 1);
});

test("a model with no areas folds at component crossings", () => {
  const beats = deriveBeats(faultedRun(), { areaOf: areaResolver(new Map()) });
  const crossings = beats.filter((b) => b.kind === "crossing");
  assert.ok(crossings.some((b) => b.iface === "router.route"), "api -> router is a crossing without areas");
});

test("a component outside the areas of a model with areas falls under Other", () => {
  assert.equal(areaOf("no-such"), "Other");
  assert.equal(areaOf("engine"), "core");
});

test("jump targets: first fault, first error, next state change", () => {
  const events = faultedRun();
  const j = jumpTargets(events);
  assert.equal(events[j.firstFault].type, "fault");
  assert.equal(events[j.firstError].type, "call.end");
  assert.equal(j.errors, 3);
  assert.deepEqual(j.stateChanges, [5], "writes to vars aren't state changes");
  assert.equal(nextStateChange(j, 0), 5);
  assert.equal(nextStateChange(j, 5), -1);
  assert.equal(openingCursor(j), j.firstFault);
  assert.equal(openingCursor({ firstFault: -1, firstError: 7 }), 7);
  assert.equal(openingCursor({ firstFault: -1, firstError: -1 }), 0);
});

test("store writes count as state changes", () => {
  const j = jumpTargets([ev("set", { component: "s", table: "rows", key: "file:///a.ts", new: 1 })]);
  assert.deepEqual(j.stateChanges, [0]);
});

test("stepping skips set and note only when they are hidden", () => {
  const events = faultedRun();
  assert.equal(stepTarget(events, 0, 1, false), 1);
  assert.equal(stepTarget(events, 0, 1, true), 2, "the vars set at 1 is hidden");
  assert.equal(stepTarget(events, 2, -1, true), 0);
  assert.equal(stepTarget(events, 0, -1, true), 0);
  assert.equal(stepTarget(events, events.length - 1, 1, true), events.length - 1);
  assert.equal(stepTarget(events, 0, 1, true, 3), 4, "three visible steps, past the hidden set");
});

test("weak mechanisms mark the beats that pass through them", () => {
  const events = faultedRun();
  const beats = deriveBeats(events, { areaOf });
  const weak = weakByInterface([
    { fidelity: "partial", interfaces: ["worker.execute", "sched.pick"] },
    { fidelity: "shell", interfaces: ["worker.execute"] },
    { fidelity: "modeled", interfaces: ["api.generate"] },
  ]);
  assert.equal(weak.get("worker.execute"), "shell", "the worst wins");
  assert.equal(weak.has("api.generate"), false);
  const marks = weakBeats(events, beats, weak);
  // The call to sched.pick is folded into the note it follows: the beat holding it gets the mark.
  const marked = beats.filter((b) => marks.has(b.id)).map((b: Beat) => b.kind);
  assert.deepEqual(marked, ["note", "crossing"]);
  assert.equal(marks.get(beats.findIndex((b) => b.iface === "worker.execute")), "shell");
  assert.equal(weakBeats(events, beats, new Map()).size, 0);
  assert.equal(worseFidelity("partial", "shell"), "shell");
  assert.equal(worseFidelity("shell", "partial"), "shell");
});

test("a stored run with a retry: beats, retries and spans from real trace data", () => {
  const run = fixture("envoy/runs/upstream-reset-retried.json");
  const events = run.trace ?? [];
  const beats = deriveBeats(events, { areaOf: (c) => c });
  assert.ok(beats.length > 0);
  assert.ok(beats.length < events.length, "a summary is shorter than its trace");
  assert.ok(beats.some((b) => b.kind === "fault"));
  assert.ok(beats.some((b) => b.kind === "retry"));
  assert.ok(jumpTargets(events).firstFault >= 0);
  assert.ok(calledInterfaces(events).size > 0);
});

test("a stored healthy run has nothing to jump to and opens at the start", () => {
  const events = fixture("envoy/runs/happy-path.json").trace ?? [];
  const j = jumpTargets(events);
  assert.equal(j.firstFault, -1);
  assert.equal(openingCursor(j), 0);
  assert.equal(deriveBeats(events, { areaOf: (c) => c }).some((b) => b.kind === "fault"), false);
});

test("an empty trace has no beats", () => {
  assert.deepEqual(deriveBeats([], { areaOf }), []);
});
