// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { EvidenceMechanism, MechanismFidelity, MechanismGateStatus } from "../../lib/api/types";
import {
  blindFigure,
  filterMechanisms,
  gateDisagrees,
  kindsOf,
  measuredNote,
  parseCitation,
  percent,
  searchWords,
  summarizeAreas,
  summarizeGate,
} from "./mechanisms.ts";

function mech(over: Partial<EvidenceMechanism> & { id: string }): EvidenceMechanism {
  return { area: "core", kind: "loop", name: over.id, citations: [], interfaces: [], fidelity: "modeled", ...over };
}

const none = { fidelities: new Set<MechanismFidelity>(), kind: "", area: "", query: "", disagreeOnly: false };

test("gateDisagrees follows the rule of check --mechanisms, both ways", () => {
  const cases: [MechanismFidelity, MechanismGateStatus | undefined, boolean][] = [
    ["modeled", "ok", false],
    ["modeled", "weak", true],
    ["modeled", "shell", true],
    ["modeled", "uncovered", true],
    ["modeled", "missing", true],
    ["partial", "ok", false],
    ["partial", "weak", false],
    ["partial", "shell", true],
    ["shell", "shell", false],
    ["shell", "uncovered", false],
    ["shell", "ok", true],
    ["shell", "weak", true],
    ["shell", "missing", true],
    ["absent", "missing", false],
    ["absent", "ok", true],
    ["absent", "uncovered", true],
    ["modeled", "skipped", false],
    ["absent", "skipped", false],
    ["modeled", undefined, false],
  ];
  for (const [f, g, want] of cases) assert.equal(gateDisagrees(f, g), want, `${f}/${g}`);
});

test("parseCitation reads a path, a line and a range", () => {
  assert.deepEqual(parseCitation("a/b.go"), { path: "a/b.go" });
  assert.deepEqual(parseCitation("a/b.go:12"), { path: "a/b.go", line: 12 });
  assert.deepEqual(parseCitation("a/b.go:12-40"), { path: "a/b.go", line: 12, end_line: 40 });
  assert.deepEqual(parseCitation(" c:/odd:name.py:3 "), { path: "c:/odd:name.py", line: 3 });
});

test("filterMechanisms keeps the list's order and applies every filter", () => {
  const items = [
    mech({ id: "z.first", fidelity: "absent", kind: "sweep", area: "z", note: "Reaper grace period" }),
    mech({ id: "a.second", fidelity: "modeled", kind: "loop", area: "a", gate_status: "shell" }),
    mech({ id: "a.third", fidelity: "partial", kind: "sweep", area: "a", citations: ["x/reaper.go:3"] }),
  ];
  const ids = (f: Partial<typeof none>) => filterMechanisms(items, { ...none, ...f }).map((m) => m.id);
  assert.deepEqual(ids({}), ["z.first", "a.second", "a.third"]);
  assert.deepEqual(ids({ fidelities: new Set<MechanismFidelity>(["partial", "absent"]) }), ["z.first", "a.third"]);
  assert.deepEqual(ids({ kind: "sweep" }), ["z.first", "a.third"]);
  assert.deepEqual(ids({ area: "a" }), ["a.second", "a.third"]);
  assert.deepEqual(ids({ disagreeOnly: true }), ["a.second"]);
  assert.deepEqual(ids({ query: "REAPER" }), ["z.first", "a.third"]);
  assert.deepEqual(ids({ query: "reaper grace" }), ["z.first"]);
  assert.deepEqual(ids({ query: "reaper", kind: "sweep", area: "a" }), ["a.third"]);
  assert.deepEqual(searchWords("  a  B "), ["a", "b"]);
});

test("summarizeAreas keeps the list's area order and counts per fidelity", () => {
  const out = summarizeAreas([
    mech({ id: "1", area: "z", fidelity: "absent" }),
    mech({ id: "2", area: "a", fidelity: "modeled", gate_status: "shell" }),
    mech({ id: "3", area: "z", fidelity: "shell", gate_status: "ok" }),
    mech({ id: "4", area: "z", fidelity: "absent" }),
  ]);
  assert.deepEqual(out.map((s) => s.area), ["z", "a"]);
  assert.deepEqual(out[0].counts, { modeled: 0, partial: 0, shell: 1, absent: 2, total: 3 });
  assert.equal(out[0].disagreements, 1);
  assert.equal(out[1].disagreements, 1);
});

test("summarizeGate leaves skipped and unmeasured out of the measured count", () => {
  const s = summarizeGate([
    mech({ id: "1", gate_status: "ok" }),
    mech({ id: "2", gate_status: "weak" }),
    mech({ id: "3", gate_status: "shell" }),
    mech({ id: "4", gate_status: "skipped" }),
    mech({ id: "5" }),
  ]);
  assert.deepEqual(s, { measured: 3, ok: 1, weak: 1, skipped: 1, unmeasured: 1, disagreements: 2 });
});

test("kindsOf is sorted and unique", () => {
  assert.deepEqual(kindsOf([mech({ id: "1", kind: "z" }), mech({ id: "2", kind: "a" }), mech({ id: "3", kind: "z" })]), ["a", "z"]);
});

test("percent never rounds a real share to 0% or 100%", () => {
  assert.equal(percent(30, 100), "30%");
  assert.equal(percent(1, 900), "<1%");
  assert.equal(percent(899, 900), ">99%");
  assert.equal(percent(0, 10), "0%");
  assert.equal(percent(10, 10), "100%");
  assert.equal(percent(0, 0), "n/a");
});

test("measuredNote says when the figure belongs to another revision", () => {
  assert.equal(measuredNote(3, "3"), "measured on r3");
  assert.equal(measuredNote(2, "3"), "measured on r2, not re-measured");
  assert.equal(measuredNote(2, "draft"), "measured on r2, not re-measured");
});

test("blindFigure is null without steps", () => {
  const blind = { measured_on_revision: 1, steps_passed: 3, steps_total: 10, cases_passed: 0, cases_total: 0, oracle_passed: 0, oracle_total: 0 };
  assert.equal(blindFigure(blind), "Blind benchmark: 30% of steps");
  assert.equal(blindFigure({ ...blind, steps_total: 0 }), null);
  assert.equal(blindFigure(undefined), null);
});
