"use client";

// The Atlas canvas (review Concept A): an xyflow drawing of one AtlasView. Which boxes and
// connections it holds comes from lib/model/atlas; this file only draws them and reports clicks.

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  BaseEdge,
  getBezierPath,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useInternalNode,
  useReactFlow,
  useStoreApi,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type Viewport,
} from "@xyflow/react";
import { memo, useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import type { AtlasBox, AtlasEdge, AtlasView } from "@/lib/model/atlas";
import { edgeWidth, scopeKey } from "@/lib/model/atlas";
import { OTHER_COLOR } from "@/lib/model/colors";
import type { Counts, Lens, LensDecor } from "@/lib/model/atlasLens";
import { tintStep } from "@/lib/model/atlasLens";
import { plural } from "@/lib/model/format";
import { FidelityStrip } from "@/components/trust/marks";
import { Button, cx } from "@/components/ui";
import { boxSize, layoutAtlas, type BoxRect } from "./atlasLayout";

export interface AtlasMapProps {
  view: AtlasView;
  /** Identifies the model and revision, to keep a view's pan between visits. */
  storeKey: string;
  colorOf: (place: string | undefined) => string;
  lens: Lens;
  decor?: LensDecor | null;
  /** Box id -> matching components, while the list is filtered. */
  matches?: Map<string, number> | null;
  selected?: string | null;
  /** Draw every connection, not only the strong ones. */
  allConnections?: boolean;
  /** Reserve room for trust marks: evidence is stored. */
  hasEvidence: boolean;
  /** Box id -> the fidelity to draw. */
  fidelity?: Map<string, Counts>;
  /** Area -> absent mechanisms there, for its dashed row. */
  ghosts?: Map<string, number>;
  onActivate: (box: AtlasBox) => void;
  onEnter: (box: AtlasBox) => void;
  onGhost: (area: string) => void;
  onClear: () => void;
}

type BoxData = {
  box: AtlasBox;
  color: string;
  selected: boolean;
  holdsSelection: boolean;
  dim: boolean;
  /** 0 to 4, the failure lens's tint. */
  tint: number;
  lit: boolean;
  badge?: string;
  match?: number;
  fidelity?: Counts;
  ghost?: number;
  onEnter?: () => void;
  onGhost?: () => void;
};

type EdgeData = {
  width: number;
  emits: boolean;
  tone: "normal" | "weak" | "lit" | "dim";
  title: string;
};

type BoxNode = Node<BoxData, "box">;
type AtlasFlowEdge = Edge<EdgeData, "atlas">;

function HiddenHandles() {
  return (
    <>
      <Handle type="source" position={Position.Right} isConnectable={false} className="!pointer-events-none !opacity-0" />
      <Handle type="target" position={Position.Left} isConnectable={false} className="!pointer-events-none !opacity-0" />
    </>
  );
}

function EnterButton({ label, onEnter }: { label: string; onEnter: () => void }) {
  return (
    <button
      type="button"
      className="nodrag nopan inline-flex h-[20px] shrink-0 items-center justify-center rounded border border-line bg-panel-3 px-1.5 text-[11px] leading-none text-muted hover:border-accent hover:text-ink"
      aria-label={`Enter ${label}`}
      title="Open what's inside"
      onClick={(ev) => {
        ev.stopPropagation();
        onEnter();
      }}
      onKeyDown={(ev) => ev.stopPropagation()}
    >
      ▸
    </button>
  );
}

const TINT = [0, 16, 30, 46, 64];

function surface(data: BoxData): string | undefined {
  if (data.tint > 0) return `color-mix(in srgb, #d95926 ${TINT[data.tint]}%, var(--color-panel-2))`;
  return undefined;
}

function Badge({ text, tone }: { text: string; tone: "lens" | "match" }) {
  return (
    <span className={cx("tnum shrink-0 whitespace-nowrap rounded px-1 text-[10px] font-semibold leading-[14px]", tone === "match" ? "bg-accent text-accent-ink" : "bg-panel-3 text-ink")}>
      {text}
    </span>
  );
}

function boxFrame(data: BoxData): string {
  return cx(
    "map-node relative h-full w-full overflow-hidden rounded-lg border transition-[opacity,border-color] duration-200",
    data.selected ? "border-accent shadow-[0_0_0_2px_rgba(204,255,120,0.3)]" : data.holdsSelection || data.lit ? "border-accent/70" : "border-line",
    data.dim && "opacity-30 hover:opacity-80",
  );
}

function Badges({ data }: { data: BoxData }) {
  return (
    <>
      {data.badge && <Badge text={data.badge} tone="lens" />}
      {data.match ? <Badge text={`${data.match} match${data.match === 1 ? "" : "es"}`} tone="match" /> : null}
    </>
  );
}

function AreaBox({ data }: { data: BoxData }) {
  const { box } = data;
  return (
    <div className={cx(boxFrame(data), "flex bg-panel-2")} style={{ background: surface(data) }} title={`${box.label}: ${box.detail ?? ""}\n${plural(box.parts, "part")}. ${plural(box.flows, "flow")} could reach it (static).`}>
      <HiddenHandles />
      <span className="w-[6px] shrink-0" style={{ background: data.color }} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span className="min-w-0 flex-1 truncate text-[14px] font-semibold leading-tight text-ink">{box.label}</span>
          <Badges data={data} />
          {data.onEnter && <EnterButton label={box.label} onEnter={data.onEnter} />}
        </div>
        <p className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-muted">{box.detail}</p>
        <div className="tnum mt-auto flex items-center gap-2 pt-1 text-[11px] text-faint">
          <span>{plural(box.parts, "part")}</span>
          <span>{plural(box.flows, "flow")}</span>
        </div>
        {data.fidelity && <FidelityStrip counts={data.fidelity} className="mt-1" />}
        {data.ghost ? (
          <button
            type="button"
            onClick={(ev) => {
              ev.stopPropagation();
              data.onGhost?.();
            }}
            onKeyDown={(ev) => ev.stopPropagation()}
            className="nodrag nopan mt-1 flex h-[20px] w-full items-center justify-between rounded border border-dashed border-muted/60 px-1.5 text-[11px] text-muted hover:border-ink hover:text-ink"
          >
            <span className="truncate">{plural(data.ghost, "mechanism")} not modeled</span>
            <span aria-hidden>›</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

function PartBox({ data }: { data: BoxData }) {
  const { box } = data;
  const tall = (box.preview?.length ?? 0) > 0;
  return (
    <div className={cx(boxFrame(data), "flex bg-panel-2", box.type === "self" && "border-dotted")} style={{ background: surface(data) }} title={box.label}>
      <HiddenHandles />
      <span className="w-[5px] shrink-0" style={{ background: data.color }} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col justify-center px-2.5 py-1">
        <div className="flex items-center gap-1.5">
          <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold leading-tight text-ink">{box.label}</span>
          <Badges data={data} />
          {data.onEnter && <EnterButton label={box.label} onEnter={data.onEnter} />}
        </div>
        <div className="mt-0.5 truncate text-[10.5px] leading-tight text-faint">
          {box.detail}
          {box.parts > 1 ? ` · ${plural(box.parts, "part")}` : ""}
          {box.stateful ? " · ◉ state" : ""}
        </div>
        {tall && (
          <div className="mt-1 truncate text-[10.5px] leading-tight text-muted">
            {box.preview!.join(", ")}
            {box.previewMore ? ` + ${box.previewMore} more` : ""}
          </div>
        )}
        {data.fidelity && <FidelityStrip counts={data.fidelity} className="mt-1" />}
      </div>
    </div>
  );
}

function MoreBox({ data }: { data: BoxData }) {
  const { box } = data;
  return (
    <div className={cx(boxFrame(data), "flex flex-col justify-center border-dashed bg-panel/70 px-2.5")} title={`${box.label}. Click to list them.`}>
      <HiddenHandles />
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-ink">{box.label}</span>
        <Badges data={data} />
      </div>
      <div className="truncate text-[10.5px] text-faint">{box.detail}</div>
    </div>
  );
}

function StubBox({ data }: { data: BoxData }) {
  const { box } = data;
  return (
    <div className={cx(boxFrame(data), "flex items-center gap-1.5 rounded-full border-dashed bg-panel/70 px-3")} title={box.label}>
      <HiddenHandles />
      <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: data.color }} aria-hidden />
      <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted">{box.label}</span>
    </div>
  );
}

function ActorBox({ data }: { data: BoxData }) {
  const { box } = data;
  return (
    <div className={cx(boxFrame(data), "flex flex-col justify-center rounded-full bg-panel px-3.5")} style={{ background: surface(data) }} title={`${box.label}: ${box.detail}`}>
      <HiddenHandles />
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">{box.label}</span>
        <Badges data={data} />
      </div>
      <div className="truncate text-[10px] uppercase tracking-wide text-faint">{box.detail}</div>
    </div>
  );
}

function BoxView({ data }: NodeProps<BoxNode>) {
  switch (data.box.type) {
    case "area":
      return <AreaBox data={data} />;
    case "more":
      return <MoreBox data={data} />;
    case "stub":
      return <StubBox data={data} />;
    case "actor":
      return <ActorBox data={data} />;
    default:
      return <PartBox data={data} />;
  }
}

const nodeTypes = { box: memo(BoxView) };

function rectOf(n: ReturnType<typeof useInternalNode>) {
  if (!n) return null;
  const { x, y } = n.internals.positionAbsolute;
  const w = n.measured.width ?? (n.width as number | undefined) ?? 0;
  const h = n.measured.height ?? (n.height as number | undefined) ?? 0;
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
}

const TONE: Record<EdgeData["tone"], { stroke: string; opacity: number }> = {
  normal: { stroke: "#5b6f80", opacity: 0.9 },
  weak: { stroke: "#5b6f80", opacity: 0.55 },
  lit: { stroke: "#ccff78", opacity: 1 },
  dim: { stroke: "#4f6070", opacity: 0.18 },
};

function FloatingAtlasEdge({ id, source, target, data, markerEnd }: EdgeProps<AtlasFlowEdge>) {
  const s = rectOf(useInternalNode(source));
  const t = rectOf(useInternalNode(target));
  if (!s || !t || !data) return null;
  const dx = t.cx - s.cx;
  const dy = t.cy - s.cy;
  const sideways = Math.abs(dx) * 0.6 >= Math.abs(dy) || Math.abs(dx) > (s.w + t.w) / 2;
  const [path] = getBezierPath(
    sideways
      ? {
          sourceX: dx >= 0 ? s.x + s.w : s.x,
          sourceY: s.cy,
          sourcePosition: dx >= 0 ? Position.Right : Position.Left,
          targetX: dx >= 0 ? t.x : t.x + t.w,
          targetY: t.cy,
          targetPosition: dx >= 0 ? Position.Left : Position.Right,
          curvature: 0.3,
        }
      : {
          sourceX: s.cx,
          sourceY: dy >= 0 ? s.y + s.h : s.y,
          sourcePosition: dy >= 0 ? Position.Bottom : Position.Top,
          targetX: t.cx,
          targetY: dy >= 0 ? t.y : t.y + t.h,
          targetPosition: dy >= 0 ? Position.Top : Position.Bottom,
          curvature: 0.3,
        },
  );
  const tone = TONE[data.tone];
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: tone.stroke,
          opacity: tone.opacity,
          strokeWidth: data.width,
          strokeDasharray: data.tone === "weak" ? "5 4" : data.emits ? "1.5 4.5" : undefined,
          strokeLinecap: "round",
          transition: "opacity 200ms",
        }}
      />
      <path d={path} fill="none" stroke="transparent" strokeWidth={14}>
        <title>{data.title}</title>
      </path>
    </>
  );
}

