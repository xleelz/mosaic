"use client";

import { memo, useEffect, useMemo, useRef, type ReactNode } from "react";
import type { Document, SimEvent } from "@/lib/api/types";
import { formatDuration, ifaceName, jsonChip, jsonInline } from "@/lib/model/format";
import type { ColorScale } from "@/lib/model/colors";
import { docIndex } from "@/lib/model/docindex";
import { laneComponent, laneInstance, setLabel, type EventLanes, type Playback } from "@/lib/sim/playback";

// Geometry
const LIFE_W = 118;
const GUTTER = 62;
const HEAD_H = 50;
const RIGHT_PAD = 260;
const ACT_W = 10;

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

function StaticLayer({ playback, rows, lifeX, width }: { playback: Playback; rows: Row[]; lifeX: (c: string) => number; width: number }) {
  const { events, spans } = playback;
  const height = rows.length ? rows[rows.length - 1].top + rows[rows.length - 1].h + 24 : 40;
  const els: ReactNode[] = [];

  // Lifelines
  playback.lifelines.forEach((c) => {
    els.push(<line key={`l-${c}`} x1={lifeX(c)} y1={0} x2={lifeX(c)} y2={height} stroke={C.life} strokeWidth={1} strokeDasharray="3 4" />);
  });

  // Activation bars
  spans.forEach((s) => {
    const r0 = rows[s.startIdx];
    const r1 = s.endIdx >= 0 ? rows[s.endIdx] : rows[rows.length - 1];
    if (!r0 || !r1) return;
    const x = lifeX(s.to) - ACT_W / 2 + s.depth * 4;
    els.push(
      <rect
        key={`a-${s.span}`}
        x={x}
        y={r0.y}
        width={ACT_W}
        height={Math.max(4, r1.y - r0.y)}
        rx={2}
        fill={s.async ? "#12302c" : "#1c2a36"}
        stroke={s.ok === false ? "#7a3434" : s.async ? "#2f6e64" : "#3b4d5c"}
        strokeWidth={1}
      />,
    );
  });

  // Multi-step scenario separators (§11.7): a band per step.
  playback.steps.forEach((m, k) => {
    const r0 = rows[m.startIdx];
    const r1 = m.endIdx >= 0 ? rows[m.endIdx] : rows[rows.length - 1];
    if (!r0 || !r1) return;
    els.push(
      <rect key={`st-${k}`} x={0} y={r0.top} width={width} height={Math.max(4, r1.top + r1.h - r0.top)} fill={k % 2 ? "rgba(204,255,120,0.025)" : "transparent"} />,
    );
  });

  // Parallel groups (§11.2): a bracket on the behavior's lane, and a bar per branch spanning its rows.
  playback.parallels.forEach((g, k) => {
    const r0 = rows[g.startIdx];
    const r1 = g.endIdx >= 0 ? rows[g.endIdx] : rows[rows.length - 1];
    if (!r0 || !r1) return;
    const x = lifeX(g.lane) - 18 - g.depth * 6;
    els.push(<path key={`pg-${k}`} d={`M ${x + 6} ${r0.y} h -6 V ${r1.y} h 6`} fill="none" stroke={C.parallel} strokeWidth={1.4} opacity={0.9} />);
    const bx = lifeX(g.lane) + ACT_W + 4;
    const keys = Array.from(g.branches.keys()).sort((a, b) => a - b);
    keys.forEach((b, n) => {
      const br = g.branches.get(b)!;
      const a = rows[br.first];
      const z = rows[br.last];
      if (!a || !z) return;
      const late = playback.events[br.last]?.late || (g.endIdx >= 0 && br.last > g.endIdx);
      els.push(
        <g key={`pb-${k}-${b}`} opacity={late ? 0.45 : 0.9}>
          <title>{`branch ${b}`}</title>
          <rect x={bx + n * BRANCH_DX} y={a.top + 2} width={3} height={Math.max(4, z.top + z.h - a.top - 4)} rx={1.5} fill={C.parallel} />
        </g>,
      );
    });
  });

  // Time gutter + events
  let lastT = -1;
  events.forEach((e, i) => {
    const r = rows[i];
    if (e.t !== lastT) {
      els.push(
        <text key={`t-${i}`} x={GUTTER - 10} y={r.y + 3.5} textAnchor="end" fontSize={10} fill={C.faint} className="tnum">
          {e.t} ms
        </text>,
      );
      lastT = e.t;
    }
    const mark = <EventMark key={`e-${i}`} i={i} e={e} r={r} rows={rows} lifeX={lifeX} playback={playback} width={width} />;
    // Late work (after a timeout or a join) is dimmed.
    els.push(e.late && e.type !== "call.end" ? <g key={`e-${i}`} opacity={0.5}>{mark}</g> : mark);
  });

  return (
    <g>
      <rect x={0} y={0} width={width} height={height} fill="transparent" />
      {els}
    </g>
  );
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
  lifeX,
  playback,
  width,
}: {
  i: number;
  e: SimEvent;
  r: Row;
  rows: Row[];
  lifeX: (c: string) => number;
  playback: Playback;
  width: number;
}) {
  const y = r.y;
  const span = e.span ? playback.spans.get(e.span) : undefined;
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
      const depth = span?.depth ?? 0;
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
        </>
      );
      if (from === to) {
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
      const depth = span?.depth ?? 0;
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
      if (from === to) {
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

export function SequenceDiagram({ playback, doc, scale, colorKey, cursor, onCursor, insets = NO_INSETS }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const { events, lifelines } = playback;

  const rows = useMemo(() => {
    const out: Row[] = [];
    let top = 8;
    for (const e of events) {
      const h = ROW_H[e.type] ?? 22;
      out.push({ top, h, y: top + h - (e.type === "call.start" || e.type === "call.end" || e.type === "emit" || e.type === "step.start" ? 8 : h / 2) });
      top += h;
    }
    return out;
  }, [events]);

  const index = useMemo(() => new Map(lifelines.map((c, i) => [c, i])), [lifelines]);
  const lifeX = useMemo(() => (c: string) => GUTTER + (index.get(c) ?? 0) * LIFE_W + LIFE_W / 2, [index]);
  const width = GUTTER + lifelines.length * LIFE_W + RIGHT_PAD;
  const height = rows.length ? rows[rows.length - 1].top + rows[rows.length - 1].h + 24 : 60;

  const curRow = rows[cursor];
  const activeLife = new Set<string>();
  const curLane = playback.lanes[cursor];
  if (curLane) {
    for (const l of [curLane.from, curLane.to, curLane.at]) if (l) activeLife.add(l);
  }

  // Keep the cursor row (and its lifelines) in view.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !curRow) return;
    // Rows sit below the sticky lifeline heads.
    // Floating panels cover the right and bottom edges; aim for what's left.
    const viewH = Math.max(HEAD_H + curRow.h, el.clientHeight - insets.bottom);
    const viewW = Math.max(LIFE_W, el.clientWidth - insets.right);
    const top = HEAD_H + curRow.top;
    const bottom = top + curRow.h;
    if (top < el.scrollTop + HEAD_H + 6 || bottom > el.scrollTop + viewH - 6) {
      el.scrollTop = Math.max(0, top - HEAD_H - (viewH - HEAD_H) * 0.4);
    }
    // Keep the active lifelines and their labels in view, moving as little as possible.
    const xs = Array.from(activeLife).map((c) => lifeX(c));
    if (xs.length) {
      const lo = Math.max(0, Math.min(...xs) - 70);
      const hi = Math.max(...xs) + 300;
      const minLeft = hi - viewW;
      if (minLeft > lo) el.scrollLeft = lo;
      else el.scrollLeft = Math.min(Math.max(el.scrollLeft, minLeft), lo);
    }
    // activeLife derives from cursor; recomputing on cursor is intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor, curRow, lifeX, insets.right, insets.bottom]);

  const name = (c: string) => {
    if (c.startsWith("?")) return `? ${c.slice(1)}`;
    const id = laneComponent(c);
    return (doc && docIndex(doc).componentsById.get(id)?.name) || id;
  };
  const kind = (c: string) => (doc ? docIndex(doc).componentsById.get(laneComponent(c))?.kind : undefined);

  return (
    <div ref={scrollRef} className="relative h-full overflow-auto" role="group" aria-label="Sequence diagram">
      <div style={{ width: width + insets.right, minWidth: "100%", paddingBottom: insets.bottom }}>
        {/* Lifeline heads */}
        <div className="sticky top-0 z-10 bg-panel/95 backdrop-blur" style={{ height: HEAD_H, width }}>
          <svg width={width} height={HEAD_H} aria-hidden>
            {lifelines.map((c) => {
              const x = lifeX(c);
              const inst = laneInstance(c);
              const [l1, l2] = inst ? [truncate(name(c), 16), truncate(`@${inst}`, 16)] : splitName(name(c));
              const active = activeLife.has(c);
              return (
                <g key={c}>
                  <title>{c}</title>
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
                  {!l2 && kind(c) && (
                    <text x={x + 2} y={38} textAnchor="middle" fontSize={9.5} fill={C.faint}>
                      {kind(c)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
        <svg width={width} height={height} className="block select-none" aria-hidden>
          <Markers />
          {/* Cursor band */}
          {curRow && (
            <g>
              <rect x={0} y={curRow.top} width={width} height={curRow.h} fill="rgba(204,255,120,0.07)" />
              <rect x={0} y={curRow.top} width={3} height={curRow.h} fill={C.accent} />
            </g>
          )}
          {/* Active lifelines */}
          {Array.from(activeLife).map((c) => (
            <line key={`al-${c}`} x1={lifeX(c)} y1={0} x2={lifeX(c)} y2={height} stroke="rgba(204,255,120,0.22)" strokeWidth={2} />
          ))}
          <MemoStatic playback={playback} rows={rows} lifeX={lifeX} width={width} />
          {/* Future events are dimmed */}
          {curRow && <rect x={0} y={curRow.top + curRow.h} width={width} height={Math.max(0, height - curRow.top - curRow.h)} fill="#11181f" opacity={0.62} pointerEvents="none" />}
          {/* Hit targets */}
          {rows.map((r, i) => (
            <rect key={`h-${i}`} x={0} y={r.top} width={width} height={r.h} fill="transparent" className="cursor-pointer hover:fill-[rgba(118,204,255,0.05)]" onClick={() => onCursor(i)} />
          ))}
        </svg>
      </div>
    </div>
  );
}
