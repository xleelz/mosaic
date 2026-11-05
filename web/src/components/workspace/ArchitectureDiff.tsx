"use client";

// The Architecture tab's before/after mode: ?commit=<sha>, or ?before=N&after=M.
// The union of both graphs is focused on the change (changed components, their
// direct neighbours dimmed, and compact parent containers holding only those),
// then laid out once. The overlay draws it with added, modified and removed
// components marked; side by side draws BEFORE and AFTER from the same layout
// so positions line up. The view opens fitted to the changed components.

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import type { Viewport } from "@xyflow/react";
import type { Change, Graph, Impact } from "@/lib/api/types";
import { ifaceComponent, plural } from "@/lib/model/format";
import type { ChangeKind } from "@/lib/model/impact";
import { useQuery } from "@/lib/hooks";
import { ArchitectureMap, MapLegend, useColorScale } from "@/components/map/ArchitectureMap";
import { DIFF_COLORS, HUB_DEGREE, focusDiff, memberCounts, subgraph, unionDiff, type DiffStatus } from "@/components/map/graphview";
import { ChangeView } from "@/components/diff";
import { Badge, Button, Empty, ErrorBox, Spinner, cx } from "@/components/ui";
import { shortSha, useCommitDetail, useWorkspace } from "./Workspace";

const EMPTY: Graph = { nodes: [], edges: [] };
const NO_IDS: string[] = [];

type Scope = "changes" | "neighbours" | "hop2" | "all";
const SCOPES: { key: Scope; label: string; title: string }[] = [
  { key: "changes", label: "Changes", title: "Only the changed components, inside their parent groups" },
  { key: "neighbours", label: "+ neighbours", title: "The changed components and their direct call neighbours (dimmed)" },
  { key: "hop2", label: "+ neighbours of neighbours", title: `One more hop out. Hubs with more than ${HUB_DEGREE} call partners aren't expanded; click one to expand it` },
  { key: "all", label: "Everything", title: "The whole model, with the changes marked" },
];

interface Source {
  title: ReactNode;
  before: number;
  after: number;
  changes: Change[];
  impact: Impact | null;
}

function useDiffSource(): { data?: Source; error: unknown; reload: () => void } {
  const ws = useWorkspace();
  const search = useSearchParams();
  const sha = search.get("commit");
  const b = search.get("before");
  const a = search.get("after");
  const commit = useCommitDetail(sha);
  // A missing or zero `before` compares against "base", the empty model before r1.
  const pair = !sha && a ? { before: b && b !== "0" ? b : "base", after: a } : null;
  const diff = useQuery(pair ? `diff:${ws.id}:${pair.before}:${pair.after}` : null, (c) => c.diff(ws.id, pair!.before, pair!.after));
  const impact = useQuery(pair ? `impact:${ws.id}:${pair.before}:${pair.after}` : null, (c) => c.impact(ws.id, pair!.before, pair!.after));
  const d = sha ? commit.data : undefined;
  const href = d ? ws.href("commits", { sha: d.commit.sha }) : "";
  // Memoized so the union graph (and its layout) isn't rebuilt on every render.
  const commitData = useMemo<Source | undefined>(
    () =>
      d && {
        title: (
          <>
            <Link href={href} className="font-mono text-link hover:underline">
              {shortSha(d.commit.sha)}
            </Link>{" "}
            <span className="text-ink">{d.commit.subject}</span>
          </>
        ),
        before: d.before,
        after: d.after,
        changes: d.changes,
        impact: d.impact,
      },
    [d, href],
  );
  const pairBefore = pair?.before;
  const pairAfter = pair?.after;
  const pairData = useMemo<Source | undefined>(
    () =>
      pairAfter && diff.data && impact.data
        ? { title: <span className="text-ink">Revision diff</span>, before: Number(pairBefore) || 0, after: Number(pairAfter), changes: diff.data.changes, impact: impact.data }
        : undefined,
    [pairBefore, pairAfter, diff.data, impact.data],
  );
  if (sha) return { error: commit.error, reload: commit.reload, data: commitData };
  return {
    error: diff.error || impact.error,
    reload: () => {
      diff.reload();
      impact.reload();
    },
    data: pairData,
  };
}

