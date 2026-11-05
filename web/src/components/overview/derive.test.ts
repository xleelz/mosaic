// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Document, EvidenceMechanism, MechanismFidelity } from "../../lib/api/types";
import { OTHER, buildDocIndex, descendantCounts } from "../../lib/model/docindex.ts";
import { areaRollup, entryPoints, mechanismArea, topLevelRows } from "./derive.ts";
import { latestOf, modelIdentity } from "./identity.ts";

function doc(over: Partial<Document>): Document {
  return { schema_version: 1, components: [], interfaces: [], links: [], schemas: [], flows: [], scenarios: [], ...over };
}

function mech(id: string, area: string, fidelity: MechanismFidelity, interfaces: string[] = []): EvidenceMechanism {
  return { id, area, kind: "k", name: id, citations: [], interfaces, fidelity };
}

const base = doc({
  components: [
    { id: "user", kind: "client" },
    { id: "hub", kind: "external" },
    { id: "cli", kind: "client" },
    { id: "api", attributes: { area: "serving" } },
    { id: "engine", attributes: { area: "core" } },
    { id: "loop", parent: "engine" },
  ],
  interfaces: [
    { component: "api", name: "get" },
    { component: "engine", name: "step" },
    { component: "loop", name: "tick" },
  ],
  flows: [
    { id: "f1", name: "Read", entry: { caller: "user", interface: "api.get" } },
    { id: "f2", entry: { caller: "api", interface: "engine.step" } },
    { id: "f3", name: "Described", description: "d", entry: { caller: "", interface: "loop.tick" } },
    { id: "f4", entry: { caller: "user", interface: "api.get" } },
  ],
  scenarios: [
    { id: "s1", flow: "f2" },
    { id: "s2", steps: [{ flow: "f2" }, { flow: "f2" }, { flow: "f1" }] },
    { id: "s3", flow: "f1", steps: [{ flow: "f1" }] },
    { id: "s4", flow: "f2" },
  ],
});

test("entry points come from outside callers and entered components", () => {
  const { entries, dependencies } = entryPoints(base, buildDocIndex(base));
  assert.deepEqual(entries.map((e) => [e.id, e.flows]), [["user", 2], ["engine", 1], ["loop", 1], ["cli", 0]]);
  assert.deepEqual(dependencies.map((e) => e.id), ["hub"]);
});

test("areas carry counts, and Other is last", () => {
  const idx = buildDocIndex(base);
  const { rows, unplaced } = areaRollup(base, idx, []);
  assert.deepEqual(rows.map((r) => [r.area, r.components, r.flows]), [["core", 2, 2], ["serving", 1, 2], [OTHER, 3, 0]]);
  assert.equal(unplaced.total, 0);
});

test("a mechanism uses its own area, falls back to its interfaces, else stays unplaced", () => {
  const idx = buildDocIndex(base);
  const known = new Set(idx.area.values());
  assert.equal(mechanismArea(mech("a", "core", "absent"), idx, known), "core");
  assert.equal(mechanismArea(mech("b", "distributed", "partial", ["api.get", "engine.step", "loop.tick"]), idx, known), "core");
  assert.equal(mechanismArea(mech("c", "distributed", "absent"), idx, known), undefined);

  const { rows, unplaced } = areaRollup(base, idx, [mech("a", "core", "absent"), mech("b", "distributed", "partial", ["api.get"]), mech("c", "distributed", "absent")]);
  assert.equal(rows.find((r) => r.area === "core")?.mechanisms.absent, 1);
  assert.equal(rows.find((r) => r.area === "serving")?.mechanisms.partial, 1);
  assert.equal(unplaced.absent, 1);
  assert.equal(unplaced.total, 1);
});

test("a model with no areas has no rows, and its mechanisms stay unplaced", () => {
  const plain = doc({ components: [{ id: "a" }, { id: "b", parent: "a" }, { id: "c" }] });
  const idx = buildDocIndex(plain);
  const r = areaRollup(plain, idx, [mech("m", "x", "modeled")]);
  assert.deepEqual(r.rows, []);
  assert.equal(r.unplaced.modeled, 1);
  assert.deepEqual(topLevelRows(idx, descendantCounts(idx)).map((t) => [t.id, t.members]), [["a", 1], ["c", 0]]);
});

test("a name contradicted by the latest revision isn't shown as fact", () => {
  const stale = modelIdentity("Thing 0.32 (round 4)", "thing", "Thing round 6: mechanism coverage");
  assert.equal(stale.title, "Thing 0.32");
  assert.match(stale.staleNote ?? "", /round 4/);
  assert.match(stale.staleNote ?? "", /round 6/);
});

test("a name that agrees, or says nothing checkable, stands", () => {
  assert.deepEqual(modelIdentity("Thing (round 6)", "t", "round 6: fixes"), { title: "Thing (round 6)" });
  assert.deepEqual(modelIdentity("Thing", "t", "round 6"), { title: "Thing" });
  assert.deepEqual(modelIdentity("Thing round 4", "t", "fixes"), { title: "Thing round 4" });
  assert.deepEqual(modelIdentity("", "t", undefined), { title: "t" });
  assert.deepEqual(modelIdentity("Around 4 things", "t", "round 6"), { title: "Around 4 things" });
});

test("latestOf picks the highest number", () => {
  assert.equal(latestOf([{ number: 1 }, { number: 3 }, { number: 2 }])?.number, 3);
  assert.equal(latestOf(undefined), undefined);
});
