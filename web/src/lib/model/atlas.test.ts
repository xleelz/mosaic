// Run with `pnpm test`. Checks the Atlas rules on small models, and on real exported models when
// they're on disk: sizes are the point, so the box rule is checked on every reachable view.
// ATLAS_MODELS adds more model files (colon separated), for models that stay out of the repo.

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { Component, Document, EvidenceMechanism, Graph, GraphEdge, Interface } from "../api/types";
import {
  ATLAS_MIN_COMPONENTS,
  ENTRY_PLACE,
  EXTERNAL_PLACE,
  MAX_ACTORS,
  MAX_BOXES,
  ROOT_SCOPE,
  allScopes,
  atlasEligible,
  buildAtlas,
  buildView,
  edgeBudget,
  edgeWidth,
  fitItems,
  matchCounts,
  parseScope,
  sameScope,
  scopeFor,
  scopeKey,
  scopeParams,
  thresholdEdges,
  type AtlasEdge,
} from "./atlas.ts";
import { buildCallIndex, faultComponent, faultScenarios, flowReach, stateWriters } from "./atlasFlows.ts";
import { boxFidelity, dataDecor, dataForBox, faultsForBox, failureDecor, flowDecor, parseLens, placeMechanisms, tintStep } from "./atlasLens.ts";
import { buildDocIndex } from "./docindex.ts";

function doc(over: Partial<Document>): Document {
  return { schema_version: 1, components: [], interfaces: [], links: [], schemas: [], flows: [], scenarios: [], ...over };
}

/** The call graph mosaicd derives, from the same behaviors: one edge per component pair. */
function graphOf(d: Document): Graph {
  const idx = buildDocIndex(d);
  const calls = buildCallIndex(d, idx);
  const pairs = new Map<string, GraphEdge>();
  for (const [from, targets] of calls.calls) {
    const a = idx.interfacesById.get(from)!.component;
    for (const t of targets) {
      const b = idx.interfacesById.get(t)!.component;
      if (a === b) continue;
      const id = `calls:${a}->${b}`;
      const e = pairs.get(id) ?? { id, from: a, to: b, kind: "calls", derived: true, interfaces: [] };
      if (!e.interfaces!.includes(t)) e.interfaces!.push(t);
      pairs.set(id, e);
    }
  }
  return {
    nodes: d.components.map((c) => ({
      id: c.id,
      name: c.name || c.id,
      kind: c.kind,
      parent: c.parent,
      layer: c.layer,
      summary: c.summary,
      interfaces: (idx.interfacesByComponent.get(c.id) ?? []).map((i) => i.id || `${i.component}.${i.name}`),
      leaf: !(idx.childrenByParent.get(c.id)?.length),
      stateful: !!c.state,
    })),
    edges: Array.from(pairs.values()),
  };
}

function atlasOf(d: Document) {
  const idx = buildDocIndex(d);
  return { idx, m: buildAtlas(d, graphOf(d), idx) };
}

function comp(id: string, over: Partial<Component> = {}): Component {
  return { id, name: id, ...over };
}

function iface(component: string, name: string, calls: string[] = []): Interface {
  return { id: `${component}.${name}`, component, name, behavior: calls.map((call) => ({ call })) };
}

/** Two areas, with actors, a large part, a stray, and a small role mix. */
function small(): Document {
  const components: Component[] = [
    comp("user", { kind: "client" }),
    comp("hub", { kind: "external", attributes: { owner: "core" } }),
    comp("core", { kind: "service", summary: "The core. It does things.", attributes: { owner: "core" } }),
    comp("stray", { kind: "module", attributes: { owner: "core" } }),
    comp("lonely", { kind: "module" }),
    comp("edge", { kind: "service", summary: "The edge.", attributes: { owner: "edge" } }),
  ];
  for (let i = 0; i < 12; i++) components.push(comp(`m${i}`, { parent: "core", kind: "module" }));
  return doc({
    components,
    interfaces: [
      iface("edge", "in", ["core.do"]),
      iface("core", "do", ["m0.x", "hub.get", "m1.x"]),
      iface("m0", "x", ["m1.x"]),
      iface("m1", "x", []),
      iface("hub", "get"),
      iface("stray", "s", ["edge.in"]),
    ],
    flows: [{ id: "f1", entry: { caller: "user", interface: "edge.in" } }],
    scenarios: [{ id: "s1", flow: "f1", faults: [{ target: "m1.x", type: "error" }] }, { id: "s2", flow: "f1", faults: [{ target: "core", type: "unavailable" }] }],
  });
}

