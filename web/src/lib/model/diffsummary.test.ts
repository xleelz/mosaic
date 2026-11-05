// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Change, Document } from "../api/types";
import { SHARED, componentArea, configArea } from "./areas.ts";
import { buildDocIndex } from "./docindex.ts";
import { changeAreaResolver, changeName, changedFields, citationsOnly, entityRows, kindsLine, summarizeDiff } from "./diffsummary.ts";

const added = (kind: string, id: string, after: object = {}): Change => ({ kind, id, change: "added", after: after as never });
const removed = (kind: string, id: string, before: object = {}): Change => ({ kind, id, change: "removed", before: before as never });
const modified = (kind: string, id: string, before: object, after: object): Change => ({ kind, id, change: "modified", before: before as never, after: after as never });

test("changedFields names the top-level fields that differ, ignoring key order", () => {
  assert.deepEqual(changedFields({ before: { a: 1, b: { x: 1, y: 2 }, c: 3 }, after: { a: 2, b: { y: 2, x: 1 }, d: 4 } }), ["a", "c", "d"]);
  assert.deepEqual(changedFields({ before: { a: 1 }, after: { a: 1 } }), []);
  assert.deepEqual(changedFields({ after: { a: 1 } }), []);
  assert.deepEqual(changedFields({ before: [1], after: [2] }), []);
});

test("citationsOnly sees through moved citations at any depth, and nothing else", () => {
  const steps = (line: number) => ({ behavior: [{ title: "t", source: { path: "a", line } }], sources: [{ path: "a", line }] });
  assert.ok(citationsOnly(modified("interface", "i", steps(1), steps(2))));
  assert.ok(!citationsOnly(modified("interface", "i", { summary: "a" }, { summary: "b" })));
  assert.ok(!citationsOnly(modified("interface", "i", { summary: "a", sources: [] }, { summary: "b", sources: [{ path: "x" }] })));
  assert.ok(!citationsOnly(added("interface", "i", steps(1))));
});

test("changeName only returns a name that adds something to the id", () => {
  assert.equal(changeName(added("flow", "f", { name: "A request" })), "A request");
  assert.equal(changeName(added("flow", "f", { name: "f" })), undefined);
  assert.equal(changeName(removed("component", "c", { name: "Gone" })), "Gone");
  assert.equal(changeName(added("flow", "f")), undefined);
  assert.equal(changeName(added("interface", "sched.step", { name: "step" })), undefined);
});

const areaByPrefix = (c: Change) => (c.id.startsWith("e-") ? "engine-core" : c.id.startsWith("a-") ? "api" : SHARED);

test("the summary counts per area, largest first and shared things last", () => {
  const changes = [
    added("component", "e-1"),
    added("interface", "e-2"),
    modified("interface", "e-3", { summary: "a" }, { summary: "b" }),
    removed("scenario", "a-1"),
    added("schema", "s-1"),
    added("schema", "s-2"),
    added("schema", "s-3"),
    added("schema", "s-4"),
  ];
  const s = summarizeDiff(changes, [], areaByPrefix);
  assert.deepEqual(
    { total: s.total, added: s.added, changed: s.changed, removed: s.removed },
    { total: 8, added: 6, changed: 1, removed: 1 },
  );
  assert.deepEqual(s.areas.map((a) => a.area), ["engine-core", "api", SHARED]);
  const e = s.areas[0];
  assert.deepEqual({ a: e.added, c: e.changed, r: e.removed, kinds: e.kinds }, { a: 2, c: 1, r: 0, kinds: { component: 1, interface: 2 } });
  assert.equal(e.changes.length, 3);
});

test("citation-only changes are counted apart, and not as changed", () => {
  const s = summarizeDiff([modified("interface", "e-1", { sources: [{ path: "a", line: 1 }] }, { sources: [{ path: "a", line: 2 }] })], [], areaByPrefix);
  assert.equal(s.changed, 0);
  assert.equal(s.citations, 1);
  assert.equal(s.areas[0].citations, 1);
  assert.equal(s.areas[0].changed, 0);
});

test("a flow counts once in total, once in each area it reaches, and by how it was found", () => {
  const changes = [added("component", "e-1"), added("interface", "e-2"), added("interface", "a-1")];
  const s = summarizeDiff(
    changes,
    [
      { flow: "f1", reasons: ["component:e-1", "interface:e-2", "interface:a-1"], basis: "traces" },
      { flow: "f2", reasons: ["interface:e-2"], basis: "static" },
      { flow: "f3", reasons: ["interface:unknown"] },
    ],
    areaByPrefix,
  );
  assert.equal(s.flowsAffected, 3);
  assert.equal(s.flowsExercised, 1);
  assert.equal(s.flowsStatic, 1);
  assert.equal(s.areas.find((a) => a.area === "engine-core")!.flowsAffected, 2);
  assert.equal(s.areas.find((a) => a.area === "api")!.flowsAffected, 1);
});

test("no changes is an empty summary", () => {
  const s = summarizeDiff([], [], areaByPrefix);
  assert.equal(s.total, 0);
  assert.deepEqual(s.areas, []);
});

