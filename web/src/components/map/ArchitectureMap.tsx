"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  getViewportForBounds,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useInternalNode,
  useReactFlow,
  useStore,
  useStoreApi,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type Viewport,
} from "@xyflow/react";
import { memo, useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import type { Graph, GraphEdge } from "@/lib/api/types";
import { categoricalScale, type ColorScale } from "@/lib/model/colors";
import type { ChangeKind } from "@/lib/model/impact";
import type { ActiveEdge } from "@/lib/sim/playback";
import { Button, cx } from "@/components/ui";
import { collapseGraph, containers, DIFF_COLORS, parentMap, type DiffStatus } from "./graphview";
import { HEADER_H, isAncestor, layoutGraph, type MapLayout } from "./layout";

export type ColorBy = "layer" | "kind";

export interface MapHighlight {
  /** The component the current event happens on. */
  active?: string;
  edge?: ActiveEdge;
  /** Components that take part in the run; others are dimmed. */
  involved?: Set<string>;
  /** Components with an open call at the cursor. */
  busy?: Set<string>;
  /** The current event is a failure. */
  error?: boolean;
  /** Changes on every cursor move, restarting the message animation. */
  seq?: number;
}

type NodeData = {
  label: string;
  kind?: string;
  layer?: string;
  color: string;
  ifaces: number;
  stateful: boolean;
  container: boolean;
  selected: boolean;
  state: "normal" | "dim" | "muted" | "active" | "error" | "busy";
  /** Diff mode: how this component changed. */
  diff?: ChangeKind;
  /** Collapsible maps: members hidden inside this collapsed container. */
  hiddenMembers?: number;
  /** Focused diff maps: [members drawn, members in the full model] of a container. */
  shownOf?: [number, number];
  /** Collapsible maps: set on containers and collapsed containers. */
  onToggle?: () => void;
  /** §11.1: the instance group under the selected fixture. */
  group?: MapInstanceGroup;
  /** §16.6: the component has a refinement; zooms into it. */
  onZoom?: () => void;
};

function ZoomButton({ onZoom, label }: { onZoom: () => void; label: string }) {
  return (
    <button
      type="button"
      className="nodrag nopan inline-flex h-[18px] items-center justify-center gap-0.5 rounded border border-[#4d6b1f] bg-[#1c2a10] px-1 text-[10.5px] leading-none text-accent hover:border-accent"
      aria-label={`Zoom into ${label}'s refinement`}
      title="Refined: zoom into the child ontology"
      onClick={(ev) => {
        ev.stopPropagation();
        onZoom();
      }}
      onKeyDown={(ev) => ev.stopPropagation()}
    >
      ⤢
    </button>
  );
}

/** A component's instance group: `owner` has the topology entry naming `instances`. */
export interface MapInstanceGroup {
  owner: string;
  instances: string[];
}

function InstanceChip({ id, group }: { id: string; group: MapInstanceGroup }) {
  const own = group.owner === id;
  const names = group.instances.join(", ");
  return (
    <span
      className={cx(
        "shrink-0 whitespace-nowrap rounded border px-1 text-[9.5px] font-semibold leading-[14px]",
        own ? "border-[#4d6b1f] bg-[#1c2a10] text-accent" : "border-line bg-panel-3 text-muted",
      )}
      title={own ? `${group.instances.length} instances: ${names}` : `Runs on the instances of ${group.owner}: ${names}`}
    >
      {own ? `×${group.instances.length}` : `⊂ ×${group.instances.length}`}
    </span>
  );
}

function groupTitle(id: string, g: MapInstanceGroup | undefined): string {
  if (!g) return "";
  return g.owner === id ? ` · instances: ${g.instances.join(", ")}` : ` · in ${g.owner}'s group: ${g.instances.join(", ")}`;
}

type EdgeData = {
  kind: string;
  derived: boolean;
  label?: string;
  /** Between a container and one of its members (either direction). */
  member: boolean;
  /** A member -> container edge. */
  memberReverse?: boolean;
  /** The container the source leaves through, when it doesn't hold the target. */
  sourceExit?: string;
  /** The container the target is entered through, when it doesn't hold the source. */
  targetExit?: string;
  active?: { kind: ActiveEdge["kind"]; reverse: boolean; seq: number };
  diff?: ChangeKind;
  dim: boolean;
  title: string;
};

type MapNode = Node<NodeData, "component" | "container">;
type MapEdge = Edge<EdgeData, "floating">;

function HiddenHandles() {
  // Floating edges compute their own endpoints, but React Flow needs handles to
  // create an edge at all.
  return (
    <>
      <Handle type="source" position={Position.Right} isConnectable={false} className="!pointer-events-none !opacity-0" />
      <Handle type="target" position={Position.Left} isConnectable={false} className="!pointer-events-none !opacity-0" />
    </>
  );
}

const DIFF_MARK: Record<ChangeKind, string> = { added: "+ added", modified: "~ modified", removed: "− removed" };

function DiffChip({ diff }: { diff: ChangeKind }) {
  return (
    <span
      className="shrink-0 whitespace-nowrap rounded px-1 text-[9.5px] font-semibold leading-[14px] text-[#0a0e12]"
      style={{ background: DIFF_COLORS[diff] }}
    >
      {DIFF_MARK[diff]}
    </span>
  );
}

function ToggleButton({ collapsed, onToggle, label }: { collapsed: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      type="button"
      className="nodrag nopan inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line bg-panel-3 px-1 text-[10.5px] leading-none text-muted hover:border-accent hover:text-ink"
      aria-label={`${collapsed ? "Expand" : "Collapse"} ${label}`}
      title={collapsed ? "Expand this group" : "Collapse this group"}
      onClick={(ev) => {
        ev.stopPropagation();
        onToggle();
      }}
      onKeyDown={(ev) => ev.stopPropagation()}
    >
      {collapsed ? "▸" : "▾"}
    </button>
  );
}

function diffBorder(d: ChangeKind | undefined): CSSProperties | undefined {
  if (!d) return undefined;
  return {
    borderColor: DIFF_COLORS[d],
    borderStyle: d === "removed" ? "dashed" : "solid",
    borderWidth: 2,
    boxShadow: `0 0 0 3px color-mix(in srgb, ${DIFF_COLORS[d]} 22%, transparent)`,
  };
}

function ComponentNode({ id, data }: NodeProps<MapNode>) {
  const ring =
    data.state === "active"
      ? "border-accent shadow-[0_0_0_3px_rgba(204,255,120,0.25)]"
      : data.state === "error"
        ? "border-st-critical shadow-[0_0_0_3px_rgba(208,59,59,0.3)]"
        : data.state === "busy"
          ? "border-[#6f8f3c]"
          : data.selected
            ? "border-accent"
            : "border-line";
  return (
    <div
      className={cx(
        "map-node flex h-full w-full overflow-hidden rounded-lg border bg-panel-2 transition-[opacity,border-color,box-shadow] duration-200",
        ring,
        data.state === "dim" && "opacity-35",
        data.state === "muted" && "opacity-55 hover:opacity-90",
        data.state === "active" && "pulse-ring",
        data.diff === "removed" && "bg-[#1a1214]",
      )}
      style={diffBorder(data.diff)}
      title={`${data.label}${data.kind ? ` · ${data.kind}` : ""}${data.layer ? ` · layer ${data.layer}` : ""}${data.diff ? ` · ${data.diff}` : ""}${data.hiddenMembers ? ` · ${data.hiddenMembers} members hidden` : ""}${groupTitle(id, data.group)}`}
    >
      <HiddenHandles />
      <span className="w-[5px] shrink-0" style={{ background: data.color, opacity: data.diff === "removed" ? 0.5 : 1 }} aria-hidden />
      <div className={cx("flex min-w-0 flex-1 flex-col justify-center px-2.5 py-1", data.diff === "removed" && "opacity-75")}>
        <div className="flex items-center gap-1.5">
          <span className={cx("truncate text-[12.5px] font-semibold leading-tight text-ink", data.diff === "removed" && "line-through decoration-[#d03b3b]")}>{data.label}</span>
          {data.diff && <DiffChip diff={data.diff} />}
          {data.group && <InstanceChip id={id} group={data.group} />}
          {data.onZoom && <ZoomButton onZoom={data.onZoom} label={data.label} />}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-[10.5px] leading-tight text-faint">
          <span>{data.kind || "component"}</span>
          {data.hiddenMembers ? (
            <span className="text-muted">· {data.hiddenMembers} inside</span>
          ) : (
            data.ifaces > 0 && <span>· {data.ifaces} if</span>
          )}
          {data.stateful && !data.hiddenMembers && (
            <span className="text-muted" title="stateful">
              · ◉ state
            </span>
          )}
        </div>
      </div>
      {data.onToggle && (
        <div className="flex items-center pr-1.5">
          <ToggleButton collapsed onToggle={data.onToggle} label={data.label} />
        </div>
      )}
    </div>
  );
}

function ContainerNode({ id, data }: NodeProps<MapNode>) {
  return (
    <div
      className={cx(
        "map-node h-full w-full rounded-xl border transition-opacity duration-200",
        data.selected ? "border-accent" : data.state === "active" ? "border-accent" : data.state === "error" ? "border-st-critical" : "",
        data.state === "dim" && "opacity-40",
      )}
      style={{
        background: data.diff === "removed" ? "#150f11" : `color-mix(in srgb, ${data.color} 6%, #0d1318)`,
        borderColor: data.selected || data.state === "active" || data.state === "error" ? undefined : `color-mix(in srgb, ${data.color} 38%, #2a3742)`,
        ...diffBorder(data.diff),
      }}
    >
      <HiddenHandles />
      <div className="flex items-center gap-2 overflow-hidden whitespace-nowrap px-3" style={{ height: HEADER_H }}>
        {data.onToggle && <ToggleButton collapsed={false} onToggle={data.onToggle} label={data.label} />}
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: data.color }} aria-hidden />
        <span className={cx("truncate text-[12.5px] font-semibold text-ink", data.diff === "removed" && "line-through decoration-[#d03b3b]")} title={data.label}>
          {data.label}
        </span>
        {data.diff && <DiffChip diff={data.diff} />}
        {data.group && <InstanceChip id={id} group={data.group} />}
        {data.onZoom && <ZoomButton onZoom={data.onZoom} label={data.label} />}
        <span className="min-w-0 truncate text-[10.5px] text-faint">
          {data.kind}
          {data.ifaces > 0 ? ` · ${data.ifaces} if` : ""}
          {data.stateful ? " · ◉ state" : ""}
          {data.shownOf && data.shownOf[0] < data.shownOf[1] ? ` · showing ${data.shownOf[0]} of ${data.shownOf[1]} members` : ""}
        </span>
      </div>
    </div>
  );
}

