// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { VALIDATION_TTL_MS, readValidation, writeValidation, type StorageLike } from "./validationcache.ts";

function memory(): StorageLike & { map: Map<string, string> } {
  const map = new Map<string, string>();
  return { map, getItem: (k) => map.get(k) ?? null, setItem: (k, v) => void map.set(k, v), removeItem: (k) => void map.delete(k) };
}

test("a result reads back per id, revision and hash", () => {
  const s = memory();
  writeValidation(s, "m", "3", "abc", { valid: true }, 1000);
  assert.deepEqual(readValidation(s, "m", "3", "abc", 2000), { valid: true });
  assert.equal(readValidation(s, "m", "3", "other", 2000), undefined);
  assert.equal(readValidation(s, "m", "4", "abc", 2000), undefined);
  assert.equal(readValidation(s, "n", "3", "abc", 2000), undefined);
});

test("a result expires, so a daemon upgrade is picked up", () => {
  const s = memory();
  writeValidation(s, "m", "3", "abc", { valid: true }, 0);
  assert.equal(readValidation(s, "m", "3", "abc", VALIDATION_TTL_MS), undefined);
});

test("the oldest results go past the bound", () => {
  const s = memory();
  for (let i = 0; i < 20; i++) writeValidation(s, "m", String(i), "h", i, 0);
  assert.equal(readValidation(s, "m", "0", "h", 0), undefined);
  assert.equal(readValidation(s, "m", "19", "h", 0), 19);
  assert.equal(s.map.size, 17, "16 results and the index");
});

test("a huge result isn't stored, and bad JSON or a full store only loses the cache", () => {
  const s = memory();
  writeValidation(s, "m", "1", "h", "x".repeat(300 * 1024), 0);
  assert.equal(readValidation(s, "m", "1", "h", 0), undefined);
  s.map.set("mosaic.validate:m:2:h", "{not json");
  assert.equal(readValidation(s, "m", "2", "h", 0), undefined);
  const full: StorageLike = {
    getItem: () => null,
    setItem: () => {
      throw new Error("quota");
    },
    removeItem: () => {},
  };
  writeValidation(full, "m", "1", "h", 1, 0);
});
