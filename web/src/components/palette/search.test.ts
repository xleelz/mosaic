// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Document } from "../../lib/api/types";
import { buildDocIndex } from "../../lib/model/docindex.ts";
import { documentEntries, mechanismEntries, pageEntries, rowWindow, scrollToRow, searchPalette } from "./search.ts";
import { globalAction } from "./shortcuts.ts";

function doc(over: Partial<Document>): Document {
  return { schema_version: 1, components: [], interfaces: [], links: [], schemas: [], flows: [], scenarios: [], ...over };
}

const sample = doc({
  components: [
    { id: "local-disk", name: "Local disk", kind: "datastore" },
    { id: "api", name: "Serving API", attributes: { area: "serving" } },
  ],
  interfaces: [{ component: "local-disk", name: "read", summary: "Reads weights" }, { id: "api.generate", component: "api", name: "generate" }],
  flows: [{ id: "generate", name: "Generate text", entry: { caller: "", interface: "api.generate" } }],
  scenarios: [
    { id: "s-healthy", name: "A request streams to completion", flow: "generate" },
    { id: "s-missing", name: "Weights missing on disk: load fails", steps: [{ flow: "generate" }], faults: [{ target: "local-disk.read", type: "unavailable" }] },
    { id: "s-disk-ok", name: "Disk read succeeds", flow: "generate" },
  ],
  configs: [{ id: "max_tokens", summary: "Upper bound on output" }],
  fixtures: [{ id: "two-replicas", name: "Two replicas" }],
});

const entries = [
  ...pageEntries([{ sub: "", label: "Overview" }, { sub: "map", label: "Map" }]),
  ...documentEntries(sample, buildDocIndex(sample)),
  ...mechanismEntries([{ id: "m.stream", area: "serving", kind: "pipeline", name: "Stream interval batching", citations: [], interfaces: [], fidelity: "absent", note: "No behavior reads it" }]),
];

const ids = (q: string) => searchPalette(entries, q).map((e) => e.id);

test("no query lists the pages", () => {
  assert.deepEqual(ids("  "), ["overview", "map"]);
});

test("each kind is found and navigates to its thing", () => {
  const first = (q: string) => searchPalette(entries, q)[0];
  assert.deepEqual([first("local disk").kind, first("local disk").sub, first("local disk").params], ["component", "map", { c: "local-disk" }]);
  const iface = first("local-disk.read");
  assert.deepEqual([iface.kind, iface.sub, iface.params], ["interface", "map", { c: "local-disk", i: "local-disk.read" }]);
  assert.deepEqual(first("Generate text").params, { flow: "generate" });
  assert.deepEqual(first("streams to completion").params, { scenario: "s-healthy", flow: "generate" });
  assert.deepEqual([first("max_tokens").kind, first("max_tokens").sub], ["config", "world"]);
  assert.deepEqual([first("two replicas").kind, first("two replicas").sub], ["fixture", "world"]);
  const m = first("stream interval");
  assert.deepEqual([m.kind, m.fidelity, m.sub, m.params], ["mechanism", "absent", "evidence", { q: "m.stream" }]);
});

test("a multi-step scenario takes its flow from a step", () => {
  assert.equal(searchPalette(entries, "s-missing")[0].params?.flow, "generate");
});

test("failure language finds the component and its fault scenario, not healthy ones", () => {
  const got = ids("local disk down");
  assert.deepEqual(got.slice(0, 2).sort(), ["local-disk", "s-missing"]);
  assert.ok(!got.includes("s-disk-ok"));
  assert.ok(!got.includes("s-healthy"));
});

test("a failure word alone only matches what literally contains it", () => {
  assert.ok(!ids("down").includes("local-disk"));
  assert.ok(ids("fails").includes("s-missing"));
});

test("a scenario is searchable by its fault's target", () => {
  assert.ok(ids("local-disk.read unavailable").includes("s-missing"));
});

test("exact beats prefix beats anywhere", () => {
  const list = [
    ...pageEntries([{ sub: "zz", label: "uses scheduler somewhere" }, { sub: "b", label: "scheduler policy" }, { sub: "a", label: "scheduler" }]),
  ];
  assert.deepEqual(searchPalette(list, "scheduler").map((e) => e.id), ["a", "b", "zz"]);
});

test("a large index stays fast", () => {
  const big = doc({
    components: Array.from({ length: 700 }, (_, i) => ({ id: `comp-${i}`, name: `Component ${i}`, summary: "Does a thing with state and retries".repeat(3) })),
    interfaces: Array.from({ length: 2800 }, (_, i) => ({ component: `comp-${i % 700}`, name: `call_${i}`, summary: "Handles a request and returns a response" })),
    flows: Array.from({ length: 600 }, (_, i) => ({ id: `flow-${i}`, name: `Flow ${i}` })),
    scenarios: Array.from({ length: 3400 }, (_, i) => ({ id: `scenario-${i}`, name: `A scenario about thing ${i}`, flow: `flow-${i % 600}`, faults: i % 7 ? [] : [{ target: `comp-${i % 700}.call_${i}`, type: "unavailable" }] })),
  });
  const all = documentEntries(big, buildDocIndex(big));
  assert.equal(all.length, 7500);
  const start = performance.now();
  for (const q of ["s", "scenario", "thing 33", "comp-12 down", "nothing matches this"]) searchPalette(all, q);
  // A guard against a change of complexity, loose enough for a loaded machine: well under 16 ms a query on a laptop.
  assert.ok(performance.now() - start < 500);
});

test("rowWindow renders only what's visible, however long the list", () => {
  assert.deepEqual(rowWindow(0, 380, 38, 8000), { start: 0, end: 14 });
  assert.deepEqual(rowWindow(3800, 380, 38, 8000), { start: 96, end: 114 });
  assert.deepEqual(rowWindow(0, 380, 38, 3), { start: 0, end: 3 });
  assert.deepEqual(rowWindow(38 * 7999, 380, 38, 8000), { start: 7995, end: 8000 });
});

test("scrollToRow moves only when the row is out of view", () => {
  assert.equal(scrollToRow(2, 0, 380, 38), 0);
  assert.equal(scrollToRow(10, 0, 380, 38), 38);
  assert.equal(scrollToRow(1, 76, 380, 38), 38);
});

test("global keys respect typing", () => {
  const k = (key: string, over = {}) => ({ key, metaKey: false, ctrlKey: false, altKey: false, ...over });
  assert.equal(globalAction(k("/"), false), "palette");
  assert.equal(globalAction(k("/"), true), null);
  assert.equal(globalAction(k("?"), false), "sheet");
  assert.equal(globalAction(k("?"), true), null);
  assert.equal(globalAction(k("k", { metaKey: true }), true), "palette");
  assert.equal(globalAction(k("K", { ctrlKey: true }), false), "palette");
  assert.equal(globalAction(k("k"), false), null);
  assert.equal(globalAction(k("/", { ctrlKey: true }), false), null);
});