const nodeTypes = { component: memo(ComponentNode), container: memo(ContainerNode) };

function rectOf(n: ReturnType<typeof useInternalNode>) {
  if (!n) return null;
  const { x, y } = n.internals.positionAbsolute;
  const w = n.measured.width ?? (n.width as number | undefined) ?? 0;
  const h = n.measured.height ?? (n.height as number | undefined) ?? 0;
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
}

const reduceMotion = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

type Rect = NonNullable<ReturnType<typeof rectOf>>;
type Pt = [number, number];

/**
 * Routes an edge whose endpoint sits inside a container that doesn't hold the
 * other end: it runs along the gap beside the card to the container's padding,
 * then along the padding to the container's border, so it never crosses a
 * sibling card. The span between the two borders is a bezier.
 */
function railPath(s: Rect, t: Rect, sp: Rect | null, tp: Rect | null): [string, number, number] {
  const right = t.cx >= s.cx;
  const head: Pt[] = [];
  const tail: Pt[] = [];
  let start: Pt;
  let end: Pt;
  if (sp) {
    const gapX = right ? s.x + s.w + 6 : s.x - 6;
    const railY = t.cy > sp.y + sp.h / 2 ? sp.y + sp.h - 7 : sp.y + HEADER_H + 3;
    start = [right ? sp.x + sp.w : sp.x, railY];
    head.push([right ? s.x + s.w : s.x, s.cy], [gapX, s.cy], [gapX, railY], start);
  } else {
    start = [right ? s.x + s.w : s.x, s.cy];
    head.push(start);
  }
  if (tp) {
    const gapX = right ? t.x - 6 : t.x + t.w + 6;
    const railY = s.cy > tp.y + tp.h / 2 ? tp.y + tp.h - 7 : tp.y + HEADER_H + 3;
    end = [right ? tp.x : tp.x + tp.w, railY];
    tail.push(end, [gapX, railY], [gapX, t.cy], [right ? t.x : t.x + t.w, t.cy]);
  } else {
    end = [right ? t.x : t.x + t.w, t.cy];
    tail.push(end);
  }
  const dx = Math.max(24, Math.abs(end[0] - start[0]) * 0.45) * (right ? 1 : -1);
  let d = `M ${head[0][0]} ${head[0][1]}`;
  for (const p of head.slice(1)) d += ` L ${p[0]} ${p[1]}`;
  d += ` C ${start[0] + dx} ${start[1]} ${end[0] - dx} ${end[1]} ${end[0]} ${end[1]}`;
  for (const p of tail.slice(1)) d += ` L ${p[0]} ${p[1]}`;
  return [d, (start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
}

function FloatingEdge({ id, source, target, data, markerEnd }: EdgeProps<MapEdge>) {
  const s = rectOf(useInternalNode(source));
  const t = rectOf(useInternalNode(target));
  const sp = rectOf(useInternalNode(data?.sourceExit ?? ""));
  const tp = rectOf(useInternalNode(data?.targetExit ?? ""));
  if (!s || !t || !data) return null;

  let path: string;
  let lx: number;
  let ly: number;
  if (data.member && data.memberReverse) {
    // Member -> container: out of the member into the gap beside it, then up to the header.
    const x = s.x - 6;
    const y1 = t.y + HEADER_H - 2;
    path = `M ${s.x} ${s.cy} L ${x} ${s.cy} L ${x} ${y1}`;
    lx = x;
    ly = (y1 + s.cy) / 2;
  } else if (data.member) {
    // Container -> member: down the gap beside the member, then into it.
    const x = t.x - 6;
    const y1 = s.y + HEADER_H - 2;
    path = `M ${x} ${y1} L ${x} ${t.cy} L ${t.x} ${t.cy}`;
    lx = x;
    ly = (y1 + t.cy) / 2;
  } else if (sp || tp) {
    [path, lx, ly] = railPath(s, t, sp, tp);
  } else {
    const dx = t.cx - s.cx;
    const dy = t.cy - s.cy;
    let spos: Position, tpos: Position, sx: number, sy: number, tx: number, ty: number;
    if (Math.abs(dx) * 0.6 >= Math.abs(dy) || Math.abs(dx) > (s.w + t.w) / 2) {
      spos = dx >= 0 ? Position.Right : Position.Left;
      tpos = dx >= 0 ? Position.Left : Position.Right;
      sx = dx >= 0 ? s.x + s.w : s.x;
      tx = dx >= 0 ? t.x : t.x + t.w;
      sy = s.cy;
      ty = t.cy;
    } else {
      spos = dy >= 0 ? Position.Bottom : Position.Top;
      tpos = dy >= 0 ? Position.Top : Position.Bottom;
      sy = dy >= 0 ? s.y + s.h : s.y;
      ty = dy >= 0 ? t.y : t.y + t.h;
      sx = s.cx;
      tx = t.cx;
    }
    [path, lx, ly] = getBezierPath({ sourceX: sx, sourceY: sy, sourcePosition: spos, targetX: tx, targetY: ty, targetPosition: tpos, curvature: 0.3 });
  }

  const active = data.active;
  const isLink = !data.derived;
  const emits = data.kind === "emits";
  let stroke = isLink ? "#9085e9" : emits ? "#5fb8a8" : "#4f6070";
  let width = isLink ? 1.5 : 1.4;
  let dash: string | undefined = isLink ? "7 5" : emits ? "1.5 4.5" : data.member ? "2 3" : undefined;
  if (data.diff && !active) {
    stroke = DIFF_COLORS[data.diff];
    width = 2.2;
    if (data.diff === "removed") dash = "6 4";
  }
  if (active) {
    width = 2.6;
    stroke =
      active.kind === "error" ? "#d03b3b" : active.kind === "timeout" || active.kind === "late" ? "#fab219" : "#ccff78";
    if (active.kind === "emit" || active.kind === "async") dash = "1.5 5";
    else if (active.kind === "late" || active.kind === "timeout") dash = "6 4";
    else dash = undefined;
  }
  const showLabel = !!active || (isLink && !!data.label) || (!!data.diff && !!data.label && !data.dim);
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke,
          strokeWidth: width,
          strokeDasharray: dash,
          strokeLinecap: "round",
          opacity: data.dim && !active ? 0.25 : 1,
          transition: "opacity 200ms",
        }}
      />
      <path d={path} fill="none" stroke="transparent" strokeWidth={12}>
        <title>{data.title}</title>
      </path>
      {active && (
        <circle key={`${active.seq}`} r={5} fill={stroke} stroke="#0a0e12" strokeWidth={2}>
          {reduceMotion ? null : (
            <animateMotion
              dur="1.1s"
              repeatCount="indefinite"
              path={path}
              keyPoints={active.reverse ? "1;0" : "0;1"}
              keyTimes="0;1"
              calcMode="linear"
            />
          )}
        </circle>
      )}
      {showLabel && (
        <EdgeLabelRenderer>
          <div
            className={cx(
              "nodrag nopan pointer-events-none absolute rounded border px-1.5 py-[1px] font-mono text-[10.5px]",
              active ? "border-[#4d6b1f] bg-[#141d0c] text-accent" : data.diff ? "border-line bg-panel text-ink" : "border-[#3d3766] bg-[#16142a] text-violet",
            )}
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)`, borderColor: data.diff && !active ? DIFF_COLORS[data.diff] : undefined }}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { floating: FloatingEdge };

function edgeTitle(e: GraphEdge): string {
  const what = e.derived ? (e.kind === "emits" ? "emits (derived)" : "calls (derived)") : `link: ${e.kind}`;
  const ifs = e.interfaces?.length ? `\n${e.interfaces.join("\n")}` : "";
  return `${e.from} → ${e.to} · ${what}${e.label ? ` · ${e.label}` : ""}${ifs}`;
}

interface MapProps {
  graph: Graph;
  colorBy?: ColorBy;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
  highlight?: MapHighlight;
  showMemberEdges?: boolean;
  className?: string;
  /** Re-fit when this changes (for example when a side panel opens). */
  fitKey?: string | number;
  /** Fit the view to this component and its neighbors. */
  focus?: string | null;
  ariaLabel?: string;
  /**
   * Lay out this graph instead of `graph` and draw only `graph`'s nodes at
   * their positions in it, so two maps of related graphs line up.
   */
  layoutGraph?: Graph;
  /** Marks added, modified and removed components and edges. */
  diff?: {
    status: DiffStatus;
    /** Strongly dim everything unchanged. */
    changedOnly?: boolean;
    /** Lightly dim unchanged components (not containers) and edges that touch no changed component. */
    dimUnchanged?: boolean;
    /** Container id -> its member count in the full model, for "showing 3 of 40". */
    memberTotals?: Map<string, number>;
  };
  /**
   * Fit the view to these components (by their layout positions, so ids that
   * this map doesn't draw still count) at a readable zoom.
   */
  fitTo?: string[];
  /** Containers get a collapse toggle; large maps start with top-level groups collapsed. */
  collapsible?: boolean;
  /** A controlled viewport, to keep two maps in step. */
  viewport?: Viewport;
  onViewportChange?: (v: Viewport) => void;
  /** §11.1: component id -> its instance group, for the selected fixture's topology. */
  instanceGroups?: Map<string, MapInstanceGroup>;
  /** §16.6: refined components get a zoom button that calls this. */
  refined?: Set<string>;
  onZoom?: (id: string) => void;
}

/** Maps with more components than this start with their top-level groups collapsed. */
export const COLLAPSE_ABOVE = 120;

export function useColorScale(graph: Graph | undefined, colorBy: ColorBy): ColorScale {
  return useMemo(
    () => categoricalScale((graph?.nodes ?? []).map((n) => (colorBy === "layer" ? n.layer : n.kind))),
    [graph, colorBy],
  );
}

function MapInner({
  graph: fullGraph,
  colorBy = "layer",
  selected,
  onSelect,
  highlight,
  showMemberEdges,
  fitKey,
  focus,
  ariaLabel,
  layoutGraph: layoutOf,
  diff,
  fitTo,
  collapsible,
  viewport,
  onViewportChange,
  instanceGroups,
  refined,
  onZoom,
}: MapProps) {
  const [layout, setLayout] = useState<{ graph: Graph; layout: MapLayout } | null>(null);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const scale = useColorScale(layoutOf ?? fullGraph, colorBy);
  const rf = useReactFlow();

  // Collapsing: start with the top-level groups of a large map collapsed.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    if (!collapsible || fullGraph.nodes.length <= COLLAPSE_ABOVE) return new Set();
    const groups = containers(fullGraph);
    return new Set(fullGraph.nodes.filter((n) => groups.has(n.id) && !n.parent).map((n) => n.id));
  });
  const toggle = useCallback(
    (id: string) =>
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    [],
  );
  const groupIds = useMemo(() => (collapsible ? containers(fullGraph) : new Set<string>()), [collapsible, fullGraph]);
  const { graph, hidden } = useMemo(() => {
    if (!collapsible || collapsed.size === 0) return { graph: fullGraph, hidden: new Map<string, number>() };
    // Never hide the selected or focused component: open its groups.
    const open = new Set<string>();
    const parents = parentMap(fullGraph);
    for (const id of [selected, focus]) {
      let cur = id ? parents.get(id) : undefined;
      while (cur && !open.has(cur)) {
        open.add(cur);
        cur = parents.get(cur);
      }
    }
    const eff = new Set(Array.from(collapsed).filter((c) => !open.has(c)));
    return collapseGraph(fullGraph, eff);
  }, [collapsible, collapsed, fullGraph, selected, focus]);
  const target = layoutOf ?? graph;

  useEffect(() => {
    let cancelled = false;
    layoutGraph(target).then(
      (l) => !cancelled && setLayout({ graph: target, layout: l }),
      (err) => !cancelled && setLayoutError(err instanceof Error ? err.message : String(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [target]);

  const ready = layout && layout.graph === target ? layout.layout : null;
  const drawn = useMemo(() => new Set(graph.nodes.map((n) => n.id)), [graph]);

  const nodes: MapNode[] = useMemo(() => {
    if (!ready) return [];
    const byId = new Map(graph.nodes.map((n) => [n.id, n]));
    return ready.nodes.filter((l) => drawn.has(l.id)).map((l) => {
      const n = byId.get(l.id) ?? l.node;
      let state: NodeData["state"] = "normal";
      if (highlight) {
        if (highlight.active === n.id) state = highlight.error ? "error" : "active";
        else if (highlight.busy?.has(n.id) && !l.container) state = "busy";
        else if (highlight.involved && !highlight.involved.has(n.id)) state = "dim";
      }
      const nd = diff?.status.nodes.get(n.id);
      const container = l.container && graph.nodes.some((m) => m.parent === n.id);
      if (diff?.changedOnly && !nd) state = "dim";
      else if (diff?.dimUnchanged && !nd && !container && state === "normal") state = "muted";
      // A node whose layout parent isn't drawn here is placed absolutely.
      const nested = !!l.parent && drawn.has(l.parent);
      const total = container ? diff?.memberTotals?.get(n.id) : undefined;
      const hiddenMembers = hidden.get(n.id);
      return {
        id: n.id,
        type: container ? "container" : "component",
        position: nested ? { x: l.x, y: l.y } : { x: l.absX, y: l.absY },
        parentId: nested ? l.parent : undefined,
        width: l.width,
        height: l.height,
        style: { width: l.width, height: l.height },
        draggable: false,
        selectable: true,
        focusable: true,
        zIndex: l.container ? l.depth : 20 + l.depth,
        ariaLabel: `${n.name}, ${n.kind || "component"}${n.layer ? `, layer ${n.layer}` : ""}`,
        data: {
          label: n.name,
          kind: n.kind,
          layer: n.layer,
          color: scale.color(colorBy === "layer" ? n.layer : n.kind),
          ifaces: n.interfaces.length,
          stateful: n.stateful,
          container,
          selected: selected === n.id,
          state,
          diff: nd,
          hiddenMembers,
          shownOf: total ? [graph.nodes.filter((m) => m.parent === n.id).length, total] : undefined,
          onToggle: collapsible && (hiddenMembers || (container && groupIds.has(n.id))) ? () => toggle(n.id) : undefined,
          group: instanceGroups?.get(n.id),
          onZoom: onZoom && refined?.has(n.id) ? () => onZoom(n.id) : undefined,
        },
      };
    });
  }, [ready, graph, drawn, highlight, scale, colorBy, selected, diff, hidden, collapsible, groupIds, toggle, instanceGroups, refined, onZoom]);

  const edges: MapEdge[] = useMemo(() => {
    if (!ready) return [];
    const parentOf = parentMap(graph);
    const exitOf = (node: string, other: string) => {
      const p = parentOf.get(node);
      return p && !isAncestor(p, other, parentOf) && p !== other ? p : undefined;
    };
    const ae = highlight?.edge;
    const out: MapEdge[] = [];
    let matched = false;
    const seq = highlight?.seq ?? 0;
    for (const e of graph.edges) {
      if (!parentOf.has(e.from) || !parentOf.has(e.to)) continue;
      const memberReverse = isAncestor(e.to, e.from, parentOf);
      const member = memberReverse || isAncestor(e.from, e.to, parentOf);
      let active: EdgeData["active"];
      if (ae && !matched && e.derived) {
        const fwd = ae.from === e.from && ae.to === e.to;
        const rev = ae.from === e.to && ae.to === e.from;
        const wantEmit = ae.kind === "emit" || ae.kind === "async";
        const kindOk = wantEmit ? e.kind === "emits" || e.kind === "calls" : e.kind === "calls";
        if ((fwd || rev) && kindOk) {
          active = { kind: ae.kind, reverse: rev, seq };
          matched = true;
        }
      }
      const ed = diff?.status.edges.get(e.id);
      // Member edges are noise, unless they're what changed.
      if (member && !showMemberEdges && !active && !ed) continue;
      const dcolor = ed ? DIFF_COLORS[ed] : undefined;
      out.push({
        id: e.id,
        source: e.from,
        target: e.to,
        type: "floating",
        zIndex: active ? 60 : ed ? 30 : 10,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: active ? (active.kind === "error" ? "#d03b3b" : active.kind === "timeout" || active.kind === "late" ? "#fab219" : "#ccff78") : dcolor ?? (!e.derived ? "#9085e9" : e.kind === "emits" ? "#5fb8a8" : "#4f6070") },
        data: {
          kind: e.kind,
          derived: e.derived,
          label: e.label,
          member,
          memberReverse,
          sourceExit: member ? undefined : exitOf(e.from, e.to),
          targetExit: member ? undefined : exitOf(e.to, e.from),
          active,
          diff: ed,
          dim:
            (!!highlight?.involved && !(highlight.involved.has(e.from) && highlight.involved.has(e.to))) ||
            (!!diff?.changedOnly && !ed) ||
            (!!diff?.dimUnchanged && !ed && !diff.status.nodes.has(e.from) && !diff.status.nodes.has(e.to)),
          title: edgeTitle(e) + (ed ? ` · ${ed}` : ""),
        },
      });
    }
    // A call the graph doesn't know about (a dynamic target, say): draw it anyway.
    if (ae && !matched && parentOf.has(ae.from) && parentOf.has(ae.to) && ae.from !== ae.to) {
      const color = ae.kind === "error" ? "#d03b3b" : ae.kind === "timeout" || ae.kind === "late" ? "#fab219" : "#ccff78";
      const reverse = ae.kind === "response" || ae.kind === "error" || ae.kind === "late";
      out.push({
        id: `transient:${ae.from}->${ae.to}`,
        source: reverse ? ae.to : ae.from,
        target: reverse ? ae.from : ae.to,
        type: "floating",
        zIndex: 61,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
        data: {
          kind: "calls",
          derived: true,
          member: isAncestor(reverse ? ae.to : ae.from, reverse ? ae.from : ae.to, parentOf),
          sourceExit: exitOf(reverse ? ae.to : ae.from, reverse ? ae.from : ae.to),
          targetExit: exitOf(reverse ? ae.from : ae.to, reverse ? ae.to : ae.from),
          active: { kind: ae.kind, reverse, seq },
          dim: false,
          title: `${ae.from} → ${ae.to}`,
        },
      });
    }
    return out;
  }, [ready, graph, highlight, showMemberEdges, diff]);

  // Fit when the layout lands; with a focus, fit its neighborhood instead.
  const store = useStoreApi();
  const paneW = useStore((s) => s.width);
  const paneH = useStore((s) => s.height);
  // Only maps fitted to a set of components refit when their pane is resized.
  const paneKey = fitTo?.length ? `${paneW}x${paneH}` : "";
  useEffect(() => {
    if (!ready) return;
    const t = window.setTimeout(() => {
      const want = new Set(fitTo ?? []);
      const fitNodes = ready.nodes.filter((l) => want.has(l.id));
      const { width: pw, height: ph } = store.getState();
      if (!focus && fitNodes.length > 0 && pw > 0 && ph > 0) {
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const l of fitNodes) {
          x0 = Math.min(x0, l.absX);
          y0 = Math.min(y0, l.absY);
          x1 = Math.max(x1, l.absX + l.width);
          y1 = Math.max(y1, l.absY + l.height);
        }
        // Never zoom in past life size: a single change stays at a normal reading scale.
        const bounds = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
        const vp = getViewportForBounds(bounds, pw, ph, 0.15, 1, 0.12);
        rf.setViewport(vp, { duration: 0 });
      } else if (focus && ready.parentOf.has(focus)) {
        const ids = new Set([focus]);
        for (const e of graph.edges) {
          if (e.from === focus) ids.add(e.to);
          if (e.to === focus) ids.add(e.from);
        }
        const parent = ready.parentOf.get(focus);
        if (parent) ids.add(parent);
        rf.fitView({ nodes: Array.from(ids, (id) => ({ id })), padding: 0.18, maxZoom: 1.15, duration: 300 });
      } else if (layoutOf) {
        // Fit the whole shared layout, so maps drawn from it frame the same area.
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const l of ready.nodes) {
          x0 = Math.min(x0, l.absX);
          y0 = Math.min(y0, l.absY);
          x1 = Math.max(x1, l.absX + l.width);
          y1 = Math.max(y1, l.absY + l.height);
        }
        if (Number.isFinite(x0)) rf.fitBounds({ x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, { padding: 0.06, duration: 0 });
      } else {
        rf.fitView({ padding: 0.08, duration: 250 });
      }
    }, 40);
    return () => window.clearTimeout(t);
  }, [ready, rf, fitKey, focus, graph, layoutOf, fitTo, store, paneKey]);

  if (layoutError) return <div className="p-4 text-bad">Layout failed: {layoutError}</div>;
  if (!ready) return <div className="flex h-full items-center justify-center text-muted">Laying out the map…</div>;

  return (
    <div
      className="h-full w-full"
      onKeyDown={(ev) => {
        // Enter or Space on a focused node opens it, like a click.
        if (!onSelect || (ev.key !== "Enter" && ev.key !== " ")) return;
        const el = (ev.target as HTMLElement).closest?.(".react-flow__node");
        const id = el?.getAttribute("data-id");
        if (id) {
          ev.preventDefault();
          onSelect(id);
        }
      }}
    >
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      colorMode="dark"
      zIndexMode="manual"
      fitView={!viewport}
      fitViewOptions={{ padding: 0.08 }}
      viewport={viewport}
      onViewportChange={onViewportChange}
      minZoom={0.15}
      maxZoom={2.5}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      elementsSelectable={!!onSelect}
      onNodeClick={(_, n) => onSelect?.(n.id)}
      onPaneClick={() => onSelect?.(null)}
      proOptions={{ hideAttribution: true }}
      aria-label={ariaLabel ?? "Architecture map"}
    >
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#22303b" />
    </ReactFlow>
    {collapsible && groupIds.size > 0 && (
      <div className="absolute bottom-2 left-2 z-10 flex items-center gap-1 rounded-md border border-line bg-panel/90 p-1 text-[11px] text-faint backdrop-blur">
        <span className="px-1">
          {groupIds.size} groups · {collapsed.size} collapsed
        </span>
        <Button size="sm" variant="ghost" onClick={() => setCollapsed(new Set(fullGraph.nodes.filter((n) => groupIds.has(n.id) && !n.parent).map((n) => n.id)))}>
          Collapse top level
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setCollapsed(new Set())} disabled={collapsed.size === 0}>
          Expand all
        </Button>
      </div>
    )}
    </div>
  );
}

function Toolbar() {
  const rf = useReactFlow();
  return (
    <div className="absolute bottom-2 right-2 z-10 flex gap-1 rounded-md border border-line bg-panel/90 p-1 backdrop-blur">
      <Button size="sm" variant="ghost" aria-label="Zoom in" title="Zoom in" onClick={() => rf.zoomIn({ duration: 150 })}>
        +
      </Button>
      <Button size="sm" variant="ghost" aria-label="Zoom out" title="Zoom out" onClick={() => rf.zoomOut({ duration: 150 })}>
        −
      </Button>
      <Button size="sm" variant="ghost" title="Fit the whole map" onClick={() => rf.fitView({ padding: 0.08, duration: 250 })}>
        Fit
      </Button>
    </div>
  );
}

export function ArchitectureMap(props: MapProps) {
  return (
    <div className={cx("relative h-full w-full", props.className)}>
      <ReactFlowProvider>
        <MapInner {...props} />
        <Toolbar />
      </ReactFlowProvider>
    </div>
  );
}

export function MapLegend({ scale, colorBy, compact }: { scale: ColorScale; colorBy: ColorBy; compact?: boolean }) {
  return (
    <div className={cx("flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted", compact && "text-[10.5px]")}>
      <span className="text-faint">{colorBy}:</span>
      {scale.entries.map((e) => (
        <span key={e.group} className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: e.color }} aria-hidden />
          {e.group}
        </span>
      ))}
      <span className="mx-1 h-3 w-px bg-line" aria-hidden />
      <span className="inline-flex items-center gap-1">
        <svg width="22" height="6" aria-hidden>
          <line x1="0" y1="3" x2="22" y2="3" stroke="#6b7f90" strokeWidth="1.5" />
        </svg>
        calls
      </span>
      <span className="inline-flex items-center gap-1">
        <svg width="22" height="6" aria-hidden>
          <line x1="1" y1="3" x2="22" y2="3" stroke="#5fb8a8" strokeWidth="1.75" strokeDasharray="1.5 4" strokeLinecap="round" />
        </svg>
        emits
      </span>
      <span className="inline-flex items-center gap-1">
        <svg width="22" height="6" aria-hidden>
          <line x1="0" y1="3" x2="22" y2="3" stroke="#9085e9" strokeWidth="1.5" strokeDasharray="6 4" />
        </svg>
        explicit link
      </span>
    </div>
  );
}
