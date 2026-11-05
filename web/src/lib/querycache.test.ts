// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryCache } from "./querycache.ts";

const done = { done: true };

test("evicts the least recently used entry past the bound", () => {
  const c = new QueryCache({ maxWeight: 2 });
  c.set("a", done);
  c.set("b", done);
  c.set("c", done);
  assert.deepEqual(c.keys(), ["b", "c"]);
});

test("touch and rewriting a key keep it", () => {
  const c = new QueryCache({ maxWeight: 2 });
  c.set("a", done);
  c.set("b", done);
  c.touch("a");
  c.set("c", done);
  assert.deepEqual(c.keys(), ["a", "c"]);
  c.set("a", done);
  c.set("d", done);
  assert.deepEqual(c.keys(), ["a", "d"]);
});

test("get doesn't change the order", () => {
  const c = new QueryCache({ maxWeight: 2 });
  c.set("a", done);
  c.set("b", done);
  c.get("a");
  c.set("c", done);
  assert.deepEqual(c.keys(), ["b", "c"]);
});

test("a fetch in flight is never evicted, and goes once it has settled and passed the bound", () => {
  const c = new QueryCache<{ done: boolean }>({ maxWeight: 1 });
  const flying = { done: false };
  c.set("flying", flying);
  c.set("b", done);
  assert.equal(c.get("flying"), flying, "the shared request stays");
  assert.deepEqual(c.keys(), ["flying"], "b was the only settled entry, so it went");
  c.set("c", { done: false });
  assert.equal(c.keys().length, 2, "over the bound while both are in flight");
  flying.done = true;
  c.evict();
  assert.deepEqual(c.keys(), ["c"]);
});

test("a pinned key stays until every pin is released", () => {
  const c = new QueryCache({ maxWeight: 1 });
  c.set("a", done);
  const one = c.pin("a");
  const two = c.pin("a");
  c.set("b", done);
  assert.ok(c.has("a"));
  one();
  one();
  c.set("c", done);
  assert.ok(c.has("a"), "one pin is still held, and releasing twice counts once");
  two();
  assert.ok(c.has("a"), "unpinning alone doesn't evict: a remount finds its data");
  c.set("d", done);
  assert.deepEqual(c.keys(), ["d"]);
});

test("a pin survives delete, for reload and invalidate", () => {
  const c = new QueryCache({ maxWeight: 1 });
  c.set("a", done);
  c.pin("a");
  c.delete("a");
  c.set("a", done);
  c.set("b", done);
  assert.ok(c.has("a"));
});

test("the bound is by weight, so heavy entries go sooner", () => {
  const c = new QueryCache({ maxWeight: 10, weightOf: (k) => (k.startsWith("doc:") ? 8 : 1) });
  c.set("doc:1", done);
  c.set("plan:1", done);
  c.set("plan:2", done);
  assert.equal(c.weight, 10);
  c.set("doc:2", done);
  assert.deepEqual(c.keys(), ["plan:1", "plan:2", "doc:2"]);
  assert.equal(c.weight, 10);
});