test("eligibility: enough components, and an area on most of them", () => {
  assert.equal(atlasEligible(buildDocIndex(small())), false);
  const many = (attrs: boolean) =>
    doc({ components: Array.from({ length: ATLAS_MIN_COMPONENTS }, (_, i) => comp(`c${i}`, attrs ? { attributes: { area: i % 2 ? "a" : "b" } } : {})) });
  assert.equal(atlasEligible(buildDocIndex(many(true))), true);
  assert.equal(atlasEligible(buildDocIndex(many(false))), false);
});

test("places partition the components: actors on the edge, the rest in an area or other", () => {
  const { m } = atlasOf(small());
  assert.equal(m.placeOf.get("user"), ENTRY_PLACE);
  assert.equal(m.placeOf.get("hub"), EXTERNAL_PLACE);
  assert.equal(m.placeOf.get("m3"), "core");
  assert.equal(m.placeOf.get("lonely"), "Other");
  const inAreas = m.areas.reduce((s, a) => s + a.parts, 0);
  const actors = [ENTRY_PLACE, EXTERNAL_PLACE].reduce((s, p) => s + (m.roots.get(p) ?? []).reduce((t, r) => t + m.size.get(r)!, 0), 0);
  assert.equal(inAreas + actors, m.nodes.size);
  assert.equal(m.areas.at(-1)!.key, "Other");
});

test("opening view: an area box each, with role and counts, actors on the edge", () => {
  const { m } = atlasOf(small());
  const v = buildView(m, ROOT_SCOPE);
  const core = v.boxes.find((b) => b.id === "area:core")!;
  assert.equal(core.parts, 14);
  assert.equal(core.detail, "The core");
  assert.equal(core.flows, 1);
  assert.deepEqual(v.boxes.filter((b) => b.type === "actor").map((b) => [b.component, b.edge]), [["user", "start"], ["hub", "end"]]);
  assert.ok(v.edges.some((e) => e.from === "c:user" || e.to === "c:hub"));
});

test("entering an area: a breadcrumb, neighbors as labeled stubs, strays under other", () => {
  const { m } = atlasOf(small());
  const v = buildView(m, { place: "core" });
  assert.deepEqual(v.crumbs.map((c) => c.label), ["Map", "core"]);
  const stubs = v.boxes.filter((b) => b.type === "stub").map((b) => b.label).sort();
  assert.deepEqual(stubs, ["from edge", "to edge", "to hub"]);
  const other = v.boxes.find((b) => b.id === "other:core")!;
  assert.equal(other.label, "other (1)");
  assert.deepEqual(other.enter, { place: "core", rest: true });
  // The stray keeps its calls, through the group.
  assert.ok(v.edges.some((e) => e.from === "other:core" && e.to === "stub:out:area:edge"));
});

test("a stray keeps its own box when selected, so the selection isn't lost", () => {
  const { m } = atlasOf(small());
  assert.deepEqual(scopeFor(m, "stray"), { place: "core", rest: true });
  const v = buildView(m, { place: "core" }, { pin: ["stray"] });
  assert.ok(v.boxes.some((b) => b.component === "stray"));
  assert.ok(!v.boxes.some((b) => b.id === "other:core"));
});

test("a level with one part opens it in place, keeping that part selectable", () => {
  const components = [comp("only", { kind: "service", attributes: { area: "a" } }), ...Array.from({ length: 12 }, (_, i) => comp(`k${i}`, { parent: "only" })), comp("z", { attributes: { area: "b" } })];
  const { m } = atlasOf(doc({ components, interfaces: [iface("only", "go", ["k1.x"]), iface("k1", "x")] }));
  const v = buildView(m, { place: "a" });
  assert.equal(v.boxes.filter((b) => b.type === "component").length, 12);
  assert.equal(v.boxes.find((b) => b.type === "self")!.component, "only");
  assert.deepEqual(v.crumbs.map((c) => c.label), ["Map", "a"]);
  assert.ok(buildView(m, scopeFor(m, "only"), { pin: ["only"] }).boxes.some((b) => b.component === "only"));
});