const doc = {
  components: [
    { id: "engine", name: "Engine core", attributes: { area: "engine-core" } },
    { id: "sched", parent: "engine" },
    { id: "api", name: "API server" },
    { id: "route", parent: "api" },
    { id: "cfg-reader", attributes: { owner: "platform" }, sources: [{ path: "conf.py" }] },
  ],
  interfaces: [{ component: "sched", name: "step", sources: [{ path: "sched.py" }] }],
  flows: [
    { id: "gen", entry: { caller: "user", interface: "sched.step" } },
    { id: "nowhere", entry: { caller: "user", interface: "x" } },
  ],
  scenarios: [],
} as unknown as Document;
const idx = buildDocIndex(doc);
const areaOf = changeAreaResolver(doc, idx);

test("a component's area is the sidebar's, inherited, with the top-level component standing in", () => {
  assert.equal(componentArea(idx, "sched"), "engine-core");
  assert.equal(componentArea(idx, "route"), "API server");
  assert.equal(componentArea(idx, "unknown"), undefined);
});

test("each kind of entity finds its area", () => {
  assert.equal(areaOf(added("component", "sched")), "engine-core");
  assert.equal(areaOf(added("interface", "sched.step", { component: "sched" })), "engine-core");
  assert.equal(areaOf(added("interface", "route.get")), "API server", "from the id when the JSON says nothing");
  assert.equal(areaOf(added("link", "l", { from: "route", to: "sched" })), "API server");
  assert.equal(areaOf(added("flow", "gen")), "engine-core");
  assert.equal(areaOf(added("flow", "nowhere")), SHARED);
  assert.equal(areaOf(added("scenario", "s", { flow: "gen" })), "engine-core");
  assert.equal(areaOf(added("scenario", "s", { steps: [{ flow: "gen" }] })), "engine-core");
  assert.equal(areaOf(added("scenario", "s", { flow: "gone" })), SHARED);
  assert.equal(areaOf(added("schema", "S")), SHARED);
  assert.equal(areaOf(added("fixture", "w")), SHARED);
});

test("something the head no longer has still finds an area from its own JSON", () => {
  assert.equal(areaOf(removed("component", "gone", { attributes: { owner: "kernels" } })), "kernels");
  assert.equal(areaOf(removed("component", "gone", { parent: "sched" })), "engine-core");
  assert.equal(areaOf(removed("component", "gone")), SHARED);
  assert.equal(areaOf(removed("interface", "gone.x", { component: "sched" })), "engine-core");
  assert.equal(areaOf(removed("flow", "old", { entry: { interface: "sched.step" } })), "engine-core");
});

test("a config takes its own attribute, else the area of a component citing its file", () => {
  assert.equal(configArea(doc, idx, { attributes: { owner: "kernels" } }), "kernels");
  assert.equal(configArea(doc, idx, { attributes: { area: "a", owner: "b" } }), "a");
  assert.equal(configArea(doc, idx, { sources: [{ path: "sched.py" }] }), "engine-core");
  assert.equal(configArea(doc, idx, { sources: [{ path: "conf.py" }] }), "platform");
  assert.equal(configArea(doc, idx, { sources: [{ path: "elsewhere.py" }] }), SHARED);
  assert.equal(areaOf(added("config", "c", { sources: [{ path: "sched.py" }] })), "engine-core");
});

test("the entity list reads kinds in order with schemas late, and added first inside a kind", () => {
  const changes = [
    added("schema", "S"),
    modified("component", "b", { a: 1 }, { a: 2 }),
    added("component", "c"),
    added("component", "a"),
    removed("component", "z"),
    added("flow", "f"),
    added("mystery", "m"),
  ];
  const rows = entityRows(changes, { area: null, query: "", hideCitations: false });
  assert.deepEqual(rows.map((r) => r.key), ["kind:component", "component:a", "component:c", "component:b", "component:z", "kind:flow", "flow:f", "kind:schema", "schema:S", "kind:mystery", "mystery:m"]);
  const head = rows[0];
  assert.ok(head.type === "kind" && head.count === 4);
});

test("the entity list filters by area, search, and citation-only changes", () => {
  const moved = modified("interface", "e-2", { sources: [{ path: "a", line: 1 }] }, { sources: [{ path: "a", line: 2 }] });
  const changes = [added("flow", "e-1", { name: "A request" }), moved, added("flow", "a-1")];
  const s = summarizeDiff(changes, [], areaByPrefix);
  const engine = s.areas.find((a) => a.area === "engine-core")!;
  assert.deepEqual(entityRows(changes, { area: engine, query: "", hideCitations: true }).map((r) => r.key), ["kind:flow", "flow:e-1"]);
  assert.deepEqual(entityRows(changes, { area: null, query: "REQUEST", hideCitations: false }).map((r) => r.key), ["kind:flow", "flow:e-1"]);
  assert.deepEqual(entityRows(changes, { area: null, query: "nope", hideCitations: false }), []);
});

test("kindsLine lists the largest kinds and counts the rest", () => {
  assert.equal(kindsLine({ scenario: 233, interface: 181, component: 41 }), "233 scenarios, 181 interfaces, 41 components");
  assert.equal(kindsLine({ schema: 1, flow: 2 }), "2 flows, 1 schema");
  assert.equal(kindsLine({ a: 4, b: 3, c: 2, d: 1 }, 2), "4 as, 3 bs, and 2 more kinds");
  assert.equal(kindsLine({}), "");
});
