// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Document } from "../api/types";
import { buildCitationIndex, citationIndex, citationsOf, fileCoverage, lineCount, type Citation } from "./citations.ts";

const doc = {
  components: [{ id: "sched", name: "Scheduler", summary: "Decides each step's batch", sources: [{ path: "a.py", line: 10, end_line: 20 }] }],
  interfaces: [
    {
      component: "sched",
      name: "step",
      sources: [{ path: "a.py", line: 15, end_line: 30 }],
      behavior: [{ title: "Pick a batch", source: { path: "a.py", line: 40 }, set: { source: { path: "a.py", line: 98 } }, then: [{ title: "Nested", source: { path: "b.py", line: 2 } }] }],
    },
  ],
  links: [{ id: "l", from: "sched", to: "x", label: "calls", sources: [{ path: "c.py" }] }],
  flows: [{ id: "f", name: "A request", sources: [{ path: "a.py", line: 1 }], steps: [{ component: "sched", title: "Schedules", source: { path: "a.py", line: 2 } }] }],
  configs: [{ id: "max-batch", summary: "The most in a batch", sources: [{ path: "a.py", line: 50, repo: "other/repo" }] }],
  fixtures: [{ id: "w", state: { sched: { source: { path: "a.py", line: 99 } } } }],
} as unknown as Document;

test("the index finds citations on every entity, in nested behavior steps too", () => {
  const idx = buildCitationIndex(doc);
  assert.deepEqual(
    idx.get("a.py")!.map((c) => `${c.kind}:${c.id}:${c.source.line}`),
    ["component:sched:10", "interface:sched.step:15", "interface:sched.step:40", "flow:f:1", "flow:f:2", "config:max-batch:50"],
  );
  assert.equal(idx.get("b.py")![0].claim, "Nested");
  assert.equal(idx.get("c.py")![0].kind, "link");
});

test("state values aren't citations, even when they look like one", () => {
  const lines = buildCitationIndex(doc).get("a.py")!.map((c) => c.source.line);
  assert.ok(!lines.includes(99), "fixture state");
  assert.ok(!lines.includes(98), "a behavior's set");
});

test("a claim uses the model's words", () => {
  const a = buildCitationIndex(doc).get("a.py")!;
  assert.equal(a[0].claim, "Decides each step's batch");
  assert.equal(a[2].claim, "Pick a batch");
  assert.equal(a[4].claim, "Schedules");
});

test("citationsOf sorts by line and separates repos", () => {
  assert.deepEqual(citationsOf(doc, "a.py").map((c) => c.source.line), [1, 2, 10, 15, 40, 50]);
  assert.equal(citationsOf(doc, "a.py", "other/repo").length, 6, "a source without a repo counts as the model's");
  assert.equal(citationsOf(doc, "a.py", "third/repo").length, 5);
  assert.deepEqual(citationsOf(doc, "nope.py"), []);
});

test("the index is built once per document", () => {
  assert.equal(citationIndex(doc), citationIndex(doc));
});

const cite = (line?: number, end_line?: number, id = "x"): Citation => ({ kind: "component", id, claim: "", source: { path: "a", line, end_line } });

test("coverage counts overlapping ranges once", () => {
  const c = fileCoverage([cite(10, 20), cite(15, 30), cite(40), cite(5, 8, "y")], 100);
  assert.deepEqual(c, { citations: 4, entities: 2, citedLines: 26, totalLines: 100, wholeFile: 0 });
});

test("coverage handles nested ranges, the file's end, and citations with no line", () => {
  assert.equal(fileCoverage([cite(1, 50), cite(10, 20)], 100).citedLines, 50);
  assert.equal(fileCoverage([cite(95, 500)], 100).citedLines, 6);
  assert.equal(fileCoverage([cite(500)], 100).citedLines, 1);
  const whole = fileCoverage([cite()], 100);
  assert.equal(whole.citedLines, 0);
  assert.equal(whole.wholeFile, 1);
});

test("a final newline doesn't count as a line", () => {
  assert.equal(lineCount(""), 0);
  assert.equal(lineCount("a"), 1);
  assert.equal(lineCount("a\nb\n"), 2);
  assert.equal(lineCount("a\nb"), 2);
});
