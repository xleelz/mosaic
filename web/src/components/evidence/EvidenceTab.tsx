"use client";

// Evidence: how far to trust this model. The passport's full data, then the mechanism list, with
// each number saying what it is and isn't (docs/ux-review-2026-11.md §5).

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, useMemo, useState } from "react";
import type { Evidence, EvidenceBlind, EvidenceMechanism, MechanismFidelity, MechanismGateStatus } from "@/lib/api/types";
import { useEvidence } from "@/lib/evidence";
import { useDocIndex } from "@/lib/hooks";
import type { DocIndex } from "@/lib/model/docindex";
import { formatDate, ifaceComponent, plural } from "@/lib/model/format";
import { Badge, Empty, ErrorBox, Notice, Panel, Select, SourceRef, Spinner, cx, inputClass } from "@/components/ui";
import { FIDELITY_MEANING, FIDELITY_ORDER, countFidelity } from "@/components/trust/fidelity";
import { FidelityMark, FidelityStrip } from "@/components/trust/marks";
import { DONT_USE_IT_TO, NOT_BENCHMARKED, SELF_CHECK_CAPTION, USE_IT_TO, builtWords } from "@/components/trust/passport";
import { revLabel, useDocument, useWorkspace } from "@/components/workspace/Workspace";
import { EvidenceNav } from "./EvidenceNav";
import { GATE_MEANING, GATE_STATUSES, disagreementText, filterMechanisms, gateDisagrees, kindsOf, measuredNote, parseCitation, percent, summarizeAreas, summarizeGate } from "./mechanisms";
import { selfCheckLine } from "./testlist";
import { useTestResults } from "./useTestResults";
import { ClaimScope } from "@/components/code/context";
import { WindowedList } from "@/components/WindowedList";

const NOT_BENCHMARKED_NOTE = "Nothing has measured this model against something outside itself. That's an unknown, not good news.";

/** One figure: its value, then plainly what it is and what it isn't. */
function Figure({ label, value, note, is, isnt, children }: { label: string; value: React.ReactNode; note?: React.ReactNode; is: string; isnt: string; children?: React.ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-0.5 border-t border-line-soft py-2.5 first:border-t-0 md:grid-cols-[150px_minmax(0,1fr)]">
      <div className="text-[12px] text-faint">{label}</div>
      <div className="min-w-0">
        <div className="text-[14px] font-semibold text-ink">{value}</div>
        {note ? <div className="mt-0.5 text-[12px] text-muted">{note}</div> : null}
        <p className="mt-1 text-[12px] leading-relaxed text-muted">
          <b className="font-medium text-ink">What it is:</b> {is} <b className="font-medium text-ink">What it isn&apos;t:</b> {isnt}
        </p>
        {children}
      </div>
    </div>
  );
}

/** Each gate status in plain words, with how many mechanisms measured it. */
function GateLegend({ items }: { items: EvidenceMechanism[] }) {
  const count = (s: MechanismGateStatus) => items.filter((m) => m.gate_status === s).length;
  return (
    <details className="mt-1.5 text-[12px] text-muted">
      <summary className="cursor-pointer select-none text-link hover:underline">What each gate status means</summary>
      <dl className="mt-1 grid gap-x-3 gap-y-1 sm:grid-cols-[110px_minmax(0,1fr)]">
        {GATE_STATUSES.map((s) => (
          <Fragment key={s}>
            <dt className="tnum font-medium text-ink">
              {s} <span className="font-normal text-faint">{count(s)}</span>
            </dt>
            <dd>{GATE_MEANING[s]}</dd>
          </Fragment>
        ))}
      </dl>
    </details>
  );
}

function BlindFigure({ blind, viewed }: { blind: EvidenceBlind | undefined; viewed: string }) {
  const is = "Fresh agents scored the model on cases and sampled tests that the builders never saw.";
  const isnt = "A verdict on the whole model. It's a sample, and it says nothing about behavior outside it.";
  if (!blind) return <Figure label="Blind benchmark" value={NOT_BENCHMARKED} note={NOT_BENCHMARKED_NOTE} is={is} isnt={isnt} />;
  const ratio = (p: number, t: number) => (t > 0 ? `${p} of ${t} (${percent(p, t)})` : "none recorded");
  return (
    <Figure
      label="Blind benchmark"
      value={blind.steps_total > 0 ? `${percent(blind.steps_passed, blind.steps_total)} of steps` : "No steps recorded"}
      note={
        <>
          <span className="block">
            Steps {ratio(blind.steps_passed, blind.steps_total)} · Cases {ratio(blind.cases_passed, blind.cases_total)} · Oracle tests {ratio(blind.oracle_passed, blind.oracle_total)}
            {blind.oracle_untranslatable ? ` · ${blind.oracle_untranslatable} couldn't be translated into scenarios` : ""}
          </span>
          <span className="block">
            {measuredNote(blind.measured_on_revision, viewed)}
            {blind.measured_at ? ` on ${formatDate(blind.measured_at)}` : ""}
            {blind.benchmark ? ` · ${blind.benchmark}` : ""}
          </span>
        </>
      }
      is={is}
      isnt={isnt}
    />
  );
}

