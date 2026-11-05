"use client";

import { useMemo } from "react";
import type { SimulationRun } from "@/lib/api/types";
import { formatDuration, jsonInline } from "@/lib/model/format";
import { areaResolver, beatIndexAt, deriveBeats, type Beat } from "@/lib/sim/beats";
import { alignBeats, firstDivergence, stateDifferences } from "@/lib/sim/compare";
import { runVerdict } from "@/lib/sim/wording";
import { VirtualRows } from "@/components/playback/VirtualRows";
import { cx } from "@/components/ui";

const ROW_H = 26;
/** How many differing fields to list. */
const STATE_SHOWN = 200;

export interface CompareSide {
  run: SimulationRun;
  /** The column's name: a scenario, a draft, a candidate. */
  label: string;
  /** component -> area, at this run's revision. */
  area?: ReadonlyMap<string, string>;
}

const NO_AREAS: ReadonlyMap<string, string> = new Map();

function beatsOf(side: CompareSide): Beat[] {
  return deriveBeats(side.run.trace ?? [], { areaOf: areaResolver(side.area ?? NO_AREAS) });
}

function BeatCell({ beat, changed }: { beat?: Beat; changed: boolean }) {
  if (!beat) return <div className="h-full border-b border-line-soft bg-panel-2/30 px-2" aria-hidden />;
  const hot = beat.kind === "fault" || beat.kind === "error";
  return (
    <div className={cx("flex h-full items-center gap-2 border-b border-line-soft px-2 text-[12px]", changed && "bg-[#1d1a10]")} title={beat.detail ?? beat.title}>
      <span className="tnum w-6 shrink-0 text-right text-[10.5px] text-faint">{beat.id + 1}</span>
      <span className={cx("min-w-0 truncate", hot ? "text-bad" : "text-ink")}>
        {beat.title}
        {beat.count > 1 && beat.kind !== "loop" ? ` ×${beat.count}` : ""}
      </span>
      {beat.area && <span className="ml-auto shrink-0 truncate text-[10.5px] text-faint">{beat.area}</span>}
    </div>
  );
}

function SideHead({ side }: { side: CompareSide }) {
  const s = side.run.summary;
  const verdict = runVerdict(s);
  return (
    <div className="min-w-0 px-2 py-1.5">
      <div className="truncate text-[13px] font-semibold text-ink" title={side.label}>
        {side.label}
      </div>
      <div className={cx("truncate text-[12px]", verdict.tone === "bad" ? "text-bad" : verdict.tone === "warn" ? "text-warn" : "text-muted")}>{verdict.text}</div>
      <div className="truncate text-[11px] text-faint">
        {formatDuration(s.duration_ms, s.duration_us)} virtual · {s.events} events · {side.run.revision === "draft" ? "draft" : `r${side.run.revision}`} · seed {s.seed}
      </div>
      <div className="truncate font-mono text-[11px] text-muted" title={s.result.ok ? jsonInline(s.result.value ?? null, 200) : s.result.error?.message}>
        {s.result.ok ? `Result ${jsonInline(s.result.value ?? null, 60)}` : `Result ${s.result.error?.status ?? ""} ${s.result.error?.code ?? "error"}`}
      </div>
    </div>
  );
}

/**
 * Two runs, side by side: both summaries and the first point they differ. It takes any two runs
 * with their traces: of one model, or of a model and a candidate, at any revisions.
 */
export function RunCompare({ left, right }: { left: CompareSide; right: CompareSide }) {
  const a = useMemo(() => beatsOf(left), [left]);
  const b = useMemo(() => beatsOf(right), [right]);
  const divergence = useMemo(() => firstDivergence(left.run.trace ?? [], right.run.trace ?? []), [left.run, right.run]);
  const rows = useMemo(() => alignBeats(a, b, divergence), [a, b, divergence]);
  const firstDiff = rows.findIndex((r) => r.diverges);
  const stateDiff = useMemo(() => stateDifferences(left.run.summary.state, right.run.summary.state), [left.run, right.run]);

  let line: string;
  if (!divergence) line = "Same path: these runs make the same calls with the same outcomes.";
  else if (divergence.a < 0) line = `First divergence: ${left.label} ends, and ${right.label} goes on at event ${(right.run.trace ?? [])[divergence.b]?.seq}.`;
  else if (divergence.b < 0) line = `First divergence: ${right.label} ends, and ${left.label} goes on at event ${(left.run.trace ?? [])[divergence.a]?.seq}.`;
  else {
    const ba = beatIndexAt(a, divergence.a) + 1;
    const bb = beatIndexAt(b, divergence.b) + 1;
    line = ba === bb ? `First divergence: beat ${ba}.` : `First divergence: beat ${ba} on the left, beat ${bb} on the right.`;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="grid grid-cols-2 divide-x divide-line-soft border-b border-line">
        <SideHead side={left} />
        <SideHead side={right} />
      </div>
      <div className="border-b border-line-soft bg-panel-2/60 px-3 py-1 text-[12px] text-ink">{line}</div>
      <VirtualRows
        label="Both runs' summaries"
        className="min-h-[120px] flex-1"
        count={rows.length}
        rowHeight={ROW_H}
        focus={firstDiff >= 0 ? firstDiff : undefined}
        focusKey={firstDiff}
        render={(i) => {
          const r = rows[i];
          return (
            <div className={cx("grid h-full grid-cols-2 divide-x divide-line-soft", r.diverges && "shadow-[inset_0_2px_0_0_var(--color-warn)]")}>
              <BeatCell beat={r.a} changed={!r.same} />
              <BeatCell beat={r.b} changed={!r.same} />
            </div>
          );
        }}
      />
      <details className="border-t border-line text-[12px]" open={stateDiff.length > 0 && stateDiff.length <= 8}>
        <summary className="cursor-pointer select-none px-3 py-1 text-faint hover:text-ink">
          {stateDiff.length === 0 ? "Both runs end in the same state." : `State differs in ${stateDiff.length} ${stateDiff.length === 1 ? "field" : "fields"} at the end`}
        </summary>
        {stateDiff.length > 0 && (
          <ul className="max-h-[150px] overflow-y-auto px-3 pb-2 font-mono text-[11px]">
            {stateDiff.slice(0, STATE_SHOWN).map((d) => (
              <li key={d.path} className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2">
                <span className="truncate text-muted" title={d.path}>
                  {d.path}
                </span>
                <span className="truncate text-ink">{d.before === undefined ? "∅" : jsonInline(d.before, 50)}</span>
                <span className="truncate text-ink">{d.after === undefined ? "∅" : jsonInline(d.after, 50)}</span>
              </li>
            ))}
            {stateDiff.length > STATE_SHOWN && <li className="text-faint">and {stateDiff.length - STATE_SHOWN} more</li>}
          </ul>
        )}
      </details>
    </div>
  );
}
