"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useState } from "react";
import { getClient } from "@/lib/api";
import type { TestReport, TestResult } from "@/lib/api/types";
import { Cel } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, PassBadge, ProgressiveList, StatusBadge, cx } from "@/components/ui";
import { revLabel, useDocument, useWorkspace } from "./Workspace";

function OpenRun({ r }: { r: TestResult }) {
  const ws = useWorkspace();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (r.run_id) {
    return (
      <Link href={ws.href(`runs/${encodeURIComponent(r.run_id)}`)} className="inline-flex h-7 items-center rounded-md border border-line bg-panel-2 px-2 text-xs font-medium text-ink hover:bg-panel-3">
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
        title="This result has no saved run; run the scenario again and open it"
      >
        {busy ? "Running…" : "Run & open →"}
      </Button>
      {error ? <span className="text-[11px] text-bad">{error instanceof Error ? error.message : String(error)}</span> : null}
    </span>
  );
}

export function TestsTab() {
  const ws = useWorkspace();
  const doc = useDocument();
  const [report, setReport] = useState<TestReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [failedOnly, setFailedOnly] = useState(false);
  const scenarioCount = doc.data?.scenarios.length;

  const runAll = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await getClient().runTests(ws.id, ws.rev);
      setReport(r);
      setExpanded(Object.fromEntries(r.results.filter((x) => !x.passed).map((x) => [x.scenario, true])));
    } catch (err) {
      setError(err);
    } finally {
      setRunning(false);
    }
  };

  const results = (report?.results ?? []).filter((r) => !failedOnly || !r.passed);
  const assertTotal = report?.results.reduce((a, r) => a + r.assertions.length, 0) ?? 0;
  const assertPassed = report?.results.reduce((a, r) => a + r.assertions.filter((x) => x.passed).length, 0) ?? 0;

  return (
    <div className="mx-auto max-w-[1400px] space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel px-4 py-3">
        <div>
          <h2 className="text-[15px] font-semibold text-ink">Scenario tests</h2>
          <p className="text-[12.5px] text-muted">
            Runs every scenario at <span className="font-mono text-ink">{revLabel(ws.rev)}</span> and checks its expectations (
            <span className="font-mono">POST /test</span>).
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {report && (
            <label className="flex items-center gap-1.5 text-[12px] text-muted">
              <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} className="accent-[#ccff78]" />
              Failed only
            </label>
          )}
          <Button variant="primary" onClick={runAll} disabled={running} className="h-9 px-4 text-[14px]">
            {running ? "Running…" : report ? "↻ Run again" : `▶ Run all${scenarioCount !== undefined ? ` ${scenarioCount}` : ""} scenarios`}
          </Button>
        </div>
      </div>

      {error ? <ErrorBox error={error} /> : null}

      {report && (
        <div className="flex flex-wrap gap-2" aria-label="Test summary">
          <div className={cx("rounded-md border px-3 py-2", report.passed ? "border-[#1f4d2a] bg-[#11251a]" : "border-[#5c2a2a] bg-[#211214]")}>
            <div className="text-[10.5px] text-faint">Result</div>
            <div className={cx("text-[18px] font-semibold", report.passed ? "text-ok" : "text-bad")}>{report.passed ? "✓ all pass" : `✗ ${report.failed} failing`}</div>
          </div>
          <div className="rounded-md border border-line-soft bg-panel-2/60 px-3 py-2">
            <div className="text-[10.5px] text-faint">Scenarios</div>
            <div className="text-[18px] font-semibold text-ink">
              <span className="text-ok">{report.total - report.failed}</span>
              <span className="text-faint"> / {report.total}</span>
            </div>
          </div>
          <div className="rounded-md border border-line-soft bg-panel-2/60 px-3 py-2">
            <div className="text-[10.5px] text-faint">Assertions</div>
            <div className="text-[18px] font-semibold text-ink">
              <span className="text-ok">{assertPassed}</span>
              <span className="text-faint"> / {assertTotal}</span>
            </div>
          </div>
          <div className="rounded-md border border-line-soft bg-panel-2/60 px-3 py-2">
            <div className="text-[10.5px] text-faint">Revision</div>
            <div className="text-[18px] font-semibold text-ink">{revLabel(report.revision)}</div>
          </div>
        </div>
      )}

      {!report && !running && !error && <Empty>Run the scenarios to see a pass/fail table with each assertion.</Empty>}

      {report && (
        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full text-[12.5px]">
            <thead className="bg-panel-2 text-left text-[11px] uppercase tracking-[0.06em] text-faint">
              <tr>
                <th className="w-[84px] px-3 py-2 font-semibold">Outcome</th>
                <th className="px-3 py-2 font-semibold">Scenario</th>
                <th className="w-[100px] px-3 py-2 font-semibold">Run status</th>
                <th className="w-[120px] px-3 py-2 font-semibold">Assertions</th>
                <th className="w-[150px] px-3 py-2 text-right font-semibold">Run</th>
              </tr>
            </thead>
            <ProgressiveList
              as="tbody"
              key={`${failedOnly}`}
              items={results}
              step={200}
              render={(r) => {
                const ok = r.assertions.filter((a) => a.passed).length;
                const open = !!expanded[r.scenario];
                return (
                  <Fragment key={r.scenario}>
                    <tr className={cx("border-t border-line-soft align-top", r.passed ? "bg-panel" : "bg-[#1a1113]")}>
                      <td className="px-3 py-2">
                        <PassBadge passed={r.passed} />
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => setExpanded((m) => ({ ...m, [r.scenario]: !open }))}
                          aria-expanded={open}
                          className="flex items-baseline gap-2 text-left"
                        >
                          <span className="text-faint" aria-hidden>
                            {open ? "▾" : "▸"}
                          </span>
                          <span className="font-medium text-ink">{r.name || r.scenario}</span>
                          <span className="font-mono text-[11px] text-faint">{r.scenario}</span>
                          {r.steps ? <Badge tone="info" title="Multi-step scenario">{r.steps} steps</Badge> : null}
                          {r.mocks || r.mocked_calls ? (
                            <Badge tone="warn" title={`${r.mocks ?? 0} mocks declared, ${r.mocked_calls ?? 0} calls mocked in the run`}>
                              {r.mocks ?? 0} mocks · {r.mocked_calls ?? 0} mocked calls
                            </Badge>
                          ) : null}
                        </button>
                        {(r.abort || r.error) && <div className="ml-5 mt-0.5 text-[12px] text-bad">{r.abort || r.error}</div>}
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="px-3 py-2">
                        <span className="tnum">
                          <span className={ok === r.assertions.length ? "text-ok" : "text-bad"}>{ok}</span>
                          <span className="text-faint"> / {r.assertions.length}</span>
                        </span>
                        <span className="ml-2 inline-flex gap-[2px] align-middle" aria-hidden>
                          {r.assertions.map((a, i) => (
                            <span key={i} className={cx("inline-block h-2.5 w-1.5 rounded-[1px]", a.passed ? "bg-st-good" : "bg-st-critical")} />
                          ))}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <OpenRun r={r} />
                      </td>
                    </tr>
                    {open && (
                      <tr className={cx("border-t border-line-soft", r.passed ? "bg-panel" : "bg-[#1a1113]")}>
                        <td />
                        <td colSpan={4} className="px-3 pb-2.5 pt-0">
                          {r.assertions.length === 0 ? (
                            <div className="text-[12px] text-faint">No expectations.</div>
                          ) : (
                            <ul className="space-y-1">
                              {r.assertions.map((a, i) => (
                                <li key={i} className="flex items-baseline gap-2">
                                  <span className={a.passed ? "text-ok" : "text-bad"} aria-label={a.passed ? "passed" : "failed"}>
                                    {a.passed ? "✓" : "✗"}
                                  </span>
                                  <Cel>{a.expr}</Cel>
                                  {a.error && <Badge tone="bad">{a.error}</Badge>}
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              }}
            />
          </table>
          {results.length === 0 && <div className="p-4 text-center text-muted">Nothing failed.</div>}
        </div>
      )}
    </div>
  );
}