function Passport({ evidence, viewed }: { evidence: Evidence | null; viewed: string }) {
  const ws = useWorkspace();
  const stored = useTestResults();
  const items = evidence?.mechanisms?.items ?? [];
  const counts = countFidelity(items);
  const gate = summarizeGate(items);
  const measuredOn = evidence?.mechanisms?.measured_on_revision;
  const builtBy = builtWords(evidence?.built_by);
  const source = evidence?.source;
  return (
    <Panel title="Passport" bodyClassName="px-4 py-2">
      {evidence === null && (
        <div className="mb-1 rounded-md border border-dashed border-line px-3 py-2">
          <div className="text-[14px] font-semibold text-ink">{NOT_BENCHMARKED}</div>
          <p className="text-[12.5px] text-muted">No evidence is stored for this revision. {NOT_BENCHMARKED_NOTE}</p>
        </div>
      )}
      {evidence && (
        <dl className="grid gap-x-4 gap-y-1 py-1.5 text-[12.5px] md:grid-cols-[150px_minmax(0,1fr)]">
          <dt className="text-faint">How it was built</dt>
          <dd className="text-ink">{builtBy}</dd>
          <dt className="text-faint">Source</dt>
          <dd className="text-ink">
            {source?.repo || source?.commit ? (
              <span className="font-mono text-[12px]">
                {source.repo}
                {source.commit ? ` @ ${source.commit.slice(0, 12)}` : ""}
              </span>
            ) : (
              "Not recorded."
            )}
          </dd>
          <dt className="text-faint">Viewing</dt>
          <dd className="font-mono text-[12px] text-ink">{revLabel(viewed)}</dd>
        </dl>
      )}
      <div className={cx(evidence && "border-t border-line-soft")}>
        {evidence && (
          <>
            <BlindFigure blind={evidence.blind} viewed={viewed} />
            <Figure
              label="Mechanisms"
              value={items.length > 0 ? `${counts.modeled} modeled of ${items.length} (${percent(counts.modeled, items.length)})` : "Not enumerated"}
              note={items.length > 0 && measuredOn !== undefined ? measuredNote(measuredOn, viewed) : undefined}
              is="An agent read the code, listed the mechanisms it found, and rated each one against the model. Each row below shows its reading."
              isnt="A count of everything the system does, or a measurement. The list holds what that agent found, and each rating is its reading."
            />
            <Figure
              label="Boundary gate"
              value={gate.measured > 0 ? `${gate.ok} of ${gate.measured} measure ok` : "Not measured"}
              note={
                gate.measured > 0
                  ? [
                      gate.weak ? `${gate.weak} weak: noticed only by an abort, or not for each interface` : "",
                      gate.skipped ? `${gate.skipped} skipped` : "",
                      gate.unmeasured ? `${gate.unmeasured} not measured` : "",
                      gate.disagreements ? `${plural(gate.disagreements, "disagreement")} with the enumerator` : "no disagreements with the enumerator",
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : undefined
              }
              is="check --mechanism-e2e reran each mechanism's scenarios with its interfaces disabled, and counted it ok when a boundary expectation then failed."
              isnt="Accuracy. It shows the mechanism matters inside the model, using scenarios written alongside it, not that the model matches the code. Read the ok count as an upper limit, not proof."
            >
              {gate.measured > 0 && <GateLegend items={items} />}
            </Figure>
          </>
        )}
        <Figure
          label="Self-checks"
          value={stored.data ? selfCheckLine(stored.data) : stored.loading ? "Loading…" : "Not run yet"}
          note={stored.data ? `Ran ${formatDate(stored.data.ran_at)} at ${revLabel(stored.data.revision)}` : undefined}
          is={SELF_CHECK_CAPTION}
          isnt="Evidence about the real system."
        />
      </div>
      <dl className="grid gap-x-4 gap-y-1 border-t border-line-soft py-2.5 text-[12.5px] md:grid-cols-[150px_minmax(0,1fr)]">
        <dt className="text-faint">Use it to</dt>
        <dd className="text-ink">{USE_IT_TO}</dd>
        <dt className="text-faint">Don&apos;t use it to</dt>
        <dd className="text-ink">{DONT_USE_IT_TO}</dd>
      </dl>
      <div className="border-t border-line-soft py-2 text-[12px]">
        <Link href={ws.href("evidence/tests")} className="text-link hover:underline">
          Open self-checks
        </Link>
      </div>
    </Panel>
  );
}

function GateMark({ status }: { status: MechanismGateStatus | undefined }) {
  if (!status) return <Badge title="check --mechanism-e2e has no result for this mechanism">gate: not measured</Badge>;
  return (
    <Badge tone={status === "shell" || status === "uncovered" || status === "weak" ? "warn" : "neutral"} title={GATE_MEANING[status]}>
      gate: {status}
    </Badge>
  );
}

function InterfaceLinks({ ids, idx }: { ids: string[]; idx: DocIndex | undefined }) {
  const ws = useWorkspace();
  if (ids.length === 0) return <span className="text-faint">none in this model</span>;
  return (
    <>
      {ids.map((id) =>
        !idx || idx.interfacesById.has(id) ? (
          <Link key={id} href={ws.href("", { c: ifaceComponent(id), i: id })} className="break-all font-mono text-[11px] text-link hover:underline">
            {id}
          </Link>
        ) : (
          <span key={id} className="break-all font-mono text-[11px] text-faint" title="Not in the model at this revision">
            {id}
          </span>
        ),
      )}
    </>
  );
}

function MechanismRow({ m, idx }: { m: EvidenceMechanism; idx: DocIndex | undefined }) {
  const disagrees = gateDisagrees(m.fidelity, m.gate_status);
  return (
    <div className="pb-1.5">
      <article className={cx("rounded-md border bg-panel px-3 py-2", m.fidelity === "absent" ? "border-dashed border-line" : "border-line-soft")}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="text-[13px] font-semibold text-ink">{m.name}</h3>
          <span className="font-mono text-[11px] text-faint">{m.id}</span>
          <Badge>{m.kind}</Badge>
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 text-[11px] text-faint">
              enumerator:
              <FidelityMark fidelity={m.fidelity} title={`The enumerator's reading. ${FIDELITY_MEANING[m.fidelity]}`} />
            </span>
            <GateMark status={m.gate_status} />
            {disagrees && m.gate_status && (
              <Badge tone="warn" title={disagreementText(m.fidelity, m.gate_status)}>
                ! disagrees
              </Badge>
            )}
          </span>
        </div>
        {disagrees && m.gate_status && <p className="mt-1 text-[12px] text-warn">{disagreementText(m.fidelity, m.gate_status)}</p>}
        {m.note && <p className="mt-1 text-[12.5px] text-ink">{m.note}</p>}
        {m.trigger && (
          <p className="mt-1 text-[12px] text-muted">
            <span className="text-faint">Trigger: </span>
            {m.trigger}
          </p>
        )}
        {m.observable && (
          <p className="mt-1 text-[12px] text-muted">
            <span className="text-faint">Observable: </span>
            {m.observable}
          </p>
        )}
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12px]">
          <span className="text-faint" title="A citation is a source, not proof">
            Code:
          </span>
          <ClaimScope claim={m.observable ? `${m.name}: ${m.observable}` : m.name}>
            {m.citations.length === 0 ? <span className="text-faint">none listed</span> : m.citations.map((c, i) => <SourceRef key={`${c}:${i}`} source={parseCitation(c)} />)}
          </ClaimScope>
        </div>
        <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12px]">
          <span className="text-faint">Interfaces:</span>
          <InterfaceLinks ids={m.interfaces} idx={idx} />
        </div>
      </article>
    </div>
  );
}

