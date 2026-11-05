"use client";

import { useMemo, useState } from "react";
import type { JsonValue, SimEvent } from "@/lib/api/types";
import { jsonInline, formatMs } from "@/lib/model/format";
import { beatIndexAt, spansInBeat, type Beat, type BeatKind, type WeakFidelity } from "@/lib/sim/beats";
import type { StateChange } from "@/lib/sim/compare";
import { FidelityMark } from "@/components/trust/marks";
import { cx } from "@/components/ui";
import { VirtualRows } from "./VirtualRows";

const BEAT_H = 42;
const SPAN_H = 24;
/** How many changed fields the closing line names before its disclosure. */
const STATE_SHOWN = 3;

const BEAT_LOOK: Record<BeatKind, { icon: string; color: string; word: string }> = {
  step: { icon: "▤", color: "text-accent", word: "step" },
  crossing: { icon: "→", color: "text-link", word: "enters" },
  back: { icon: "↩", color: "text-muted", word: "back" },
  choice: { icon: "◆", color: "text-warn", word: "choice" },
  fault: { icon: "⚡", color: "text-[#f5b294]", word: "fault" },
  error: { icon: "✗", color: "text-bad", word: "error" },
  retry: { icon: "↻", color: "text-violet", word: "retry" },
  timeout: { icon: "⏱", color: "text-warn", word: "timeout" },
  warning: { icon: "⚠", color: "text-warn", word: "warning" },
  note: { icon: "✎", color: "text-muted", word: "note" },
  loop: { icon: "⟳", color: "text-muted", word: "repeats" },
};

/** "41 calls folded · 20 set and note", what a beat holds beyond its own line. */
function foldedText(b: Beat): string {
  const parts: string[] = [];
  if (b.calls > 0) parts.push(`${b.calls} ${b.calls === 1 ? "call" : "calls"}${b.area ? ` in ${b.area}` : ""}`);
  if (b.collapsed > 0) parts.push(`${b.collapsed} set and note`);
  if (b.count > 1 && b.kind !== "loop") parts.push(`×${b.count}`);
  return parts.join(" · ");
}

function BeatRow({
  beat,
  events,
  active,
  open,
  weak,
  onClick,
}: {
  beat: Beat;
  events: readonly SimEvent[];
  active: boolean;
  open: boolean;
  weak?: WeakFidelity;
  onClick: () => void;
}) {
  const look = BEAT_LOOK[beat.kind];
  const folded = foldedText(beat);
  const sub = [beat.fromArea && beat.area ? `${beat.fromArea} → ${beat.area}` : beat.area, beat.detail && beat.detail !== beat.title ? beat.detail : "", folded].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className={cx("flex h-full w-full items-start gap-2 border-b border-l-2 border-b-line-soft px-2 py-1 text-left hover:bg-panel-2", active ? "border-l-accent bg-[#141d0c]" : "border-l-transparent")}
    >
      <span aria-hidden className={cx("w-4 shrink-0 text-center text-[12px] leading-[18px]", look.color)}>
        {look.icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className={cx("truncate text-[12.5px] font-medium", beat.kind === "fault" || beat.kind === "error" ? look.color : "text-ink")}>{beat.title}</span>
          {weak && <FidelityMark fidelity={weak} />}
        </span>
        <span className="block truncate text-[11px] text-faint" title={sub}>
          {sub || look.word}
        </span>
      </span>
      <span className="tnum shrink-0 text-[10.5px] leading-[18px] text-faint">{formatMs(events[beat.at]?.t ?? 0)}</span>
    </button>
  );
}

function shortValue(v: JsonValue | undefined): string {
  return v === undefined ? "∅" : jsonInline(v, 40);
}

/** The run's closing line: the state it left different from where it started. */
function StateLeft({ changes }: { changes: StateChange[] }) {
  const [open, setOpen] = useState(false);
  if (changes.length === 0) return <div className="border-t border-line-soft px-3 py-1.5 text-[11.5px] text-faint">State left unchanged.</div>;
  const head = changes.slice(0, STATE_SHOWN).map((c) => `${c.path} = ${shortValue(c.after)}`).join(", ");
  return (
    <div className="border-t border-line-soft px-3 py-1.5 text-[11.5px]">
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 text-faint">State left changed:</span>
        <span className="min-w-0 flex-1 truncate font-mono text-muted" title={head}>
          {head}
        </span>
        {changes.length > STATE_SHOWN && (
          <button type="button" className="shrink-0 text-link hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? "Less" : `and ${changes.length - STATE_SHOWN} more`}
          </button>
        )}
      </div>
      {open && (
        <VirtualRows
          label="State the run changed"
          className="mt-1 max-h-[160px] min-h-[120px]"
          count={changes.length}
          rowHeight={18}
          render={(i) => (
            <div className="truncate font-mono text-[11px] text-muted">
              {changes[i].path} <span className="text-faint">{shortValue(changes[i].before)} →</span> {shortValue(changes[i].after)}
            </div>
          )}
        />
      )}
    </div>
  );
}

