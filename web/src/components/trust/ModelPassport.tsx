"use client";

// The model passport: how far to trust a model, on every page. <ModelPassport> is the chip with
// its expanding panel, <PassportBody> the panel's contents for embedding (Overview).

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import type { Revision, RevisionList, RevSelector, StoredTestReport } from "@/lib/api/types";
import { useEvidence } from "@/lib/evidence";
import { useQuery } from "@/lib/hooks";
import { formatDate } from "@/lib/model/format";
import { cx } from "@/components/ui";
import { FidelityStrip } from "./marks";
import { DONT_USE_IT_TO, NOT_BENCHMARKED, SELF_CHECK_CAPTION, USE_IT_TO, passportFacts, selfCheckWords, viewedRevision, type PassportFacts } from "./passport";

export interface ModelPassportProps {
  /** The model's id. */
  id: string;
  /** The revision selector being viewed; default latest. */
  rev?: RevSelector;
  /** Where "Open Evidence" goes; default that model's Evidence tab. */
  evidenceHref?: string;
  className?: string;
}

const PANEL_WIDTH = 480;

function evidenceLink(id: string, rev: RevSelector | undefined): string {
  return `/o/${encodeURIComponent(id)}/evidence${rev && rev !== "latest" ? `?rev=${encodeURIComponent(rev)}` : ""}`;
}

/** The chip's words, once they're known. An unanswered or failed request isn't "Not benchmarked". */
function usePassport(id: string, rev: RevSelector | undefined): { facts: PassportFacts | null; loading: boolean; failed: boolean; latest: number | undefined } {
  const detail = useQuery(`detail:${id}`, (c) => c.getOntology(id));
  const { evidence, loading, error } = useEvidence(id, rev);
  const latest = detail.data?.latest_revision;
  const facts = evidence === undefined || (!detail.data && detail.loading) ? null : passportFacts(evidence, viewedRevision(rev, latest));
  return { facts, loading: loading || detail.loading, failed: !!error, latest };
}