test("a component's own interfaces get a box inside it; its calls to members don't draw", () => {
  const { m } = atlasOf(small());
  const v = buildView(m, { place: "core", parent: "core" });
  const self = v.boxes.find((b) => b.type === "self")!;
  assert.equal(self.component, "core");
  assert.ok(!v.edges.some((e) => e.from === self.id && e.to === "c:m0"));
  assert.ok(v.edges.some((e) => e.from === "stub:in:area:edge" && e.to === self.id));
  assert.deepEqual(v.crumbs.map((c) => c.label), ["Map", "core", "core"]);
});

/** One place with `n` flat parts. */
function flat(n: number, kinds: string[]) {
  const components = Array.from({ length: n }, (_, i) => comp(`p${String(i).padStart(3, "0")}`, { kind: kinds[i % kinds.length], attributes: { area: "a" } }));
  return atlasOf(doc({ components }));
}

test("40-box rule: over budget groups by role and says how many", () => {
  const { m } = flat(100, ["function", "module", "router"]);
  const v = buildView(m, { place: "a" });
  assert.ok(v.boxes.length <= MAX_BOXES);
  assert.deepEqual(v.boxes.map((b) => b.label), ["function (34)", "module (33)", "router (33)"]);
  assert.equal(v.boxes.reduce((s, b) => s + b.parts, 0), 100);
  const inner = buildView(m, v.boxes[0].enter!);
  assert.equal(inner.boxes.length, 34);
  assert.deepEqual(inner.crumbs.map((c) => c.label), ["Map", "a", "function"]);
});

test("40-box rule: one role falls back to the heaviest, then 'and N more'", () => {
  const { m } = flat(78, ["module"]);
  const v = buildView(m, { place: "a" });
  assert.equal(v.boxes.length, MAX_BOXES);
  const more = v.boxes.at(-1)!;
  assert.equal(more.label, "and 39 more");
  assert.equal(more.more!.length, 39);
  assert.equal(v.boxes.reduce((s, b) => s + b.parts, 0), 78);
});

test("40-box rule: parts holding others stay visible, since they're the next parent", () => {
  const components = Array.from({ length: 60 }, (_, i) => comp(`p${i}`, { kind: "module", attributes: { area: "a" } }));
  for (let i = 0; i < 5; i++) for (let j = 0; j < 3; j++) components.push(comp(`p${i}-k${j}`, { parent: `p${i}`, kind: "module" }));
  const { m } = atlasOf(doc({ components }));
  const v = buildView(m, { place: "a" });
  assert.ok(v.boxes.length <= MAX_BOXES);
  for (let i = 0; i < 5; i++) assert.ok(v.boxes.some((b) => b.component === `p${i}`));
  assert.equal(v.boxes.reduce((s, b) => s + b.parts, 0), 75);
});

test("40-box rule: a pinned part keeps its box, wherever it would have been grouped", () => {
  const { m } = flat(100, ["module"]);
  const v = buildView(m, { place: "a" }, { pin: ["p099"] });
  assert.ok(v.boxes.length <= MAX_BOXES);
  assert.equal(v.repOf.get("p099"), "c:p099");
  assert.equal(v.boxes.reduce((s, b) => s + b.parts, 0), 100);
  const grouped = fitItems(m, { place: "a" }, m.roots.get("a")!, 10, new Set(["p099"]));
  assert.equal(grouped.length, 10);
  assert.equal(grouped[0].component, "p099");
});

