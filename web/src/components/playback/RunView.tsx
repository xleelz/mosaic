"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import type { SimulationRun } from "@/lib/api/types";
import { formatDate } from "@/lib/model/format";
import { useQuery } from "@/lib/hooks";
import { docIndex } from "@/lib/model/docindex";
import { Badge, ErrorBox, Spinner, StatusBadge } from "@/components/ui";
import { useWorkspace } from "@/components/workspace/Workspace";
import { Playback, type PlaybackLayout } from "./Playback";

export function RunHeader({ run, scenarioName, actions }: { run: SimulationRun; scenarioName?: string; actions?: ReactNode }) {
  const req = run.request;
  const overrides: string[] = [];
  if (req.choices && Object.keys(req.choices).length) overrides.push(`${Object.keys(req.choices).length} choices`);
  if (req.faults?.length) overrides.push(`${req.faults.length} faults`);
  if (req.state && Object.keys(req.state).length) overrides.push(`state: ${Object.keys(req.state).join(", ")}`);
  if (req.fixtures?.length) overrides.push(`fixtures: ${req.fixtures.join(", ")}`);
  if (req.topology && Object.keys(req.topology).length) overrides.push(`topology: ${Object.keys(req.topology).join(", ")}`);
  if (req.config && Object.keys(req.config).length) overrides.push(`config: ${Object.keys(req.config).join(", ")}`);
  if (req.clock?.epoch || req.clock?.epoch_ms) overrides.push(`clock ${req.clock.epoch ?? req.clock.epoch_ms}`);
  const refinedPaths = Object.entries(req.resolution ?? {}).filter(([, v]) => v === "refined").map(([c]) => c);
  if (refinedPaths.length) overrides.push(`refined: ${refinedPaths.join(", ")}`);
  const steps = run.summary.steps?.length ?? 0;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h2 className="text-[16px] font-semibold text-ink">{scenarioName || run.scenario || `Ad hoc run of ${run.flow}`}</h2>
      <StatusBadge status={run.summary.status} />
      {steps > 0 && <Badge tone="info">{steps} steps</Badge>}
      {run.summary.assertions.length > 0 && (run.summary.passed ? <Badge tone="ok">✓ expectations pass</Badge> : <Badge tone="bad">✗ expectations fail</Badge>)}
      <span className="text-[12px] text-faint">
        flow <span className="font-mono text-muted">{run.flow}</span>
        {run.scenario && (
          <>
            {" "}
            · scenario <span className="font-mono text-muted">{run.scenario}</span>
          </>
        )}{" "}
        · rev <span className="font-mono text-muted">{run.revision === "draft" ? "draft" : `r${run.revision}`}</span> · seed{" "}
        <span className="font-mono text-muted">{run.summary.seed}</span>
        {overrides.length > 0 && <> · {overrides.join(" · ")}</>}
      </span>
      <span className="ml-auto flex items-center gap-2 text-[11px] text-faint">
        {run.id && <span className="hidden font-mono 2xl:inline">{run.id}</span>}
        <span title={run.id}>{formatDate(run.created_at)}</span>
        {actions}
      </span>
    </div>
  );
}

/** Loads the document and graph at the run's revision and plays it back. */
export function RunPlayback({
  run,
  ontology,
  initialCursor,
  layout,
  className,
}: {
  run: SimulationRun;
  ontology: string;
  initialCursor?: number;
  layout?: PlaybackLayout;
  className?: string;
}) {
  const rev = run.revision || "draft";
  const doc = useQuery(`doc:${ontology}:${rev}`, (c) => c.getDocument(ontology, rev));
  const graph = useQuery(`graph:${ontology}:${rev}`, (c) => c.getGraph(ontology, rev));
  if (doc.loading || graph.loading) return <Spinner label="Loading the run's revision" />;
  return (
    <>
      {(doc.error || graph.error) ? <ErrorBox error={doc.error || graph.error} className="mb-2" /> : null}
      <Playback run={run} doc={doc.data} graph={graph.data} initialCursor={initialCursor} layout={layout} className={className} />
    </>
  );
}

export function RunPage({ ontology, runId, at }: { ontology: string; runId: string; at?: number }) {
  const { chromeSlot } = useWorkspace();
  const run = useQuery(`run:${runId}`, (c) => c.getRun(runId));
  const doc = useQuery(run.data ? `doc:${ontology}:${run.data.revision || "draft"}` : null, (c) => c.getDocument(ontology, run.data?.revision || "draft"));
  if (run.error) return <div className="p-4"><ErrorBox error={run.error} onRetry={run.reload} /></div>;
  if (!run.data) return <Spinner label="Loading run" />;
  const sc = doc.data && run.data.scenario ? docIndex(doc.data).scenariosById.get(run.data.scenario) : undefined;
  const header = (
    <RunHeader
      run={run.data}
      scenarioName={sc?.name}
      actions={
        <Link href={`/o/${encodeURIComponent(ontology)}/simulate?flow=${encodeURIComponent(run.data.flow)}${run.data.scenario ? `&scenario=${encodeURIComponent(run.data.scenario)}` : ""}`} className="rounded border border-line px-1.5 py-0.5 text-link hover:bg-panel-2">
          Configure a new run
        </Link>
      }
    />
  );
  // The title and meta lines live in the workspace's hidden header overlay, so
  // the summary, transport and diagrams get the whole viewport.
  return (
    <div className="flex h-full flex-col gap-2 p-3">
      {chromeSlot ? createPortal(header, chromeSlot) : header}
      <RunPlayback run={run.data} ontology={ontology} initialCursor={at !== undefined ? at - 1 : undefined} layout="page" className="min-h-0 flex-1" />
    </div>
  );
}
