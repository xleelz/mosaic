// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { buildLaneView, groupsByDefault, laneAreas, laneDepths } from "./lanes.ts";

const area = new Map([
  ["api", "serving"],
  ["router", "serving"],
  ["engine", "core"],
  ["worker", "workers"],
]);
const lifelines = ["client", "api", "router", "engine", "worker@rank0", "worker@rank1", "?ghost.call"];

test("a collapsed area draws as one lane, and its members map to it", () => {
  const v = buildLaneView(lifelines, area, true, new Set());
  assert.equal(v.grouped, true);
  assert.deepEqual(v.lanes.map((l) => l.key), ["area:Other", "area:serving", "area:core", "area:workers"]);
  assert.equal(v.indexOf.get("api"), v.indexOf.get("router"));
  assert.equal(v.indexOf.get("worker@rank0"), v.indexOf.get("worker@rank1"));
  assert.equal(v.indexOf.get("?ghost.call"), v.indexOf.get("client"), "phantom lanes and unknown components share Other");
  assert.deepEqual(v.lanes[1].members, ["api", "router"]);
});

test("an expanded area draws its components, in place", () => {
  const v = buildLaneView(lifelines, area, true, new Set(["workers"]));
  assert.deepEqual(v.lanes.map((l) => l.key), ["area:Other", "area:serving", "area:core", "worker@rank0", "worker@rank1"]);
  assert.equal(v.lanes[3].area, "workers");
  assert.equal(v.lanes[3].collapsed, false);
  assert.notEqual(v.indexOf.get("worker@rank0"), v.indexOf.get("worker@rank1"));
});

test("a model with no areas keeps today's lanes, even if grouping was asked for", () => {
  const v = buildLaneView(lifelines, new Map(), true, new Set());
  assert.equal(v.grouped, false);
  assert.deepEqual(v.lanes.map((l) => l.key), lifelines);
  assert.deepEqual(laneAreas(lifelines, new Map()), []);
  assert.equal(groupsByDefault(lifelines, new Map()), false);
});

test("grouping starts only with enough lanes and at least two areas", () => {
  assert.equal(groupsByDefault(lifelines, area), false, "7 lanes fit as they are");
  const many = Array.from({ length: 13 }, (_, i) => (i % 2 ? "api" : "engine") + `@i${i}`);
  assert.equal(groupsByDefault(many, area), true);
  const oneArea = Array.from({ length: 13 }, (_, i) => `api@i${i}`);
  assert.equal(groupsByDefault(oneArea, area), false, "one area would be one lane");
});

test("spans sharing a collapsed lane nest together", () => {
  const v = buildLaneView(["api", "router", "engine"], area, true, new Set());
  const depths = laneDepths(
    [
      { span: 1, to: "api", startIdx: 0, endIdx: 5 },
      { span: 2, to: "router", startIdx: 1, endIdx: 2 },
      { span: 3, to: "engine", startIdx: 3, endIdx: 4 },
      { span: 4, to: "router", startIdx: 6, endIdx: -1 },
    ],
    v.indexOf,
  );
  assert.equal(depths.get(1), 0);
  assert.equal(depths.get(2), 1, "the router call is inside the api call's lane");
  assert.equal(depths.get(3), 0);
  assert.equal(depths.get(4), 0, "the api call has ended");
});
