"use client";

import { useMemo, useState } from "react";
import type { Scenario, SimulationRun } from "@/lib/api/types";
import { getClient } from "@/lib/api";
import { docIndex } from "@/lib/model/docindex";
import { useQuery } from "@/lib/hooks";
import { runVerdict } from "@/lib/sim/wording";
import { Button, ErrorBox, Panel, Spinner, inputClass } from "@/components/ui";
import { RunCompare } from "./RunCompare";

/** How many runs to offer. */
const RUN_LIMIT = 200;
/** How many rows each list shows before asking for a filter. */
const LIST_CAP = 40;

function runLabel(run: Pick<SimulationRun, "scenario" | "flow" | "id">, names: ReadonlyMap<string, Scenario> | undefined): string {
  if (run.scenario) return names?.get(run.scenario)?.name || run.scenario;
  return `Ad hoc run of ${run.flow}`;
}

function setCompareParam(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("compare", id);
  else url.searchParams.delete("compare");
  window.history.replaceState(window.history.state, "", url);
}

/** A button on the run page, and the panel it opens: pick another run, and see the two side by side. */
export function CompareWith({ run, ontology, initial }: { run: SimulationRun; ontology: string; initial?: string }) {
  const [open, setOpen] = useState(!!initial);
  const [other, setOther] = useState<string | null>(initial ?? null);
  const [filter, setFilter] = useState("");
  const [starting, setStarting] = useState<string | null>(null);
  const [runError, setRunError] = useState<unknown>(null);

  const rev = run.revision || "draft";
  const doc = useQuery(open ? `doc:${ontology}:${rev}` : null, (c) => c.getDocument(ontology, rev));
  const runs = useQuery(open && !other ? `runs:${ontology}:${RUN_LIMIT}` : null, (c) => c.listRuns(ontology, RUN_LIMIT));
  const otherRun = useQuery(other ? `run:${other}` : null, (c) => c.getRun(other as string));
  const otherRev = otherRun.data?.revision || "draft";
  const otherDoc = useQuery(otherRun.data ? `doc:${ontology}:${otherRev}` : null, (c) => c.getDocument(ontology, otherRev));
  const names = doc.data ? docIndex(doc.data).scenariosById : undefined;
  const words = filter.trim().toLowerCase();
  const matches = (text: string) => !words || text.toLowerCase().includes(words);

  const choices = useMemo(() => {
    const list = (runs.data?.runs ?? []).filter((r) => r.id !== run.id);
    // The same flow's runs come first: the healthy path is usually one of them.
    return [...list.filter((r) => r.flow === run.flow), ...list.filter((r) => r.flow !== run.flow)];
  }, [runs.data, run.id, run.flow]);
  const scenarios = doc.data ? (docIndex(doc.data).scenariosByFlow.get(run.flow) ?? []).filter((s) => s.id !== run.scenario) : [];

  const choose = (id: string | null) => {
    setOther(id);
    setCompareParam(id);
  };
  const runScenario = async (s: Scenario) => {
    setStarting(s.id);
    setRunError(null);
    try {
      const made = await getClient().runSimulation(ontology, { scenario: s.id, rev: run.revision || "draft" });
      choose(made.id);
    } catch (err) {
      setRunError(err);
    } finally {
      setStarting(null);
    }
  };

  if (!open) {
    return (
      <Button size="sm" onClick={() => setOpen(true)}>
        Compare with...
      </Button>
    );
  }

  const close = () => {
    setOpen(false);
    choose(null);
  };

  return (
    <>
      <Button size="sm" onClick={close} aria-expanded>
        Compare with...
      </Button>
      <div className="absolute inset-2 z-30 flex min-h-0 flex-col">
        <Panel
          title={other ? "Compare two runs" : "Compare with..."}
          className="min-h-0 flex-1"
          bodyClassName="p-0"
          actions={
            <span className="flex items-center gap-2">
              {other && (
                <Button size="sm" variant="ghost" onClick={() => choose(null)}>
                  Choose another
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={close}>
                Close
              </Button>
            </span>
          }
        >
          {other ? (
            otherRun.error ? (
              <ErrorBox error={otherRun.error} className="m-3" />
            ) : !otherRun.data || otherDoc.loading ? (
              <Spinner label="Loading the other run" />
            ) : (
              <RunCompare
                left={{ run, label: runLabel(run, names), area: doc.data ? docIndex(doc.data).area : undefined }}
                right={{ run: otherRun.data, label: runLabel(otherRun.data, otherDoc.data ? docIndex(otherDoc.data).scenariosById : names), area: otherDoc.data ? docIndex(otherDoc.data).area : undefined }}
              />
            )
          ) : (
            <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto p-3">
              <input value={filter} onChange={(ev) => setFilter(ev.target.value)} placeholder="Filter runs and scenarios" aria-label="Filter runs and scenarios" className={inputClass} />
              {runError ? <ErrorBox error={runError} /> : null}
              {runs.error ? <ErrorBox error={runs.error} onRetry={runs.reload} /> : null}
              {runs.loading && <Spinner label="Loading runs" />}
              {scenarios.length > 0 && (
                <section aria-label="Scenarios of this flow">
                  <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Run a scenario of this flow, and compare</h4>
                  <ul className="space-y-0.5">
                    {scenarios
                      .filter((s) => matches(`${s.name ?? ""} ${s.id}`))
                      .slice(0, LIST_CAP)
                      .map((s) => (
                        <li key={s.id}>
                          <button type="button" disabled={starting !== null} onClick={() => runScenario(s)} className="w-full truncate rounded px-1.5 py-0.5 text-left text-[12px] text-link hover:bg-panel-2 disabled:opacity-50">
                            {starting === s.id ? "Running: " : ""}
                            {s.name || s.id}
                          </button>
                        </li>
                      ))}
                  </ul>
                </section>
              )}
              {choices.length > 0 && (
                <section aria-label="Stored runs">
                  <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Stored runs</h4>
                  <ul className="space-y-0.5">
                    {choices
                      .filter((r) => matches(`${runLabel(r, names)} ${r.flow} ${r.id}`))
                      .slice(0, LIST_CAP)
                      .map((r) => (
                        <li key={r.id}>
                          <button type="button" onClick={() => choose(r.id)} className="flex w-full items-baseline gap-2 rounded px-1.5 py-0.5 text-left text-[12px] hover:bg-panel-2">
                            <span className="min-w-0 truncate text-ink">{runLabel(r, names)}</span>
                            <span className="ml-auto shrink-0 text-[11px] text-faint">{runVerdict(r.summary).text}</span>
                          </button>
                        </li>
                      ))}
                  </ul>
                </section>
              )}
              {!runs.loading && choices.length === 0 && scenarios.length === 0 && <div className="text-[12px] text-faint">No other runs or scenarios to compare with.</div>}
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
