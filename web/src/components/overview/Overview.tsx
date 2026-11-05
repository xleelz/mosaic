"use client";

// A model's front page: what this is, where it starts, what it does, how far to trust it, where next.
// Nothing here is hand-curated, so each derived list says how it was derived.

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, type ReactNode } from "react";
import type { Document } from "@/lib/api/types";
import { useEvidence } from "@/lib/evidence";
import { useDocIndex } from "@/lib/hooks";
import { OTHER, descendantCounts, mainFlows, type DocIndex } from "@/lib/model/docindex";
import { plural } from "@/lib/model/format";
import { ErrorBox, Panel } from "@/components/ui";
import { PassportBody } from "@/components/trust/ModelPassport";
import { FidelityMark, FidelityStrip } from "@/components/trust/marks";
import { fidelitySentence } from "@/components/trust/fidelity";
import { isMapQuery } from "@/components/workspace/tabs";
import { useDocument, useWorkspace } from "@/components/workspace/Workspace";
import { areaRollup, entryPoints, topLevelRows } from "./derive";
import { MapSkeleton, OverviewSkeleton } from "./Skeletons";

/** Rows per list before "and N more". */
const LIST_CAP = 10;
const MAIN_FLOWS = 8;
/** The scale rule: no view draws more than about 40 boxes. */
const AREA_CAP = 40;

const COUNTS: { key: keyof Pick<Document, "components" | "interfaces" | "flows" | "scenarios">; one: string; explain: string }[] = [
  { key: "components", one: "component", explain: "A part of the system the model names" },
  { key: "interfaces", one: "interface", explain: "Any callable the model tracks" },
  { key: "flows", one: "flow", explain: "One entry point and all it can do" },
  { key: "scenarios", one: "scenario", explain: "One concrete situation the model can run" },
];

