"use client";

import { useMemo, type ReactNode } from "react";
import type { Jumps } from "@/lib/sim/beats";
import { formatMs } from "@/lib/model/format";
import { eventLabel, eventTone, type EventTone, type Playback } from "@/lib/sim/playback";
import { binTicks } from "@/lib/sim/window";
import { Button, Kbd, Select } from "@/components/ui";

export const SPEEDS = [0.5, 1, 2, 4, 8];

const TICK: Partial<Record<string, string>> = {
  error: "#d03b3b",
  fault: "#ec835a",
  retry: "#9085e9",
  timeout: "#fab219",
  late: "#fab219",
  warning: "#fab219",
  choice: "#8a7a4a",
  call: "#4f6070",
  async: "#3f8076",
  queue: "#c9a24a",
  parallel: "#5a8fb8",
  step: "#ccff78",
};

/** Scrubber ticks: one per bin, so a long trace costs what a short one does. */
const TICK_BINS = 600;
/** When two events share a bin, the one that matters most shows. */
const TICK_RANK: EventTone[] = ["error", "fault", "timeout", "retry", "step", "warning", "late", "queue", "parallel", "choice", "async", "call"];
const tickRank = (t: EventTone) => {
  const r = TICK_RANK.indexOf(t);
  return r < 0 ? TICK_RANK.length : r;
};

export function Transport({
  playback,
  cursor,
  setCursor,
  playing,
  setPlaying,
  speed,
  setSpeed,
  jumps,
  extraHints,
}: {
  playback: Playback;
  cursor: number;
  setCursor: (i: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  speed: number;
  setSpeed: (s: number) => void;
  jumps?: Jumps;
  extraHints?: ReactNode;
}) {
  const n = playback.events.length;
  const e = playback.events[cursor];
  // One path per tone over the whole scrubber: a handful of elements, whatever the trace's length.
  const ticks = useMemo(() => {
    const tones = playback.events.map((ev) => {
      const t = eventTone(ev);
      return TICK[t] ? t : null;
    });
    const paths = new Map<EventTone, string>();
    for (const { bin, tone } of binTicks(tones, TICK_BINS, tickRank)) {
      const major = tone !== "call" && tone !== "async" && tone !== "choice";
      const x = (bin / (TICK_BINS - 1)) * 1000;
      paths.set(tone, `${paths.get(tone) ?? ""}M${x.toFixed(1)} ${major ? 1 : 4}V${major ? 15 : 12}`);
    }
    return Array.from(paths, ([tone, d]) => ({ tone, d }));
  }, [playback]);
  const atEnd = cursor >= n - 1;
  const pct = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * 100);

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-line bg-panel px-2.5 py-2">
      <div className="flex items-center gap-1" role="toolbar" aria-label="Playback controls">
        <Button size="sm" variant="ghost" onClick={() => { setPlaying(false); setCursor(0); }} title="Reset to the first event (Home)" aria-label="Reset">
          ⏮
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { setPlaying(false); setCursor(Math.max(0, cursor - 1)); }} disabled={cursor <= 0} title="Step back (←)" aria-label="Step back">
          ◀
        </Button>
        <Button
          size="sm"
          variant="primary"
          className="w-[76px]"
          onClick={() => {
            if (!playing && atEnd) setCursor(0);
            setPlaying(!playing);
          }}
          title="Play or pause (Space)"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? "❚❚ Pause" : atEnd ? "↺ Replay" : "▶ Play"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { setPlaying(false); setCursor(Math.min(n - 1, cursor + 1)); }} disabled={atEnd} title="Step forward (→)" aria-label="Step forward">
          ▶
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { setPlaying(false); setCursor(n - 1); }} disabled={atEnd} title="Jump to the end (End)" aria-label="Jump to end">
          ⏭
        </Button>
        <label className="ml-1 flex items-center gap-1 text-[11px] text-faint">
          speed
          <Select value={String(speed)} onChange={(ev) => setSpeed(Number(ev.target.value))} className="h-7 px-1 text-[12px]" aria-label="Playback speed">
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </Select>
        </label>
      </div>

      <div className="relative min-w-[220px] flex-1">
        <svg className="pointer-events-none absolute inset-x-[7px] top-1/2 h-4 -translate-y-1/2" width="100%" height="16" aria-hidden preserveAspectRatio="none" viewBox="0 0 1000 16">
          <rect x="0" y="7" width="1000" height="2" fill="#2a3742" />
          <rect x="0" y="7" width={pct(cursor) * 10} height="2" fill="#6f8f3c" />
          {ticks.map((t) => (
            <path key={t.tone} d={t.d} stroke={TICK[t.tone]} strokeWidth="2" vectorEffect="non-scaling-stroke" fill="none" />
          ))}
          {/* What's ahead of the cursor is dimmed. */}
          <rect x={pct(cursor) * 10} y="0" width={Math.max(0, 1000 - pct(cursor) * 10)} height="16" fill="#11181f" opacity="0.45" />
        </svg>
        <input
          type="range"
          min={0}
          max={Math.max(0, n - 1)}
          value={cursor}
          onChange={(ev) => {
            setPlaying(false);
            setCursor(Number(ev.target.value));
          }}
          className="scrubber relative w-full"
          aria-label="Trace position"
          aria-valuetext={e ? `Event ${e.seq} of ${n}: ${eventLabel(e)}` : undefined}
        />
      </div>

      <div className="tnum flex min-w-[150px] items-baseline justify-end gap-2 text-[12px]">
        <span className="text-ink">
          <span className="font-semibold">{e ? e.seq : 0}</span>
          <span className="text-faint"> / {n}</span>
        </span>
        <span className="text-muted">t = {formatMs(e?.t ?? 0)} virtual</span>
      </div>
      <div className="flex w-full flex-wrap items-center gap-x-1 gap-y-0.5 text-[10.5px] text-faint" aria-label="Keyboard shortcuts">
        <Kbd>Space</Kbd> play <Kbd>←</Kbd>
        <Kbd>→</Kbd> step <Kbd>Home</Kbd>
        <Kbd>End</Kbd>
        {jumps?.firstFault !== undefined && jumps.firstFault >= 0 && (
          <>
            <Kbd>f</Kbd> first fault
          </>
        )}
        {jumps?.firstError !== undefined && jumps.firstError >= 0 && (
          <>
            <Kbd>e</Kbd> first error
          </>
        )}
        {jumps && jumps.stateChanges.length > 0 && (
          <>
            <Kbd>n</Kbd> next state change
          </>
        )}
        {extraHints}
      </div>
    </div>
  );
}
