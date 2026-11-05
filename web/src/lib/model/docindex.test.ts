// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Document, EvidenceMechanism, Flow, Scenario } from "../api/types";
import {
  CALLED_GROUP,
  COMPONENT_GROUP,
  OTHER,
  REACHABLE_GROUP,
  ancestors,
  buildDocIndex,
  componentMechanisms,
  componentRows,
  defaultFlowGrouping,
  derivedFlowLine,
  docIndex,
  faultScenarios,
  faultTargetOptions,
  filterOptions,
  flowMatches,
  flowScenarios,
  flowTitle,
  flowsThrough,
  groupFlows,
  groupMembers,
  happyPath,
  isFailureHandling,
  mainFlows,
  rankFlows,
  scenarioClass,
  scenarioTitle,
  searchFlows,
  subgroupFlows,
  touchLabel,
} from "./docindex.ts";

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
  assert.deepEqual(idx.unfiledScenarios.map((s) => s.id), ["s4"]);
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

// ---- Scenarios under every flow they touch

const touching = doc({
  components: [
    { id: "client", kind: "client" },
    { id: "gateway", kind: "module", parent: "edge" },
    { id: "edge", kind: "service", attributes: { area: "serving" } },
    { id: "engine", kind: "module" },
    { id: "disk", kind: "datastore", parent: "engine", state: { initial: {} } },
    { id: "helper", kind: "module", parent: "engine" },
    { id: "pool", kind: "module", parent: "engine" },
    { id: "pool-a", kind: "module", parent: "pool" },
  ],
  interfaces: [
    { component: "gateway", name: "generate", behavior: [{ call: "engine.step" }] },
    { component: "engine", name: "step", behavior: [{ if: "x", then: [{ call: "disk.read" }], else: [{ targets: ["helper.h"] }] }] },
    { component: "engine", name: "loop" },
    { component: "disk", name: "read" },
    { component: "helper", name: "h" },
  ],
  flows: [
    { id: "generate", name: "Generate", entry: { caller: "client", interface: "gateway.generate" } },
    { id: "loop", name: "Busy loop", entry: { caller: "engine", interface: "engine.loop" } },
    { id: "direct", entry: { caller: "engine", interface: "engine.step" } },
    { id: "lonely", description: "Nothing touches this. Really.", entry: { caller: "engine", interface: "disk.read" } },
  ],
  scenarios: [
    { id: "gen-refused", flow: "generate", expect: ["!result.ok && result.error.code == 'x'"] },
    { id: "gen-dies", flow: "generate", name: "Engine dies", faults: [{ target: "engine.step", type: "error", code: "engine-dead-error" }] },
    { id: "gen-state", flow: "generate", state: { engine: {} }, expect: ["result.ok"] },
    { id: "gen-happy", name: "A request streams to completion", steps: [{ flow: "loop" }, { flow: "generate" }, { interface: "engine.step" }], expect: ["steps.a.result.ok"] },
    { id: "disk-down", flow: "loop", faults: [{ target: "disk", type: "unavailable" }] },
    { id: "bare", steps: [{ interface: "helper.h" }] },
  ],
});

test("a scenario is indexed under every flow it touches, not only its first", () => {
  const idx = buildDocIndex(touching);
  assert.deepEqual(idx.flowsOfScenario.get("gen-happy"), ["loop", "generate", "direct"]);
  const generate = idx.touchesByFlow.get("generate")!;
  assert.deepEqual(generate.map((t) => [t.scenario.id, t.how, t.step]), [
    ["gen-refused", "runs", undefined],
    ["gen-dies", "runs", undefined],
    ["gen-state", "runs", undefined],
    ["gen-happy", "step", 2],
  ]);
  assert.equal(idx.scenariosByFlow.get("generate")?.length, 4);
  // Called directly by a step, it touches the flow entered there.
  assert.deepEqual(idx.touchesByFlow.get("direct")?.map((t) => [t.scenario.id, t.how, t.step]), [["gen-happy", "calls-entry", 3]]);
  assert.equal(idx.scenariosByFlow.get("lonely"), undefined);
  assert.deepEqual(idx.unfiledScenarios.map((s) => s.id), ["bare"]);
  assert.equal(touchLabel(generate[3]), "this flow is step 2 of 3");
  assert.equal(touchLabel(generate[0]), "");
});

