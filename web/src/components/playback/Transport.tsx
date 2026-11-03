"use client";

import { useMemo } from "react";
import { formatMs } from "@/lib/model/format";
import { eventLabel, eventTone, type Playback } from "@/lib/sim/playback";
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

export function Transport({
  playback,
  cursor,
  setCursor,
  playing,
  setPlaying,
  speed,
  setSpeed,
}: {
  playback: Playback;
  cursor: number;
  setCursor: (i: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  speed: number;
  setSpeed: (s: number) => void;
}) {
  const n = playback.events.length;
  const e = playback.events[cursor];
  const ticks = useMemo(
    () =>
      playback.events
        .map((ev, i) => ({ i, tone: eventTone(ev) }))
        .filter((t) => TICK[t.tone]),
    [playback],
  );
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
        <svg className="pointer-events-none absolute inset-x-[7px] top-1/2 h-4 -translate-y-1/2" width="100%" height="16" aria-hidden preserveAspectRatio="none">
          <rect x="0" y="7" width="100%" height="2" fill="#2a3742" rx="1" />
          <rect x="0" y="7" width={`${pct(cursor)}%`} height="2" fill="#6f8f3c" rx="1" />
          {ticks.map((t) => {
            const major = t.tone !== "call" && t.tone !== "async" && t.tone !== "choice";
            return (
              <rect key={t.i} x={`${pct(t.i)}%`} y={major ? 1 : 4} width="2" height={major ? 14 : 8} fill={TICK[t.tone]} transform="translate(-1 0)" opacity={t.i > cursor ? 0.55 : 1} />
            );
          })}
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
        <span className="text-muted">t = {formatMs(e?.t ?? 0)}</span>
      </div>
      <div className="hidden items-center gap-1 text-[10.5px] text-faint 2xl:flex" aria-hidden>
        <Kbd>Space</Kbd> play <Kbd>←</Kbd>
        <Kbd>→</Kbd> step <Kbd>Home</Kbd>
        <Kbd>End</Kbd>
      </div>
    </div>
  );
}
