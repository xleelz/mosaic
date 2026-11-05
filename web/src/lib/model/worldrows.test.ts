// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { configMatches, configRows, type ConfigItem } from "./worldrows.ts";

const item = (id: string, area: string, differs = false, summary?: string): ConfigItem => ({ config: { id, summary }, area, differs });
const items = [item("a", "engine"), item("b", "engine", true, "The batch size"), item("c", "api"), item("d", "Shared"), item("e", "Shared"), item("f", "Shared")];
const base = { query: "", differsOnly: false, groupByArea: true, open: new Set<string>(), last: "Shared" };

test("search needs every word, across any field", () => {
  const c = { id: "max-batch", type: "integer", summary: "The most requests", attributes: { key: "maxBatchSize" }, sources: [{ path: "vllm/config.py" }], tags: ["tuning"] };
  for (const q of ["", "max", "MOST requests", "maxbatchsize", "config.py", "tuning", "integer"]) assert.ok(configMatches(c, q), q);
  assert.ok(!configMatches(c, "most nope"));
});

test("areas go largest first with the shared one last, and start closed", () => {
  const { rows, areas, matches } = configRows(items, base);
  assert.deepEqual(areas, ["engine", "api", "Shared"]);
  assert.equal(matches, 6);
  assert.ok(rows.every((r) => r.type === "group"));
  const engine = rows[0];
  assert.ok(engine.type === "group" && engine.count === 2 && engine.differing === 1 && !engine.open);
});

test("an open area shows its configs", () => {
  const { rows } = configRows(items, { ...base, open: new Set(["api"]) });
  assert.deepEqual(rows.map((r) => r.key), ["area:engine", "area:api", "c", "area:Shared"]);
});

test("a search opens the areas with matches and hides the rest", () => {
  const { rows, matches } = configRows(items, { ...base, query: "batch" });
  assert.deepEqual(rows.map((r) => r.key), ["area:engine", "b"]);
  assert.equal(matches, 1);
});

test("differs only filters before grouping", () => {
  const { rows } = configRows(items, { ...base, differsOnly: true, open: new Set(["engine"]) });
  assert.deepEqual(rows.map((r) => r.key), ["area:engine", "b"]);
});

test("without grouping it's a flat list", () => {
  const { rows, areas } = configRows(items, { ...base, groupByArea: false });
  assert.equal(rows.length, 6);
  assert.deepEqual(areas, []);
  assert.ok(rows.every((r) => r.type === "config"));
});