test("a step's strongest touch wins", () => {
  const idx = buildDocIndex(doc({
    flows: [{ id: "f", entry: { caller: "a", interface: "a.b" } }],
    scenarios: [{ id: "s", steps: [{ interface: "a.b" }, { flow: "f" }] }, { id: "t", flow: "f", steps: [{ flow: "f" }] }],
  }));
  assert.deepEqual(idx.touchesByFlow.get("f")?.map((t) => [t.scenario.id, t.how]), [["s", "step"], ["t", "runs"]]);
});

test("search finds scenarios, by words in their name, description and faults", () => {
  const idx = buildDocIndex(touching);
  const found = searchFlows(touching.flows, idx, "engine dead");
  assert.deepEqual(found.scenarios.map((s) => s.id), ["gen-dies"]);
  assert.deepEqual(found.flows.map((f) => f.id), ["generate"]);
  assert.deepEqual(found.viaScenario.get("generate")?.map((s) => s.id), ["gen-dies"]);
  // Scenarios that touch no flow can still be found.
  assert.deepEqual(searchFlows(touching.flows, idx, "bare").scenarios.map((s) => s.id), ["bare"]);
  // A flow matching by itself needs no scenario.
  assert.deepEqual(searchFlows(touching.flows, idx, "busy").flows.map((f) => f.id), ["loop"]);
  assert.equal(searchFlows(touching.flows, idx, "  ").flows.length, 4);
});

test("scenarioClass reads faults, expectations and words", () => {
  const c = (s: Partial<Scenario>) => scenarioClass({ id: "x", ...s });
  assert.equal(c({ faults: [{ target: "a", type: "error" }] }), "fault");
  assert.equal(c({ mocks: [{ interface: "a.b", fail: { code: "x" } }] }), "fault");
  assert.equal(c({ expect: ["!result.ok"] }), "expected-error");
  assert.equal(c({ expect: ["!steps.bad.result.ok"] }), "expected-error");
  assert.equal(c({ expect: ["steps.c3.result.error.code == 'x'"] }), "expected-error");
  assert.equal(c({ expect: ["result.ok == false"] }), "expected-error");
  assert.equal(c({ id: "login-refused" }), "expected-error");
  assert.equal(c({ expect: ["result.ok", "steps.a.result.value.ok"] }), "normal");
});

test("happyPath prefers a scenario named as the normal path, even at a later step", () => {
  const idx = buildDocIndex(touching);
  const h = happyPath(idx.touchesByFlow.get("generate")!)!;
  assert.equal(h.touch.scenario.id, "gen-happy");
  assert.match(h.why, /named/);
  const split = flowScenarios(idx.touchesByFlow.get("generate")!);
  assert.deepEqual(split.faults.map((t) => t.scenario.id), ["gen-dies"]);
  assert.deepEqual(split.expectedErrors.map((t) => t.scenario.id), ["gen-refused"]);
  assert.deepEqual(split.starts.map((t) => t.scenario.id), ["gen-state"]);
  assert.deepEqual(split.uses, []);
});

test("happyPath falls back to the fewest overrides, and to nothing when all are failures", () => {
  const t = (s: Scenario) => ({ scenario: s, how: "runs" as const, stepCount: 0 });
  assert.equal(happyPath([t({ id: "a", state: { x: {} } }), t({ id: "b" })])?.touch.scenario.id, "b");
  assert.equal(happyPath([t({ id: "a", faults: [{ target: "x", type: "error" }] })]), null);
  assert.equal(happyPath([]), null);
});

test("titles say where they come from, so an id never passes as a title", () => {
  assert.deepEqual(scenarioTitle({ id: "s", name: "Named" }), { text: "Named", from: "name" });
  assert.deepEqual(scenarioTitle({ id: "s", description: "First one. Second one." }), { text: "First one.", from: "description" });
  assert.deepEqual(scenarioTitle({ id: "s", name: "  " }), { text: "s", from: "id" });
  assert.deepEqual(flowTitle({ id: "f" }), { text: "f", from: "id" });
  assert.ok(scenarioTitle({ id: "s", description: "x".repeat(200) }).text.length <= 90);
  const idx = buildDocIndex(touching);
  assert.equal(derivedFlowLine(touching.flows[1], idx), "engine calls engine.loop.");
  assert.equal(derivedFlowLine({ id: "x" }, idx), "");
});

