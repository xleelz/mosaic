// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { rowAt, rowOffsets, rowWindow } from "./windowing.ts";

test("offsets add up variable heights", () => {
  assert.deepEqual(Array.from(rowOffsets(3, (i) => (i + 1) * 10)), [0, 10, 30, 60]);
});

test("rowAt finds the row containing a position, clamped to the list", () => {
  const o = rowOffsets(3, () => 10);
  assert.equal(rowAt(o, 0), 0);
  assert.equal(rowAt(o, 9.5), 0);
  assert.equal(rowAt(o, 10), 1);
  assert.equal(rowAt(o, 29), 2);
  assert.equal(rowAt(o, 1000), 2);
  assert.equal(rowAt(rowOffsets(0, () => 10), 5), 0);
});

test("the window draws what's in view plus the overscan, and spacers keep the height", () => {
  const o = rowOffsets(1000, () => 20);
  const w = rowWindow(o, 2000, 100, 2);
  assert.deepEqual({ start: w.start, end: w.end }, { start: 98, end: 108 });
  assert.equal(w.before, 98 * 20);
  assert.equal(w.after, (1000 - 108) * 20);
  assert.equal(w.before + (w.end - w.start) * 20 + w.after, 20000);
});

test("the window clamps at both ends and past a list that shrank", () => {
  const o = rowOffsets(10, () => 20);
  assert.deepEqual(rowWindow(o, 0, 50, 1), { start: 0, end: 4, before: 0, after: 120 });
  assert.equal(rowWindow(o, 1e6, 50, 1).end, 10);
  assert.equal(rowWindow(o, 1e6, 50, 1).after, 0);
  assert.deepEqual(rowWindow(rowOffsets(0, () => 20), 100, 50, 1), { start: 0, end: 0, before: 0, after: 0 });
});

test("a short list draws every row", () => {
  const w = rowWindow(rowOffsets(3, () => 20), 0, 500, 2);
  assert.deepEqual({ start: w.start, end: w.end }, { start: 0, end: 3 });
});
