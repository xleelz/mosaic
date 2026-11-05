"use client";

import { memo, useCallback, useLayoutEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import type { Document, SimEvent } from "@/lib/api/types";
import { formatDuration, ifaceName, jsonChip, jsonInline } from "@/lib/model/format";
import type { ColorScale } from "@/lib/model/colors";
import { docIndex } from "@/lib/model/docindex";
import { isNoise, type WeakFidelity } from "@/lib/sim/beats";
import { laneDepths, type LaneView } from "@/lib/sim/lanes";
import { covers, drawRegion, firstRowAt, lastRowBefore, type Viewport } from "@/lib/sim/window";
import { laneComponent, laneInstance, setLabel, type EventLanes, type Playback } from "@/lib/sim/playback";

// Geometry
const LIFE_W = 118;
const GUTTER = 62;
const HEAD_H = 50;
/** The strip above the heads that names and toggles each area, when lanes are grouped. */
const AREA_STRIP_H = 15;
const RIGHT_PAD = 260;
const ACT_W = 10;
/** How far past the viewport to draw, so most scrolling needs no render. */
const MARGIN_X = 600;
const MARGIN_Y = 800;
/** How far a lane's mark or label can reach to the right of its lane. */
const LABEL_REACH = 480;
/** Activation bars stop stepping right past this depth. */
const MAX_DEPTH_STEP = 8;

const ROW_H: Record<string, number> = {
  "call.start": 32,
  "call.end": 30,
  note: 28,
  set: 17,
  choice: 22,
  fault: 24,
  retry: 26,
  timeout: 32,
  emit: 30,
  warning: 22,
  queue: 24,
  publish: 28,
  "parallel.start": 28,
  "parallel.end": 28,
  "step.start": 30,
  "step.end": 24,
  deadline: 30,
  yield: 24,
  put: 24,
  receive: 24,
  kill: 28,
};

// Colors (marks). Text uses text tokens.
const C = {
  life: "#2a3742",
  call: "#c9d6df",
  ret: "#7d8d99",
  error: "#d03b3b",
  late: "#fab219",
  async: "#5fb8a8",
  fault: "#ec835a",
  retry: "#9085e9",
  timeout: "#fab219",
  choice: "#fab219",
  note: "#3a4a57",
  set: "#5b6b78",
  ink: "#edf3f6",
  muted: "#a2b1bc",
  faint: "#8796a1",
  accent: "#ccff78",
  parallel: "#5a8fb8",
  queue: "#c9a24a",
  mock: "#b3a8ff",
  step: "#4d6b1f",
};

/** Lanes per branch bar, offset right of the lifeline. */
const BRANCH_DX = 5;

interface Row {
  top: number;
  h: number;
  /** y of the arrow / marker line */
  y: number;
  /** Draws its time in the gutter: the first row shown at that time. */
  showT: boolean;
}

/** What the static layer needs from the lane view. */
interface LaneGeometry {
  lifeX: (c: string) => number;
  depthOf: (span: SpanRef | undefined) => number;
  weak?: ReadonlyMap<string, WeakFidelity>;
}

type SpanRef = { span: number; depth: number };

/** The fidelity vocabulary's shapes, as text a label can carry (components/trust). */
const WEAK_LABEL: Record<WeakFidelity, { text: string; color: string; meaning: string }> = {
  partial: { text: "◐ partial", color: "#ffd08a", meaning: "Partial: the main path only" },
  shell: { text: "○ shell", color: "#ec835a", meaning: "Shell: the model claims this, but doesn't do it" },
  absent: { text: "◌ absent", color: "#a2b1bc", meaning: "Absent: known to exist in the code, not in this model" },
};

function WeakTag({ fidelity }: { fidelity?: WeakFidelity }) {
  if (!fidelity) return null;
  const w = WEAK_LABEL[fidelity];
  return (
    <tspan dx={5} fill={w.color} fontSize={10} style={{ fontWeight: 600 }}>
      {w.text}
    </tspan>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, Math.max(1, max - 1))}…` : s;
}

/** Squeeze a lifeline head line that would overflow its box (wide glyphs in a 16-character name). */
function fitHead(text: string): { textLength?: number; lengthAdjust?: "spacingAndGlyphs" } {
  const room = LIFE_W - 26;
  return text.length * 6.9 > room ? { textLength: room, lengthAdjust: "spacingAndGlyphs" } : {};
}

function splitName(name: string, max = 16): [string, string?] {
  if (name.length <= max) return [name];
  const words = name.split(/\s+/);
  let a = "";
  let i = 0;
  while (i < words.length && (a + (a ? " " : "") + words[i]).length <= max) {
    a += (a ? " " : "") + words[i];
    i++;
  }
  if (!a) return [truncate(name, max)];
  return [a, truncate(words.slice(i).join(" "), max)];
}

function Markers() {
  const m = (id: string, color: string, open = false) => (
    <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      {open ? (
        <path d="M 1 1 L 9 5 L 1 9" fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      ) : (
        <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
      )}
    </marker>
  );
  return (
    <defs>
      {m("sq-call", C.call)}
      {m("sq-ret", C.ret, true)}
      {m("sq-err", C.error)}
      {m("sq-late", C.late, true)}
      {m("sq-async", C.async, true)}
      {m("sq-retry", C.retry)}
    </defs>
  );
}

interface Props {
  playback: Playback;
  doc?: Document;
  scale: ColorScale;
  colorKey: (component: string) => string | undefined;
  cursor: number;
  onCursor: (i: number) => void;
  /**
   * How far floating panels cover the diagram's right and bottom edges, in
   * pixels. The cursor row scrolls into the uncovered region, and the content
   * gets that much extra room so its last rows and lifelines can clear them.
   */
  insets?: { right: number; bottom: number };
  /** The lanes to draw. */
  view: LaneView;
  /** Toggles an area between one lane and its components. */
  onToggleArea?: (area: string) => void;
  /** Hide `set` and `note` rows. */
  hideNoise?: boolean;
  /** interface -> its worst fidelity, for the calls that pass through a weak mechanism. */
  weak?: ReadonlyMap<string, WeakFidelity>;
  /** Change this to center the diagram on the cursor, rather than just keep it in view. */
  centerKey?: number;
}

function Glyph({ x, y, color, children, title }: { x: number; y: number; color: string; children: string; title?: string }) {
  return (
    <g>
      {title && <title>{title}</title>}
      <circle cx={x} cy={y} r={8} fill="#0d1318" stroke={color} strokeWidth={1.5} />
      <text x={x} y={y + 3.5} textAnchor="middle" fontSize={10} fill={color} style={{ fontWeight: 700 }}>
        {children}
      </text>
    </g>
  );
}

function StaticLayer({ playback, rows, geo, width, spanList, region }: { playback: Playback; rows: Row[]; geo: LaneGeometry; width: number; spanList: SpanRefFull[]; region: Viewport }) {
  const { events } = playback;
  const { lifeX, depthOf } = geo;
  const els: ReactNode[] = [];
  const y0 = region.y;
  const y1 = region.y + region.h;
  const x0 = region.x;
  const x1 = region.x + region.w;
  const laneShown = (x: number) => x >= x0 - LABEL_REACH && x <= x1 + LIFE_W;
  // A band from row r0 to r1 (its y range) meets the drawn region.
  const meets = (top: number, bottom: number) => bottom >= y0 && top <= y1;

  // Lifelines: one line per drawn lane.
  const lanesDrawn = new Set<number>();
  playback.lifelines.forEach((c) => {
    const x = lifeX(c);
    if (lanesDrawn.has(x) || x < x0 || x > x1) return;
    lanesDrawn.add(x);
    els.push(<line key={`l-${x}`} x1={x} y1={y0} x2={x} y2={y1} stroke={C.life} strokeWidth={1} strokeDasharray="3 4" />);
  });

  // Activation bars
  for (const s of spanList) {
    const r0 = rows[s.startIdx];
    const r1 = s.endIdx >= 0 ? rows[s.endIdx] : rows[rows.length - 1];
    if (!r0 || !r1 || !meets(r0.y, r1.y)) continue;
    const x = lifeX(s.to) - ACT_W / 2 + Math.min(depthOf(s), MAX_DEPTH_STEP) * 4;
    if (x < x0 - ACT_W || x > x1) continue;
    const weak = geo.weak?.get(s.iface);
    els.push(
      <rect
        key={`a-${s.span}`}
        x={x}
        y={r0.y}
        width={ACT_W}
        height={Math.max(4, r1.y - r0.y)}
        rx={2}
        fill={weak === "shell" ? "transparent" : s.async ? "#12302c" : "#1c2a36"}
        stroke={weak ? WEAK_LABEL[weak].color : s.ok === false ? "#7a3434" : s.async ? "#2f6e64" : "#3b4d5c"}
        strokeWidth={1}
        strokeDasharray={weak === "partial" ? "4 2" : undefined}
      />,
    );
  }

  // Multi-step scenario separators (§11.7): a band per step.
  playback.steps.forEach((m, k) => {
    const r0 = rows[m.startIdx];
    const r1 = m.endIdx >= 0 ? rows[m.endIdx] : rows[rows.length - 1];
    if (!r0 || !r1 || !meets(r0.top, r1.top + r1.h) || !(k % 2)) return;
    els.push(<rect key={`st-${k}`} x={x0} y={r0.top} width={region.w} height={Math.max(4, r1.top + r1.h - r0.top)} fill="rgba(204,255,120,0.025)" />);
  });

  // Parallel groups (§11.2): a bracket on the behavior's lane, and a bar per branch spanning its rows.
  playback.parallels.forEach((g, k) => {
    const r0 = rows[g.startIdx];
    const r1 = g.endIdx >= 0 ? rows[g.endIdx] : rows[rows.length - 1];
    if (!r0 || !r1 || !meets(r0.y, r1.y) || !laneShown(lifeX(g.lane))) return;
    const x = lifeX(g.lane) - 18 - g.depth * 6;
    els.push(<path key={`pg-${k}`} d={`M ${x + 6} ${r0.y} h -6 V ${r1.y} h 6`} fill="none" stroke={C.parallel} strokeWidth={1.4} opacity={0.9} />);
    const bx = lifeX(g.lane) + ACT_W + 4;
    const keys = Array.from(g.branches.keys()).sort((a, b) => a - b);
    keys.forEach((b, n) => {
      const br = g.branches.get(b)!;
      const a = rows[br.first];
      const z = rows[br.last];
      if (!a || !z || !meets(a.top, z.top + z.h)) return;
      const late = playback.events[br.last]?.late || (g.endIdx >= 0 && br.last > g.endIdx);
      els.push(
        <g key={`pb-${k}-${b}`} opacity={late ? 0.45 : 0.9}>
          <title>{`branch ${b}`}</title>
          <rect x={bx + n * BRANCH_DX} y={a.top + 2} width={3} height={Math.max(4, z.top + z.h - a.top - 4)} rx={1.5} fill={C.parallel} />
        </g>,
      );
    });
  });

  // Time gutter + events, for the rows in the drawn region only.
  const first = firstRowAt(rows, y0);
  const last = lastRowBefore(rows, y1);
  for (let i = first; i <= last; i++) {
    const r = rows[i];
    if (r.h === 0) continue;
    const e = events[i];
    if (r.showT && x0 < GUTTER) {
      els.push(
        <text key={`t-${i}`} x={GUTTER - 10} y={r.y + 3.5} textAnchor="end" fontSize={10} fill={C.faint} className="tnum">
          {e.t} ms
        </text>,
      );
    }
    if (!rowInView(playback.lanes[i] ?? {}, e, lifeX, x0, x1)) continue;
    const mark = <EventMark key={`e-${i}`} i={i} e={e} r={r} rows={rows} geo={geo} playback={playback} width={width} />;
    // Late work (after a timeout or a join) is dimmed.
    els.push(e.late && e.type !== "call.end" ? <g key={`e-${i}`} opacity={0.5}>{mark}</g> : mark);
  }

  return <g>{els}</g>;
}

/** Whether a row's mark can reach the drawn columns: an arrow if it overlaps them, a lane mark if its label can. */
function rowInView(lane: EventLanes, e: SimEvent, lifeX: (c: string) => number, x0: number, x1: number): boolean {
  if (e.type === "step.start" || e.type === "step.end") return true;
  const xs: number[] = [];
  for (const l of [lane.from, lane.to, lane.at]) if (l !== undefined) xs.push(lifeX(l));
  if (xs.length === 0) return true;
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  return hi + LABEL_REACH >= x0 && lo <= x1;
}

const MemoStatic = memo(StaticLayer);

/**
 * A caller-side mark (timeout, deadline): a glyph on the caller's lane and a
 * dashed arrow toward the callee lane, labelled above the arrow.
 */
function CallerMark({
  x,
  y,
  tx,
  color,
  marker,
  glyph,
  title,
  label,
  target,
  clearX,
}: {
  x: number;
  y: number;
  tx: number;
  color: string;
  marker: string;
  glyph: string;
  title?: string;
  label: ReactNode;
  target: string;
  clearX: (x: number) => number;
}) {
  const dir = tx >= x ? 1 : -1;
  const x1 = x + dir * 9;
  const x2 = tx - dir * (ACT_W / 2);
  return (
    <g>
      {Math.abs(x2 - x1) > 12 && (
        <line x1={x1} y1={y} x2={x2} y2={y} stroke={color} strokeWidth={1.3} strokeDasharray="4 4" opacity={0.85} markerEnd={marker} />
      )}
      <Glyph x={x} y={y} color={color} title={title}>
        {glyph}
      </Glyph>
      {arrowLabel(Math.min(x, tx) + 4, Math.max(x, tx), y, label, `→ ${target}`, C.faint, clearX)}
    </g>
  );
}

function arrowLabel(x1: number, x2: number, y: number, label: ReactNode, chip?: string, chipColor = C.faint, clearX?: (x: number) => number) {
  const left = clearX ? clearX(Math.min(x1, x2) + 8) : Math.min(x1, x2) + 8;
  return (
    <text x={left} y={y - 6} fontSize={11}>
      {label}
      {chip ? (
        <tspan dx={6} fill={chipColor} fontSize={10.5} style={{ fontFamily: "var(--font-mono)" }}>
          {chip}
        </tspan>
      ) : null}
    </text>
  );
}

function MockTag() {
  return (
    <tspan fill={C.mock} fontSize={10} style={{ fontWeight: 700 }}>
      {" [mock]"}
    </tspan>
  );
}

function EventMark({
  i,
  e,
  r,
  rows,
  geo,
  playback,
  width,
}: {
  i: number;
  e: SimEvent;
  r: Row;
  rows: Row[];
  geo: LaneGeometry;
  playback: Playback;
  width: number;
}) {
  const { lifeX } = geo;
  const y = r.y;
  const span = e.span ? playback.spans.get(e.span) : undefined;
  const weak = e.interface ? geo.weak?.get(e.interface) : undefined;
  const lane: EventLanes = playback.lanes[i] ?? {};
  const atX = lifeX(lane.at ?? e.component ?? "");
  const branch = e.branch !== undefined ? <tspan fill={C.parallel} fontSize={10}>{`#${e.branch} `}</tspan> : null;
  // A label that starts on a lane carrying branch bars begins right of the bars.
  const group = playback.branchGroup[i] >= 0 ? playback.parallels[playback.branchGroup[i]] : undefined;
  const clearX = (left: number) => {
    if (!group) return left;
    const bx = lifeX(group.lane) + ACT_W + 4;
    const end = bx + group.branches.size * BRANCH_DX + 4;
    return left >= bx - 8 && left < end ? end : left;
  };
  switch (e.type) {
    case "call.start": {
      const from = lane.from ?? "";
      const to = lane.to ?? "";
      const x1 = lifeX(from);
      const x2raw = lifeX(to);
      const dir = x2raw >= x1 ? 1 : -1;
      const depth = Math.min(geo.depthOf(span), MAX_DEPTH_STEP);
      const x2 = x2raw - dir * (ACT_W / 2) + depth * 4;
      const async = !!e.async;
      const attempt = e.attempt ?? 1;
      const color = async ? C.async : C.call;
      const label = (
        <>
          {attempt > 1 && (
            <tspan fill={C.retry} style={{ fontWeight: 700 }}>
              ↻{attempt}{" "}
            </tspan>
          )}
          {branch}
          {async && <tspan fill={C.async}>⇢ async </tspan>}
          <tspan fill={C.ink} style={{ fontWeight: 600 }}>
            {ifaceName(e.interface ?? "")}
          </tspan>
          {e.mock && <MockTag />}
          <WeakTag fidelity={weak} />
        </>
      );
      // Same drawn lane: a real self-call, or two components in one collapsed area.
      if (x1 === x2raw) {
        return (
          <g>
            <path d={`M ${x1} ${y - 8} h 26 v 10 h -${26 - ACT_W / 2}`} fill="none" stroke={color} strokeWidth={1.4} markerEnd={async ? "url(#sq-async)" : "url(#sq-call)"} strokeDasharray={async ? "1.5 4" : undefined} strokeLinecap="round" />
            {arrowLabel(x1 + 24, x1 + 24, y - 6, label, jsonChip(e.input))}
          </g>
        );
      }
      return (
        <g>
          <line x1={x1} y1={y} x2={x2} y2={y} stroke={color} strokeWidth={1.5} strokeDasharray={async ? "1.5 4.5" : undefined} strokeLinecap="round" markerEnd={async ? "url(#sq-async)" : "url(#sq-call)"} />
          {arrowLabel(x1, x2, y, label, jsonChip(e.input), C.faint, clearX)}
        </g>
      );
    }
    case "call.end": {
      const from = lane.from ?? "";
      const to = lane.to ?? "";
      const depth = Math.min(geo.depthOf(span), MAX_DEPTH_STEP);
      const xs0 = lifeX(to);
      const xd = lifeX(from);
      const dir = xd >= xs0 ? 1 : -1;
      const xs = xs0 + dir * (ACT_W / 2) + depth * 4;
      const failed = e.ok === false;
      const late = !!e.late;
      const async = !!e.async;
      const color = late ? C.late : failed ? C.error : async ? C.async : C.ret;
      const marker = late ? "url(#sq-late)" : failed ? "url(#sq-err)" : async ? "url(#sq-async)" : "url(#sq-ret)";
      const dash = late ? "6 4" : async ? "1.5 4.5" : undefined;
      const chip = failed ? `${e.error?.status ? `${e.error.status} ` : ""}${e.error?.code ?? "error"}` : jsonChip(e.output);
      const label = (
        <>
          {late && <tspan fill={C.late} style={{ fontWeight: 700 }}>⇠ late </tspan>}
          {failed && <tspan fill="#ff9b99" style={{ fontWeight: 700 }}>✗ </tspan>}
          {branch}
          <tspan fill={C.muted}>{failed ? "error" : "return"}</tspan>
          <tspan fill={C.faint} fontSize={10}>{` ${formatDuration(e.duration_ms ?? 0, e.duration_us)}`}</tspan>
          {e.mock && <MockTag />}
        </>
      );
      if (xs0 === xd) {
        return (
          <g>
            <path d={`M ${xs0 + ACT_W / 2} ${y - 8} h 20 v 10 h -20`} fill="none" stroke={color} strokeWidth={1.3} markerEnd={marker} strokeDasharray={dash} />
            {arrowLabel(xs0 + 24, xs0 + 24, y - 6, label, chip, failed ? "#ff9b99" : C.faint)}
          </g>
        );
      }
      return (
        <g>
          <line x1={xs} y1={y} x2={xd} y2={y} stroke={color} strokeWidth={failed ? 1.6 : 1.25} strokeDasharray={dash} markerEnd={marker} />
          {arrowLabel(xs, xd, y, label, chip, failed ? "#ff9b99" : C.faint, clearX)}
        </g>
      );
    }
    case "note": {
      const x = atX + 10;
      const text = e.title || e.detail || "note";
      const w = Math.min(Math.max(80, text.length * 6.2 + 26), LIFE_W * 3.2);
      const chars = Math.floor((w - 26) / 6.2);
      return (
        <g>
          <title>{[e.title, e.detail].filter(Boolean).join("\n")}</title>
          <path d={`M ${x} ${y - 9} h ${w - 7} l 7 7 v 11 h -${w} z`} fill="#161f29" stroke={C.note} strokeWidth={1} />
          <path d={`M ${x + w - 7} ${y - 9} v 7 h 7`} fill="none" stroke={C.note} strokeWidth={1} />
          <text x={x + 7} y={y + 4} fontSize={11} fill={C.ink}>
            <tspan fill={C.faint}>✎ </tspan>
            {truncate(text, chars)}
          </text>
        </g>
      );
    }
    case "set": {
      const x = atX;
      return (
        <g>
          <rect x={x - 3} y={y - 3} width={6} height={6} transform={`rotate(45 ${x} ${y})`} fill={C.set} />
          <text x={x + 10} y={y + 3.5} fontSize={10} fill={C.faint} style={{ fontFamily: "var(--font-mono)" }}>
            {truncate(`${setLabel(e)} = ${jsonInline(e.new ?? null, 40)}`, 54)}
          </text>
        </g>
      );
    }
    case "choice": {
      const x = atX;
      const name = (e.key ?? "").split(".").pop();
      return (
        <g>
          <rect x={x - 5} y={y - 5} width={10} height={10} transform={`rotate(45 ${x} ${y})`} fill="#2a2213" stroke={C.choice} strokeWidth={1.3} />
          <text x={x + 12} y={y + 4} fontSize={11}>
            <tspan fill={C.muted}>{name} → </tspan>
            <tspan fill={C.ink} style={{ fontWeight: 600 }}>{e.option}</tspan>
            <tspan fill={C.faint} fontSize={10}>{` (${e.origin})`}</tspan>
          </text>
        </g>
      );
    }
    case "fault": {
      const x = atX;
      return (
        <g>
          <Glyph x={x} y={y} color={C.fault} title={`fault ${e.fault} on ${e.interface}`}>
            ⚡
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            <tspan fill="#f5b294" style={{ fontWeight: 600 }}>fault: {e.fault}</tspan>
            {e.message && <tspan fill={C.faint}>{` · ${e.message}`}</tspan>}
          </text>
        </g>
      );
    }
    case "retry": {
      const x = atX;
      return (
        <g>
          <Glyph x={x} y={y} color={C.retry} title={e.title || "retry"}>
            ↻
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            <tspan fill="#c9c0ff" style={{ fontWeight: 600 }}>retry → attempt {e.attempt}</tspan>
            <tspan fill={C.faint}>{` · ${e.message ?? ""} · backoff ${e.backoff_ms ?? 0} ms`}</tspan>
            {e.title && <tspan fill={C.muted}>{` · ${truncate(e.title, 44)}`}</tspan>}
          </text>
        </g>
      );
    }
    case "timeout": {
      // On the caller's lane (§13.1 item 11): a bracket from the call's start
      // to the timeout, and a dashed arrow toward the callee it gave up on.
      const x = atX;
      const start = span ? rows[span.startIdx] : undefined;
      const y0 = start ? start.y : y;
      const bx = x - 14;
      const msg = e.message && <tspan fill={C.faint}>{` · ${truncate(e.message, 48)}`}</tspan>;
      const label = (
        <>
          {branch}
          <tspan fill={C.late} style={{ fontWeight: 600 }}>⏱ timeout {e.duration_ms} ms</tspan>
        </>
      );
      return (
        <g>
          {y0 < y - 4 && (
            <path d={`M ${bx + 5} ${y0} h -5 V ${y} h 5`} fill="none" stroke={C.timeout} strokeWidth={1.2} strokeDasharray="3 3" opacity={0.8} />
          )}
          {lane.to ? (
            <CallerMark x={x} y={y} tx={lifeX(lane.to)} color={C.timeout} marker="url(#sq-late)" glyph="⏱" title={e.message} label={label} target={lane.to} clearX={clearX} />
          ) : (
            <>
              <Glyph x={x} y={y} color={C.timeout} title={e.message}>
                ⏱
              </Glyph>
              <text x={clearX(x + 13)} y={y + 4} fontSize={11}>
                {label}
                {msg}
              </text>
            </>
          )}
        </g>
      );
    }
    case "emit": {
      const x1 = lifeX(lane.from ?? "");
      const x2 = lifeX(lane.to ?? "");
      return (
        <g>
          <line x1={x1} y1={y} x2={x2} y2={y} stroke={C.async} strokeWidth={1.6} strokeDasharray="1.5 4.5" strokeLinecap="round" markerEnd="url(#sq-async)" />
          {arrowLabel(
            x1,
            x2,
            y,
            <>
              {branch}
              <tspan fill={C.async} style={{ fontWeight: 600 }}>⇢ emit </tspan>
              <tspan fill={C.ink}>{ifaceName(e.interface ?? "")}</tspan>
              <tspan fill={C.faint} fontSize={10}> queued</tspan>
            </>,
            jsonChip(e.input),
          )}
        </g>
      );
    }
    case "warning": {
      const x = atX;
      return (
        <g>
          <Glyph x={x} y={y} color={C.late}>
            ⚠
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11} fill={C.late}>
            {truncate(e.message ?? "warning", 60)}
          </text>
        </g>
      );
    }
    case "queue": {
      const x = atX;
      return (
        <g>
          <Glyph x={x} y={y} color={C.queue} title={`waited ${e.wait_ms ?? 0} ms for a capacity slot`}>
            ⧗
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            {branch}
            <tspan fill={C.queue} style={{ fontWeight: 600 }}>queued {e.wait_ms ?? 0} ms</tspan>
            {e.interface && <tspan fill={C.faint}>{` · ${ifaceName(e.interface)}`}</tspan>}
          </text>
        </g>
      );
    }
    case "deadline": {
      // On the caller's lane (§13.1 item 11), pointing at the callee it never called.
      const x = atX;
      const title = e.message || e.error?.message || "deadline exceeded";
      const label = (
        <>
          {branch}
          <tspan fill="#ff9b99" style={{ fontWeight: 600 }}>⌛ deadline exceeded</tspan>
          {e.interface && <tspan fill={C.faint}>{` · ${ifaceName(e.interface)} not called`}</tspan>}
        </>
      );
      if (lane.to) {
        return <CallerMark x={x} y={y} tx={lifeX(lane.to)} color={C.error} marker="url(#sq-err)" glyph="⌛" title={title} label={label} target={lane.to} clearX={clearX} />;
      }
      return (
        <g>
          <Glyph x={x} y={y} color={C.error} title={title}>
            ⌛
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            {label}
          </text>
        </g>
      );
    }
    case "publish": {
      const x = atX;
      const subs = playback.fanout.get(i) ?? [];
      const last = subs.length ? rows[subs[subs.length - 1]] : undefined;
      return (
        <g>
          {last && last.y > y && <path d={`M ${x - 12} ${y} h -4 V ${last.y} h 4`} fill="none" stroke={C.async} strokeWidth={1.2} strokeDasharray="2 3" />}
          {subs.map((j) => {
            const sl = playback.lanes[j];
            const tx = lifeX(sl?.to ?? "");
            return <circle key={j} cx={tx} cy={y} r={2.5} fill={C.async} />;
          })}
          <Glyph x={x} y={y} color={C.async} title={`publish ${e.topic ?? ""}`}>
            ◉
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            {branch}
            <tspan fill={C.async} style={{ fontWeight: 600 }}>publish </tspan>
            <tspan fill={C.ink}>{e.topic ?? e.interface}</tspan>
            <tspan fill={C.faint} fontSize={10}>{` → ${subs.length} subscriber${subs.length === 1 ? "" : "s"}`}</tspan>
          </text>
        </g>
      );
    }
    case "parallel.start":
    case "parallel.end": {
      const x = atX;
      const o = (e.output && typeof e.output === "object" && !Array.isArray(e.output) ? e.output : {}) as Record<string, unknown>;
      const failed = !!e.error;
      const text =
        e.type === "parallel.start"
          ? `parallel · ${String(o.branches ?? "?")} branches · need ${String(o.need ?? "?")}`
          : failed
            ? `join failed: ${e.error?.code} · ${String(o.received ?? "?")}/${String(o.required ?? "?")}`
            : `joined · ${String(o.received ?? "?")}/${String(o.required ?? "?")}${o.duration_ms !== undefined ? ` in ${String(o.duration_ms)} ms` : ""}`;
      return (
        <g>
          <Glyph x={x} y={y} color={failed ? C.error : C.parallel}>
            ⫴
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11} fill={failed ? "#ff9b99" : "#8fc1e8"} style={{ fontWeight: 600 }}>
            {text}
          </text>
        </g>
      );
    }
    case "yield": {
      // §13.1 item 18: one streamed item, on the callee's lane.
      const x = atX;
      return (
        <g>
          <Glyph x={x} y={y} color={C.async} title={`yield #${e.index ?? 0}: ${truncate(JSON.stringify(e.output ?? null), 200)}`}>
            ↟
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            {branch}
            <tspan fill={C.async} style={{ fontWeight: 600 }}>{`yield #${e.index ?? 0} `}</tspan>
            <tspan fill={C.faint}>{truncate(JSON.stringify(e.output ?? null), 40)}</tspan>
          </text>
        </g>
      );
    }
    case "put":
    case "receive": {
      // §13.1 item 18: a channel operation, with its wait when it blocked.
      const x = atX;
      const put = e.type === "put";
      const failed = !!e.error;
      const color = failed ? C.error : C.queue;
      const value = put ? e.input : e.output;
      return (
        <g>
          <Glyph x={x} y={y} color={color} title={`${put ? "put on" : "receive from"} ${e.key ?? ""}${e.wait_ms ? ` after waiting ${e.wait_ms} ms` : ""}`}>
            {put ? "⇥" : "⇤"}
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            {branch}
            <tspan fill={failed ? "#ff9b99" : C.queue} style={{ fontWeight: 600 }}>{`${put ? "put" : "receive"} ${e.key ?? ""}`}</tspan>
            {failed && <tspan fill="#ff9b99">{` · ✗ ${e.error?.code}`}</tspan>}
            {!!e.wait_ms && <tspan fill={C.faint}>{` · waited ${e.wait_ms} ms`}</tspan>}
            {!failed && value !== undefined && <tspan fill={C.faint}>{` · ${truncate(JSON.stringify(value), 40)}`}</tspan>}
          </text>
        </g>
      );
    }
    case "kill": {
      // §13.1 item 18: an instance terminated.
      const x = atX;
      const o = (e.output && typeof e.output === "object" && !Array.isArray(e.output) ? e.output : {}) as Record<string, unknown>;
      return (
        <g>
          <Glyph x={x} y={y} color={C.error} title={`kill ${e.component ?? ""}${e.instance ? `@${e.instance}` : ""}`}>
            ✖
          </Glyph>
          <text x={x + 13} y={y + 4} fontSize={11}>
            <tspan fill="#ff9b99" style={{ fontWeight: 700 }}>{`killed ${e.component ?? ""}${e.instance ? `@${e.instance}` : ""}`}</tspan>
            <tspan fill={C.faint}>{` · ${String(o.failed ?? 0)} calls failed · ${String(o.stopped ?? 0)} tasks stopped`}</tspan>
          </text>
        </g>
      );
    }
    case "step.start":
    case "step.end": {
      const start = e.type === "step.start";
      const failed = e.ok === false || !!e.error;
      return (
        <g>
          <line x1={0} y1={start ? r.top + 2 : y} x2={width} y2={start ? r.top + 2 : y} stroke={start ? C.accent : C.step} strokeWidth={start ? 1.2 : 1} strokeDasharray={start ? undefined : "4 4"} opacity={0.7} />
          <text x={GUTTER} y={y + 4} fontSize={11}>
            <tspan fill={C.accent} style={{ fontWeight: 700 }}>{start ? "▤ step " : "end of step "}</tspan>
            <tspan fill={C.ink} style={{ fontWeight: 600 }}>{e.key}</tspan>
            {start && e.interface && <tspan fill={C.faint}>{` · ${e.interface}`}</tspan>}
            {start && e.instance && <tspan fill={C.faint}>{` on ${e.instance}`}</tspan>}
            {!start && <tspan fill={failed ? "#ff9b99" : C.faint}>{failed ? ` · ✗ ${e.error?.code ?? "failed"}` : " · ✓"}</tspan>}
          </text>
        </g>
      );
    }
    default:
      return null;
  }
}

