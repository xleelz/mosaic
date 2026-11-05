// Run with `pnpm test`.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { AtlasBox, AtlasEdge, AtlasView } from "../../lib/model/atlas";
import { layoutAtlas } from "./atlasLayout.ts";

function box(id: string, over: Partial<AtlasBox> = {}): AtlasBox {
  return { id, type: "area", label: id, parts: 1, flows: 0, members: [], ...over };
}

function edge(from: string, to: string, strong = true): AtlasEdge {
  return { id: `${from}->${to}`, from, to, weight: 3, emits: false, strong };
}

const view: AtlasView = {
  scope: {},
  crumbs: [],
  repOf: new Map(),
  stubFor: () => undefined,
  boxes: [box("in", { type: "actor", edge: "start" }), box("a"), box("b"), box("c"), box("lone"), box("out", { type: "actor", edge: "end" })],
  edges: [edge("in", "a"), edge("a", "b"), edge("b", "c"), edge("c", "a"), edge("b", "out"), edge("lone", "out", false)],
};

test("actors sit on the edges, and boxes with no drawn connection go below", async () => {
  const l = await layoutAtlas(view, false);
  assert.equal(l.size, view.boxes.length);
  for (const id of ["a", "b", "c"]) {
    assert.ok(l.get("in")!.x < l.get(id)!.x, id);
    assert.ok(l.get("out")!.x > l.get(id)!.x, id);
  }
  const bottom = Math.max(...["in", "a", "b", "c", "out"].map((id) => l.get(id)!.y + l.get(id)!.height));
  assert.ok(l.get("lone")!.y >= bottom);
});

test("an actor that also receives or makes calls the other way stays on its edge", async () => {
  const l = await layoutAtlas({ ...view, edges: [...view.edges, edge("a", "in"), edge("out", "c")] }, false);
  for (const id of ["a", "b", "c"]) {
    assert.ok(l.get("in")!.x < l.get(id)!.x, id);
    assert.ok(l.get("out")!.x > l.get(id)!.x, id);
  }
});

test("layout is the same on every visit, and ignores weak connections", async () => {
  const one = await layoutAtlas(view, false);
  const two = await layoutAtlas(view, false);
  assert.deepEqual(Array.from(two), Array.from(one));
  const moreWeak = await layoutAtlas({ ...view, edges: [...view.edges, edge("a", "c", false)] }, false);
  assert.deepEqual(Array.from(moreWeak), Array.from(one));
});
