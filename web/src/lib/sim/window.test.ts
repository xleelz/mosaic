// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { binTicks, covers, drawRegion, firstRowAt, lastRowBefore } from "./window.ts";

const rows = [
  { top: 0, h: 10 },
  { top: 10, h: 10 },
  { top: 20, h: 0 },
  { top: 20, h: 10 },
];

test("finds the rows around a y, through hidden rows", () => {
  assert.equal(firstRowAt(rows, 0), 0);
  assert.equal(firstRowAt(rows, 9.5), 0);
  assert.equal(firstRowAt(rows, 10), 1);
  assert.equal(firstRowAt(rows, 20), 3, "a hidden row ends where it starts");
  assert.equal(firstRowAt(rows, 500), 4);
  assert.equal(lastRowBefore(rows, 0), -1);
  assert.equal(lastRowBefore(rows, 15), 1);
  assert.equal(lastRowBefore(rows, 500), 3);
});

test("the drawn region is the viewport plus margins, clamped to the content", () => {
  assert.deepEqual(drawRegion({ x: 0, y: 0, w: 100, h: 100 }, 1000, 1000, 50, 50), { x: 0, y: 0, w: 150, h: 150 });
  assert.deepEqual(drawRegion({ x: 900, y: 900, w: 100, h: 100 }, 1000, 1000, 50, 50), { x: 850, y: 850, w: 150, h: 150 });
});

test("a region stops covering a viewport that leaves it, but not at the content's edge", () => {
  const region = drawRegion({ x: 0, y: 500, w: 100, h: 100 }, 1000, 1000, 50, 200);
  assert.equal(covers(region, { x: 0, y: 450, w: 100, h: 100 }, 1000, 1000), true);
  assert.equal(covers(region, { x: 0, y: 200, w: 100, h: 100 }, 1000, 1000), false);
  const atEnd = drawRegion({ x: 0, y: 900, w: 100, h: 100 }, 1000, 1000, 50, 50);
  assert.equal(covers(atEnd, { x: 0, y: 900, w: 100, h: 200 }, 1000, 1000), true);
});

test("ticks are bounded by bins, and the worst tone in a bin wins", () => {
  const tones = Array.from({ length: 20000 }, (_, i) => (i === 7 ? "error" : i % 2 ? "call" : null));
  const rank = (t: string) => (t === "error" ? 0 : 1);
  const ticks = binTicks(tones, 100, rank);
  assert.ok(ticks.length <= 100);
  assert.equal(ticks[0].tone, "error", "the error survives in a bin full of calls");
  assert.deepEqual(binTicks([], 100, rank), []);
  assert.deepEqual(binTicks(["call"], 10, rank), [{ bin: 0, tone: "call" }]);
});
