// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { SystemVersion } from "./api/types";
import { ago, chipLabel, waitForCommit } from "./update.ts";

function version(commit: string, behind = 0): SystemVersion {
  return {
    version: "0.1.0",
    commit,
    dirty: false,
    branch: "main",
    upstream: "origin/main",
    source_dir: "/src/mosaic",
    update: { available: behind > 0, behind, ahead: 0, latest_commit: "", latest_subject: "", checked_at: null },
  };
}

test("chipLabel shows the short commit and new commits", () => {
  assert.deepEqual(chipLabel(version("0123456789abcdef", 3)), { commit: "0123456", behind: "3 new commits" });
  assert.deepEqual(chipLabel(version("0123456789abcdef", 1)), { commit: "0123456", behind: "1 new commit" });
  assert.deepEqual(chipLabel(version("0123456789abcdef")), { commit: "0123456", behind: null });
  assert.equal(chipLabel({ ...version(""), version: "fixtures" }).commit, "fixtures");
});

test("ago is coarse", () => {
  const now = Date.parse("2026-11-03T12:00:00Z");
  assert.equal(ago(null, now), "never");
  assert.equal(ago("2026-11-03T11:59:50Z", now), "just now");
  assert.equal(ago("2026-11-03T11:56:00Z", now), "4 min ago");
  assert.equal(ago("2026-11-03T09:00:00Z", now), "3 h ago");
});

test("waitForCommit retries errors until the new commit answers", async () => {
  let t = 0;
  const answers: (SystemVersion | Error)[] = [version("old"), new Error("down"), new Error("down"), version("new")];
  const result = await waitForCommit({
    target: "new",
    fetchVersion: async () => {
      const a = answers.shift()!;
      if (a instanceof Error) throw a;
      return a;
    },
    now: () => t,
    sleep: async (ms) => {
      t += ms;
    },
  });
  assert.equal(result, "ready");
  assert.equal(t, 6000);
});

test("waitForCommit times out after three minutes", async () => {
  let t = 0;
  const result = await waitForCommit({
    target: "new",
    fetchVersion: async () => version("old"),
    now: () => t,
    sleep: async (ms) => {
      t += ms;
    },
  });
  assert.equal(result, "timeout");
  assert.ok(t >= 180_000 && t < 185_000);
});
