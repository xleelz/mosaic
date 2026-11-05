// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Evidence, EvidenceMechanism, MechanismFidelity } from "../../lib/api/types";
import { countFidelity, fidelitySentence } from "./fidelity.ts";
import { NOT_BENCHMARKED, passportFacts, selfCheckWords, viewedRevision } from "./passport.ts";

function mechanisms(spec: Partial<Record<MechanismFidelity, number>>): EvidenceMechanism[] {
  const out: EvidenceMechanism[] = [];
  for (const [fidelity, n] of Object.entries(spec)) {
    for (let i = 0; i < (n ?? 0); i++) {
      out.push({ id: `${fidelity}-${i}`, area: "a", kind: "k", name: "n", citations: [], interfaces: [], fidelity: fidelity as MechanismFidelity });
    }
  }
  return out;
}

const blind = { measured_on_revision: 3, steps_passed: 30, steps_total: 100, cases_passed: 2, cases_total: 10, oracle_passed: 14, oracle_total: 45 };

test("no evidence says Not benchmarked and invents nothing", () => {
  const f = passportFacts(null, 3);
  assert.equal(f.chip, NOT_BENCHMARKED);
  assert.equal(f.blind.headline, NOT_BENCHMARKED);
  assert.equal(f.blind.detail, undefined);
  assert.equal(f.mechanisms.modeledPct, null);
  assert.equal(f.source, undefined);
});

test("a measured model's chip gives both figures", () => {
  const e: Evidence = { revision: 3, built_by: "generated", blind, mechanisms: { measured_on_revision: 3, items: mechanisms({ modeled: 24, absent: 76 }) } };
  const f = passportFacts(e, 3);
  assert.equal(f.chip, "Generated model · blind benchmark 30% of steps · 24% of mechanisms modeled");
  assert.equal(f.blind.stale, false);
  assert.equal(f.blind.measured, "measured on r3");
});

test("a figure from an older revision says so", () => {
  const e: Evidence = { revision: 5, blind, mechanisms: { measured_on_revision: 4, items: mechanisms({ modeled: 1, shell: 1 }) } };
  const f = passportFacts(e, 5);
  assert.equal(f.blind.measured, "measured on r3, not re-measured");
  assert.equal(f.blind.stale, true);
  assert.equal(f.mechanisms.measured, "measured on r4, not re-measured");
  assert.match(f.chip, /30% of steps \(r3\)/);
  assert.match(f.chip, /50% of mechanisms modeled \(r4\)/);
});

test("the draft is never counted as measured", () => {
  const f = passportFacts({ revision: 3, blind }, null);
  assert.equal(f.blind.measured, "measured on r3, not on this draft");
  assert.equal(f.blind.stale, true);
});

test("a blind record with no steps isn't a benchmark", () => {
  const f = passportFacts({ revision: 3, blind: { ...blind, steps_passed: 0, steps_total: 0 } }, 3);
  assert.equal(f.blind.headline, NOT_BENCHMARKED);
  assert.equal(f.blind.measured, undefined);
});

test("mechanisms without a blind figure still say Not benchmarked", () => {
  const f = passportFacts({ revision: 1, built_by: "handwritten", mechanisms: { measured_on_revision: 1, items: mechanisms({ partial: 2 }) } }, 1);
  assert.equal(f.chip, "Hand-written model · Not benchmarked · 0% of mechanisms modeled");
});

test("source reads as pinned", () => {
  const f = passportFacts({ revision: 1, source: { repo: "org/repo", commit: "5df63a7abcdef" } }, 1);
  assert.equal(f.source, "org/repo @ 5df63a7 (pinned)");
});

test("selfCheckWords always says self-checks and never claims more", () => {
  assert.equal(selfCheckWords({ total: 1805, failed: 0 }, 1805), "1805 of 1805 self-checks pass");
  assert.equal(selfCheckWords({ total: 10, failed: 3 }, 10), "7 of 10 self-checks pass");
  assert.equal(selfCheckWords(null, 22), "Not run yet (22 scenarios)");
  assert.equal(selfCheckWords(null, 0), "No scenarios to check");
  assert.equal(selfCheckWords(null, undefined), "Not run yet");
});

test("viewedRevision resolves selectors", () => {
  assert.equal(viewedRevision("4", 6), 4);
  assert.equal(viewedRevision("latest", 6), 6);
  assert.equal(viewedRevision(undefined, 6), 6);
  assert.equal(viewedRevision("draft", 6), null);
  assert.equal(viewedRevision("latest", 0), null);
});

test("counts and sentence", () => {
  const c = countFidelity(mechanisms({ modeled: 2, absent: 1 }));
  assert.deepEqual(c, { modeled: 2, partial: 0, shell: 0, absent: 1, total: 3 });
  assert.equal(fidelitySentence(c), "2 modeled, 1 absent");
  assert.equal(fidelitySentence(countFidelity([])), "No mechanisms");
});