export function ModelPassport({ id, rev, evidenceHref, className }: ModelPassportProps) {
  const { facts, failed } = usePassport(id, rev);
  const [open, setOpen] = useState(false);
  const [left, setLeft] = useState(0);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const text = failed ? "Evidence unavailable" : (facts?.chip ?? null);

  return (
    <div ref={root} className={cx("relative min-w-0", open ? "z-50" : "z-10", className)}>
      {text === null ? (
        <span role="status" aria-label="Loading the model passport" className="block h-6 w-56 max-w-full animate-pulse rounded-md border border-line-soft bg-panel-2" />
      ) : (
        <button
          type="button"
          aria-expanded={open}
          aria-haspopup="dialog"
          title={text}
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            // Keep the panel on screen: it starts at the chip and shifts left when it would overflow.
            const width = Math.min(PANEL_WIDTH, window.innerWidth - 16);
            setLeft(Math.min(0, window.innerWidth - 8 - width - r.left));
            setOpen((v) => !v);
          }}
          className={cx(
            "flex h-6 max-w-full items-center gap-1.5 rounded-md border bg-panel-2 px-2 text-[11.5px] font-medium text-muted hover:bg-panel-3 hover:text-ink",
            facts?.blind.headline === NOT_BENCHMARKED || failed ? "border-dashed border-[#46555f]" : "border-line",
          )}
        >
          <span className="truncate">{text}</span>
          <span aria-hidden className="shrink-0 text-faint">
            {open ? "▴" : "▾"}
          </span>
        </button>
      )}
      {open && (
        <div
          role="dialog"
          aria-label="Model passport"
          className="absolute top-full mt-1.5 max-h-[calc(100dvh-7rem)] overflow-y-auto rounded-lg border border-line bg-panel p-3 shadow-[0_12px_32px_rgba(0,0,0,0.55)]"
          style={{ left, width: `min(${PANEL_WIDTH}px, calc(100vw - 16px))` }}
        >
          <PassportBody id={id} rev={rev} evidenceHref={evidenceHref} />
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="pt-px text-[12px] text-faint">{label}</dt>
      <dd className="min-w-0 text-[12.5px] text-ink">{children}</dd>
    </>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-faint">{children}</h3>;
}

/** The passport's full contents, reading the same data as the chip. */
export function PassportBody({ id, rev, evidenceHref }: Omit<ModelPassportProps, "className">) {
  const { facts, failed } = usePassport(id, rev);
  const detail = useQuery(`detail:${id}`, (c) => c.getOntology(id));
  const revisions = useQuery<RevisionList>(`revisions:${id}`, (c) => c.listRevisions(id));
  // The same key the Evidence tab reads, so a new run there shows up here.
  const latest = detail.data?.latest_revision;
  const testsRev = rev && rev !== "latest" ? rev : latest ? String(latest) : latest === 0 ? "draft" : null;
  const tests = useQuery<StoredTestReport | null>(testsRev && `test-results:${id}:${testsRev}`, async (c) => {
    try {
      return await c.getTestResults(id, rev);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });

  if (failed) return <p className="text-[12.5px] text-muted">The evidence for this model couldn&apos;t be read, so this says nothing about how far to trust it.</p>;
  if (!facts) {
    return (
      <div role="status" aria-label="Loading the model passport" className="space-y-2">
        <div className="h-3 w-3/4 animate-pulse rounded bg-panel-2" />
        <div className="h-3 w-1/2 animate-pulse rounded bg-panel-2" />
      </div>
    );
  }

  const viewed = viewedRevision(rev, detail.data?.latest_revision);
  const revision: Revision | undefined = viewed === null ? undefined : revisions.data?.revisions.find((r) => r.number === viewed);
  const report = tests.data ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-[12px]">
        <span className="min-w-0 break-words text-muted">{facts.source}</span>
        <span className="tnum shrink-0 text-faint">
          {viewed === null ? "The draft" : `Revision r${viewed}`}
          {revision ? `, ${formatDate(revision.created_at)}` : ""}
        </span>
      </div>
      <section className="space-y-1">
        <Heading>How this was built</Heading>
        <p className="text-[12.5px] text-ink">{facts.built}</p>
      </section>
      <section className="space-y-1.5">
        <Heading>How good is it</Heading>
        <dl className="grid grid-cols-[112px_minmax(0,1fr)] gap-x-3 gap-y-2">
          <Row label="Blind benchmark">
            <div className="font-medium">{facts.blind.headline}</div>
            {facts.blind.detail ? (
              <div className="text-[11.5px] text-muted">
                {facts.blind.detail}. <span className={cx(facts.blind.stale && "text-warn")}>{facts.blind.measured}</span>, on cases and tests the builders never saw.
              </div>
            ) : (
              <div className="text-[11.5px] text-muted">Nothing outside the model has measured it.</div>
            )}
          </Row>
          <Row label="Mechanisms">
            {facts.mechanisms.counts.total > 0 ? (
              <>
                <FidelityStrip counts={facts.mechanisms.counts} legend />
                <div className="mt-1 text-[11.5px] text-muted">
                  {facts.mechanisms.modeledPct}% of {facts.mechanisms.counts.total} modeled.{" "}
                  <span className={cx(facts.mechanisms.stale && "text-warn")}>{facts.mechanisms.measured}</span>.
                </div>
              </>
            ) : (
              <div className="text-[11.5px] text-muted">No mechanism list is stored, so what&apos;s missing isn&apos;t known.</div>
            )}
          </Row>
          <Row label="Self-checks">
            <div className="font-medium">{tests.error ? "Couldn't read the last run" : tests.loading ? "…" : selfCheckWords(report, detail.data?.counts?.scenario)}</div>
            <div className="text-[11.5px] text-muted">{SELF_CHECK_CAPTION}</div>
          </Row>
        </dl>
      </section>
      <section className="space-y-1 border-t border-line-soft pt-2.5 text-[12.5px]">
        <p className="text-muted">
          <span className="font-semibold text-ink">Use it to</span> {USE_IT_TO}
        </p>
        <p className="text-muted">
          <span className="font-semibold text-ink">Don&apos;t use it to</span> {DONT_USE_IT_TO}
        </p>
      </section>
      <div className="text-right">
        <Link href={evidenceHref ?? evidenceLink(id, rev)} className="text-[12px] text-link hover:underline">
          Open Evidence
        </Link>
      </div>
    </div>
  );
}