test("the opening view folds actors over the cap, and every actor stays reachable", () => {
  const components = Array.from({ length: 20 }, (_, i) => comp(`x${i}`, { kind: "external" }));
  components.push(comp("a1", { attributes: { area: "a" } }));
  const { m } = atlasOf(doc({ components }));
  const v = buildView(m, ROOT_SCOPE, { pin: ["x19"] });
  const ext = v.boxes.filter((b) => b.edge === "end");
  assert.equal(ext.length, MAX_ACTORS);
  assert.ok(ext.some((b) => b.component === "x19"));
  const more = ext.at(-1)!;
  assert.equal(more.label, `and ${20 - (MAX_ACTORS - 1)} more`);
  assert.deepEqual(more.enter, { place: EXTERNAL_PLACE });
});

test("thresholding: heaviest first, each box keeps its strongest, order doesn't matter", () => {
  const edges: AtlasEdge[] = [];
  for (let a = 0; a < 13; a++) for (let b = 0; b < 13; b++) if (a !== b && (a * b) % 2 === 0) edges.push({ id: `b${a}->b${b}`, from: `b${a}`, to: `b${b}`, weight: 200 - a * b, emits: false, strong: false });
  const out = thresholdEdges(edges, 13);
  const strong = out.filter((e) => e.strong);
  assert.equal(out.length, edges.length);
  assert.ok(strong.length >= edgeBudget(13) && strong.length <= edgeBudget(13) + 13);
  for (let a = 0; a < 13; a++) assert.ok(strong.some((e) => e.from === `b${a}` || e.to === `b${a}`), `b${a}`);
  assert.deepEqual(thresholdEdges([...edges].reverse(), 13), out);
});

test("edge width grows with call count, within bounds", () => {
  assert.equal(edgeWidth(1, 1), 1.25);
  assert.ok(edgeWidth(10, 400) < edgeWidth(100, 400));
  assert.equal(edgeWidth(400, 400), 6);
});

test("scopes round-trip through URL values; unknown ones fall back", () => {
  const { m } = atlasOf(small());
  for (const s of [{ place: "core" }, { place: "core", parent: "core" }, { place: "core", rest: true }, { place: "edge", role: "service" }]) {
    assert.ok(sameScope(parseScope(m, scopeParams(s)), s), scopeKey(s));
  }
  assert.ok(sameScope(parseScope(m, { area: "gone" }), ROOT_SCOPE));
  assert.ok(sameScope(parseScope(m, { area: "edge", in: "core" }), { place: "edge" }));
});

test("a group inside an area with one top-level part opens to its parts, not an empty view", () => {
  const components: Component[] = [comp("only", { kind: "service", attributes: { owner: "core" } })];
  for (let i = 0; i < 60; i++) components.push(comp(`m${i}`, { parent: "only", kind: i % 2 ? "module" : "queue", attributes: { owner: "core" } }));
  const { m } = atlasOf(doc({ components }));
  for (const s of allScopes(m)) {
    if (s.place) assert.ok(buildView(m, s).boxes.some((b) => b.type !== "stub"), scopeKey(s));
  }
  const group = buildView(m, { place: "core" }).boxes.find((b) => b.id === "role:module");
  assert.deepEqual(group?.enter, { place: "core", parent: "only", role: "module" });
});

test("selecting navigates: scopeFor lands on a view drawing the component", () => {
  const { m } = atlasOf(small());
  for (const id of m.nodes.keys()) {
    const v = buildView(m, scopeFor(m, id), { pin: [id] });
    assert.ok(v.boxes.some((b) => b.component === id), id);
  }
});

test("filter counts matches per box", () => {
  const { m } = atlasOf(small());
  const v = buildView(m, ROOT_SCOPE);
  assert.deepEqual(matchCounts(v, new Set(["m0", "m1", "edge"])), new Map([["area:core", 2], ["area:edge", 1]]));
});

test("static calls: literals inside a dynamic target count, unknown ones don't", () => {
  const d = doc({
    components: [comp("a"), comp("b"), comp("c")],
    interfaces: [
      { id: "a.go", component: "a", name: "go", behavior: [{ if: "x", then: [{ call: "= x ? 'b.one' : 'c.two'" }], else: [{ call: "= input.who" }] }] },
      { id: "b.one", component: "b", name: "one", behavior: [{ set: { "state.n": 1 } }] },
      { id: "c.two", component: "c", name: "two", store: { table: "t", op: "get" } },
      { id: "c.put", component: "c", name: "put", store: { table: "t", op: "put" } },
    ],
  });
  const idx = buildDocIndex(d);
  const calls = buildCallIndex(d, idx);
  assert.deepEqual(calls.calls.get("a.go"), ["b.one", "c.two"]);
  assert.deepEqual(Array.from(calls.writes).sort(), ["b.one", "c.put"]);
  assert.deepEqual(stateWriters(["b"], calls, idx).get("b"), ["a", "b"]);
  const reach = flowReach({ id: "f", entry: { caller: "a", interface: "a.go" } }, calls, idx);
  assert.deepEqual(Array.from(reach.components).sort(), ["a", "b", "c"]);
});