function useRevGraph(rev: number | undefined) {
  const ws = useWorkspace();
  return useQuery(rev ? `graph:${ws.id}:${rev}` : null, (c) => c.getGraph(ws.id, String(rev)));
}

/** Keeps only the statuses a side shows: BEFORE has no added nodes, AFTER no removed ones. */
function sideStatus(s: DiffStatus, drop: ChangeKind): DiffStatus {
  const keep = <K,>(m: Map<K, ChangeKind>) => new Map(Array.from(m).filter(([, v]) => v !== drop));
  return { nodes: keep(s.nodes), edges: keep(s.edges), ifaces: s.ifaces };
}

export function DiffLegend() {
  const items: [ChangeKind, string][] = [
    ["added", "added"],
    ["modified", "modified"],
    ["removed", "removed (ghost from before)"],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted" aria-label="Diff legend">
      {items.map(([k, label]) => (
        <span key={k} className="inline-flex items-center gap-1">
          <span
            className="inline-block h-3 w-4 rounded-[3px] border-2"
            style={{ borderColor: DIFF_COLORS[k], borderStyle: k === "removed" ? "dashed" : "solid" }}
            aria-hidden
          />
          {label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1">
        <svg width="22" height="6" aria-hidden>
          <line x1="0" y1="3" x2="22" y2="3" stroke={DIFF_COLORS.added} strokeWidth="2" />
        </svg>
        <svg width="22" height="6" aria-hidden>
          <line x1="0" y1="3" x2="22" y2="3" stroke={DIFF_COLORS.removed} strokeWidth="2" strokeDasharray="6 4" />
        </svg>
        changed edges
      </span>
      <span className="inline-flex items-center gap-1">
        <span className="inline-block h-3 w-4 rounded-[3px] border border-line opacity-40" aria-hidden />
        unchanged
      </span>
    </div>
  );
}

function DiffPanel({
  id,
  graph,
  status,
  changes,
  after,
  onClose,
  onSelect,
}: {
  id: string;
  graph: Graph;
  status: DiffStatus;
  changes: Change[];
  after: number;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const ws = useWorkspace();
  const node = graph.nodes.find((n) => n.id === id);
  const st = status.nodes.get(id);
  const own = changes.filter((c) => (c.kind === "component" && c.id === id) || (c.kind === "interface" && ifaceComponent(c.id) === id));
  const edges = graph.edges.filter((e) => (e.from === id || e.to === id) && status.edges.has(e.id));
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start gap-2 border-b border-line-soft px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold text-ink">{node?.name ?? id}</h3>
            {st ? (
              <Badge tone={st === "added" ? "ok" : st === "removed" ? "bad" : "warn"}>{st}</Badge>
            ) : (
              <Badge>unchanged</Badge>
            )}
          </div>
          <div className="font-mono text-[11px] text-faint">
            {id}
            {node?.kind ? ` · ${node.kind}` : ""}
            {node?.parent ? ` · in ${node.parent}` : ""}
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close panel">
          ✕
        </Button>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {own.length === 0 ? (
          <div className="text-[12.5px] text-muted">
            {st ? "Only its edges changed." : "Not changed by this commit."}
            {st !== "removed" && after > 0 && (
              <>
                {" "}
                <Link href={ws.href("map", { rev: String(after), c: id })} className="text-link hover:underline">
                  Open it at r{after}
                </Link>
                .
              </>
            )}
          </div>
        ) : (
          <section>
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Field diff · before → after</h4>
            <ul className="space-y-1.5">
              {own.map((c) => (
                <ChangeView key={`${c.kind}:${c.id}`} c={c} defaultOpen={c.kind === "component" || own.length <= 3} />
              ))}
            </ul>
          </section>
        )}
        {edges.length > 0 && (
          <section>
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Changed edges</h4>
            <ul className="space-y-1 text-[12px]">
              {edges.map((e) => {
                const k = status.edges.get(e.id)!;
                const other = e.from === id ? e.to : e.from;
                return (
                  <li key={e.id} className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={k === "added" ? "ok" : k === "removed" ? "bad" : "warn"}>{k}</Badge>
                    <span className="text-faint">{e.from === id ? "→" : "←"}</span>
                    <button type="button" className="font-mono text-link hover:underline" onClick={() => onSelect(other)}>
                      {other}
                    </button>
                    <span className="text-faint">
                      {e.kind}
                      {e.label ? ` · ${e.label}` : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        {st !== "removed" && after > 0 && own.length > 0 && (
          <Link href={ws.href("map", { rev: String(after), c: id })} className="inline-block text-[12px] text-link hover:underline">
            Open {node?.name ?? id} at r{after} →
          </Link>
        )}
      </div>
    </div>
  );
}

export function ArchitectureDiff() {
  const ws = useWorkspace();
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const src = useDiffSource();
  const beforeG = useRevGraph(src.data?.before);
  const afterG = useRevGraph(src.data?.after);
  const [mode, setMode] = useState<"overlay" | "side">(search.get("view") === "side" ? "side" : "overlay");
  const [scope, setScope] = useState<Scope>("neighbours");
  // Components whose neighbours were added by clicking them, for one diff.
  const [expanded, setExpanded] = useState<{ key: string; ids: string[] }>({ key: "", ids: [] });
  const [fitNonce, setFitNonce] = useState(0);
  const [viewport, setViewport] = useState<Viewport | undefined>(undefined);
  const selected = search.get("c");

  const select = useCallback(
    (id: string | null) => {
      const q = new URLSearchParams(search.toString());
      if (id) q.set("c", id);
      else q.delete("c");
      router.replace(`${pathname}?${q.toString()}`, { scroll: false });
    },
    [pathname, router, search],
  );

  const bg = src.data && !src.data.before ? EMPTY : beforeG.data;
  const ag = afterG.data;
  const union = useMemo(() => (bg && ag && src.data ? unionDiff(bg, ag, src.data.impact) : null), [bg, ag, src.data]);
  const diffKey = src.data ? `${src.data.before}:${src.data.after}` : "";
  const expandedIds = expanded.key === diffKey ? expanded.ids : NO_IDS;
  const totals = useMemo(() => (union ? memberCounts(union.graph) : new Map<string, number>()), [union]);
  const focus = useMemo(
    () => (union ? focusDiff(union.graph, union.status, { hops: scope === "changes" ? 0 : scope === "hop2" ? 2 : 1, expand: expandedIds }) : null),
    [union, scope, expandedIds],
  );
  const noChanges = !!union && union.status.nodes.size + union.status.edges.size === 0;
  const scoped = useMemo(() => {
    if (!union || !focus) return null;
    return scope === "all" || noChanges ? union.graph : focus.graph;
  }, [union, focus, scope, noChanges]);
  const fitTo = useMemo(() => (focus && !noChanges ? [...focus.changed, ...expandedIds] : undefined), [focus, noChanges, expandedIds]);
  const onMapSelect = useCallback(
    (id: string | null) => {
      // Clicking an unchanged component or a hub (not a group) also draws its neighbours.
      const expandable = !!id && !!union && (!union.status.nodes.has(id) || !!focus?.hubs.includes(id));
      if (id && expandable && scope !== "all" && !totals.has(id) && !expandedIds.includes(id))
        setExpanded({ key: diffKey, ids: [...expandedIds, id] });
      select(id);
    },
    [union, focus, scope, totals, expandedIds, diffKey, select],
  );
  const sides = useMemo(() => {
    if (!scoped || !bg || !ag || !union) return null;
    const bIds = new Set(bg.nodes.map((n) => n.id));
    const aIds = new Set(ag.nodes.map((n) => n.id));
    return {
      before: subgraph(scoped, bIds),
      after: subgraph(scoped, aIds),
      beforeStatus: sideStatus(union.status, "added"),
      afterStatus: sideStatus(union.status, "removed"),
    };
  }, [scoped, bg, ag, union]);
  const scale = useColorScale(union?.graph, "layer");
  const memberTotals = scope === "all" ? undefined : totals;
  const overlayDiff = useMemo(() => (union ? { status: union.status, dimUnchanged: true, memberTotals } : undefined), [union, memberTotals]);
  const beforeDiff = useMemo(() => (sides ? { status: sides.beforeStatus, dimUnchanged: true, memberTotals } : undefined), [sides, memberTotals]);
  const afterDiff = useMemo(() => (sides ? { status: sides.afterStatus, dimUnchanged: true, memberTotals } : undefined), [sides, memberTotals]);

  const error = src.error || beforeG.error || afterG.error;
  if (error)
    return (
      <div className="p-4">
        <ErrorBox error={error} onRetry={() => { src.reload(); beforeG.reload(); afterG.reload(); }} />
      </div>
    );
  if (src.data && !src.data.after)
    return (
      <div className="p-4">
        <Empty>
          No revision models this commit, so there is no architecture to compare. <Link href={ws.href("map")} className="text-link">Back to the map</Link>
        </Empty>
      </div>
    );
  if (!src.data || !union || !scoped || !sides || !focus) return <Spinner label="Loading both revisions" />;

  const counts = { added: 0, modified: 0, removed: 0 };
  for (const v of union.status.nodes.values()) counts[v]++;
  const hiddenCount = union.graph.nodes.length - scoped.nodes.length;
  const node = selected ? union.graph.nodes.find((n) => n.id === selected) : undefined;
  const changedIds = Array.from(union.status.nodes.keys()).sort();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line-soft px-4 py-2 text-[12px]">
        <div className="flex min-w-0 items-center gap-2">
          <Link href={ws.href("map")} className="text-faint hover:text-ink" title="Back to the normal map">
            ← Map
          </Link>
          <span className="min-w-0 truncate">{src.data.title}</span>
          <span className="font-mono text-faint">
            {src.data.before ? `r${src.data.before}` : "∅"} → r{src.data.after}
          </span>
        </div>
        <div className="flex items-center gap-1" role="radiogroup" aria-label="Diff view">
          {(
            [
              ["overlay", "Overlay"],
              ["side", "Side by side"],
            ] as const
          ).map(([m, label]) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={cx(
                "h-7 rounded-md border px-2 text-[12px]",
                mode === m ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1" role="radiogroup" aria-label="How much of the model to show">
          <span className="text-faint">Show</span>
          {SCOPES.map((o) => (
            <button
              key={o.key}
              type="button"
              role="radio"
              aria-checked={scope === o.key}
              title={o.title}
              onClick={() => setScope(o.key)}
              disabled={noChanges && o.key !== "all"}
              className={cx(
                "h-7 rounded-md border px-2 text-[12px] disabled:opacity-40",
                scope === o.key ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink",
              )}
            >
              {o.label}
            </button>
          ))}
          {hiddenCount > 0 && (
            <span className="text-faint" title="Components not drawn. Click a dimmed neighbour to draw its neighbours too.">
              +{hiddenCount} hidden
            </span>
          )}
          {focus.hubs.length > 0 && scope !== "all" && !noChanges && (
            <span
              className="cursor-help text-faint underline decoration-dotted"
              title={`Hubs with more than ${HUB_DEGREE} call partners only show the neighbours on changed edges or interfaces: ${focus.hubs.join(", ")}. Click one to draw all its neighbours.`}
            >
              {plural(focus.hubs.length, "hub")} not expanded
            </span>
          )}
          {expandedIds.length > 0 && scope !== "all" && (
            <Button size="sm" variant="ghost" title={`Expanded: ${expandedIds.join(", ")}`} onClick={() => setExpanded({ key: diffKey, ids: [] })}>
              Reset {plural(expandedIds.length, "expansion")}
            </Button>
          )}
        </div>
        <Button size="sm" onClick={() => setFitNonce((n) => n + 1)} disabled={!fitTo?.length} title="Fit the view to the changed components">
          Fit to changes
        </Button>
        <div className="flex items-center gap-1.5">
          {counts.added > 0 && <Badge tone="ok">+{counts.added}</Badge>}
          {counts.modified > 0 && <Badge tone="warn">~{counts.modified}</Badge>}
          {counts.removed > 0 && <Badge tone="bad">−{counts.removed}</Badge>}
          {counts.added + counts.modified + counts.removed === 0 && <Badge>no component changes</Badge>}
          <span className="text-faint">{plural(union.status.edges.size, "edge")} changed</span>
        </div>
        <select
          aria-label="Jump to a changed component"
          value={selected ?? ""}
          onChange={(e) => select(e.target.value || null)}
          className="h-7 max-w-[200px] rounded-md border border-line bg-panel-2 px-2 text-[12px] text-ink"
        >
          <option value="">Changed components…</option>
          {changedIds.map((id) => (
            <option key={id} value={id}>
              {union.status.nodes.get(id) === "added" ? "+ " : union.status.nodes.get(id) === "removed" ? "− " : "~ "}
              {id}
            </option>
          ))}
        </select>
        <Link href={ws.href("flows", { commit: search.get("commit") ?? "" })} className={cx("text-link hover:underline", !search.get("commit") && "hidden")}>
          Flows changed →
        </Link>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-1 border-b border-line-soft px-4 py-1.5">
        <DiffLegend />
        <div className="ml-auto">
          <MapLegend scale={scale} colorBy="layer" compact />
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          {mode === "overlay" ? (
            <ArchitectureMap
              key="overlay"
              graph={scoped}
              diff={overlayDiff}
              selected={selected}
              onSelect={onMapSelect}
              fitTo={fitTo}
              fitKey={fitNonce}
              ariaLabel="Architecture before and after: added components are green, modified amber, removed red and dashed."
            />
          ) : (
            <div className="grid h-full grid-cols-2 divide-x divide-line">
              {(
                [
                  ["Before", src.data.before ? `r${src.data.before}` : "nothing", sides.before, beforeDiff],
                  ["After", `r${src.data.after}`, sides.after, afterDiff],
                ] as const
              ).map(([label, rev, g, d]) => (
                <div key={label} className="relative min-w-0">
                  <div className="pointer-events-none absolute left-2 top-2 z-10 rounded border border-line bg-panel/90 px-2 py-0.5 text-[12px] font-semibold text-ink">
                    {label} <span className="font-mono font-normal text-faint">{rev}</span>
                  </div>
                  <ArchitectureMap
                    key={label}
                    graph={g}
                    layoutGraph={scoped}
                    diff={d}
                    selected={selected}
                    onSelect={onMapSelect}
                    fitTo={fitTo}
                    fitKey={fitNonce}
                    viewport={viewport}
                    onViewportChange={setViewport}
                    ariaLabel={`Architecture ${label.toLowerCase()} the change`}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        {node && (
          <aside aria-label={`Changes to ${node.name}`} className="w-[min(480px,40vw)] shrink-0 border-l border-line bg-panel">
            <DiffPanel
              id={node.id}
              graph={union.graph}
              status={union.status}
              changes={src.data.changes}
              after={src.data.after}
              onClose={() => select(null)}
              onSelect={(id) => select(id)}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