const NO_INSETS = { right: 0, bottom: 0 };

type SpanRefFull = SpanRef & { to: string; startIdx: number; endIdx: number; iface: string; async: boolean; ok?: boolean };

function regionEqual(a: Viewport, b: Viewport): boolean {
  return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
}

/**
 * The diagram is windowed: its scroll content has the full trace's size, but only the rows and
 * lanes near the viewport are in the DOM, in an SVG positioned over them. So its cost follows
 * the screen, not the trace. A click finds its row by position, so rows need no hit targets.
 */
export function SequenceDiagram({ playback, doc, scale, colorKey, cursor, onCursor, insets = NO_INSETS, view, onToggleArea, hideNoise = false, weak, centerKey }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const hoverRef = useRef<HTMLDivElement>(null);
  const { events } = playback;
  const lanes = view.lanes;
  const headH = HEAD_H + (view.grouped ? AREA_STRIP_H : 0);

  const rows = useMemo(() => {
    const out: Row[] = [];
    let top = 8;
    let lastT = -1;
    for (const e of events) {
      if (hideNoise && isNoise(e)) {
        // Hidden: no height, but still a position, so everything that indexes rows by event holds.
        out.push({ top, h: 0, y: top, showT: false });
        continue;
      }
      const h = ROW_H[e.type] ?? 22;
      out.push({ top, h, y: top + h - (e.type === "call.start" || e.type === "call.end" || e.type === "emit" || e.type === "step.start" ? 8 : h / 2), showT: e.t !== lastT });
      lastT = e.t;
      top += h;
    }
    return out;
  }, [events, hideNoise]);

  const laneX = useCallback((i: number) => GUTTER + i * LIFE_W + LIFE_W / 2, []);
  const spanList = useMemo(() => Array.from(playback.spans.values()) as SpanRefFull[], [playback]);
  const depths = useMemo(() => (view.grouped ? laneDepths(spanList, view.indexOf) : null), [view, spanList]);
  const geo = useMemo<LaneGeometry>(
    () => ({
      lifeX: (c: string) => laneX(view.indexOf.get(c) ?? 0),
      depthOf: (s) => (s ? (depths ? (depths.get(s.span) ?? 0) : s.depth) : 0),
      weak,
    }),
    [view, depths, laneX, weak],
  );
  const width = GUTTER + lanes.length * LIFE_W + RIGHT_PAD;
  const last = rows[rows.length - 1];
  const height = last ? last.top + last.h + 24 : 60;

  const [region, setRegion] = useState<Viewport>({ x: 0, y: 0, w: 1600, h: 1600 });
  // Redraws only when the viewport leaves what's drawn.
  const syncRegion = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const v = { x: el.scrollLeft, y: Math.max(0, el.scrollTop - headH), w: el.clientWidth, h: el.clientHeight };
    setRegion((cur) => {
      if (covers(cur, v, width, height) && cur.x + cur.w <= width && cur.y + cur.h <= height && cur.h > 0) return cur;
      const next = drawRegion(v, width, height, MARGIN_X, MARGIN_Y);
      return regionEqual(cur, next) ? cur : next;
    });
  }, [width, height, headH]);

  const curRow = rows[cursor];
  const curLane = playback.lanes[cursor];
  const activeLanes = new Set<number>();
  if (curLane) {
    for (const l of [curLane.from, curLane.to, curLane.at]) {
      const i = l ? view.indexOf.get(l) : undefined;
      if (i !== undefined) activeLanes.add(i);
    }
  }
  const activeKey = Array.from(activeLanes).join(",");

  // Keep the cursor row (and its lanes) in view; center on it when asked, and on first showing.
  const centered = useRef<number | undefined>(undefined);
  const mounted = useRef(false);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && curRow) {
      const center = !mounted.current || centered.current !== centerKey;
      mounted.current = true;
      centered.current = centerKey;
      // Rows sit below the sticky lifeline heads.
      // Floating panels cover the right and bottom edges; aim for what's left.
      const viewH = Math.max(headH + curRow.h, el.clientHeight - insets.bottom);
      const viewW = Math.max(LIFE_W, el.clientWidth - insets.right);
      const top = headH + curRow.top;
      const bottom = top + curRow.h;
      if (center) el.scrollTop = Math.max(0, top - headH - (viewH - headH) / 2);
      else if (top < el.scrollTop + headH + 6 || bottom > el.scrollTop + viewH - 6) {
        el.scrollTop = Math.max(0, top - headH - (viewH - headH) * 0.4);
      }
      // Keep the active lanes and their labels in view, moving as little as possible.
      const xs = Array.from(activeLanes).map((i) => laneX(i));
      if (xs.length) {
        const lo = Math.max(0, Math.min(...xs) - 70);
        const hi = Math.max(...xs) + 300;
        const minLeft = hi - viewW;
        if (center) el.scrollLeft = Math.max(0, (lo + hi - viewW) / 2);
        else if (minLeft > lo) el.scrollLeft = lo;
        else el.scrollLeft = Math.min(Math.max(el.scrollLeft, minLeft), lo);
      }
    }
    syncRegion();
    // activeLanes derives from the cursor; recomputing on cursor is intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor, curRow, activeKey, centerKey, insets.right, insets.bottom, syncRegion, headH, laneX]);

  // A resize can show more than was drawn.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(syncRegion);
    ro.observe(el);
    return () => ro.disconnect();
  }, [syncRegion]);

  const rowAt = (ev: MouseEvent<HTMLDivElement>): number => {
    const y = ev.clientY - ev.currentTarget.getBoundingClientRect().top;
    let i = firstRowAt(rows, y);
    while (i < rows.length && rows[i].h === 0) i++;
    return i < rows.length && rows[i].top <= y ? i : -1;
  };
  const onMove = (ev: MouseEvent<HTMLDivElement>) => {
    const el = hoverRef.current;
    if (!el) return;
    const i = rowAt(ev);
    if (i < 0) {
      el.style.display = "none";
      return;
    }
    el.style.display = "block";
    el.style.top = `${rows[i].top}px`;
    el.style.height = `${rows[i].h}px`;
  };
  const onLeave = () => {
    if (hoverRef.current) hoverRef.current.style.display = "none";
  };
  const onClick = (ev: MouseEvent<HTMLDivElement>) => {
    const i = rowAt(ev);
    if (i >= 0) onCursor(i);
  };

  const name = (c: string) => {
    if (c.startsWith("?")) return `? ${c.slice(1)}`;
    const id = laneComponent(c);
    return (doc && docIndex(doc).componentsById.get(id)?.name) || id;
  };
  const kind = (c: string) => (doc ? docIndex(doc).componentsById.get(laneComponent(c))?.kind : undefined);

  // Only the lanes near the viewport get a head.
  const headFrom = Math.max(0, Math.floor((region.x - GUTTER) / LIFE_W) - 1);
  const headTo = Math.min(lanes.length - 1, Math.ceil((region.x + region.w - GUTTER) / LIFE_W));
  const strips: { area: string; from: number; to: number; collapsed: boolean; members: number }[] = [];
  if (view.grouped) {
    lanes.forEach((l, i) => {
      const a = l.area ?? "";
      const prev = strips[strips.length - 1];
      if (prev && prev.area === a) {
        prev.to = i;
        prev.members += l.members.length;
      } else strips.push({ area: a, from: i, to: i, collapsed: l.collapsed, members: l.members.length });
    });
  }

  const dimTop = curRow ? curRow.top + Math.max(curRow.h, 0) : 0;

  return (
    <div ref={scrollRef} onScroll={syncRegion} tabIndex={0} className="relative h-full overflow-auto" role="group" aria-label="Sequence diagram">
      <div style={{ width: width + insets.right, minWidth: "100%", paddingBottom: insets.bottom }}>
        {/* Lifeline heads */}
        <div className="sticky top-0 z-10 bg-panel" style={{ height: headH, width }}>
          <div className="absolute left-1 top-1 text-[10px] leading-tight text-faint" style={{ width: GUTTER - 6 }}>
            virtual time
          </div>
          {strips.filter((a) => a.to >= headFrom && a.from <= headTo).map((a) => (
            <button
              key={a.area}
              type="button"
              onClick={() => onToggleArea?.(a.area)}
              aria-expanded={!a.collapsed}
              title={a.collapsed ? `Show the ${a.members} lanes in ${a.area}` : `Fold ${a.area} into one lane`}
              className="absolute top-0 truncate border-b border-line px-1.5 text-left text-[10px] font-medium leading-[14px] text-muted hover:bg-panel-3 hover:text-ink"
              style={{ left: GUTTER + a.from * LIFE_W + 4, width: (a.to - a.from + 1) * LIFE_W - 8, height: AREA_STRIP_H }}
            >
              {a.collapsed ? "▸" : "▾"} {a.collapsed ? `${a.members} lane${a.members === 1 ? "" : "s"}` : a.area}
            </button>
          ))}
          <svg width={width} height={HEAD_H} aria-hidden className="absolute left-0" style={{ top: headH - HEAD_H }}>
            {lanes.map((lane, i) => {
              if (i < headFrom || i > headTo) return null;
              const c = lane.members[0];
              const x = laneX(i);
              const inst = lane.collapsed ? "" : laneInstance(c);
              const [l1, l2] = lane.collapsed ? splitName(lane.area ?? "") : inst ? [truncate(name(c), 16), truncate(`@${inst}`, 16)] : splitName(name(c));
              const active = activeLanes.has(i);
              const sub = lane.collapsed ? "area" : kind(c);
              return (
                <g key={lane.key}>
                  <title>{lane.collapsed ? `${lane.area}: ${lane.members.join(", ")}` : c}</title>
                  <rect x={x - LIFE_W / 2 + 6} y={6} width={LIFE_W - 12} height={HEAD_H - 12} rx={6} fill={active ? "#1c2a10" : "#17212b"} stroke={active ? C.accent : "#2a3742"} strokeWidth={active ? 1.5 : 1} />
                  <rect x={x - LIFE_W / 2 + 6} y={6} width={4} height={HEAD_H - 12} rx={2} fill={scale.color(colorKey(c))} />
                  <text x={x + 2} y={l2 ? 21 : 26} textAnchor="middle" fontSize={11} fill={C.ink} style={{ fontWeight: 600 }} {...fitHead(l1)}>
                    {l1}
                  </text>
                  {l2 && (
                    <text x={x + 2} y={33} textAnchor="middle" fontSize={11} fill={C.ink} style={{ fontWeight: 600 }} {...fitHead(l2)}>
                      {l2}
                    </text>
                  )}
                  {!l2 && sub && (
                    <text x={x + 2} y={38} textAnchor="middle" fontSize={9.5} fill={C.faint}>
                      {sub}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
        <div className="relative cursor-pointer select-none" style={{ width, height }} onClick={onClick} onMouseMove={onMove} onMouseLeave={onLeave}>
          <svg
            className="absolute block"
            style={{ left: region.x, top: region.y }}
            width={region.w}
            height={region.h}
            viewBox={`${region.x} ${region.y} ${region.w} ${region.h}`}
            aria-hidden
          >
            <Markers />
            {/* Cursor band */}
            {curRow && (
              <g>
                <rect x={region.x} y={curRow.top} width={region.w} height={Math.max(curRow.h, 2)} fill="rgba(204,255,120,0.07)" />
                <rect x={0} y={curRow.top} width={3} height={Math.max(curRow.h, 2)} fill={C.accent} />
              </g>
            )}
            {/* Active lanes */}
            {Array.from(activeLanes).map((i) => (
              <line key={`al-${i}`} x1={laneX(i)} y1={region.y} x2={laneX(i)} y2={region.y + region.h} stroke="rgba(204,255,120,0.22)" strokeWidth={2} />
            ))}
            <MemoStatic playback={playback} rows={rows} geo={geo} width={width} spanList={spanList} region={region} />
            {/* Future events are dimmed */}
            {curRow && dimTop < region.y + region.h && (
              <rect x={region.x} y={Math.max(dimTop, region.y)} width={region.w} height={region.y + region.h - Math.max(dimTop, region.y)} fill="#11181f" opacity={0.62} pointerEvents="none" />
            )}
          </svg>
          <div ref={hoverRef} className="pointer-events-none absolute inset-x-0 hidden bg-[rgba(118,204,255,0.05)]" />
        </div>
      </div>
    </div>
  );
}