test("main flows: entered from outside first, then by scenarios; flows nothing touches stay out", () => {
  const idx = buildDocIndex(touching);
  const main = mainFlows(touching.flows, idx);
  assert.deepEqual(main.map((m) => m.flow.id), ["generate", "loop", "direct"]);
  assert.equal(main[0].reason, "entered from outside the model, 4 scenarios");
  assert.equal(main[1].reason, "2 scenarios");
  assert.deepEqual(rankFlows(touching.flows, idx).map((f) => f.id), ["generate", "loop", "direct", "lonely"]);
  assert.deepEqual(mainFlows(touching.flows, idx, 1).map((m) => m.flow.id), ["generate"]);
});

test("subgroupFlows divides by top-level component, else by id word", () => {
  const comps = [{ id: "a" }, { id: "b" }, { id: "a1", parent: "a" }, { id: "a2", parent: "a" }];
  const ifaces = comps.map((c) => ({ component: c.id, name: "i" }));
  const flow = (id: string, c: string): Flow => ({ id, entry: { caller: "z", interface: `${c}.i` } });
  const d = doc({ components: comps, interfaces: ifaces, flows: [flow("x-1", "a1"), flow("x-2", "a1"), flow("y-1", "a2"), flow("y-2", "b"), flow("y-3", "b"), flow("q", "b")] });
  const idx = buildDocIndex(d);
  assert.deepEqual(subgroupFlows(d.flows, idx, "area").map((g) => [g.key, g.flows.length]), [["b", 3], ["a", 3]].sort((p, q) => String(p[0]).localeCompare(String(q[0]))));
  // Grouped by top-level component already: its direct members, and single flows go to Other.
  const inA = d.flows.slice(0, 3);
  assert.deepEqual(subgroupFlows(inA, idx, "parent").map((g) => [g.key, g.flows.length]), [["a1", 2], [OTHER, 1]]);
  // One component holds them all: id words divide them instead.
  const allB = [flow("p-1", "b"), flow("p-2", "b"), flow("r-1", "b"), flow("r-2", "b")];
  assert.deepEqual(subgroupFlows(allB, idx, "area").map((g) => g.key), ["p", "r"]);
});

test("flowsThrough: entered here, then could reach through declared calls", () => {
  const idx = buildDocIndex(touching);
  const disk = flowsThrough(touching, idx, "disk");
  assert.deepEqual(disk.enters.map((f) => f.id), ["lonely"]);
  assert.deepEqual(disk.reaches.map((f) => f.id), ["generate", "direct"]);
  // targets are followed, and members roll up.
  assert.deepEqual(flowsThrough(touching, idx, "helper").reaches.map((f) => f.id), ["generate", "direct"]);
  const engine = flowsThrough(touching, idx, "engine");
  assert.deepEqual(engine.enters.map((f) => f.id), ["loop", "direct", "lonely"]);
  assert.deepEqual(engine.reaches.map((f) => f.id), ["generate"]);
  assert.deepEqual(flowsThrough(touching, idx, "client"), { enters: [], reaches: [] });
});

test("faultScenarios: faults on the component, its interfaces and its members", () => {
  const idx = buildDocIndex(touching);
  assert.deepEqual(faultScenarios(idx, "disk").map((x) => x.scenario.id), ["disk-down"]);
  const engine = faultScenarios(idx, "engine");
  assert.deepEqual(engine.map((x) => x.scenario.id), ["gen-dies", "disk-down"]);
  assert.equal(engine[1].faults[0].target, "disk");
  assert.deepEqual(faultScenarios(idx, "helper"), []);
});

test("groupMembers puts what flows enter and infrastructure first", () => {
  const idx = buildDocIndex(touching);
  assert.deepEqual(groupMembers(idx, "engine").map((g) => [g.key, g.members.map((m) => m.id)]), [
    ["entered", ["disk"]],
    ["containers", ["pool"]],
    ["rest", ["helper"]],
  ]);
  const bigger = buildDocIndex(doc({ components: [{ id: "p" }, { id: "db", parent: "p", kind: "datastore" }, { id: "s", parent: "p", state: { initial: {} } }] }));
  assert.deepEqual(groupMembers(bigger, "p").map((g) => [g.key, g.members.length]), [["infrastructure", 2]]);
});

