// Go encodes nil slices and maps as null. These helpers make the lists the UI
// iterates over safe to use as arrays, without changing any field names.

import type {
  Change,
  Commit,
  CommitDetail,
  CommitList,
  Diff,
  Graph,
  Impact,
  ImpactSet,
  RevisionList,
  RunList,
  SimulationRun,
  Summary,
  TestReport,
  Validation,
} from "./types";

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

// mosaicd returns graph nodes sorted by id; the fixtures keep document order.
// Put both into one canonical order (nodes by id, edges by from, to, kind, id)
// so the map's layout, member order and colors don't depend on the source.
export function normalizeGraph(g: Graph): Graph {
  return {
    nodes: (g.nodes ?? []).map((n) => ({ ...n, interfaces: n.interfaces ?? [] })).sort((a, b) => cmp(a.id, b.id)),
    edges: [...(g.edges ?? [])].sort((a, b) => cmp(a.from, b.from) || cmp(a.to, b.to) || cmp(a.kind, b.kind) || cmp(a.id, b.id)),
  };
}

export function normalizeDiff(d: Diff): Diff {
  return { ...d, changes: d.changes ?? [] };
}

export function normalizeValidation(v: Validation): Validation {
  return { ...v, issues: v.issues ?? [] };
}

export function normalizeSummary(s: Summary): Summary {
  return {
    ...s,
    calls: s.calls ?? {},
    ctx: s.ctx ?? {},
    state: s.state ?? {},
    initial_state: s.initial_state ?? {},
    assertions: s.assertions ?? [],
    warnings: s.warnings ?? [],
    calls_by_instance: s.calls_by_instance ?? {},
    steps: (s.steps ?? []).map((x) => ({ ...x, result: x.result ?? { ok: false } })),
    queued: s.queued ?? 0,
    mocks: s.mocks ?? 0,
    executed: s.executed ?? [],
  };
}

export function normalizeRun(r: SimulationRun): SimulationRun {
  return { ...r, request: r.request ?? {}, summary: normalizeSummary(r.summary), trace: r.trace ?? [] };
}

export function normalizeRuns(l: RunList): RunList {
  return { runs: (l.runs ?? []).map((r) => ({ ...r, request: r.request ?? {}, summary: normalizeSummary(r.summary) })) };
}

export function normalizeReport(r: TestReport): TestReport {
  return {
    ...r,
    results: (r.results ?? []).map((x) => ({ ...x, assertions: x.assertions ?? [] })),
  };
}

export function normalizeRevisions(l: RevisionList): RevisionList {
  return { revisions: l.revisions ?? [] };
}

export function normalizeCommit(c: Commit): Commit {
  return { ...c, files: c.files ?? [], changed: !!c.changed };
}

export function normalizeCommits(l: CommitList): CommitList {
  return { repo: l.repo ?? "", commits: (l.commits ?? []).map(normalizeCommit) };
}

function normalizeSet(s: ImpactSet | null | undefined): ImpactSet {
  return { added: s?.added ?? [], removed: s?.removed ?? [], modified: s?.modified ?? [], cited: s?.cited ?? [] };
}

export function normalizeImpact(i: Impact | null | undefined): Impact {
  return {
    components: normalizeSet(i?.components),
    interfaces: normalizeSet(i?.interfaces),
    links: normalizeSet(i?.links),
    schemas: normalizeSet(i?.schemas),
    flows: normalizeSet(i?.flows),
    scenarios: normalizeSet(i?.scenarios),
    configs: normalizeSet(i?.configs),
    fixtures: normalizeSet(i?.fixtures),
    flows_affected: (i?.flows_affected ?? []).map((f) => ({ ...f, reasons: f.reasons ?? [] })),
  };
}

export function normalizeCommitDetail(d: CommitDetail): CommitDetail {
  return {
    ...d,
    commit: normalizeCommit(d.commit),
    before: d.before ?? 0,
    after: d.after ?? 0,
    changes: (d.changes ?? []) as Change[],
    impact: d.impact ? normalizeImpact(d.impact) : null,
  };
}
