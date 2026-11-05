// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { TestResult } from "../../lib/api/types";
import { elapsedLabel, filterTests, keepTracesHint, outcomeOf, selfCheckLine, sortTests, testRows } from "./testlist.ts";

function res(scenario: string, over: Partial<TestResult> = {}): TestResult {
  return { scenario, name: "", passed: true, status: "ok", assertions: [], ...over };
}
const one = [{ expr: "a == 1", passed: true }];

test("selfCheckLine counts passes, never a bare all-pass", () => {
  assert.equal(selfCheckLine({ total: 1805, failed: 0 }), "1805 of 1805 self-checks pass.");
  assert.equal(selfCheckLine({ total: 10, failed: 3 }), "7 of 10 self-checks pass.");
});

test("outcomeOf says failed as expected only with a held expectation", () => {
  assert.equal(outcomeOf(res("a", { status: "error", assertions: one })), "failed-as-expected");
  assert.equal(outcomeOf(res("a", { status: "error" })), "pass");
  assert.equal(outcomeOf(res("a", { assertions: one })), "pass");
  assert.equal(outcomeOf(res("a", { status: "error", passed: false, assertions: one })), "fail");
  assert.equal(outcomeOf(res("a", { status: "aborted", assertions: one })), "pass");
});

test("filterTests searches names, ids, expressions, errors and group labels", () => {
  const all = [
    res("s1", { name: "Checkout retry" }),
    res("s2", { passed: false, error: "timed out" }),
    res("s3", { assertions: [{ expr: "summary.ok", passed: true }] }),
  ];
  const ids = (q: string, failed = false, labels?: (r: TestResult) => string) => filterTests(all, q, failed, labels).map((r) => r.scenario);
  assert.deepEqual(ids(""), ["s1", "s2", "s3"]);
  assert.deepEqual(ids("", true), ["s2"]);
  assert.deepEqual(ids("CHECKOUT retry"), ["s1"]);
  assert.deepEqual(ids("timed"), ["s2"]);
  assert.deepEqual(ids("summary.ok"), ["s3"]);
  assert.deepEqual(ids("billing", false, (r) => (r.scenario === "s3" ? "billing" : "core")), ["s3"]);
  assert.deepEqual(ids("s1", true), []);
});

test("sortTests keeps the model's order on ties and doesn't change its input", () => {
  const all = [res("b", { name: "B" }), res("c", { name: "A", passed: false }), res("a", { name: "C", assertions: one }), res("d", { name: "D", passed: false })];
  const ids = (by: Parameters<typeof sortTests>[1]) => sortTests(all, by).map((r) => r.scenario);
  assert.deepEqual(ids("model"), ["b", "c", "a", "d"]);
  assert.deepEqual(ids("failed"), ["c", "d", "b", "a"]);
  assert.deepEqual(ids("name"), ["c", "b", "a", "d"]);
  assert.deepEqual(ids("assertions"), ["a", "b", "c", "d"]);
  assert.equal(all[0].scenario, "b");
});

test("testRows groups: failures first, then largest, Other last, with order kept inside", () => {
  const all = [res("a1"), res("o1", { passed: false }), res("b1"), res("c1", { passed: false }), res("b2")];
  const group = (r: TestResult) => ({ a: "alpha", o: "Other", b: "beta", c: "gamma" })[r.scenario[0] as "a" | "o" | "b" | "c"];
  const rows = testRows(all, group, "Other");
  assert.deepEqual(rows.map((r) => r.key), ["group:gamma", "c1", "group:beta", "b1", "b2", "group:alpha", "a1", "group:Other", "o1"]);
  assert.deepEqual(rows[0], { kind: "group", key: "group:gamma", label: "gamma", total: 1, failed: 1 });
});

test("testRows without grouping is the results in order", () => {
  assert.deepEqual(testRows([res("x"), res("y")], null, "Other").map((r) => r.key), ["x", "y"]);
});

test("elapsedLabel", () => {
  assert.equal(elapsedLabel(0), "0 s");
  assert.equal(elapsedLabel(9500), "9 s");
  assert.equal(elapsedLabel(65000), "1 min 05 s");
});

test("keepTracesHint names the cost", () => {
  assert.match(keepTracesHint(1805), /Saves 1805 runs, one per scenario/);
  assert.match(keepTracesHint(undefined), /Saves one run per scenario/);
});
