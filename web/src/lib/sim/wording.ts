// What a run's outcome and figures say, in words that never pass a simulated result off as
// a fact about the real system (docs/ux-review-2026-11.md, section 5).
//
// Only type imports here: node --test runs this file with type stripping.

import type { Summary } from "../api/types";

export type VerdictTone = "neutral" | "bad" | "warn";

export interface RunVerdict {
  /** "Failed as expected: 500 engine-dead-error". */
  text: string;
  /** Green is never one of these: a run's expectations are a self-check. */
  tone: VerdictTone;
}

/** "500 engine-dead-error" for a failed result. */
export function resultErrorText(s: Pick<Summary, "result">): string {
  const e = s.result.error;
  if (!e) return "error";
  return `${e.status ? `${e.status} ` : ""}${e.code ?? "error"}`;
}

/** One line for how a run ended, read against its expectations. */
export function runVerdict(s: Pick<Summary, "status" | "result" | "assertions" | "passed" | "abort">): RunVerdict {
  const expected = s.assertions.length > 0;
  const met = expected && s.passed;
  if (s.status === "ok") {
    if (met) return { text: "Passed, as the model expects", tone: "neutral" };
    if (expected) return { text: "Finished, but the model expected otherwise", tone: "bad" };
    return { text: "Finished, with no expectations to check", tone: "neutral" };
  }
  if (s.status === "error") {
    const err = resultErrorText(s);
    if (met) return { text: `Failed as expected: ${err}`, tone: "neutral" };
    if (expected) return { text: `Failed: ${err}, and the model expected otherwise`, tone: "bad" };
    return { text: `Failed: ${err}`, tone: "bad" };
  }
  return { text: s.abort ? `Stopped: ${s.abort}` : `Stopped: ${s.status}`, tone: "warn" };
}

/** A count and noun, with the noun's plural. */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "This run passed through 3 partial and 1 shell mechanism". Empty when there are none. */
export function mechanismSentence(items: readonly { fidelity: string }[]): string {
  if (items.length === 0) return "";
  const counts = (["partial", "shell", "absent"] as const)
    .map((f) => ({ f, n: items.filter((m) => m.fidelity === f).length }))
    .filter((p) => p.n > 0);
  const parts = counts.map((p) => `${p.n} ${p.f}`);
  const last = parts.pop();
  const joined = parts.length ? `${parts.join(", ")} and ${last}` : last;
  // The noun agrees with the count next to it: "3 partial and 1 shell mechanism".
  return `This run passed through ${joined} ${counts[counts.length - 1].n === 1 ? "mechanism" : "mechanisms"}`;
}

/** How many distinct instances a run's "<interface>@<instance>" call counts name. */
export function instanceCount(callsByInstance: Readonly<Record<string, number>> | undefined): number {
  const seen = new Set<string>();
  for (const k of Object.keys(callsByInstance ?? {})) seen.add(k.slice(k.lastIndexOf("@") + 1));
  return seen.size;
}