const estimateRow = (m: EvidenceMechanism) => 96 + (m.note ? 22 : 0) + (m.trigger ? 22 : 0) + (m.observable ? 22 : 0);
const rowKey = (m: EvidenceMechanism) => m.id;

function fidelityFromParam(v: string | null): Set<MechanismFidelity> {
  return new Set(FIDELITY_ORDER.filter((f) => v?.split(",").includes(f)));
}

/** The list and its filters. Deep links: ?area=, ?fidelity=absent,shell, ?kind=, ?q=. */
function MechanismList({ items, idx }: { items: EvidenceMechanism[]; idx: DocIndex | undefined }) {
  const search = useSearchParams();
  const [fidelities, setFidelities] = useState(() => fidelityFromParam(search.get("fidelity")));
  const [kind, setKind] = useState(() => search.get("kind") ?? "");
  const [area, setArea] = useState(() => search.get("area") ?? "");
  const [query, setQuery] = useState(() => search.get("q") ?? "");
  const [disagreeOnly, setDisagreeOnly] = useState(false);

  const areas = useMemo(() => summarizeAreas(items), [items]);
  const kinds = useMemo(() => kindsOf(items), [items]);
  const all = useMemo(() => countFidelity(items), [items]);
  const disagreements = useMemo(() => areas.reduce((a, s) => a + s.disagreements, 0), [areas]);
  const shown = useMemo(() => filterMechanisms(items, { fidelities, kind, area, query, disagreeOnly }), [items, fidelities, kind, area, query, disagreeOnly]);

  const toggle = (f: MechanismFidelity) =>
    setFidelities((prev) => {
      const next = new Set(prev);
      if (!next.delete(f)) next.add(f);
      return next;
    });

  return (
    <>
      <Panel title={`By area · ${plural(areas.length, "area")}`} bodyClassName="p-2">
        <p className="px-1 pb-1.5 text-[12px] text-muted">The enumerator&apos;s reading, in the list&apos;s own areas, which can differ from the areas on the map. Select an area to filter.</p>
        <ul className="space-y-0.5">
          {areas.map((s) => (
            <li key={s.area}>
              <button
                type="button"
                aria-pressed={area === s.area}
                onClick={() => setArea((a) => (a === s.area ? "" : s.area))}
                className={cx("grid w-full grid-cols-[minmax(90px,180px)_minmax(0,1fr)_auto] items-center gap-3 rounded px-1.5 py-1 text-left hover:bg-panel-2", area === s.area && "bg-panel-2")}
              >
                <span className="truncate font-mono text-[12px] text-ink">{s.area}</span>
                <FidelityStrip counts={s.counts} />
                <span className="flex items-center gap-2 text-[11.5px] text-muted">
                  <span className="tnum">
                    {s.counts.modeled} of {s.counts.total} modeled
                  </span>
                  {s.disagreements > 0 && <Badge tone="warn" title="Where the enumerator and the gate tell different stories">! {s.disagreements}</Badge>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      <div className="sticky top-0 z-10 space-y-2 rounded-lg border border-line bg-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Filter by fidelity" className="flex flex-wrap gap-1">
            {FIDELITY_ORDER.map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={fidelities.has(f)}
                onClick={() => toggle(f)}
                className={cx("inline-flex h-7 items-center gap-1.5 rounded-md border px-2", fidelities.has(f) ? "border-ink bg-panel-3" : "border-line hover:bg-panel-2")}
              >
                <FidelityMark fidelity={f} />
                <span className="tnum text-[11px] text-muted">{all[f]}</span>
              </button>
            ))}
          </div>
          <Select aria-label="Filter by kind" value={kind} onChange={(e) => setKind(e.target.value)} className="h-7 text-[12px]">
            <option value="">All kinds</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
          <input
            type="search"
            aria-label="Search mechanisms"
            placeholder="Search names, notes, code, interfaces"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={cx(inputClass, "h-7 min-w-[220px] flex-1 text-[12px]")}
          />
          <label className={cx("flex items-center gap-1.5 text-[12px]", disagreements > 0 ? "text-muted" : "text-faint")}>
            <input type="checkbox" checked={disagreeOnly} onChange={(e) => setDisagreeOnly(e.target.checked)} className="accent-[#ccff78]" />
            Disagreements only ({disagreements})
          </label>
          <span role="status" className="tnum ml-auto text-[12px] text-muted">
            {shown.length === items.length ? plural(items.length, "mechanism") : `${shown.length} of ${items.length} mechanisms`}
            {area ? ` in ${area}` : ""}
          </span>
        </div>
      </div>

      {shown.length === 0 ? (
        <Empty>No mechanism matches these filters.</Empty>
      ) : (
        <WindowedList items={shown} itemKey={rowKey} estimate={estimateRow} label="Mechanisms" render={(m) => <MechanismRow m={m} idx={idx} />} />
      )}
    </>
  );
}

export function EvidenceTab() {
  const ws = useWorkspace();
  const doc = useDocument();
  const idx = useDocIndex(doc.data);
  const { evidence, loading, error } = useEvidence(ws.id, ws.rev);
  const items = evidence?.mechanisms?.items ?? [];
  return (
    <div className="mx-auto max-w-[1400px] space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-semibold text-ink">Evidence</h2>
        <EvidenceNav active="mechanisms" />
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {loading && evidence === undefined && <Spinner label="Loading evidence" />}
      {evidence !== undefined && <Passport evidence={evidence} viewed={ws.dataRev} />}
      {evidence && items.length === 0 && <Notice title="No mechanism list">No enumerator has listed this model&apos;s mechanisms, so there&apos;s no denominator to read its coverage against.</Notice>}
      {items.length > 0 && <MechanismList key={`${ws.id}:${ws.dataRev}`} items={items} idx={idx} />}
    </div>
  );
}
