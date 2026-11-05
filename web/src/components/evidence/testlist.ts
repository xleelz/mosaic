// Pure logic for the Tests section: wording, search, sort and groups. Kept free of React and "@/"
// imports so `pnpm test` can run it.

import type { TestReport, TestResult } from "../../lib/api/types";

/** "1805 of 1805 self-checks pass." */
export function selfCheckLine(report: Pick<TestReport, "total" | "failed">): string {
  return `${report.total - report.failed} of ${report.total} self-checks pass.`;
}

export type TestOutcome = "pass" | "fail" | "failed-as-expected";

/** The run ended in an error and its expectations hold: the model expects this failure. */
export function outcomeOf(r: Pick<TestResult, "passed" | "status" | "assertions">): TestOutcome {
  if (!r.passed) return "fail";
  return r.status === "error" && r.assertions.length > 0 ? "failed-as-expected" : "pass";
}

export type TestSort = "failed" | "model" | "name" | "assertions";
export const TEST_SORTS: { value: TestSort; label: string }[] = [
  { value: "failed", label: "Failed first" },
  { value: "model", label: "Model order" },
  { value: "name", label: "Name" },
  { value: "assertions", label: "Most assertions" },
];

export type TestGrouping = "none" | "area" | "flow";
export const TEST_GROUPINGS: { value: TestGrouping; label: string }[] = [
  { value: "none", label: "No grouping" },
  { value: "area", label: "Area" },
  { value: "flow", label: "Flow" },
];

function titleOf(r: TestResult): string {
  return r.name || r.scenario;
}

/** A result's search text matches every word; `labels` adds what the row is grouped under. */
export function filterTests(results: TestResult[], query: string, failedOnly: boolean, labels?: (r: TestResult) => string): TestResult[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return results.filter((r) => {
    if (failedOnly && r.passed) return false;
    if (words.length === 0) return true;
    const hay = [r.name, r.scenario, r.status, r.abort, r.error, labels?.(r), ...r.assertions.map((a) => a.expr)].filter(Boolean).join("\n").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** A new sorted list. Ties keep the model's order. */
export function sortTests(results: TestResult[], by: TestSort): TestResult[] {
  if (by === "model") return results;
  const cmp: Record<Exclude<TestSort, "model">, (a: TestResult, b: TestResult) => number> = {
    failed: (a, b) => Number(a.passed) - Number(b.passed),
    name: (a, b) => titleOf(a).localeCompare(titleOf(b)),
    assertions: (a, b) => b.assertions.length - a.assertions.length,
  };
  return results
    .map((r, i) => ({ r, i }))
    .sort((a, b) => cmp[by](a.r, b.r) || a.i - b.i)
    .map((x) => x.r);
}

export type TestRow =
  | { kind: "group"; key: string; label: string; total: number; failed: number }
  | { kind: "result"; key: string; result: TestResult };

/**
 * The flat rows to window. Grouped, sections with failures come first, then the largest, then by
 * name, with `other` always last. Results keep their order inside a section.
 */
export function testRows(results: TestResult[], groupOf: ((r: TestResult) => string) | null, other: string): TestRow[] {
  if (!groupOf) return results.map((r) => ({ kind: "result", key: r.scenario, result: r }));
  const groups = new Map<string, TestResult[]>();
  for (const r of results) {
    const g = groupOf(r);
    const list = groups.get(g);
    if (list) list.push(r);
    else groups.set(g, [r]);
  }
  const failedIn = (l: TestResult[]) => l.filter((r) => !r.passed).length;
  const sorted = [...groups.entries()].sort(([a, la], [b, lb]) => {
    if ((a === other) !== (b === other)) return a === other ? 1 : -1;
    return Number(failedIn(lb) > 0) - Number(failedIn(la) > 0) || lb.length - la.length || a.localeCompare(b);
  });
  const rows: TestRow[] = [];
  for (const [label, list] of sorted) {
    rows.push({ kind: "group", key: `group:${label}`, label, total: list.length, failed: failedIn(list) });
    for (const r of list) rows.push({ kind: "result", key: r.scenario, result: r });
  }
  return rows;
}

/** "9 s", "1 min 05 s". */
export function elapsedLabel(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

/** What the "keep traces" toggle costs, for its label. */
export function keepTracesHint(scenarios: number | undefined): string {
  const n = scenarios === undefined ? "one run" : `${scenarios} ${scenarios === 1 ? "run" : "runs"}`;
  return `Saves ${n}${scenarios === undefined ? " per scenario" : ", one per scenario"}, so each row can open what ran. Off by default: traces take storage.`;
}