const edgeTypes = { atlas: FloatingAtlasEdge };

// The pan of each view for this session. A view opens where it was left.
function viewportStoreKey(storeKey: string, view: AtlasView): string {
  return `atlas-viewport:${storeKey}:${scopeKey(view.scope)}`;
}

function readViewport(key: string): Viewport | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return undefined;
    const v = JSON.parse(raw) as Viewport;
    return Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.zoom) ? v : undefined;
  } catch {
    return undefined;
  }
}

function writeViewport(key: string, v: Viewport): void {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(v));
  } catch {
    // Storage may be full or off; the view just opens fitted next time.
  }
}

function layoutKeyOf(view: AtlasView, hasEvidence: boolean): string {
  const boxes = view.boxes.map((b) => b.id).join("|");
  const edges = view.edges.filter((e) => e.strong).map((e) => e.id).join("|");
  return `${scopeKey(view.scope)}#${boxes}#${edges}#${hasEvidence}`;
}

function Canvas(props: AtlasMapProps & { layout: Map<string, BoxRect> }) {
  const { view, layout, colorOf, lens, decor, matches, selected, allConnections, hasEvidence, fidelity, ghosts, onActivate, onEnter, onGhost, onClear, storeKey } = props;
  const [hover, setHover] = useState<string | null>(null);
  const rf = useReactFlow();
  const store = useStoreApi();
  const vpKey = viewportStoreKey(storeKey, view);
  const [saved] = useState(() => readViewport(vpKey));

  const heaviestCount = useMemo(() => Math.max(0, ...(decor ? Array.from(decor.counts.values()) : [])), [decor]);
  const nodes: BoxNode[] = useMemo(() => {
    const filtering = !!matches;
    return view.boxes.flatMap((box) => {
      const r = layout.get(box.id);
      if (!r) return [];
      const lensCount = decor?.counts.get(box.id);
      const match = matches?.get(box.id);
      const dimByLens = !!decor?.lit && !decor.lit.has(box.id);
      const dimByFilter = filtering && !match && box.members.length > 0;
      const size = boxSize(box, hasEvidence);
      const node: BoxNode = {
        id: box.id,
        type: "box",
        position: { x: r.x, y: r.y },
        width: size.width,
        height: size.height,
        style: { width: size.width, height: size.height },
        draggable: false,
        selectable: true,
        focusable: true,
        // Connections run behind the boxes, so they never cross a box's text.
        zIndex: 20,
        ariaLabel: `${box.label}${box.detail ? `, ${box.detail}` : ""}${box.parts > 0 ? `, ${plural(box.parts, "part")}` : ""}${box.flows ? `, ${plural(box.flows, "flow")}` : ""}${lensCount ? `, ${lensCount} in this lens` : ""}`,
        data: {
          box,
          color: box.type === "more" && !box.place ? OTHER_COLOR : colorOf(box.place),
          selected: !!selected && box.component === selected,
          holdsSelection: !!selected && box.component !== selected && box.members.includes(selected),
          dim: dimByLens || dimByFilter,
          tint: lens === "failure" ? tintStep(lensCount ?? 0, heaviestCount) : 0,
          lit: !!decor?.lit?.has(box.id) && lens !== "failure",
          badge: lensCount ? String(lensCount) : undefined,
          match,
          fidelity: fidelity?.get(box.id),
          ghost: box.type === "area" && box.place ? ghosts?.get(box.place) : undefined,
          onEnter: box.enter && box.type !== "stub" && box.type !== "more" ? () => onEnter(box) : undefined,
          onGhost: box.place ? () => onGhost(box.place!) : undefined,
        },
      };
      return [node];
    });
  }, [view, layout, decor, matches, hasEvidence, colorOf, selected, lens, heaviestCount, fidelity, ghosts, onEnter, onGhost]);

  const edges: AtlasFlowEdge[] = useMemo(() => {
    const labels = new Map(view.boxes.map((b) => [b.id, b.label]));
    const lit = new Map((decor?.edges ?? []).map((e) => [e.id, e]));
    const pool = new Map<string, AtlasEdge>(view.edges.map((e) => [e.id, e]));
    for (const [id, e] of lit) if (!pool.has(id)) pool.set(id, e);
    const heaviest = Math.max(1, ...Array.from(pool.values(), (e) => e.weight));
    const dimming = !!decor?.lit;
    const out: AtlasFlowEdge[] = [];
    for (const e of pool.values()) {
      const isLit = lit.has(e.id);
      const touched = !!hover && (e.from === hover || e.to === hover);
      if (!e.strong && !isLit && !touched && !allConnections) continue;
      const offFilter = !!matches && !(matches.has(e.from) && matches.has(e.to));
      const tone: EdgeData["tone"] = isLit ? "lit" : dimming || (offFilter && !touched) ? "dim" : e.strong || touched ? "normal" : "weak";
      out.push({
        id: e.id,
        source: e.from,
        target: e.to,
        type: "atlas",
        zIndex: isLit ? 12 : touched ? 11 : 10,
        markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13, color: TONE[tone].stroke },
        data: {
          width: edgeWidth(e.weight, heaviest),
          emits: e.emits,
          tone,
          title: `${labels.get(e.from)} → ${labels.get(e.to)}: ${plural(e.weight, "call")}`,
        },
      });
    }
    return out;
  }, [view, decor, hover, allConnections, matches]);

  // A selection that lands off screen pans into view, at no less than a readable zoom.
  useEffect(() => {
    const box = selected ? view.boxes.find((b) => b.component === selected) : undefined;
    const r = box ? layout.get(box.id) : undefined;
    if (!r) return;
    const t = window.setTimeout(() => {
      const { width, height, transform } = store.getState();
      const [tx, ty, zoom] = transform;
      const inside = r.x * zoom + tx >= 0 && r.y * zoom + ty >= 0 && (r.x + r.width) * zoom + tx <= width && (r.y + r.height) * zoom + ty <= height;
      if (!inside) rf.setCenter(r.x + r.width / 2, r.y + r.height / 2, { zoom: Math.max(zoom, 0.7), duration: 250 });
    }, 60);
    return () => window.clearTimeout(t);
  }, [selected, view, layout, rf, store]);

  const boxOf = useMemo(() => new Map(view.boxes.map((b) => [b.id, b])), [view]);
  return (
    <div
      className="h-full w-full"
      onKeyDown={(ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        const id = (ev.target as HTMLElement).closest?.(".react-flow__node")?.getAttribute("data-id");
        const box = id ? boxOf.get(id) : undefined;
        if (box) {
          ev.preventDefault();
          onActivate(box);
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
        fitView={!saved}
        fitViewOptions={{ padding: 0.08, maxZoom: 1.1 }}
        defaultViewport={saved}
        minZoom={0.15}
        maxZoom={2.5}
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        onMoveEnd={(_: unknown, v: Viewport) => writeViewport(vpKey, v)}
        onNodeClick={(_: ReactMouseEvent, n: BoxNode) => onActivate(n.data.box)}
        onNodeDoubleClick={(_: ReactMouseEvent, n: BoxNode) => {
          if (n.data.box.enter && n.data.box.type === "component") onEnter(n.data.box);
        }}
        onNodeMouseEnter={(_: ReactMouseEvent, n: BoxNode) => setHover(n.id)}
        onNodeMouseLeave={() => setHover(null)}
        onPaneClick={onClear}
        proOptions={{ hideAttribution: true }}
        aria-label="Map of the model by area"
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#22303b" />
      </ReactFlow>
      <div className="absolute bottom-2 right-2 z-10 flex gap-1 rounded-md border border-line bg-panel/90 p-1 backdrop-blur">
        <Button size="sm" variant="ghost" aria-label="Zoom in" title="Zoom in" onClick={() => rf.zoomIn({ duration: 150 })}>
          +
        </Button>
        <Button size="sm" variant="ghost" aria-label="Zoom out" title="Zoom out" onClick={() => rf.zoomOut({ duration: 150 })}>
          −
        </Button>
        <Button size="sm" variant="ghost" title="Fit this view" onClick={() => rf.fitView({ padding: 0.08, maxZoom: 1.1, duration: 250 })}>
          Fit
        </Button>
      </div>
    </div>
  );
}

export function AtlasMap(props: AtlasMapProps) {
  const { view, hasEvidence } = props;
  const key = layoutKeyOf(view, hasEvidence);
  const [done, setDone] = useState<{ key: string; layout: Map<string, BoxRect> } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    layoutAtlas(view, hasEvidence).then(
      (layout) => !cancelled && setDone({ key, layout }),
      (err) => !cancelled && setFailed(err instanceof Error ? err.message : String(err)),
    );
    return () => {
      cancelled = true;
    };
    // The key is what the layout depends on; a new view object with the same key keeps it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (failed) return <div className="p-4 text-bad">Layout failed: {failed}</div>;
  if (!done || done.key !== key) return <div className="flex h-full items-center justify-center text-muted">Laying out the map…</div>;
  return (
    <div className="relative h-full w-full">
      <ReactFlowProvider key={key}>
        <Canvas {...props} layout={done.layout} />
      </ReactFlowProvider>
    </div>
  );
}