test("failure lens counts each scenario once per box, and lists them", () => {
  const d = small();
  const { idx, m } = atlasOf(d);
  const faults = faultScenarios(d, idx);
  assert.equal(faultComponent("m1.x", idx), "m1");
  const v = buildView(m, ROOT_SCOPE);
  assert.equal(failureDecor(v, faults).counts.get("area:core"), 2);
  assert.deepEqual(faultsForBox(v.boxes.find((b) => b.id === "area:core")!, faults).map((s) => s.id).sort(), ["s1", "s2"]);
  assert.equal(failureDecor(v, faults).counts.has("area:edge"), false);
});

test("flow lens lights the path, through stubs when it leaves the view", () => {
  const d = small();
  const { idx, m } = atlasOf(d);
  const root = flowDecor(buildView(m, ROOT_SCOPE), d.flows[0], m.calls, idx);
  assert.ok(root.lit!.has("area:core") && root.lit!.has("c:user"));
  assert.ok(root.edges.some((e) => e.from === "c:user" && e.to === "area:edge"));
  const inside = flowDecor(buildView(m, { place: "core", parent: "core" }), d.flows[0], m.calls, idx);
  assert.ok(inside.edges.some((e) => e.from === "stub:in:area:edge"));
});

test("data lens: stateful components and who writes them", () => {
  const d = doc({
    components: [comp("w", { attributes: { area: "a" } }), comp("s", { attributes: { area: "b" }, state: { schema: {} } }), comp("x", { attributes: { area: "c" } })],
    interfaces: [iface("w", "go", ["s.put"]), { id: "s.put", component: "s", name: "put", store: { table: "t", op: "put" } }],
  });
  const { m, idx } = atlasOf(d);
  const writers = stateWriters(["s"], m.calls, idx);
  const v = buildView(m, ROOT_SCOPE);
  const decor = dataDecor(v, m, writers);
  assert.equal(decor.counts.get("area:b"), 1);
  assert.ok(decor.lit!.has("area:a") && !decor.lit!.has("area:c"));
  assert.ok(decor.edges.some((e) => e.from === "area:a" && e.to === "area:b"));
  assert.deepEqual(dataForBox(v.boxes.find((b) => b.id === "area:b")!, m, writers), [{ component: "s", writers: ["s", "w"] }]);
});

test("tint steps: none, then a logarithmic scale", () => {
  assert.equal(tintStep(0, 10), 0);
  assert.equal(tintStep(1, 1), 4);
  assert.equal(tintStep(100, 100), 4);
  assert.ok(tintStep(2, 100) < tintStep(50, 100));
  assert.equal(parseLens("nope"), "area");
});

function mech(id: string, area: string, fidelity: EvidenceMechanism["fidelity"], interfaces: string[] = []): EvidenceMechanism {
  return { id, area, kind: "k", name: id, citations: [], interfaces, fidelity };
}

test("mechanisms: same name, then interfaces, then the list's own placements, and nothing is dropped", () => {
  const { m, idx } = atlasOf(small());
  const items = [
    mech("a", "core", "absent"), // same name
    mech("b", "scheduling", "modeled", ["m0.x", "m1.x", "edge.in"]), // via interfaces: core wins
    mech("c", "scheduling", "absent"), // no interfaces, list has placements
    mech("d", "nowhere", "absent"), // nothing to go on
  ];
  const p = placeMechanisms(m, idx, items);
  assert.deepEqual(p.byArea.get("core")!.absent.map((x) => x.id), ["a", "c"]);
  assert.equal(p.byArea.get("core")!.counts.modeled, 1);
  assert.deepEqual(p.unplaced.map((x) => x.id), ["d"]);
  const v = buildView(m, { place: "core", parent: "core" });
  assert.equal(boxFidelity(v, idx, items).get("c:m0")!.modeled, 1);
});

