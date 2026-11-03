"use client";

// §16.6: the compose run store (.mosaic/compose/runs, §14.11), read-only.
// The list groups tasks by tree; a tree page shows the tree with stats, and
// the selected task's stages, change requests and artifacts.

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import type {
  ComposeAgentStats,
  ComposeChangeRequest,
  ComposeRunDetail,
  ComposeRunSummary,
  ComposeStageState,
  ComposeTree,
  ComposeTreeNode,
  JsonValue,
} from "@/lib/api/types";
import { formatDate, formatMs, isPlainObject, plural } from "@/lib/model/format";
import { FIXTURE_MODE } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { JsonView } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, Notice, Panel, Spinner, cx, type Tone } from "@/components/ui";

const enc = encodeURIComponent;

export function stateTone(state: string): Tone {
  switch (state) {
    case "done":
      return "ok";
    case "failed":
      return "bad";
    case "running":
      return "info";
    case "cancelled":
    case "interrupted":
      return "warn";
    default:
      return "neutral";
  }
}

const STATE_MARK: Record<string, string> = { done: "✓", failed: "✗", running: "●", pending: "○", skipped: "–", cancelled: "⊘", interrupted: "⊘" };

export function StateBadge({ state, reason }: { state: string; reason?: string }) {
  return (
    <Badge tone={stateTone(state)} title={reason ? `${state}: ${reason}` : state}>
      {STATE_MARK[state] ?? "·"} {state}
      {reason ? <span className="opacity-80">· {reason}</span> : null}
    </Badge>
  );
}

function agentText(a: ComposeAgentStats | undefined): string {
  if (!a || !a.sessions) return "";
  const parts = [`${plural(a.sessions, "session")}`, `${a.num_turns} turns`];
  if (a.duration_ms) parts.push(formatMs(a.duration_ms));
  if (a.total_cost_usd) parts.push(`$${a.total_cost_usd.toFixed(2)}`);
  return parts.join(" · ");
}

function wallBetween(start?: string, end?: string): number | undefined {
  if (!start || !end) return undefined;
  const ms = Date.parse(end) - Date.parse(start);
  return Number.isFinite(ms) && ms >= 0 ? ms : undefined;
}

// ------------------------------------------------------------------ list

