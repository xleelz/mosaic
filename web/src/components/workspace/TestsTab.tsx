"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getClient } from "@/lib/api";
import type { Evidence, TestReport, TestResult } from "@/lib/api/types";
import { useEvidence } from "@/lib/evidence";
import { useDocIndex } from "@/lib/hooks";
import { OTHER, flowSectionKeys, type DocIndex } from "@/lib/model/docindex";
import { formatDate, plural, scenarioFlow } from "@/lib/model/format";
import { Cel } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, Select, Spinner, cx, inputClass } from "@/components/ui";
import { EvidenceNav } from "@/components/evidence/EvidenceNav";
import { blindFigure, measuredNote } from "@/components/evidence/mechanisms";
import {
  TEST_GROUPINGS,
  TEST_SORTS,
  elapsedLabel,
  filterTests,
  keepTracesHint,
  outcomeOf,
  selfCheckLine,
  sortTests,
  testRows,
  type TestGrouping,
  type TestRow,
  type TestSort,
} from "@/components/evidence/testlist";
import { useTestResults } from "@/components/evidence/useTestResults";
import { NOT_BENCHMARKED, SELF_CHECK_CAPTION } from "@/components/trust/passport";
import { WindowedList } from "@/components/WindowedList";
import { revLabel, useDocument, useWorkspace } from "./Workspace";

function OpenRun({ r }: { r: TestResult }) {
  const ws = useWorkspace();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (r.run_id) {
    return (
      <Link
        href={ws.href(`runs/${encodeURIComponent(r.run_id)}`)}
        title="Open the trace this test run kept"
        className="inline-flex h-7 items-center rounded-md border border-line bg-panel-2 px-2 text-xs font-medium text-ink hover:bg-panel-3"
      >
        Open run →
      </Link>
    );
  }
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button
        size="sm"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            const run = await getClient().runSimulation(ws.id, { rev: ws.rev, scenario: r.scenario });
            router.push(ws.href(`runs/${encodeURIComponent(run.id)}`));
          } catch (err) {
            setError(err);
            setBusy(false);
          }
        }}
        title="This test run kept no trace, so this runs the scenario again, saves that one run and opens it"
      >
        {busy ? "Running…" : "Run & open →"}
      </Button>
      {error ? <span className="text-[11px] text-bad">{error instanceof Error ? error.message : String(error)}</span> : null}
    </span>
  );
}

function Outcome({ r }: { r: TestResult }) {
  const o = outcomeOf(r);
  if (o === "fail") return <Badge tone="bad">✗ fail</Badge>;
  if (o === "failed-as-expected") {
    return <Badge title="The run ended in an error and every expectation holds: this is the failure the model expects">Failed as expected</Badge>;
  }
  return <Badge>pass</Badge>;
}

function RunStatus({ r }: { r: TestResult }) {
  if (r.status === "error") return <Badge tone={outcomeOf(r) === "failed-as-expected" ? "neutral" : "bad"}>error</Badge>;
  if (r.status === "aborted") return <Badge tone="warn">⊘ aborted</Badge>;
  return <Badge>{r.status}</Badge>;
}

const GRID = "grid grid-cols-[132px_minmax(0,1fr)_84px_130px_120px] gap-x-2 px-3";