test("no evidence, no extras: an empty list places nothing", () => {
  const { m, idx } = atlasOf(small());
  const p = placeMechanisms(m, idx, []);
  assert.equal(p.byArea.size, 0);
  assert.equal(p.unplaced.length, 0);
});

// ---- Real models ---------------------------------------------------------

const here = new URL(".", import.meta.url).pathname;
const repo = join(here, "../../../..");
const named = ["examples/vllm/vllm.json", "examples/vscode/vscode.json", "examples/cassandra/cassandra.json"].map((p) => join(repo, p));
const extra = (process.env.ATLAS_MODELS ?? "").split(":").filter(Boolean);

let label = 0;
for (const path of [...named, ...extra]) {
  if (!existsSync(path)) continue;
  label++;
  test(`real model ${label}: the box rule holds on every view, and selection never gets lost`, () => {
    const d = JSON.parse(readFileSync(path, "utf8")) as Document;
    const { idx, m } = atlasOf(d);
    assert.equal(atlasEligible(idx), true);
    const root = buildView(m, ROOT_SCOPE);
    assert.ok(root.boxes.filter((b) => b.type === "area").length >= 5);
    assert.ok(root.boxes.filter((b) => b.type === "area").length <= 16);
    assert.ok(root.boxes.length <= MAX_BOXES);
    assert.ok(root.edges.filter((e) => e.strong).length <= edgeBudget(root.boxes.length) + root.boxes.length);

    const scopes = allScopes(m);
    let biggest = 0;
    for (const s of scopes) {
      const v = buildView(m, s);
      biggest = Math.max(biggest, v.boxes.length);
      assert.ok(v.boxes.length <= MAX_BOXES, `${scopeKey(s)}: ${v.boxes.length}`);
      assert.equal(new Set(v.boxes.map((b) => b.id)).size, v.boxes.length, `duplicate box in ${scopeKey(s)}`);
      for (const e of v.edges) assert.ok(v.boxes.some((b) => b.id === e.from) && v.boxes.some((b) => b.id === e.to), e.id);
    }
    for (const id of m.nodes.keys()) {
      const v = buildView(m, scopeFor(m, id), { pin: [id] });
      assert.ok(v.boxes.length <= MAX_BOXES, id);
      assert.ok(v.boxes.some((b) => b.component === id), `lost ${id}`);
    }
    console.log(`  model ${label}: ${m.nodes.size} components, opening ${root.boxes.length} boxes, ${root.edges.length} connections (${root.edges.filter((e) => e.strong).length} strong), ${scopes.length} views, largest ${biggest}`);
  });
}

const mechDir = join(repo, "examples/vllm/mechanisms");
if (existsSync(mechDir) && existsSync(named[0])) {
  test("real mechanism lists: every absent mechanism lands on an area or is counted as unplaced", () => {
    const d = JSON.parse(readFileSync(named[0], "utf8")) as Document;
    const { idx, m } = atlasOf(d);
    const items: EvidenceMechanism[] = [];
    for (const f of readdirSync(mechDir)) {
      if (!f.endsWith(".json")) continue;
      const list = JSON.parse(readFileSync(join(mechDir, f), "utf8")) as { area: string; mechanisms: EvidenceMechanism[] };
      for (const x of list.mechanisms) items.push({ ...x, area: x.area ?? list.area });
    }
    const p = placeMechanisms(m, idx, items);
    const placed = Array.from(p.byArea.values()).reduce((s, a) => s + a.items.length, 0);
    assert.equal(placed + p.unplaced.length, items.length);
    const absent = Array.from(p.byArea.values()).reduce((s, a) => s + a.absent.length, 0) + p.unplaced.filter((x) => x.fidelity === "absent").length;
    assert.equal(absent, items.filter((x) => x.fidelity === "absent").length);
    assert.ok(absent > 0);
  });
}
