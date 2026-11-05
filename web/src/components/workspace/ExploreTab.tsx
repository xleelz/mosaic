"use client";

// §16.6: race search, the UI's name for exploration. `check --explore` writes
// each failing schedule as a replay file (.mosaic/replay, §15.5). This lists the
// ones for this model's scenarios at the viewed revision, re-runs each to show
// whether it still fails, and removes the stale ones (DESIGN §6).

import Link from "next/link";
import { useRef, useState } from "react";
import { FIXTURE_MODE, getClient, isFixtureUnsupported } from "@/lib/api";
import type { ReplayFile, ReplayRun } from "@/lib/api/types";
import { formatDate, formatMs, plural, scenarioFlow } from "@/lib/model/format";
import { invalidate, limiter, useDocIndex, useQueries, useQuery, type QueryState } from "@/lib/hooks";
import { docIndex } from "@/lib/model/docindex";
import { Cel } from "@/components/json";
import { RunHeader, RunPlayback } from "@/components/playback/RunView";
import { Badge, Button, ErrorBox, Notice, Panel, Spinner, cx } from "@/components/ui";
import { EvidenceNav } from "@/components/evidence/EvidenceNav";
import { useDocument, useWorkspace } from "./Workspace";

const KIND_TONE: Record<string, "info" | "violet" | "warn" | "neutral"> = { tie: "info", delivery: "info", jitter: "warn", branch: "violet", join: "violet" };

/** Status re-runs share one queue: at most 3 replays run at a time. */
const statusQueue = limiter(3);
const STATUS_PREFIX = "replay-status:";

type Verdict = "fails" | "checking" | "unknown" | "passes";
const ORDER: Record<Verdict, number> = { fails: 0, checking: 1, unknown: 2, passes: 3 };

function verdict(st: QueryState<ReplayRun>): Verdict {
  if (st.data) return st.data.failures.length > 0 ? "fails" : "passes";
  return st.loading ? "checking" : "unknown";
}

function StatusBadge({ st }: { st: QueryState<ReplayRun> }) {
  const v = verdict(st);
  if (v === "checking")
    return (
      <span role="status" className="inline-flex items-center gap-1.5 text-[12px] text-muted">
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden />
        Checking…
      </span>
    );
  if (v === "fails") return <Badge tone="bad">✗ Still fails</Badge>;
  if (v === "passes")
    return (
      <Badge title="The recorded schedule passes on this revision: the race is gone from the model, and the file is stale">
        Passes now · stale
      </Badge>
    );
  const msg = st.error instanceof Error ? st.error.message : String(st.error);
  return isFixtureUnsupported(st.error) ? (
    <Badge tone="warn" title={msg}>? Unknown (needs mosaicd)</Badge>
  ) : (
    <Badge tone="warn" title={msg}>! Couldn&apos;t run</Badge>
  );
}

function FailureList({ items, tone }: { items: string[]; tone: "bad" | "faint" }) {
  return (
    <ul className="space-y-0.5">
      {items.map((f, i) => (
        <li key={i} className={cx("flex items-baseline gap-1.5 text-[12px]", tone === "faint" && "opacity-70")}>
          <span className={tone === "bad" ? "text-bad" : "text-faint"}>✗</span>
          <Cel>{f}</Cel>
        </li>
      ))}
    </ul>
  );
}

