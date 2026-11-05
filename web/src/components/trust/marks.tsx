"use client";

// The trust marks. Every fidelity and claim display in the UI uses these, so a reader learns
// one vocabulary, carried by shape and word as well as color.
//
//   <FidelityMark fidelity="partial" />                 half circle and the word
//   <FidelityMark fidelity="absent" label={false} />    the shape alone; the word stays in title and aria-label
//   <FidelityStrip counts={countFidelity(items)} />     a proportional bar, with a legend if `legend`
//   <FidelityLegend />                                  the four marks in a row
//   <ClaimMark kind="assumed" />                        "assumed", "open-decision", "cited", "cited-exercised"
//
// None of these is green. Green is only for checks against something outside the model.

import type { MechanismFidelity } from "@/lib/api/types";
import { FIDELITY_MEANING, FIDELITY_ORDER, fidelitySentence, type FidelityCounts } from "./fidelity";
import { cx } from "@/components/ui";

export interface FidelityMarkProps {
  fidelity: MechanismFidelity;
  /** Show the word beside the shape (default true). With false, the word stays in the title and aria-label. */
  label?: boolean;
  /** Overrides the hover text, for a mechanism's own note. */
  title?: string;
  className?: string;
}

export interface FidelityStripProps {
  counts: FidelityCounts;
  /** Show each fidelity's count under the bar. */
  legend?: boolean;
  className?: string;
}

export interface FidelityLegendProps {
  className?: string;
}

export type ClaimKind = "assumed" | "open-decision" | "cited" | "cited-exercised";

export interface ClaimMarkProps {
  kind: ClaimKind;
  /** Overrides the hover text. */
  title?: string;
  className?: string;
}

const FIDELITY_COLOR: Record<MechanismFidelity, string> = {
  modeled: "text-link",
  partial: "text-warn",
  shell: "text-st-serious",
  absent: "text-muted",
};

/** The fidelity shape on its own: solid, half, hollow, dashed. It draws in currentColor. */
function FidelityShape({ fidelity }: { fidelity: MechanismFidelity }) {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden className="shrink-0">
      {fidelity === "modeled" && <circle cx="6" cy="6" r="5" fill="currentColor" />}
      {fidelity === "partial" && (
        <>
          <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M6 1.5 A4.5 4.5 0 0 0 6 10.5 Z" fill="currentColor" />
        </>
      )}
      {fidelity === "shell" && <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />}
      {fidelity === "absent" && <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 1.6" />}
    </svg>
  );
}

export function FidelityMark({ fidelity, label = true, title, className }: FidelityMarkProps) {
  const meaning = title ?? FIDELITY_MEANING[fidelity];
  return (
    <span
      title={meaning}
      role={label ? undefined : "img"}
      aria-label={label ? undefined : fidelity}
      className={cx("inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[11px] font-medium leading-none", FIDELITY_COLOR[fidelity], className)}
    >
      <FidelityShape fidelity={fidelity} />
      {label && fidelity}
    </span>
  );
}

const SEGMENT: Record<MechanismFidelity, string> = {
  modeled: "bg-link",
  partial: "border border-warn bg-[linear-gradient(135deg,var(--color-warn)_0_50%,transparent_50%_100%)] bg-[length:6px_6px]",
  shell: "border border-st-serious",
  absent: "border border-dashed border-muted",
};

/** A bar with a segment per fidelity, each drawn in its shape's style, sized by count. */
export function FidelityStrip({ counts, legend, className }: FidelityStripProps) {
  const sentence = fidelitySentence(counts);
  return (
    <div className={cx("min-w-0", className)}>
      <div role="img" aria-label={sentence} title={sentence} className="flex h-2.5 w-full gap-px">
        {counts.total === 0 ? (
          <span className="h-full flex-1 rounded-sm border border-dashed border-line" />
        ) : (
          FIDELITY_ORDER.filter((f) => counts[f] > 0).map((f) => (
            <span key={f} className={cx("h-full min-w-[3px] rounded-sm", SEGMENT[f])} style={{ flexGrow: counts[f], flexBasis: 0 }} />
          ))
        )}
      </div>
      {legend && (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {FIDELITY_ORDER.map((f) => (
            <span key={f} className="inline-flex items-center gap-1">
              <FidelityMark fidelity={f} />
              <span className="tnum text-[11px] text-muted">{counts[f]}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function FidelityLegend({ className }: FidelityLegendProps) {
  return (
    <div className={cx("flex flex-wrap items-center gap-x-3 gap-y-1", className)}>
      {FIDELITY_ORDER.map((f) => (
        <FidelityMark key={f} fidelity={f} />
      ))}
    </div>
  );
}

const CLAIM: Record<ClaimKind, { word: string; glyph: string; meaning: string; className: string }> = {
  assumed: {
    word: "assumed",
    glyph: "~",
    meaning: "A number or choice with no basis in the code",
    className: "border-dashed border-[#5a4520] text-warn",
  },
  "open-decision": {
    word: "open decision",
    glyph: "?",
    meaning: "Open decision: the model doesn't compute this, so you pick",
    className: "border-[#3d3766] text-violet",
  },
  cited: {
    word: "cited",
    glyph: "§",
    meaning: "Someone pointed at these lines, and nothing runs them. A citation is a source, not proof",
    className: "border-line text-muted",
  },
  "cited-exercised": {
    word: "cited, exercised",
    glyph: "§",
    meaning: "Has a citation, and a scenario runs it. A citation is a source, not proof",
    className: "border-[#24445a] bg-[#122230] text-link",
  },
};

export function ClaimMark({ kind, title, className }: ClaimMarkProps) {
  const c = CLAIM[kind];
  return (
    <span
      title={title ?? c.meaning}
      className={cx("inline-flex h-[18px] shrink-0 items-center gap-1 whitespace-nowrap rounded border px-1 text-[10.5px] font-medium leading-none", c.className, className)}
    >
      <span aria-hidden className="font-mono">
        {c.glyph}
      </span>
      {c.word}
    </span>
  );
}
