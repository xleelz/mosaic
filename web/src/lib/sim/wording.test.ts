// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { instanceCount, mechanismSentence, plural, runVerdict } from "./wording.ts";

const assertion = (passed: boolean) => ({ expr: "x", passed });
const err = { ok: false, error: { code: "engine-dead-error", message: "m", status: 500 } };

test("an error whose expectations pass reads as failed as expected, and isn't marked bad", () => {
  const v = runVerdict({ status: "error", result: err, assertions: [assertion(true)], passed: true });
  assert.equal(v.text, "Failed as expected: 500 engine-dead-error");
  assert.equal(v.tone, "neutral");
});

test("an error whose expectations fail is bad", () => {
  const v = runVerdict({ status: "error", result: err, assertions: [assertion(false)], passed: false });
  assert.equal(v.text, "Failed: 500 engine-dead-error, and the model expected otherwise");
  assert.equal(v.tone, "bad");
});

test("an error with no expectations is bad, and doesn't say expected", () => {
  const v = runVerdict({ status: "error", result: { ok: false, error: { code: "x", message: "" } }, assertions: [], passed: true });
  assert.equal(v.text, "Failed: x");
  assert.equal(v.tone, "bad");
});

test("a pass is as the model expects, and neutral: expectations are a self-check", () => {
  const v = runVerdict({ status: "ok", result: { ok: true }, assertions: [assertion(true)], passed: true });
  assert.equal(v.text, "Passed, as the model expects");
  assert.equal(v.tone, "neutral");
});

test("ok with failing expectations is bad; ok with none claims nothing", () => {
  assert.equal(runVerdict({ status: "ok", result: { ok: true }, assertions: [assertion(false)], passed: false }).tone, "bad");
  assert.equal(runVerdict({ status: "ok", result: { ok: true }, assertions: [], passed: true }).text, "Finished, with no expectations to check");
});

test("an aborted run says why it stopped", () => {
  const v = runVerdict({ status: "aborted", result: { ok: false }, assertions: [], passed: false, abort: "max events" });
  assert.equal(v.text, "Stopped: max events");
  assert.equal(v.tone, "warn");
});

test("the mechanism sentence counts by fidelity, and is empty for none", () => {
  const m = (fidelity: string) => ({ fidelity });
  assert.equal(mechanismSentence([m("partial"), m("partial"), m("partial"), m("shell")]), "This run passed through 3 partial and 1 shell mechanism");
  assert.equal(mechanismSentence([m("shell")]), "This run passed through 1 shell mechanism");
  assert.equal(mechanismSentence([m("partial"), m("shell"), m("absent")]), "This run passed through 1 partial, 1 shell and 1 absent mechanism");
  assert.equal(mechanismSentence([]), "");
});

test("instances are counted, not interface-instance pairs", () => {
  assert.equal(instanceCount({ "a.x@rank0": 1, "a.y@rank0": 2, "b.z@rank0": 1 }), 1);
  assert.equal(instanceCount({ "a.x@h1": 1, "a.x@h2": 2 }), 2);
  assert.equal(instanceCount(undefined), 0);
  assert.equal(plural(1, "instance"), "1 instance");
  assert.equal(plural(2, "instance"), "2 instances");
});