export function ComposeRunList() {
  const runs = useQuery("compose:runs", (c) => c.listComposeRuns());
  const trees = useMemo(() => {
    const by = new Map<string, ComposeRunSummary[]>();
    for (const r of runs.data?.runs ?? []) {
      if (!by.has(r.tree_root)) by.set(r.tree_root, []);
      by.get(r.tree_root)!.push(r);
    }
    return Array.from(by.entries())
      .map(([root, tasks]) => ({ root, tasks, head: tasks.find((t) => t.id === root) ?? tasks[0] }))
      .sort((a, b) => b.head.updated.localeCompare(a.head.updated));
  }, [runs.data]);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-3 p-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[18px] font-semibold text-ink">Compose runs</h1>
        <span className="font-mono text-[12px] text-faint">{runs.data?.root ?? ".mosaic/compose/runs"}</span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={runs.reload}>
          ↻ Reload
        </Button>
      </div>
      <p className="text-[12.5px] text-muted">
        Run trees of the compose emulator (<span className="font-mono">mosaic compose run</span>): one tree per root task, with its children and
        detached zooms. Read-only.
      </p>
      {FIXTURE_MODE && (
        <Notice tone="warn" title="Fixture mode">
          Showing a recorded tree from web/fixtures/compose: a scripted run of the generation templates with a zoom into one component.
        </Notice>
      )}
      {runs.error ? <ErrorBox error={runs.error} onRetry={runs.reload} /> : null}
      {runs.loading && <Spinner label="Loading compose runs" />}
      {runs.data && trees.length === 0 && <Empty>No compose runs in the store.</Empty>}
      {trees.length > 0 && (
        <ul className="divide-y divide-line-soft overflow-hidden rounded-lg border border-line bg-panel">
          {trees.map(({ root, tasks, head }) => {
            const failed = tasks.filter((t) => t.state === "failed").length;
            const depth = Math.max(...tasks.map((t) => t.depth));
            return (
              <li key={root}>
                <Link href={`/compose/${enc(root)}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 hover:bg-panel-2">
                  <span className="font-mono text-[13px] font-semibold text-ink">{root}</span>
                  <StateBadge state={head.state} reason={head.reason} />
                  <span className="text-[12px] text-muted">
                    {head.workflow}
                    {head.version ? `@${head.version}` : ""}
                  </span>
                  <Badge>{plural(tasks.length, "task")}</Badge>
                  {depth > 1 && <Badge tone="info">depth {depth}</Badge>}
                  {failed > 0 && <Badge tone="bad">{failed} failed</Badge>}
                  <span className="ml-auto tnum text-[11.5px] text-faint" title={`created ${formatDate(head.created)}`}>
                    {formatDate(head.updated)}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ tree

function TreeRow({ node, selected, onSelect, depth }: { node: ComposeTreeNode; selected: string; onSelect: (id: string) => void; depth: number }) {
  const s = node.stats;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.id)}
        aria-current={selected === node.id ? "true" : undefined}
        className={cx(
          "flex w-full flex-col gap-0.5 rounded-md border px-2 py-1.5 text-left",
          selected === node.id ? "border-accent bg-[#1c2a10]/60" : "border-transparent hover:bg-panel-2",
        )}
        style={{ marginLeft: depth * 14, width: `calc(100% - ${depth * 14}px)` }}
      >
        <span className="flex flex-wrap items-center gap-1.5">
          {depth > 0 && (
            <span className="text-faint" aria-hidden>
              └
            </span>
          )}
          <span className="font-mono text-[12px] text-ink">{node.id}</span>
          <StateBadge state={node.state} reason={node.reason} />
          {node.detached && <Badge tone="violet">detached</Badge>}
          {node.requests?.length ? <Badge tone="warn">{plural(node.requests.length, "request")}</Badge> : null}
          {node.refusals?.length ? <Badge tone="bad">{plural(node.refusals.length, "refusal")}</Badge> : null}
        </span>
        <span className="flex flex-wrap gap-x-2 text-[11px] text-faint">
          <span>
            {node.workflow}
            {node.version ? `@${node.version}` : ""}
          </span>
          {s && s.wall_ms > 0 && <span>⏱ {formatMs(s.wall_ms)}</span>}
          {s && agentText(s.agent) && <span>{agentText(s.agent)}</span>}
        </span>
      </button>
      {node.children?.length ? (
        <ul className="mt-0.5 space-y-0.5">
          {node.children.map((c) => (
            <TreeRow key={c.id} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function findNode(n: ComposeTreeNode, id: string): ComposeTreeNode | undefined {
  if (n.id === id) return n;
  for (const c of n.children ?? []) {
    const hit = findNode(c, id);
    if (hit) return hit;
  }
  return undefined;
}

export function ComposeTreePage({ task }: { task: string }) {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tree = useQuery(`compose:tree:${task}`, (c) => c.getComposeTree(task));
  const selected = search.get("t") || task;
  const select = (id: string) => {
    const q = new URLSearchParams(search.toString());
    q.set("t", id);
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  };

  if (tree.error) {
    return (
      <div className="p-4">
        <ErrorBox error={tree.error} onRetry={tree.reload} />
      </div>
    );
  }
  if (!tree.data) return <Spinner label="Loading the run tree" />;
  const t: ComposeTree = tree.data;
  const node = findNode(t.root, selected) ?? t.root;

  return (
    <div className="flex h-[calc(100dvh-2.75rem)] min-h-[560px] flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-panel/60 px-4 py-2.5">
        <Link href="/compose" className="text-[12px] text-faint hover:text-ink">
          Compose runs
        </Link>
        <span className="text-faint">/</span>
        <h1 className="font-mono text-[15px] font-semibold text-ink">{t.root.id}</h1>
        <StateBadge state={t.root.state} reason={t.root.reason} />
        <span className="text-[12px] text-faint">
          {plural(t.tasks, "task")} · {plural(t.descendants, "descendant")} · max depth {t.max_depth}
          {t.stats && t.stats.wall_ms > 0 && <> · ⏱ {formatMs(t.stats.wall_ms)}</>}
          {t.stats && agentText(t.stats.agent) && <> · {agentText(t.stats.agent)}</>}
        </span>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={tree.reload}>
          ↻ Reload
        </Button>
      </div>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Run tree" className="w-[min(420px,36vw)] shrink-0 overflow-y-auto border-r border-line bg-panel p-2">
          <ul className="space-y-0.5">
            <TreeRow node={t.root} selected={node.id} onSelect={select} depth={0} />
          </ul>
        </nav>
        <div className="min-w-0 flex-1 overflow-y-auto p-3">
          <TaskDetail key={node.id} node={node} />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ task

/** Stage ids in template order, then any the record has that the template doesn't list. */
function stageOrder(detail: ComposeRunDetail): string[] {
  const tpl = detail.run.template;
  const out: string[] = [];
  if (isPlainObject(tpl) && Array.isArray(tpl.stages)) {
    for (const s of tpl.stages) if (isPlainObject(s) && typeof s.id === "string") out.push(s.id);
  }
  for (const id of Object.keys(detail.run.stages ?? {})) if (!out.includes(id)) out.push(id);
  return out.filter((id) => detail.run.stages?.[id]);
}

function stageKind(detail: ComposeRunDetail, id: string): string | undefined {
  const tpl = detail.run.template;
  if (!isPlainObject(tpl) || !Array.isArray(tpl.stages)) return undefined;
  const s = tpl.stages.find((x) => isPlainObject(x) && x.id === id);
  return isPlainObject(s) && typeof s.kind === "string" ? s.kind : undefined;
}

function TaskDetail({ node }: { node: ComposeTreeNode }) {
  const detail = useQuery(`compose:run:${node.id}`, (c) => c.getComposeRun(node.id));
  if (detail.error) return <ErrorBox error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return <Spinner label={`Loading ${node.id}`} />;
  const d = detail.data;
  const r = d.run;
  const stats = new Map((node.stats?.stages ?? []).map((s) => [s.stage, s]));
  const order = stageOrder(d);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="font-mono text-[15px] font-semibold text-ink">{r.id}</h2>
        <StateBadge state={r.state} reason={r.reason} />
        <span className="text-[12px] text-muted">
          {r.workflow}
          {r.version ? `@${r.version}` : ""}
        </span>
        <span className="text-[12px] text-faint">depth {r.depth}</span>
        {node.stats && node.stats.wall_ms > 0 && <span className="text-[12px] text-faint">⏱ {formatMs(node.stats.wall_ms)}</span>}
        {node.stats && agentText(node.stats.agent) && <span className="text-[12px] text-faint">{agentText(node.stats.agent)}</span>}
      </div>
      {r.error && (
        <div role="alert" className="rounded-md border border-[#5c2a2a] bg-[#2a1517] px-3 py-2 font-mono text-[12px] text-bad">
          {r.error}
        </div>
      )}
      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[12.5px]">
        {r.parent && (
          <>
            <dt className="text-faint">parent</dt>
            <dd className="font-mono text-ink">{r.parent}</dd>
          </>
        )}
        {r.origin && (
          <>
            <dt className="text-faint">admitted by</dt>
            <dd className="font-mono text-muted">
              {[r.origin.stage && `stage ${r.origin.stage}`, r.origin.visit && `visit ${r.origin.visit}`, r.origin.branch !== undefined && `branch ${r.origin.branch}`, r.origin.detached && "detached"]
                .filter(Boolean)
                .join(" · ")}
            </dd>
          </>
        )}
        {r.template_path && (
          <>
            <dt className="text-faint">template</dt>
            <dd className="font-mono text-muted">{r.template_path}</dd>
          </>
        )}
        <dt className="text-faint">out dir</dt>
        <dd className="break-all font-mono text-muted">{r.out_dir}</dd>
        <dt className="text-faint">created</dt>
        <dd className="tnum text-muted">
          {formatDate(r.created)} · updated {formatDate(r.updated)}
        </dd>
        {r.from_parent && Object.keys(r.from_parent).length > 0 && (
          <>
            <dt className="text-faint">from parent</dt>
            <dd className="font-mono text-[11.5px] text-muted">
              {Object.entries(r.from_parent)
                .map(([k, v]) => `${k} ← ${v}`)
                .join(" · ")}
            </dd>
          </>
        )}
      </dl>

      <Panel title={`Stages · ${order.length}`} bodyClassName="p-0">
        <table className="w-full text-[12px]">
          <thead className="text-left text-[11px] uppercase tracking-[0.06em] text-faint">
            <tr className="border-b border-line-soft">
              <th className="px-3 py-1.5 font-medium">stage</th>
              <th className="px-2 py-1.5 font-medium">state</th>
              <th className="px-2 py-1.5 font-medium">wall</th>
              <th className="px-2 py-1.5 font-medium">agent</th>
              <th className="px-3 py-1.5 font-medium">details</th>
            </tr>
          </thead>
          <tbody>
            {order.map((id) => (
              <StageRow key={id} id={id} kind={stageKind(d, id)} st={r.stages[id]} wall={stats.get(id)?.wall_ms} agent={stats.get(id)?.agent} branches={stats.get(id)?.branches} />
            ))}
          </tbody>
        </table>
      </Panel>

      <Requests requests={d.requests} />

      <Artifacts task={r.id} artifacts={r.artifacts ?? {}} outputs={node.outputs ?? []} />

      {Object.keys(d.turns ?? {}).length > 0 && (
        <Panel title={`Agent sessions · ${Object.keys(d.turns).length} stages`} bodyClassName="p-0">
          <table className="w-full text-[12px]">
            <thead className="text-left text-[11px] uppercase tracking-[0.06em] text-faint">
              <tr className="border-b border-line-soft">
                <th className="px-3 py-1.5 font-medium">stage</th>
                <th className="px-2 py-1.5 font-medium">turn.attempt</th>
                <th className="px-2 py-1.5 font-medium">turns</th>
                <th className="px-2 py-1.5 font-medium">duration</th>
                <th className="px-2 py-1.5 font-medium">cost</th>
                <th className="px-3 py-1.5 font-medium">session</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(d.turns)
                .sort(([a], [b]) => a.localeCompare(b))
                .flatMap(([stage, m]) =>
                  m.attempts.map((a, i) => (
                    <tr key={`${stage}:${i}`} className="border-t border-line-soft">
                      <td className="px-3 py-1 font-mono text-ink">{stage}</td>
                      <td className="px-2 py-1 tnum text-muted">
                        {a.turn}.{a.attempt}
                        {a.is_error && <span className="ml-1 text-bad">✗ {a.subtype}</span>}
                      </td>
                      <td className="px-2 py-1 tnum text-muted">{a.num_turns}</td>
                      <td className="px-2 py-1 tnum text-muted">{formatMs(a.duration_ms)}</td>
                      <td className="px-2 py-1 tnum text-muted">{a.total_cost_usd ? `$${a.total_cost_usd.toFixed(2)}` : "—"}</td>
                      <td className="px-3 py-1 font-mono text-[11px] text-faint">{a.session_id ?? ""}</td>
                    </tr>
                  )),
                )}
            </tbody>
          </table>
        </Panel>
      )}

      <details className="rounded-lg border border-line bg-panel px-3 py-2">
        <summary className="cursor-pointer text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">Inputs</summary>
        <JsonView value={r.inputs as JsonValue} className="mt-2" maxHeight={360} />
      </details>
    </div>
  );
}

function StageRow({
  id,
  kind,
  st,
  wall,
  agent,
  branches,
}: {
  id: string;
  kind?: string;
  st: ComposeStageState;
  wall?: number;
  agent?: ComposeAgentStats;
  branches?: number;
}) {
  const [open, setOpen] = useState(false);
  const ms = wall ?? wallBetween(st.started, st.finished);
  const hasBranches = (st.branches?.length ?? 0) > 0;
  return (
    <>
      <tr className="border-t border-line-soft align-baseline">
        <td className="px-3 py-1">
          <span className="font-mono text-ink">{id}</span>
          {kind && <span className="ml-1.5 text-[10.5px] text-faint">{kind}</span>}
        </td>
        <td className="px-2 py-1">
          <StateBadge state={st.state} reason={st.reason} />
        </td>
        <td className="whitespace-nowrap px-2 py-1 tnum text-muted">{ms !== undefined ? formatMs(ms) : "—"}</td>
        <td className="px-2 py-1 text-[11.5px] text-muted">{agentText(agent) || "—"}</td>
        <td className="px-3 py-1 text-[11.5px] text-faint">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            {st.visit ? <span>visit {st.visit}</span> : null}
            {st.count !== undefined && <span>{plural(st.count, "branch", "branches")}</span>}
            {branches ? <span>{branches} ran</span> : null}
            {st.children?.length ? <span className="font-mono">→ {st.children.join(", ")}</span> : null}
            {st.routed_to && <span>failure routed to {st.routed_to}</span>}
            {st.routed && <span>handles {st.routed.stage} ({st.routed.reason})</span>}
            {st.request && <span className="font-mono">request {st.request}</span>}
            {st.error && <span className="text-bad">{st.error}</span>}
            {hasBranches && (
              <button type="button" className="text-link hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
                {open ? "hide" : "show"} branches
              </button>
            )}
          </span>
        </td>
      </tr>
      {open &&
        st.branches!.map((b) => (
          <tr key={b.index} className="bg-panel-2/40 align-baseline">
            <td className="py-1 pl-8 pr-3 font-mono text-[11.5px] text-muted">
              [{b.index}]
            </td>
            <td className="px-2 py-1">
              <StateBadge state={b.state} reason={b.reason} />
            </td>
            <td className="px-2 py-1" />
            <td className="px-2 py-1" />
            <td className="px-3 py-1 text-[11.5px] text-faint">
              <span className="flex flex-wrap gap-x-2">
                {Object.entries(b.stages ?? {}).map(([sid, s]) => (
                  <span key={sid}>
                    <span className="font-mono text-muted">{sid}</span> {STATE_MARK[s.state] ?? s.state}
                    {wallBetween(s.started, s.finished) !== undefined && <span className="tnum"> {formatMs(wallBetween(s.started, s.finished)!)}</span>}
                  </span>
                ))}
                {b.error && <span className="text-bad">{b.error}</span>}
              </span>
            </td>
          </tr>
        ))}
    </>
  );
}

function Requests({ requests }: { requests: ComposeChangeRequest[] }) {
  return (
    <Panel title={`Change requests · ${requests.length}`}>
      {requests.length === 0 ? (
        <div className="text-[12px] text-faint">No change requests are addressed to this task.</div>
      ) : (
        <ul className="space-y-2">
          {requests.map((q) => (
            <li key={q.id} className="rounded-md border border-line-soft bg-panel-2/40 p-2">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
                <span className="font-mono text-ink">{q.id}</span>
                <Badge tone={q.state === "pending" ? "warn" : "neutral"}>{q.state}</Badge>
                <span className="text-faint">
                  from <span className="font-mono text-muted">{q.from_task}</span> · stage <span className="font-mono text-muted">{q.from_stage}</span>
                  {q.target.artifact && (
                    <>
                      {" "}
                      · on <span className="font-mono text-muted">{q.target.artifact}</span>
                    </>
                  )}
                </span>
                <span className="ml-auto tnum text-[11px] text-faint">{formatDate(q.recorded)}</span>
              </div>
              <JsonView value={q.body} className="mt-1.5" maxHeight={260} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Artifacts({ task, artifacts, outputs }: { task: string; artifacts: ComposeRunDetail["run"]["artifacts"]; outputs: string[] }) {
  const keys = Object.keys(artifacts).sort();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title={`Artifacts · ${keys.length}`} bodyClassName="p-0">
      {keys.length === 0 ? (
        <div className="p-3 text-[12px] text-faint">No artifacts recorded.</div>
      ) : (
        <ul className="divide-y divide-line-soft">
          {keys.map((k) => {
            const a = artifacts[k];
            return (
              <li key={k}>
                <button
                  type="button"
                  onClick={() => setOpen((o) => (o === k ? null : k))}
                  aria-expanded={open === k}
                  className="flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 px-3 py-1.5 text-left text-[12px] hover:bg-panel-2"
                >
                  <span className="text-faint" aria-hidden>
                    {open === k ? "▾" : "▸"}
                  </span>
                  <span className="font-mono text-ink">{k}</span>
                  {outputs.includes(k) && <Badge tone="accent">output</Badge>}
                  <span className="font-mono text-[11px] text-faint">{a.provenance}</span>
                  <span className="ml-auto tnum text-[11px] text-faint" title={`sha256 ${a.sha256}`}>
                    {formatDate(a.recorded)}
                  </span>
                </button>
                {open === k && (
                  <div className="px-3 pb-2">
                    <ArtifactBody task={task} k={k} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

function ArtifactBody({ task, k }: { task: string; k: string }) {
  const a = useQuery(`compose:artifact:${task}:${k}`, (c) => c.getComposeArtifact(task, k));
  if (a.error) return <ErrorBox error={a.error} onRetry={a.reload} />;
  if (a.loading) return <Spinner label={`Loading ${k}`} />;
  return <JsonView value={a.data} maxHeight={420} />;
}
