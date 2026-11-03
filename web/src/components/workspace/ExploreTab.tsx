"use client";

// §16.6: exploration results. `check --explore` writes each failing
// schedule as a replay file (.mosaic/replay, §15.5); this lists the ones
// for this ontology's scenarios and replays them through mosaicd.

import Link from "next/link";
import { useRef, useState } from "react";
import { FIXTURE_MODE, getClient, isFixtureUnsupported } from "@/lib/api";
import type { ReplayFile, ReplayRun } from "@/lib/api/types";
import { formatDate, formatMs, plural, scenarioFlow } from "@/lib/model/format";
import { useDocIndex, useQuery } from "@/lib/hooks";
import { docIndex } from "@/lib/model/docindex";
import { Cel } from "@/components/json";
import { RunHeader, RunPlayback } from "@/components/playback/RunView";
import { Badge, Button, Empty, ErrorBox, Notice, Panel, Spinner, cx } from "@/components/ui";
import { useDocument, useWorkspace } from "./Workspace";

const KIND_TONE: Record<string, "info" | "violet" | "warn" | "neutral"> = { tie: "info", delivery: "info", jitter: "warn", branch: "violet", join: "violet" };

function ReplayCard({ rp, scenarioName, active, onReplay, busy }: { rp: ReplayFile; scenarioName?: string; active: boolean; onReplay: () => void; busy: boolean }) {
  const ws = useWorkspace();
  const doc = useDocument();
  const [showPoints, setShowPoints] = useState(false);
  const idx = useDocIndex(doc.data);
  const sc = idx?.scenariosById.get(rp.scenario);
  const deviations = rp.decisions.filter((d) => d !== 0).length;
  const points = rp.points ?? [];
  return (
    <li className={cx("rounded-lg border bg-panel", active ? "border-accent" : "border-line")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-soft px-3 py-2">
        <h3 className="text-[13.5px] font-semibold text-ink">{scenarioName || rp.scenario}</h3>
        <span className="font-mono text-[11px] text-faint">{rp.name}.replay.json</span>
        <Badge tone="bad">✗ failing schedule</Badge>
        <Badge>{plural(rp.decisions.length, "decision")}</Badge>
        {deviations > 0 && <Badge tone="accent">{plural(deviations, "deviation")} from default</Badge>}
        {rp.jitter_ms ? <Badge tone="warn">±{formatMs(rp.jitter_ms)} jitter</Badge> : null}
        <span className="ml-auto flex items-center gap-2">
          <span className="tnum text-[11px] text-faint">{formatDate(rp.modified)}</span>
          {sc && (
            <Link
              href={ws.href("simulate", { flow: scenarioFlow(sc), scenario: sc.id })}
              className="rounded border border-line px-1.5 py-0.5 text-[12px] text-link hover:bg-panel-2"
              title="The scenario on its default schedule"
            >
              Default schedule
            </Link>
          )}
          <Button size="sm" variant="primary" onClick={onReplay} disabled={busy}>
            {busy ? "Replaying…" : "▶ Replay"}
          </Button>
        </span>
      </div>
      <div className="space-y-2 px-3 py-2">
        {rp.failed?.length ? (
          <div>
            <div className="mb-0.5 text-[11px] text-faint">Failed under this schedule</div>
            <ul className="space-y-0.5">
              {rp.failed.map((f, i) => (
                <li key={i} className="flex items-baseline gap-1.5 text-[12px]">
                  <span className="text-bad">✗</span>
                  <Cel>{f}</Cel>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-1 text-[11.5px]">
          <span className="text-faint">decisions</span>
          <span className="font-mono text-muted">[{rp.decisions.join(", ")}]</span>
          {points.length > 0 && (
            <button type="button" className="ml-2 text-link hover:underline" onClick={() => setShowPoints((s) => !s)} aria-expanded={showPoints}>
              {showPoints ? "hide" : "show"} {plural(points.length, "choice point")}
            </button>
          )}
        </div>
        {showPoints && (
          <table className="w-full text-[11.5px]">
            <thead className="text-left text-[10.5px] uppercase tracking-[0.06em] text-faint">
              <tr>
                <th className="py-0.5 pr-2 font-medium">#</th>
                <th className="py-0.5 pr-2 font-medium">kind</th>
                <th className="py-0.5 pr-2 font-medium">at</th>
                <th className="py-0.5 pr-2 font-medium">choice</th>
                <th className="py-0.5 font-medium">alternatives</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={i} className={cx("border-t border-line-soft", p.choice !== 0 && "bg-[#1c2a10]/50")}>
                  <td className="py-0.5 pr-2 tnum text-faint">{i + 1}</td>
                  <td className="py-0.5 pr-2">
                    <Badge tone={KIND_TONE[p.kind] ?? "neutral"}>{p.kind}</Badge>
                  </td>
                  <td className="py-0.5 pr-2 tnum text-muted">{p.at_ms !== undefined ? formatMs(p.at_ms) : "—"}</td>
                  <td className={cx("py-0.5 pr-2 tnum", p.choice !== 0 ? "text-accent" : "text-muted")}>
                    {p.choice} of {p.n}
                  </td>
                  <td className="py-0.5 font-mono text-muted">{p.label ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </li>
  );
}

export function ExploreTab() {
  const ws = useWorkspace();
  const doc = useDocument();
  const replays = useQuery("replays", (c) => c.listReplays());
  const [result, setResult] = useState<ReplayRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  if (doc.error) return <div className="p-4"><ErrorBox error={doc.error} onRetry={doc.reload} /></div>;
  if (!doc.data) return <Spinner label="Loading" />;
  const ids = new Set(doc.data.scenarios.map((s) => s.id));
  const all = replays.data?.replays ?? [];
  const mine = all.filter((r) => ids.has(r.scenario));
  const others = all.length - mine.length;

  const replay = async (rp: ReplayFile) => {
    setBusy(rp.name);
    setError(null);
    try {
      const r = await getClient().runReplay(ws.id, rp.name, ws.rev);
      setResult(r);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-[15px] font-semibold text-ink">Exploration results</h2>
        <span className="font-mono text-[12px] text-faint">{replays.data?.dir ?? ".mosaic/replay"}</span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={replays.reload}>
          ↻ Reload
        </Button>
      </div>
      <p className="text-[12.5px] text-muted">
        <span className="font-mono">check --explore &lt;regex&gt; --schedules N</span> reruns scenarios under perturbed schedules and writes each failing
        schedule as a replay file. Replaying runs the scenario under that exact schedule at revision{" "}
        <span className="font-mono text-ink">{ws.rev}</span>; the run isn&apos;t saved.
      </p>
      {FIXTURE_MODE && (
        <Notice tone="warn" title="Fixture mode">
          Replays come from web/fixtures/replays.json; a replay plays back its recorded run when the fixtures have one, and otherwise needs a live mosaicd.
        </Notice>
      )}
      {replays.error ? <ErrorBox error={replays.error} onRetry={replays.reload} /> : null}
      {replays.loading && <Spinner label="Loading replay files" />}
      {replays.data && mine.length === 0 && (
        <Empty>
          No failing schedules for this ontology&apos;s scenarios{others > 0 ? ` (${plural(others, "replay file")} belong to other models)` : ""}.
        </Empty>
      )}
      {mine.length > 0 && (
        <Panel title={`Failing schedules · ${mine.length}`} bodyClassName="p-2">
          <ul className="space-y-2">
            {mine.map((rp) => (
              <ReplayCard
                key={rp.name}
                rp={rp}
                scenarioName={docIndex(doc.data!).scenariosById.get(rp.scenario)?.name}
                active={result?.replay.name === rp.name}
                busy={busy === rp.name}
                onReplay={() => replay(rp)}
              />
            ))}
          </ul>
          {others > 0 && <div className="mt-2 text-[11.5px] text-faint">{plural(others, "other replay file")} name scenarios this model doesn&apos;t have.</div>}
        </Panel>
      )}
      {error ? isFixtureUnsupported(error) ? <Notice tone="warn" title="Needs mosaicd">{(error as Error).message}</Notice> : <ErrorBox error={error} /> : null}
      {result && (
        <div ref={resultRef} className="scroll-mt-2 space-y-2">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-[12px]">
            <span className="text-faint">Replay of</span>
            <span className="font-mono text-ink">{result.replay.name}</span>
            {result.failures.length === 0 ? (
              <Badge tone="ok">✓ passes under its schedule now</Badge>
            ) : (
              <Badge tone="bad">✗ still fails: {plural(result.failures.length, "failure")}</Badge>
            )}
            {result.diverged && (
              <Badge tone="warn" title={result.diverged}>
                ! model changed since it was written
              </Badge>
            )}
            {result.diverged && <span className="text-faint">{result.diverged}</span>}
          </div>
          {result.failures.length > 0 && (
            <ul className="space-y-0.5 px-1">
              {result.failures.map((f, i) => (
                <li key={i} className="flex items-baseline gap-1.5 text-[12px]">
                  <span className="text-bad">✗</span>
                  <Cel>{f}</Cel>
                </li>
              ))}
            </ul>
          )}
          <RunHeader run={result.run} scenarioName={docIndex(doc.data).scenariosById.get(result.run.scenario ?? "")?.name} />
          <div className="flex h-[calc(100dvh-10.5rem)] min-h-[640px] flex-col">
            <RunPlayback key={`${result.replay.name}:${result.run.created_at}`} run={result.run} ontology={ws.id} className="min-h-0 flex-1" />
          </div>
        </div>
      )}
    </div>
  );
}