/**
 * The run as a story: one line per beat. Clicking a beat moves the cursor there, which centers
 * the sequence diagram if it's showing, and opens the spans the beat folds.
 */
export function SummaryTrace({
  events,
  beats,
  cursor,
  onBeat,
  onSpan,
  weakBeats,
  weakIfaces,
  stateLeft,
  focusKey,
  insetRight = 0,
  insetBottom = 0,
  initialOpen,
}: {
  events: readonly SimEvent[];
  beats: readonly Beat[];
  cursor: number;
  onBeat: (beat: Beat) => void;
  onSpan: (idx: number) => void;
  weakBeats: ReadonlyMap<number, WeakFidelity>;
  weakIfaces: ReadonlyMap<string, WeakFidelity>;
  stateLeft: StateChange[];
  focusKey?: unknown;
  insetRight?: number;
  insetBottom?: number;
  /** The beat to open at first: a failed run opens on its fault. */
  initialOpen?: number;
}) {
  const [open, setOpen] = useState<number | null>(initialOpen ?? null);
  const current = beatIndexAt(beats, cursor);
  const openBeat = open !== null ? beats[open] : undefined;
  const spans = useMemo(() => (openBeat ? spansInBeat(events, openBeat) : []), [events, openBeat]);

  if (beats.length === 0) return <div className="p-4 text-[12px] text-faint">Nothing to summarize: this run made no calls.</div>;

  return (
    <div className="flex h-full min-h-0 flex-col" style={{ paddingRight: insetRight, paddingBottom: insetBottom }}>
      <VirtualRows
        label="Summary of the run"
        className="min-h-[120px] flex-1"
        count={beats.length}
        rowHeight={BEAT_H}
        focus={current}
        focusKey={focusKey}
        render={(i) => (
          <BeatRow
            beat={beats[i]}
            events={events}
            active={i === current}
            open={open === i}
            weak={weakBeats.get(beats[i].id)}
            onClick={() => {
              setOpen((o) => (o === i ? null : i));
              onBeat(beats[i]);
            }}
          />
        )}
      />
      {openBeat && (
        <div className="flex max-h-[42%] min-h-[110px] flex-col border-t border-line">
          <div className="flex items-baseline gap-2 px-3 py-1 text-[11px] text-faint">
            <span className="truncate font-medium text-muted">{openBeat.title}</span>
            <span className="tnum shrink-0">
              {spans.length} {spans.length === 1 ? "span" : "spans"}
            </span>
            <button type="button" className="ml-auto shrink-0 text-link hover:underline" onClick={() => setOpen(null)}>
              Close
            </button>
          </div>
          {spans.length === 0 ? (
            <div className="px-3 pb-2 text-[11.5px] text-faint">No calls start inside this beat.</div>
          ) : (
            <VirtualRows
              label="Spans in this beat"
              className="min-h-0 flex-1"
              count={spans.length}
              rowHeight={SPAN_H}
              render={(i) => {
                const s = spans[i];
                const weak = weakIfaces.get(s.iface);
                return (
                  <button type="button" onClick={() => onSpan(s.idx)} className={cx("flex h-full w-full items-center gap-1.5 pr-2 text-left text-[11.5px] hover:bg-panel-2", s.idx === cursor && "bg-[#141d0c]")} style={{ paddingLeft: 12 + Math.min(s.indent, 12) * 12 }}>
                    <span className={cx("min-w-0 truncate font-mono", s.ok === false ? "text-bad" : "text-ink")}>
                      {s.ok === false ? "✗ " : ""}
                      {s.attempt > 1 ? `↻${s.attempt} ` : ""}
                      {s.iface}
                    </span>
                    {weak && <FidelityMark fidelity={weak} label={false} />}
                  </button>
                );
              }}
            />
          )}
        </div>
      )}
      <StateLeft changes={stateLeft} />
    </div>
  );
}
