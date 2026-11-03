// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Document, Flow } from "../api/types";
import { OTHER, ancestors, buildDocIndex, componentRows, defaultFlowGrouping, docIndex, flowMatches, groupFlows } from "./docindex.ts";

function doc(over: Partial<Document>): Document {
  return { schema_version: 1, components: [], interfaces: [], links: [], schemas: [], flows: [], scenarios: [], ...over };
}

const base = doc({
  components: [
    { id: "platform", attributes: { area: "core" } },
    { id: "api", parent: "platform" },
    { id: "store", parent: "platform", attributes: { owner: "data" } },
    { id: "cache", parent: "store" },
    { id: "web", attributes: { owner: "frontend" } },
    { id: "user" },
    { id: "loop-a", parent: "loop-b" },
    { id: "loop-b", parent: "loop-a" },
  ],
  interfaces: [
    { component: "api", name: "get" },
    { id: "store.put", component: "store", name: "put" },
    { component: "web", name: "page" },
  ],
  flows: [
    { id: "f1", name: "Read", tags: ["feature:reads"], entry: { caller: "user", interface: "api.get" } },
    { id: "f2", name: "Write", tags: ["writes", "feature:writes"], entry: { caller: "api", interface: "store.put" } },
    { id: "f3", name: "Browse", tags: ["ui"], entry: { caller: "user", interface: "web.page" } },
    { id: "f4", name: "No entry" },
  ],
  scenarios: [
    { id: "s1", flow: "f1" },
    { id: "s2", flow: "f1" },
    { id: "s3", steps: [{ flow: "f2" }] },
    { id: "s4" },
  ],
});

test("buildDocIndex maps ids, scenarios by flow and members", () => {
  const idx = buildDocIndex(base);
  assert.equal(idx.componentsById.get("store")?.parent, "platform");
  assert.equal(idx.interfacesById.get("api.get")?.name, "get");
  assert.equal(idx.interfacesById.get("store.put")?.component, "store");
  assert.deepEqual(idx.interfacesByComponent.get("api")?.map((i) => i.name), ["get"]);
  assert.deepEqual(idx.scenariosByFlow.get("f1")?.map((s) => s.id), ["s1", "s2"]);
  assert.deepEqual(idx.scenariosByFlow.get("f2")?.map((s) => s.id), ["s3"]);
  assert.deepEqual(idx.scenariosByFlow.get("")?.map((s) => s.id), ["s4"]);
  assert.deepEqual(idx.childrenByParent.get("platform")?.map((c) => c.id), ["api", "store"]);
  assert.deepEqual(idx.childrenByParent.get("")?.map((c) => c.id), ["platform", "user", "web"]);
});

test("top-level parent and inherited area", () => {
  const idx = buildDocIndex(base);
  assert.equal(idx.topLevel.get("cache"), "platform");
  assert.equal(idx.topLevel.get("platform"), "platform");
  assert.equal(idx.area.get("api"), "core");
  assert.equal(idx.area.get("store"), "data");
  assert.equal(idx.area.get("cache"), "data");
  assert.equal(idx.area.get("user"), undefined);
  // A parent cycle doesn't hang and still gets a top level.
  assert.ok(idx.topLevel.has("loop-a") && idx.topLevel.has("loop-b"));
  assert.deepEqual(ancestors(idx, "cache"), ["store", "platform"]);
});

test("docIndex is built once per document", () => {
  assert.equal(docIndex(base), docIndex(base));
  assert.notEqual(docIndex(base), docIndex(doc({})));
});

const keys = (flows: Flow[]) => flows.map((f) => f.id);

test("groupFlows by feature tag puts untagged flows in Other, last", () => {
  const g = groupFlows(base.flows, docIndex(base), "feature");
  assert.deepEqual(
    g.map((x) => [x.key, keys(x.flows)]),
    [
      ["reads", ["f1"]],
      ["writes", ["f2"]],
      [OTHER, ["f3", "f4"]],
    ],
  );
});

test("groupFlows by area uses the entered component, then the caller", () => {
  const g = groupFlows(base.flows, docIndex(base), "area");
  const m = Object.fromEntries(g.map((x) => [x.key, keys(x.flows)]));
  assert.deepEqual(m, { core: ["f1"], data: ["f2"], frontend: ["f3"], [OTHER]: ["f4"] });
});

test("groupFlows by top-level parent labels sections by component name", () => {
  const idx = docIndex(base);
  const g = groupFlows(base.flows, idx, "parent");
  assert.deepEqual(
    g.map((x) => [x.key, keys(x.flows)]),
    [
      ["platform", ["f1", "f2"]],
      ["web", ["f3"]],
      [OTHER, ["f4"]],
    ],
  );
});

test("defaultFlowGrouping prefers feature tags only when most flows have one", () => {
  assert.equal(defaultFlowGrouping(base.flows, docIndex(base)), "area");
  const tagged = doc({ ...base, flows: base.flows.map((f) => ({ ...f, tags: ["feature:x"] })) });
  assert.equal(defaultFlowGrouping(tagged.flows, docIndex(tagged)), "feature");
  const bare = doc({ components: [{ id: "a" }], flows: [{ id: "x", entry: { caller: "a", interface: "a.b" } }] });
  assert.equal(defaultFlowGrouping(bare.flows, docIndex(bare)), "parent");
});

test("flowMatches searches name, id and tags", () => {
  const f = base.flows[1];
  assert.ok(flowMatches(f, "write"));
  assert.ok(flowMatches(f, "F2"));
  assert.ok(flowMatches(f, "feature:writes"));
  assert.ok(!flowMatches(f, "read"));
  assert.ok(flowMatches(f, "  "));
});

test("componentRows: collapsed tree, expanded tree, filter and area grouping", () => {
  const idx = docIndex(base);
  const ids = (rows: ReturnType<typeof componentRows>) => rows.map((r) => `${"  ".repeat(r.depth)}${r.key}`);
  const collapsed = componentRows(idx, "tree", new Set(), "");
  assert.deepEqual(ids(collapsed), ["platform", "user", "web", "loop-a", "loop-b"]);
  assert.equal(collapsed[0].count, 3);
  assert.ok(collapsed[0].expandable && !collapsed[0].expanded);

  assert.deepEqual(ids(componentRows(idx, "tree", new Set(["platform"]), "")).slice(0, 3), ["platform", "  api", "  store"]);

  // Filtering opens the ancestors of matches and hides the rest.
  const filtered = componentRows(idx, "tree", new Set(), "cache");
  assert.deepEqual(ids(filtered), ["platform", "  store", "    cache"]);
  assert.deepEqual(filtered.map((r) => r.match), [false, false, true]);

  const byArea = componentRows(idx, "area", new Set(["area:data"]), "");
  assert.deepEqual(ids(byArea), ["area:core", "area:data", "  cache", "  store", "area:frontend", "area:Other"]);
  assert.equal(byArea.find((r) => r.key === "area:Other")?.count, 3);
});
