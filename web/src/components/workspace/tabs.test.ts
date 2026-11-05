// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { TAB_GROUPS, activeTab, isMapQuery, routeSegment } from "./tabs.ts";

test("the tabs read Overview Map Flows Runs, then Evidence History, with a slot left", () => {
  assert.deepEqual(TAB_GROUPS.map((g) => g.map((t) => t.label)), [["Overview", "Map", "Flows", "Runs"], ["Evidence", "History"], []]);
});

test("every older route lights a tab", () => {
  const cases: [string, string][] = [
    ["", "Overview"],
    ["map", "Map"],
    ["world", "Map"],
    ["flows", "Flows"],
    ["simulate", "Runs"],
    ["runs", "Runs"],
    ["evidence", "Evidence"],
    ["tests", "Evidence"],
    ["explore", "Evidence"],
    ["revisions", "History"],
    ["commits", "History"],
  ];
  for (const [seg, label] of cases) assert.equal(activeTab(seg)?.label, label, seg);
  assert.equal(activeTab("nope"), undefined);
});

test("routeSegment takes the first segment under the base", () => {
  assert.equal(routeSegment("/o/x", "/o/x"), "");
  assert.equal(routeSegment("/o/x/runs/abc", "/o/x"), "runs");
});

test("older map links are recognised, and rev alone isn't one", () => {
  assert.equal(isMapQuery(["c"]), true);
  assert.equal(isMapQuery(["rev", "commit"]), true);
  assert.equal(isMapQuery(["rev"]), false);
  assert.equal(isMapQuery([]), false);
});
