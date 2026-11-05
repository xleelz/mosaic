// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { SimEvent, SimulationRun } from "../api/types.ts";
import { deriveBeats } from "./beats.ts";
import { alignBeats, firstDivergence, runPath, stateChanges, stateDifferences } from "./compare.ts";

function fixture(path: string): SimulationRun {
  return JSON.parse(readFileSync(new URL(`../../../fixtures/${path}`, import.meta.url), "utf8")) as SimulationRun;
}

const healthy = fixture("envoy/runs/happy-path.json");
const faulted = fixture("envoy/runs/upstream-reset-retried.json");

test("a run doesn't diverge from itself", () => {
  assert.equal(firstDivergence(healthy.trace ?? [], healthy.trace ?? []), null);
});

test("two stored runs diverge at the first differing step, on both sides", () => {
  const a = healthy.trace ?? [];
  const b = faulted.trace ?? [];
  const d = firstDivergence(a, b);
  assert.ok(d);
  const pa = runPath(a);
  const pb = runPath(b);
  const i = pa.findIndex((p) => p.idx === d.a);
  assert.ok(i >= 0);
  assert.notEqual(pa[i].sig, pb[i].sig);
  assert.deepEqual(pa.slice(0, i).map((p) => p.sig), pb.slice(0, i).map((p) => p.sig));
});

test("set and note don't count as a divergence, and times don't either", () => {
  const start = { seq: 1, t: 0, type: "call.start", span: 1, interface: "a.b" } as SimEvent;
  const setE = { seq: 2, t: 0, type: "set", span: 1, path: "vars.x", new: 1 } as SimEvent;
  const end = { seq: 3, t: 5, type: "call.end", span: 1, interface: "a.b", ok: true } as SimEvent;
  assert.equal(firstDivergence([start, setE, end], [{ ...start, t: 9 }, { ...end, t: 99 }]), null);
});

test("one run ending first diverges where the other goes on", () => {
  const start = { seq: 1, t: 0, type: "call.start", span: 1, interface: "a.b" } as SimEvent;
  const end = { seq: 2, t: 5, type: "call.end", span: 1, interface: "a.b", ok: true } as SimEvent;
  assert.deepEqual(firstDivergence([start], [start, end]), { a: -1, b: 1 });
  assert.deepEqual(firstDivergence([start, end], [start]), { a: 1, b: -1 });
});

test("the same call failing is a divergence", () => {
  const start = { seq: 1, t: 0, type: "call.start", span: 1, interface: "a.b" } as SimEvent;
  const ok = { seq: 2, t: 5, type: "call.end", span: 1, interface: "a.b", ok: true } as SimEvent;
  const bad = { ...ok, ok: false, error: { code: "boom", message: "" } } as SimEvent;
  assert.deepEqual(firstDivergence([start, ok], [start, bad]), { a: 1, b: 1 });
});

test("alignment keeps the shared prefix together and marks the first differing row", () => {
  const areaOf = (c: string) => c;
  const a = healthy.trace ?? [];
  const b = faulted.trace ?? [];
  const ba = deriveBeats(a, { areaOf });
  const bb = deriveBeats(b, { areaOf });
  const rows = alignBeats(ba, bb, firstDivergence(a, b));
  const diverging = rows.filter((r) => r.diverges);
  assert.equal(diverging.length, 1);
  const at = rows.indexOf(diverging[0]);
  assert.ok(rows.slice(0, at).every((r) => r.same && r.a?.signature === r.b?.signature));
  assert.equal(rows.length, Math.max(ba.length, bb.length));
});

test("identical runs align fully with no divergence", () => {
  const areaOf = (c: string) => c;
  const beats = deriveBeats(healthy.trace ?? [], { areaOf });
  const rows = alignBeats(beats, beats, null);
  assert.ok(rows.every((r) => r.same && !r.diverges));
});

test("state changes walk to the leaves, and report additions and removals", () => {
  const ch = stateChanges(
    { engine: { dead: false, n: 1, deep: { a: 1 } }, gone: { x: 1 } },
    { engine: { dead: true, n: 1, deep: { a: 2 } }, added: { y: 2 } },
  );
  assert.deepEqual(ch.map((c) => c.path), ["added.y", "engine.dead", "engine.deep.a", "gone.x"]);
  assert.equal(ch[1].after, true);
  assert.equal(ch[0].before, undefined);
  assert.deepEqual(stateChanges({ a: { x: 1 } }, { a: { x: 1 } }), []);
  assert.deepEqual(stateDifferences({ a: { x: 1 } }, { a: { x: 2 } }).map((c) => [c.path, c.before, c.after]), [["a.x", 1, 2]]);
});