const mech = (over: Partial<EvidenceMechanism>): EvidenceMechanism => ({ id: "m", area: "serving", kind: "pipeline", name: "n", citations: [], interfaces: [], fidelity: "modeled", ...over });

test("componentMechanisms matches the area when a list has it, and falls back to its interfaces", () => {
  const idx = buildDocIndex(touching);
  const items = [
    mech({ id: "a", interfaces: ["gateway.generate"], fidelity: "partial" }),
    mech({ id: "b", fidelity: "absent", name: "Retry on engine failure" }),
    mech({ id: "c", fidelity: "absent", name: "Stream interval batching" }),
    mech({ id: "d", area: "storage", interfaces: ["disk.read"], fidelity: "shell" }),
    mech({ id: "e", area: "storage", fidelity: "absent", kind: "retry", name: "Reopen" }),
    mech({ id: "f", area: "other", fidelity: "absent", name: "Crash recovery" }),
  ];
  // edge's area, serving, is also a list's area.
  const edge = componentMechanisms(idx, "edge", items);
  assert.deepEqual(edge.areas, ["serving"]);
  assert.deepEqual(edge.own.map((m) => m.id), ["a"]);
  assert.deepEqual(edge.absent.map((m) => m.id), ["b", "c"]);
  assert.deepEqual(edge.absentFailureHandling.map((m) => m.id), ["b"]);
  // disk has no area of its own: its interfaces' mechanisms name it.
  const disk = componentMechanisms(idx, "disk", items);
  assert.deepEqual(disk.areas, ["storage"]);
  assert.deepEqual(disk.absentFailureHandling.map((m) => m.id), ["e"]);
  // Nothing to go on: no areas, and nothing claimed about it.
  assert.deepEqual(componentMechanisms(idx, "client", items), { own: [], absent: [], absentFailureHandling: [], areas: [] });
});

test("isFailureHandling reads the kind and whole words", () => {
  assert.ok(isFailureHandling(mech({ kind: "retry", name: "x" })));
  assert.ok(isFailureHandling(mech({ observable: "the engine dead error reaches the client" })));
  assert.ok(!isFailureHandling(mech({ name: "Errorless terror handling" })));
});

test("filterOptions needs every word, puts prefix matches first and caps what it returns", () => {
  const o = [{ value: "a.get" , label: "a.get" }, { value: "disk.read", label: "disk.read", hint: "Local disk" }, { value: "b.disk", label: "b.disk" }];
  assert.deepEqual(filterOptions(o, "disk").shown.map((x) => x.value), ["disk.read", "b.disk"]);
  assert.deepEqual(filterOptions(o, "local read").shown.map((x) => x.value), ["disk.read"]);
  const many = Array.from({ length: 1041 }, (_, i) => ({ value: `t${i}`, label: `t${i}` }));
  const r = filterOptions(many, "", 60);
  assert.equal(r.shown.length, 60);
  assert.equal(r.total, 1041);
});

test("faultTargetOptions starts from what a default run called, entry last", () => {
  const idx = buildDocIndex(touching);
  const out = faultTargetOptions(["gateway.generate", "engine.step", "disk.read", "helper.h", "engine"], { "gateway.generate": 1, "engine.step": 2, "disk.read": 3, "not.faultable": 9 }, "gateway.generate", idx);
  assert.deepEqual(out.map((o) => [o.value, o.group, o.hint]), [
    ["disk.read", CALLED_GROUP, "3x"],
    ["engine.step", CALLED_GROUP, "2x"],
    ["gateway.generate", CALLED_GROUP, "the entry, 1x"],
    ["helper.h", REACHABLE_GROUP, undefined],
    ["engine", COMPONENT_GROUP, "engine"],
  ]);
  // No run to go on: the static list, without the called group.
  assert.ok(faultTargetOptions(["a.b"], undefined, undefined, idx).every((o) => o.group !== CALLED_GROUP));
});