function ReplayCard({
  rp,
  st,
  scenarioName,
  active,
  onReplay,
  busy,
  onRemove,
  removing,
}: {
  rp: ReplayFile;
  st: QueryState<ReplayRun>;
  scenarioName?: string;
  active: boolean;
  onReplay: () => void;
  busy: boolean;
  onRemove: () => void;
  removing: boolean;
}) {
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
        <StatusBadge st={st} />
        {st.data?.diverged && (
          <Badge tone="warn" title={st.data.diverged}>
            ! model changed since it was written
          </Badge>
        )}
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
          {verdict(st) === "passes" && (
            <Button size="sm" variant="danger" onClick={onRemove} disabled={removing} title={`Delete ${rp.name}.replay.json: it passes on this revision`}>
              {removing ? "Removing…" : "Remove"}
            </Button>
          )}
          <Button size="sm" variant="primary" onClick={onReplay} disabled={busy}>
            {busy ? "Replaying…" : "▶ Replay"}
          </Button>
        </span>
      </div>
      <div className="space-y-2 px-3 py-2">
        {st.data && st.data.failures.length > 0 && (
          <div>
            <div className="mb-0.5 text-[11px] text-faint">Fails on this revision</div>
            <FailureList items={st.data.failures} tone="bad" />
          </div>
        )}
        {verdict(st) === "unknown" && !isFixtureUnsupported(st.error) && (
          <div className="text-[12px] text-warn">{st.error instanceof Error ? st.error.message : String(st.error)}</div>
        )}
        {rp.failed?.length ? (
          <div>
            <div className="mb-0.5 text-[11px] text-faint">Recorded when written ({formatDate(rp.modified)})</div>
            <FailureList items={rp.failed} tone="faint" />
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-1 text-[11.5px]">
          <span className="text-faint">decisions</span>
          <span className="font-mono text-muted">[{rp.decisions.join(", ")}]</span>
          {points.length > 0 && (
            <button type="button" className="ml-2 text-link hover:underline" onClick={() => setShowPoints((s) => !s)} aria-expanded={showPoints}>
              {showPoints ? "hide" : "show"} {plural(points.length, "open decision")}
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
  const replays = useQuery(`replays:${ws.id}:${ws.rev}`, (c) => c.listReplays({ ontology: ws.id, rev: ws.rev }));
  const mine = replays.data?.replays ?? [];
  const statuses = useQueries(
    mine.map((rp) => ({
      key: `${STATUS_PREFIX}${ws.id}:${ws.rev}:${rp.name}:${rp.modified}`,
      fn: (c) => statusQueue(() => c.runReplay(ws.id, rp.name, ws.rev)),
    })),
  );
  const [result, setResult] = useState<ReplayRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Set<string>>(new Set());
  const [error, setError] = useState<unknown>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  if (doc.error) return <div className="p-4"><ErrorBox error={doc.error} onRetry={doc.reload} /></div>;
  if (!doc.data) return <Spinner label="Loading" />;

  const rows = mine
    .map((rp, i) => ({ rp, st: statuses[i] }))
    .sort((a, b) => ORDER[verdict(a.st)] - ORDER[verdict(b.st)] || a.rp.name.localeCompare(b.rp.name));
  const count = (v: Verdict) => rows.filter((r) => verdict(r.st) === v).length;
  const failing = count("fails");
  const passing = rows.filter((r) => verdict(r.st) === "passes").map((r) => r.rp.name);
  const checking = count("checking");

  const reload = () => {
    invalidate(`${STATUS_PREFIX}${ws.id}:`);
    replays.reload();
  };

  const replay = async (rp: ReplayFile, known?: ReplayRun) => {
    setError(null);
    if (known) {
      setResult(known);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
      return;
    }
    setBusy(rp.name);
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

  const remove = async (names: string[]) => {
    setError(null);
    setRemoving((s) => new Set([...s, ...names]));
    try {
      for (const name of names) await getClient().deleteReplay(name);
    } catch (err) {
      setError(err);
    } finally {
      setRemoving((s) => new Set([...s].filter((n) => !names.includes(n))));
      if (result && names.includes(result.replay.name)) setResult(null);
      // Every ontology's list may have held the removed files.
      invalidate("replays:");
      replays.reload();
    }
  };

  const title = (
    <span className="flex flex-wrap items-center gap-2">
      <span>Replays · {mine.length}</span>
      {failing > 0 && <Badge tone="bad">{failing} still {failing === 1 ? "fails" : "fail"}</Badge>}
      {passing.length > 0 && <Badge>{passing.length} {passing.length === 1 ? "passes" : "pass"} now</Badge>}
      {checking > 0 && <Badge>{checking} checking</Badge>}
    </span>
  );

  return (
    <div className="mx-auto max-w-[1400px] space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-semibold text-ink">Evidence</h2>
        <EvidenceNav active="race-search" />
      </div>
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="text-[14px] font-semibold text-ink">Race search</h3>
        <span className="font-mono text-[12px] text-faint">{replays.data?.dir ?? ".mosaic/replay"}</span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={reload}>
          ↻ Reload
        </Button>
      </div>
      <p className="text-[12.5px] text-muted">
        A schedule is one order concurrent events could land in: which of two tied calls goes first, which message arrives next.
      </p>
      <p className="text-[12.5px] text-muted">
        <span className="font-mono">check --explore &lt;regex&gt; --schedules N</span> reruns scenarios under other schedules and writes each failing one as a
        replay file. Each replay of this model&apos;s scenarios is re-run here under its exact schedule at revision{" "}
        <span className="font-mono text-ink">{ws.rev}</span> (runs aren&apos;t saved): <b className="text-bad">Still fails</b> or{" "}
        <b className="text-ink">Passes now</b>, which means the race is gone from the model and the file is stale.
      </p>
      {FIXTURE_MODE && (
        <Notice tone="warn" title="Fixture mode">
          Replays come from web/fixtures/replays.json; a replay&apos;s status comes from its recorded run when the fixtures have one, and otherwise needs a
          live mosaicd. Removing one hides it for this session.
        </Notice>
      )}
      {replays.error ? <ErrorBox error={replays.error} onRetry={replays.reload} /> : null}
      {replays.loading && <Spinner label="Loading replay files" />}
      {replays.data && mine.length === 0 && (
        <div className="rounded-lg border border-dashed border-line bg-panel px-4 py-5 text-center">
          <div className="text-[14px] font-semibold text-ink">Not explored yet</div>
          <p className="mx-auto mt-1 max-w-[640px] text-[12.5px] text-muted">
            No race search has recorded a result for this model, so this says nothing about whether it has races. A search that finds no failure writes no file,
            so it would look the same here. To run one: <span className="font-mono">check --explore &lt;regex&gt; --schedules N</span>.
          </p>
        </div>
      )}
      {mine.length > 0 && (
        <Panel title={title} bodyClassName="p-2">
          <ul className="space-y-2">
            {rows.map(({ rp, st }) => (
              <ReplayCard
                key={rp.name}
                rp={rp}
                st={st}
                scenarioName={docIndex(doc.data!).scenariosById.get(rp.scenario)?.name}
                active={result?.replay.name === rp.name}
                busy={busy === rp.name}
                onReplay={() => replay(rp, st.data)}
                onRemove={() => remove([rp.name])}
                removing={removing.has(rp.name)}
              />
            ))}
          </ul>
          {passing.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line-soft px-1 pt-2">
              <Button size="sm" variant="danger" onClick={() => remove(passing)} disabled={passing.some((n) => removing.has(n))}>
                Remove all passing ({passing.length})
              </Button>
              <span className="text-[12px] text-muted">Deletes these replay files for good. They pass on this revision, but may still fail on another.</span>
            </div>
          )}
        </Panel>
      )}
      {error ? isFixtureUnsupported(error) ? <Notice tone="warn" title="Needs mosaicd">{(error as Error).message}</Notice> : <ErrorBox error={error} /> : null}
      {result && (
        <div ref={resultRef} className="scroll-mt-2 space-y-2">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-[12px]">
            <span className="text-faint">Replay of</span>
            <span className="font-mono text-ink">{result.replay.name}</span>
            {result.failures.length === 0 ? (
              <Badge>passes under its schedule now</Badge>
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