function ResultRow({ r, open, onToggle }: { r: TestResult; open: boolean; onToggle: () => void }) {
  const ok = r.assertions.filter((a) => a.passed).length;
  return (
    <div className={cx("border-t border-line-soft", r.passed ? "bg-panel" : "bg-[#1a1113]")}>
      <div className={cx(GRID, "items-start py-2")}>
        <div>
          <Outcome r={r} />
        </div>
        <div className="min-w-0">
          <button type="button" onClick={onToggle} aria-expanded={open} className="block text-left [&>*]:mr-2">
            <span className="text-faint" aria-hidden>
              {open ? "▾" : "▸"}
            </span>
            <span className="font-medium text-ink">{r.name || r.scenario}</span>
            <span className="break-all font-mono text-[11px] text-faint">{r.scenario}</span>
            {r.steps ? <Badge tone="info" title="Multi-step scenario">{plural(r.steps, "step")}</Badge> : null}
            {r.mocks || r.mocked_calls ? (
              <Badge tone="warn" title={`${r.mocks ?? 0} mocks declared, ${r.mocked_calls ?? 0} calls mocked in the run`}>
                {r.mocks ?? 0} mocks · {r.mocked_calls ?? 0} mocked calls
              </Badge>
            ) : null}
          </button>
          {(r.abort || r.error) && <div className={cx("ml-5 mt-0.5 text-[12px]", r.passed ? "text-muted" : "text-bad")}>{r.abort || r.error}</div>}
        </div>
        <div>
          <RunStatus r={r} />
        </div>
        <div className="flex items-center">
          <span className="tnum">
            <span className={ok === r.assertions.length ? "text-ink" : "text-bad"}>{ok}</span>
            <span className="text-faint"> / {r.assertions.length}</span>
          </span>
          {r.assertions.length <= 16 && (
            <span className="ml-2 inline-flex gap-[2px]" aria-hidden>
              {r.assertions.map((a, i) => (
                <span key={i} className={cx("inline-block h-2.5 w-1.5 rounded-[1px]", a.passed ? "bg-faint" : "bg-st-critical")} />
              ))}
            </span>
          )}
        </div>
        <div className="text-right">
          <OpenRun r={r} />
        </div>
      </div>
      {open && (
        <div className="pb-2.5 pl-[152px] pr-3">
          {r.assertions.length === 0 ? (
            <div className="text-[12px] text-faint">No expectations.</div>
          ) : (
            <ul className="space-y-1">
              {r.assertions.map((a, i) => (
                <li key={i} className="flex items-baseline gap-2">
                  <span className={a.passed ? "text-muted" : "text-bad"} aria-label={a.passed ? "passed" : "failed"}>
                    {a.passed ? "✓" : "✗"}
                  </span>
                  <Cel>{a.expr}</Cel>
                  {a.error && <Badge tone="bad">{a.error}</Badge>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function GroupRow({ row }: { row: Extract<TestRow, { kind: "group" }> }) {
  return (
    <div className="flex items-baseline gap-2 border-t border-line bg-panel-2 px-3 py-1.5">
      <span className="text-[12.5px] font-semibold text-ink">{row.label}</span>
      <span className="tnum text-[11.5px] text-muted">
        {row.total - row.failed} of {row.total} pass
      </span>
      {row.failed > 0 && <Badge tone="bad">{row.failed} failing</Badge>}
    </div>
  );
}

function groupFn(by: TestGrouping, idx: DocIndex | undefined): ((r: TestResult) => string) | null {
  if (by === "none" || !idx) return null;
  return (r) => {
    const sc = idx.scenariosById.get(r.scenario);
    const flow = sc ? idx.flowsById.get(scenarioFlow(sc)) : undefined;
    if (!flow) return OTHER;
    return by === "flow" ? flow.name || flow.id : flowSectionKeys(flow, idx, "area")[0];
  };
}

function Caption({ report, evidence, viewed }: { report: TestReport; evidence: Evidence | null | undefined; viewed: string }) {
  const blind = blindFigure(evidence?.blind);
  return (
    <p className="rounded-lg border border-line bg-panel px-4 py-2.5 text-[13px] text-ink">
      <b className="font-semibold">{selfCheckLine(report)}</b> {SELF_CHECK_CAPTION}{" "}
      {blind && evidence?.blind ? (
        <span>
          {blind} ({measuredNote(evidence.blind.measured_on_revision, viewed)}).
        </span>
      ) : evidence !== undefined ? (
        <span className="text-muted">{NOT_BENCHMARKED}.</span>
      ) : null}
    </p>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line-soft bg-panel-2/60 px-3 py-1.5">
      <div className="text-[10.5px] text-faint">{label}</div>
      <div className="tnum text-[14px] font-semibold text-ink">{children}</div>
    </div>
  );
}

const estimateRow = (row: TestRow) => (row.kind === "group" ? 32 : row.result.passed ? 46 : 46 + row.result.assertions.length * 24);
const rowKey = (row: TestRow) => row.key;

export function TestsTab() {
  const ws = useWorkspace();
  const doc = useDocument();
  const idx = useDocIndex(doc.data);
  const stored = useTestResults();
  const { evidence } = useEvidence(ws.id, ws.rev);
  /** A run from this page, for the revision it ran at: the server may not record one (fixtures don't). */
  const [fresh, setFresh] = useState<{ rev: string; report: TestReport; ranAt: string } | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [keepTraces, setKeepTraces] = useState(false);
  const [error, setError] = useState<unknown>(null);
  /** Only what the reader toggled. By default, failures are open. */
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const [failedOnly, setFailedOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [grouping, setGrouping] = useState<TestGrouping>("none");
  const [sort, setSort] = useState<TestSort>("failed");
  const scenarioCount = doc.data?.scenarios.length;
  const running = startedAt !== null;
  const reloadStored = stored.reload;

  useEffect(() => {
    if (startedAt === null) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [startedAt]);

  const runAll = async () => {
    const t = Date.now();
    setStartedAt(t);
    setNow(t);
    setError(null);
    try {
      const report = await getClient().runTests(ws.id, ws.rev, { keepTraces });
      setFresh({ rev: ws.dataRev, report, ranAt: new Date().toISOString() });
      setToggled({});
      reloadStored();
    } catch (err) {
      setError(err);
    } finally {
      setStartedAt(null);
    }
  };

  const local = fresh?.rev === ws.dataRev ? fresh : null;
  const report: TestReport | null = local?.report ?? stored.data ?? null;
  const ranAt = local?.ranAt ?? stored.data?.ran_at;

  const groupOf = useMemo(() => groupFn(grouping, idx), [grouping, idx]);
  const rows = useMemo(() => {
    const areaOrFlow = groupFn(grouping === "none" ? "flow" : grouping, idx) ?? undefined;
    const matched = filterTests(report?.results ?? [], query, failedOnly, areaOrFlow);
    return testRows(sortTests(matched, sort), groupOf, OTHER);
  }, [report, query, failedOnly, sort, groupOf, grouping, idx]);
  const shownCount = rows.filter((r) => r.kind === "result").length;
  const assertTotal = report?.results.reduce((a, r) => a + r.assertions.length, 0) ?? 0;
  const assertPassed = report?.results.reduce((a, r) => a + r.assertions.filter((x) => x.passed).length, 0) ?? 0;
  const groupings = TEST_GROUPINGS.filter((g) => g.value !== "area" || (idx?.area.size ?? 0) > 0);

  const renderRow = useCallback(
    (row: TestRow) => {
      if (row.kind === "group") return <GroupRow row={row} />;
      const r = row.result;
      const open = toggled[r.scenario] ?? !r.passed;
      return <ResultRow r={r} open={open} onToggle={() => setToggled((m) => ({ ...m, [r.scenario]: !open }))} />;
    },
    [toggled],
  );

  return (
    <div className="mx-auto max-w-[1400px] space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-semibold text-ink">Evidence</h2>
        <EvidenceNav active="tests" />
      </div>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel px-4 py-3">
        <div>
          <h3 className="text-[14px] font-semibold text-ink">Self-checks</h3>
          <p className="text-[12.5px] text-muted">
            Runs every scenario at <span className="font-mono text-ink">{revLabel(ws.rev)}</span> and checks its expectations.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5 text-[12px] text-muted" title={keepTracesHint(scenarioCount)}>
            <input type="checkbox" checked={keepTraces} onChange={(e) => setKeepTraces(e.target.checked)} className="accent-[#ccff78]" />
            Keep traces
          </label>
          <Button variant="primary" onClick={runAll} disabled={running} className="h-9 px-4 text-[14px]">
            {running ? "Running…" : report ? "↻ Run again" : `▶ Run all${scenarioCount !== undefined ? ` ${scenarioCount}` : ""} scenarios`}
          </Button>
        </div>
      </div>

      {running && startedAt !== null && (
        <div role="status" className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel-2 px-4 py-2 text-[12.5px] text-ink">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden />
          <span>
            Running {scenarioCount !== undefined ? plural(scenarioCount, "scenario") : "every scenario"}: <span className="tnum">{elapsedLabel(now - startedAt)}</span> elapsed.
          </span>
          <span className="text-muted">
            The results arrive together when the last one finishes{report ? ", and the ones below are from the last run" : ""}.
          </span>
        </div>
      )}

      {error ? <ErrorBox error={error} /> : null}
      {stored.error ? <ErrorBox error={stored.error} onRetry={stored.reload} /> : null}
      {stored.loading && !report && <Spinner label="Loading the last run" />}

      {report && (
        <>
          <Caption report={report} evidence={evidence} viewed={ws.dataRev} />
          <div className="flex flex-wrap gap-2" aria-label="Test summary">
            <Stat label="Scenarios">
              {report.total - report.failed}
              <span className="text-faint"> of {report.total}</span>
              {report.failed > 0 && <span className="text-bad"> · {report.failed} failing</span>}
            </Stat>
            <Stat label="Assertions">
              {assertPassed}
              <span className="text-faint"> of {assertTotal}</span>
            </Stat>
            <Stat label="Revision">{revLabel(report.revision)}</Stat>
            <Stat label="Ran">{ranAt ? formatDate(ranAt) : "Not recorded"}</Stat>
          </div>
        </>
      )}

      {!report && !running && !stored.loading && !stored.error && !error && (
        <Empty>Not run yet at {revLabel(ws.rev)}. Run the scenarios to see a table with each assertion.</Empty>
      )}

      {report && (
        <>
          <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2">
            <input
              type="search"
              aria-label="Search scenarios"
              placeholder="Search names, ids, errors, expressions"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className={cx(inputClass, "h-7 min-w-[220px] flex-1 text-[12px]")}
            />
            <label className="flex items-center gap-1.5 text-[12px] text-muted">
              Group
              <Select value={grouping} onChange={(e) => setGrouping(e.target.value as TestGrouping)} className="h-7 text-[12px]">
                {groupings.map((g) => (
                  <option key={g.value} value={g.value}>
                    {g.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex items-center gap-1.5 text-[12px] text-muted">
              Sort
              <Select value={sort} onChange={(e) => setSort(e.target.value as TestSort)} className="h-7 text-[12px]">
                {TEST_SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex items-center gap-1.5 text-[12px] text-muted">
              <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} className="accent-[#ccff78]" />
              Failed only
            </label>
            <span role="status" className="tnum ml-auto text-[12px] text-muted">
              {shownCount} of {report.results.length}
            </span>
          </div>
          <div className="overflow-hidden rounded-lg border border-line text-[12.5px]">
            <div className={cx(GRID, "bg-panel-2 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-faint")} aria-hidden>
              <div>Outcome</div>
              <div>Scenario</div>
              <div>Run status</div>
              <div>Assertions</div>
              <div className="text-right">Run</div>
            </div>
            {rows.length > 0 ? (
              <WindowedList items={rows} itemKey={rowKey} estimate={estimateRow} label="Self-check results" render={renderRow} />
            ) : (
              <div className="p-4 text-center text-muted">{failedOnly && !query ? "Nothing failed." : "No scenario matches."}</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