function Caption({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-[11.5px] text-faint">{children}</p>;
}

function More({ total, shown, href, what }: { total: number; shown: number; href: string; what: string }) {
  if (total <= shown) return null;
  return (
    <Link href={href} className="mt-1.5 inline-block text-[12px] text-link hover:underline">
      and {total - shown} more {what}
    </Link>
  );
}

function RowLink({ href, title, mono, right }: { href: string; title: string; mono?: string; right?: ReactNode }) {
  return (
    <li>
      <Link href={href} className="flex min-w-0 items-baseline gap-2 rounded px-1 py-1 text-[13px] text-ink hover:bg-panel-2">
        <span className="truncate">{title}</span>
        {mono && mono !== title && <span className="truncate font-mono text-[10.5px] text-faint">{mono}</span>}
        {right && <span className="tnum ml-auto shrink-0 pl-2 text-[11.5px] text-faint">{right}</span>}
      </Link>
    </li>
  );
}

function About({ doc, description }: { doc: Document; description: string | undefined }) {
  const src = doc.source;
  return (
    <section aria-label="What this is" className="space-y-2">
      {description ? (
        <p className="max-w-4xl text-[14px] leading-relaxed text-ink">{description}</p>
      ) : (
        <p className="max-w-4xl text-[14px] leading-relaxed text-muted">Nobody has written a description of this model. What follows is only what its data shows.</p>
      )}
      <dl className="flex flex-wrap gap-x-5 gap-y-1">
        {COUNTS.map(({ key, one, explain }) => (
          <div key={key} className="flex items-baseline gap-1.5" title={explain}>
            <dd className="tnum text-[15px] font-semibold text-ink">{(doc[key] ?? []).length}</dd>
            <dt className="text-[12px] text-faint">{(doc[key] ?? []).length === 1 ? one : `${one}s`}</dt>
          </div>
        ))}
      </dl>
      {src && (src.repo || src.sha) && (
        <p className="text-[12px] text-faint">
          Models{" "}
          {src.url ? (
            <a href={src.url} target="_blank" rel="noreferrer" className="text-link hover:underline">
              {src.repo || src.url}
            </a>
          ) : (
            <span className="text-muted">{src.repo}</span>
          )}
          {src.sha && <span className="font-mono"> @ {src.sha.slice(0, 7)}</span>}
        </p>
      )}
    </section>
  );
}

function EntryPoints({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const ws = useWorkspace();
  const { entries, dependencies } = useMemo(() => entryPoints(doc, idx), [doc, idx]);
  return (
    <Panel title="Entry points">
      <Caption>Derived from components of kind client or external and from each flow&apos;s entry. Nobody chose these.</Caption>
      {entries.length === 0 ? (
        <p className="text-[12.5px] text-muted">No flow has an entry and no component is of kind client, so the data doesn&apos;t show where requests come in.</p>
      ) : (
        <>
          <ul>
            {entries.slice(0, LIST_CAP).map((e) => (
              <RowLink key={e.id} href={ws.href("map", { c: e.id })} title={e.name} mono={e.kind} right={e.flows > 0 ? plural(e.flows, "flow") : "starts no flow"} />
            ))}
          </ul>
          <More total={entries.length} shown={LIST_CAP} href={ws.href("flows")} what="in Flows" />
        </>
      )}
      {dependencies.length > 0 && (
        <div className="mt-3">
          <h3 className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-faint">External dependencies</h3>
          <ul>
            {dependencies.slice(0, LIST_CAP).map((e) => (
              <RowLink key={e.id} href={ws.href("map", { c: e.id })} title={e.name} />
            ))}
          </ul>
          <More total={dependencies.length} shown={LIST_CAP} href={ws.href("map")} what="on the map" />
        </div>
      )}
    </Panel>
  );
}

function MainFlows({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const ws = useWorkspace();
  const main = useMemo(() => mainFlows(doc.flows ?? [], idx, MAIN_FLOWS), [doc, idx]);
  const flows = doc.flows ?? [];
  return (
    <Panel title="Main flows">
      <Caption>Derived, not chosen by anyone: flows entered from outside the model first, then those most scenarios touch.</Caption>
      {main.length === 0 ? (
        <p className="text-[12.5px] text-muted">{flows.length === 0 ? "This model has no flows." : "No scenario exercises a flow, so nothing here says which matter most."}</p>
      ) : (
        <ul>
          {main.map(({ flow, reason }) => (
            <RowLink key={flow.id} href={ws.href("flows", { flow: flow.id })} title={flow.name || flow.id} mono={flow.id} right={reason.replace("entered from outside the model, ", "")} />
          ))}
        </ul>
      )}
      <More total={flows.length} shown={main.length} href={ws.href("flows")} what="in Flows" />
    </Panel>
  );
}

function Areas({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const ws = useWorkspace();
  const { evidence } = useEvidence(ws.id, ws.rev);
  const items = evidence?.mechanisms?.items;
  const rollup = useMemo(() => areaRollup(doc, idx, items ?? []), [doc, idx, items]);
  const hasList = (items?.length ?? 0) > 0;
  const top = useMemo(() => (rollup.rows.length ? [] : topLevelRows(idx, descendantCounts(idx))), [rollup.rows.length, idx]);

  if (rollup.rows.length === 0) {
    return (
      <Panel title="What it's made of">
        <Caption>This model has no areas, so these are its top-level components.</Caption>
        <ul className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
          {top.slice(0, AREA_CAP).map((t) => (
            <RowLink key={t.id} href={ws.href("map", { c: t.id })} title={t.name} mono={t.kind} right={t.members > 0 ? `${t.members} inside` : undefined} />
          ))}
        </ul>
        <More total={top.length} shown={AREA_CAP} href={ws.href("map")} what="on the map" />
        {rollup.unplaced.total > 0 && (
          <div className="mt-3 max-w-md">
            <h3 className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-faint">Mechanisms</h3>
            <FidelityStrip counts={rollup.unplaced} legend />
          </div>
        )}
      </Panel>
    );
  }

  const shown = rollup.rows.slice(0, AREA_CAP);
  return (
    <Panel title={`Areas · ${rollup.rows.length}`} bodyClassName="p-0">
      <div className="px-3 pt-2.5">
        <Caption>{hasList ? "Bars show how the mechanisms enumerated from the code are modeled. A dashed line counts what isn't in this model." : "No mechanism list is stored, so there's no way to show how much of each area is modeled."}</Caption>
      </div>
      <ul className="divide-y divide-line-soft">
        {shown.map((r) => (
          <li key={r.area} className="px-3 py-2 hover:bg-panel-2">
            <Link href={r.area === OTHER ? ws.href("map") : ws.href("map", { area: r.area })} className="grid grid-cols-[minmax(120px,1fr)_auto_minmax(120px,2fr)] items-center gap-x-4">
              <span className="truncate text-[13px] font-medium text-ink" title={r.area}>
                {r.area === OTHER ? "No area" : r.area}
              </span>
              <span className="tnum whitespace-nowrap text-[11.5px] text-faint">
                {plural(r.components, "part")} · {plural(r.flows, "flow")}
              </span>
              {r.mechanisms.total > 0 ? (
                <FidelityStrip counts={r.mechanisms} />
              ) : (
                <span className="text-[11.5px] text-faint">{hasList ? "No mechanisms listed" : ""}</span>
              )}
            </Link>
            {r.mechanisms.absent > 0 && (
              <Link
                href={ws.href("evidence", { area: r.area, fidelity: "absent" })}
                className="mt-1 flex items-center gap-1.5 rounded border border-dashed border-line px-2 py-0.5 text-[11.5px] text-muted hover:text-ink"
              >
                <FidelityMark fidelity="absent" label={false} />
                {plural(r.mechanisms.absent, "mechanism")} {r.mechanisms.absent === 1 ? "isn't" : "aren't"} in this model
              </Link>
            )}
          </li>
        ))}
      </ul>
      {rollup.rows.length > shown.length && <div className="px-3 py-2 text-[12px] text-faint">and {rollup.rows.length - shown.length} more</div>}
      {rollup.unplaced.total > 0 && (
        <div className="border-t border-line-soft px-3 py-2 text-[11.5px] text-muted">
          <Link href={ws.href("evidence")} className="hover:underline">
            {plural(rollup.unplaced.total, "mechanism")} match no area here: {fidelitySentence(rollup.unplaced)}.
          </Link>
        </div>
      )}
    </Panel>
  );
}

function NextSteps({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const ws = useWorkspace();
  const first = useMemo(() => mainFlows(doc.flows ?? [], idx, 1)[0]?.flow, [doc, idx]);
  const steps = [
    { title: "See what it's made of", detail: "The map", href: ws.href("map") },
    first
      ? { title: "Follow a request", detail: first.name || first.id, href: ws.href("flows", { flow: first.id }) }
      : { title: "Follow a request", detail: "Flows", href: ws.href("flows") },
    { title: "Ask what happens if something fails", detail: "Runs", href: ws.href("simulate") },
    { title: "Check how good this model is", detail: "Evidence", href: ws.href("evidence") },
  ];
  return (
    <Panel title="Where to go next">
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
        {steps.map((s) => (
          <li key={s.title}>
            <Link href={s.href} className="block h-full rounded-md border border-line-soft bg-panel-2 px-3 py-2 hover:border-line hover:bg-panel-3">
              <div className="text-[13px] font-medium text-ink">{s.title}</div>
              <div className="truncate text-[11.5px] text-faint">{s.detail}</div>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11.5px] text-faint">Know the name of what you&apos;re after? Press / to search everything.</p>
    </Panel>
  );
}

export function Overview() {
  const ws = useWorkspace();
  const doc = useDocument();
  const idx = useDocIndex(doc.data);
  if (doc.error) {
    return (
      <div className="p-4">
        <ErrorBox error={doc.error} onRetry={doc.reload} />
      </div>
    );
  }
  if (!doc.data || !idx) return <OverviewSkeleton />;
  const description = ws.detail.data?.description || doc.data.description;
  return (
    <div className="mx-auto w-full max-w-[1280px] space-y-3 p-4">
      <About doc={doc.data} description={description} />
      <div className="grid grid-cols-1 items-start gap-3 lg:grid-cols-2">
        <EntryPoints doc={doc.data} idx={idx} />
        <MainFlows doc={doc.data} idx={idx} />
      </div>
      <Panel title="How far to trust it">
        <PassportBody id={ws.id} rev={ws.rev} evidenceHref={ws.href("evidence")} />
      </Panel>
      <Areas doc={doc.data} idx={idx} />
      <NextSteps doc={doc.data} idx={idx} />
    </div>
  );
}

/** The default route. A link written when the map was the default still opens the map. */
export function OverviewRoute() {
  const ws = useWorkspace();
  const search = useSearchParams();
  const router = useRouter();
  const legacy = isMapQuery(search.keys());
  useEffect(() => {
    if (!legacy) return;
    const q = search.toString();
    router.replace(`/o/${encodeURIComponent(ws.id)}/map${q ? `?${q}` : ""}`);
  }, [legacy, router, search, ws.id]);
  if (legacy) return <MapSkeleton />;
  return <Overview />;
}
