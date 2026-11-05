"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Component, Document, EvidenceMechanism, Flow, Graph, Interface, JsonValue, MechanismFidelity, OntologyRef } from "@/lib/api/types";
import { refRev } from "@/lib/model/hierarchy";
import { componentMechanisms, componentScope, descendantCounts, faultScenarios, flowsThrough, groupMembers, nameOf, type DocIndex } from "@/lib/model/docindex";
import { useDocIndex } from "@/lib/hooks";
import { useEvidence } from "@/lib/evidence";
import { countFidelity } from "@/components/trust/fidelity";
import { FidelityMark, FidelityStrip } from "@/components/trust/marks";
import { WindowedList } from "@/components/WindowedList";
import { CompactScenarioRow, LazyDetails } from "./FlowsTab";
import { useDocument, useWorkspace } from "./Workspace";
import { ifaceId, latencyString } from "@/lib/model/format";
import { resolveSchema, schemaFields, schemaRefId } from "@/lib/model/schema";
import { StepList, StoreView } from "@/components/behavior/StepList";
import { JsonView } from "@/components/json";
import { ClaimScope } from "@/components/code/context";
import { Badge, Button, SourceRef, cx } from "@/components/ui";

function SchemaView({ doc, label, schema }: { doc: Document; label: string; schema: JsonValue | undefined }) {
  const [raw, setRaw] = useState(false);
  if (schema === undefined) {
    return (
      <div className="text-[12px]">
        <span className="text-faint">{label}:</span> <span className="text-faint">none</span>
      </div>
    );
  }
  const ref = schemaRefId(schema);
  const resolved = resolveSchema(doc, schema);
  const fields = schemaFields(resolved);
  const type = resolved && typeof resolved.type === "string" ? resolved.type : undefined;
  return (
    <div>
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-faint">{label}</span>
        {ref ? <Badge tone="info">{ref}</Badge> : <Badge>inline</Badge>}
        {type && <span className="font-mono text-[11px] text-faint">{type}</span>}
        <button type="button" onClick={() => setRaw((r) => !r)} className="ml-auto text-[11px] text-link hover:underline">
          {raw ? "fields" : "JSON"}
        </button>
      </div>
      {raw ? (
        <JsonView value={resolved ?? schema} className="mt-1" maxHeight={220} />
      ) : fields.length > 0 ? (
        <table className="mt-1 w-full text-[11.5px]">
          <tbody>
            {fields.map((f) => (
              <tr key={f.name} className="border-t border-line-soft align-baseline">
                <td className="py-0.5 pr-2 font-mono text-[#9fd2ff]">
                  {f.name}
                  {f.required && <span className="text-bad" title="required">*</span>}
                </td>
                <td className="py-0.5 pr-2 font-mono text-muted">{f.type}</td>
                <td className="py-0.5 text-faint">{f.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mt-1 text-[11.5px] text-faint">{resolved ? "No top-level properties." : `Unresolved schema reference.`}</div>
      )}
    </div>
  );
}

function InterfaceCard({ doc, iface, onSelectInterface, flash }: { doc: Document; iface: Interface; onSelectInterface: (id: string) => void; flash: boolean }) {
  const id = ifaceId(iface);
  // HTTP interfaces carry `path` and an optional `method`; show whichever is set.
  const method = typeof iface.attributes?.method === "string" && iface.attributes.method ? iface.attributes.method.toUpperCase() : undefined;
  const path = typeof iface.attributes?.path === "string" && iface.attributes.path ? iface.attributes.path : undefined;
  const otherAttrs = Object.fromEntries(Object.entries(iface.attributes ?? {}).filter(([k]) => k !== "method" && k !== "path"));
  return (
    <article
      id={`iface-${id}`}
      className={cx("scroll-mt-2 rounded-lg border bg-panel-2/60 transition-colors duration-700", flash ? "border-accent" : "border-line")}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-line-soft px-3 py-2">
        <h4 className="font-mono text-[13px] font-semibold text-ink">{iface.name}</h4>
        {iface.kind && <Badge tone="info">{iface.kind}</Badge>}
        {(method || path) && (
          <span className="font-mono text-[11px] text-muted">
            {method && <span className="font-semibold text-ink">{method}</span>}
            {method && path ? " " : null}
            {path}
          </span>
        )}
        {iface.implements && (
          <Badge tone="violet" title="Implements this parent interface (§14.3)">
            ⇡ {iface.implements}
          </Badge>
        )}
        {iface.latency_source?.refined && (
          <Badge tone="accent" title="latency_ms measured from a refinement (§14.3)">
            timing from {iface.latency_source.refined}
          </Badge>
        )}
        {iface.latency_source?.pinned && (
          <Badge tone="warn" title={`Pinned: ${iface.latency_source.pinned}`}>
            timing pinned
          </Badge>
        )}
        <span className="ml-auto text-[11px] text-faint" title="Simulated latency: virtual time, not a measurement">
          ⏲ {latencyString(iface.latency_ms)} virtual
        </span>
      </header>
      <div className="space-y-3 px-3 py-2.5">
        {(iface.summary || iface.description) && (
          <p className="text-[12.5px] text-muted">
            {iface.summary}
            {iface.description ? ` ${iface.description}` : ""}
          </p>
        )}
        {iface.sources?.length ? (
          <div className="flex flex-wrap gap-x-3">
            {iface.sources.map((s, i) => (
              <ClaimScope key={i} claim={iface.summary || iface.description || ifaceId(iface)}>
                <SourceRef source={s} />
              </ClaimScope>
            ))}
          </div>
        ) : null}
        {Object.keys(otherAttrs).length > 0 && <JsonView value={otherAttrs} maxHeight={120} />}
        <div className="grid grid-cols-1 gap-3">
          <SchemaView doc={doc} label="request" schema={iface.request} />
          <SchemaView doc={doc} label="response" schema={iface.response} />
        </div>
        {iface.errors?.length ? (
          <div>
            <div className="mb-1 text-[12px] text-faint">errors</div>
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-left text-faint">
                  <th className="pb-0.5 font-normal">code</th>
                  <th className="pb-0.5 font-normal">status</th>
                  <th className="pb-0.5 font-normal">retryable</th>
                  <th className="pb-0.5 font-normal">summary</th>
                </tr>
              </thead>
              <tbody>
                {iface.errors.map((e) => (
                  <tr key={e.code} className="border-t border-line-soft">
                    <td className="py-0.5 pr-2 font-mono text-bad">{e.code}</td>
                    <td className="tnum py-0.5 pr-2 text-muted">{e.status ?? "–"}</td>
                    <td className="py-0.5 pr-2 text-muted">{e.retryable ? "↻ yes" : "no"}</td>
                    <td className="py-0.5 text-faint">{e.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div>
          <div className="mb-1.5 flex items-center gap-2 text-[12px] text-faint">
            behavior
            <span className="text-[11px]">
              {iface.behavior?.length ? `${iface.behavior.length} top-level steps` : iface.store ? "store operation" : "stub"}
            </span>
          </div>
          {iface.behavior?.length && iface.store ? (
            <div className="mb-2">
              <div className="mb-1 text-[11px] text-faint">The behavior takes precedence, so this store operation is not used:</div>
              <StoreView store={iface.store} />
            </div>
          ) : null}
          {iface.behavior?.length ? (
            <StepList steps={iface.behavior} iface={id} onSelectInterface={onSelectInterface} />
          ) : iface.store ? (
            <StoreView store={iface.store} />
          ) : (
            <div className="rounded-md border border-dashed border-line px-2 py-1.5 text-[12px] text-muted">
              Stub: returns fake data generated from its response schema.
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function defaultOntologyHref(ontology: string, rev?: string): string {
  return `/o/${encodeURIComponent(ontology)}${rev ? `?rev=${encodeURIComponent(rev)}` : ""}`;
}

/** §14.3: the child ontologies refining a component, with zoom and open actions. */
function RefinementSection({
  refs,
  onZoom,
  ontologyHref,
}: {
  refs: OntologyRef[];
  onZoom?: () => void;
  ontologyHref: (ontology: string, rev?: string) => string;
}) {
  return (
    <section aria-label="Refinements" className="rounded-lg border border-[#4d6b1f] bg-[#121b10] px-3 py-2">
      <div className="flex items-center gap-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Refined by</h4>
        {onZoom && (
          <Button size="sm" variant="primary" onClick={onZoom} className="ml-auto" title="Open the child model inline">
            ⤢ Zoom in
          </Button>
        )}
      </div>
      <ul className="mt-1 space-y-0.5">
        {refs.map((r) => {
          const rev = refRev(r.revision);
          return (
            <li key={`${r.ontology}@${r.revision ?? ""}`} className="flex items-baseline gap-2 text-[12px]">
              <span className="font-mono text-ink">{r.ontology}</span>
              <span className="text-faint">{r.revision ? `@ ${r.revision}` : "@ latest"}</span>
              <Link href={ontologyHref(r.ontology, rev)} className="ml-auto text-link hover:underline">
                Open model →
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const NONE: never[] = [];

const sectionHeading = "text-[11px] font-semibold uppercase tracking-[0.08em] text-faint";

const WEAKEST_FIRST: Record<MechanismFidelity, number> = { shell: 0, absent: 1, partial: 2, modeled: 3 };

function MechanismRow({ m }: { m: EvidenceMechanism }) {
  return (
    <div className="pb-1 text-[12px]">
      <div className="flex items-baseline gap-1.5">
        <FidelityMark fidelity={m.fidelity} label={false} title={m.note} />
        <span className="text-ink">{m.name}</span>
      </div>
      {m.note && <div className="pl-[18px] text-[11.5px] text-faint">{m.note}</div>}
    </div>
  );
}

/** How much of this component the model holds: from the mechanism list, never silent about having none. */
function FidelitySection({ idx, id, rev }: { idx: DocIndex; id: string; rev: string }) {
  const ws = useWorkspace();
  const { evidence, loading } = useEvidence(ws.id, rev);
  const list = evidence?.mechanisms;
  const m = useMemo(() => (list ? componentMechanisms(idx, id, list.items) : null), [idx, id, list]);
  if (evidence === undefined || loading) return null;
  if (!list || !m) {
    return (
      <section aria-label="Fidelity" className="text-[12px] text-faint">
        <h4 className={sectionHeading}>Fidelity</h4>
        Not benchmarked: no mechanism list is stored for this model.
      </section>
    );
  }
  const weak = m.own.filter((x) => x.fidelity !== "modeled").sort((a, b) => WEAKEST_FIRST[a.fidelity] - WEAKEST_FIRST[b.fidelity]);
  const stale = list.measured_on_revision !== evidence?.revision;
  return (
    <section aria-label="Fidelity" className="space-y-1.5">
      <h4 className={sectionHeading}>Fidelity</h4>
      {m.own.length + m.absent.length === 0 ? (
        <div className="text-[12px] text-faint">The mechanism list doesn&apos;t cover this component, so it says nothing about it.</div>
      ) : (
        <FidelityStrip counts={countFidelity([...m.own, ...m.absent])} legend />
      )}
      {stale && <div className="text-[11.5px] text-faint">Listed on r{list.measured_on_revision}, not re-checked on this revision.</div>}
      {weak.length > 0 && (
        <LazyDetails summary={`${weak.length} on this component aren't fully modeled`} summaryClassName="text-[12px] text-link">
          <div className="mt-1 max-h-[220px] overflow-y-auto">
            <WindowedList items={weak} itemKey={(x) => x.id} estimate={40} render={(x) => <MechanismRow m={x} />} />
          </div>
        </LazyDetails>
      )}
      {m.absent.length > 0 && (
        <LazyDetails
          className="rounded border border-dashed border-line px-2 py-1"
          summaryClassName="text-[12px] text-muted"
          summary={`${m.absent.length} mechanisms in ${m.areas.join(", ")} aren't in this model`}
        >
          <div className="mt-1 max-h-[220px] overflow-y-auto">
            <WindowedList items={m.absent} itemKey={(x) => x.id} estimate={40} render={(x) => <MechanismRow m={x} />} />
          </div>
        </LazyDetails>
      )}
    </section>
  );
}

/** The gap to know about before running a failure here. */
function FailureHandlingGaps({ idx, id, rev }: { idx: DocIndex; id: string; rev: string }) {
  const ws = useWorkspace();
  const { evidence } = useEvidence(ws.id, rev);
  const items = evidence?.mechanisms?.items;
  const gaps = useMemo(() => (items ? componentMechanisms(idx, id, items).absentFailureHandling : []), [idx, id, items]);
  if (gaps.length === 0) return null;
  return (
    <LazyDetails
      className="mb-1.5 rounded border border-dashed border-line px-2 py-1"
      summaryClassName="text-[12px] text-ink"
      summary={`Before you run: this area lists ${gaps.length} failure-handling ${gaps.length === 1 ? "mechanism" : "mechanisms"} as absent, so a run here can't show ${gaps.length === 1 ? "it" : "them"}.`}
    >
      <div className="mt-1 max-h-[200px] overflow-y-auto">
        <WindowedList items={gaps} itemKey={(x) => x.id} estimate={40} render={(x) => <MechanismRow m={x} />} />
      </div>
    </LazyDetails>
  );
}

interface ThroughRow {
  flow: Flow;
  how: "enters here" | "could reach (static)";
}

function FlowsThroughSection({ doc, idx, comp, members }: { doc: Document; idx: DocIndex; comp: Component; members: number }) {
  const ws = useWorkspace();
  const rows = useMemo<ThroughRow[]>(() => {
    const t = flowsThrough(doc, idx, comp.id);
    return [...t.enters.map((flow): ThroughRow => ({ flow, how: "enters here" })), ...t.reaches.map((flow): ThroughRow => ({ flow, how: "could reach (static)" }))];
  }, [doc, idx, comp.id]);
  return (
    <section aria-label="Flows through here">
      <h4 className={sectionHeading}>
        Flows through here <span className="tnum font-normal">({rows.length})</span>
      </h4>
      {members > 0 && rows.length > 0 && <div className="text-[11.5px] text-faint">Counting its {members} members.</div>}
      {rows.length === 0 ? (
        <div className="text-[12px] text-faint">No flow enters here, or declares a call that could reach it.</div>
      ) : (
        <div className="mt-1 max-h-[220px] overflow-y-auto">
          <WindowedList
            items={rows}
            itemKey={(r) => r.flow.id}
            estimate={24}
            render={(r) => (
              <div className="flex items-baseline gap-2 py-0.5 text-[12.5px]">
                <Link href={ws.href("flows", { flow: r.flow.id })} className="min-w-0 flex-1 truncate text-link hover:underline" title={r.flow.id}>
                  {r.flow.name || <span className="font-mono text-[11.5px]">{r.flow.id}</span>}
                </Link>
                <span className="shrink-0 text-[11px] text-faint">{r.how}</span>
              </div>
            )}
          />
        </div>
      )}
    </section>
  );
}

function IfThisFails({ doc, idx, comp, rev, hasInterfaces }: { doc: Document; idx: DocIndex; comp: Component; rev: string; hasInterfaces: boolean }) {
  const ws = useWorkspace();
  const list = useMemo(() => faultScenarios(idx, comp.id), [idx, comp.id]);
  const tryFlow = useMemo(() => {
    const t = flowsThrough(doc, idx, comp.id);
    return t.reaches[0] ?? t.enters[0];
  }, [doc, idx, comp.id]);
  return (
    <section aria-label="If this fails">
      <h4 className={sectionHeading}>
        If this fails <span className="tnum font-normal">({list.length})</span>
      </h4>
      <div className="mt-1">
        <FailureHandlingGaps idx={idx} id={comp.id} rev={rev} />
        {list.length === 0 ? (
          <div className="text-[12px] text-faint">No scenario injects a fault here.</div>
        ) : (
          <div className="max-h-[280px] overflow-y-auto">
            <WindowedList
              items={list}
              itemKey={(x) => x.scenario.id}
              estimate={52}
              rowClassName="pb-1"
              render={(x) => (
                <CompactScenarioRow
                  s={x.scenario}
                  note={x.faults
                    .slice(0, 2)
                    .map((f) => `${f.type} on ${f.target}${f.code ? ` (${f.code})` : ""}`)
                    .join("; ")}
                />
              )}
            />
          </div>
        )}
        {tryFlow && hasInterfaces && (
          <Link href={ws.href("simulate", { flow: tryFlow.id, fault: comp.id })} className="mt-1 inline-block text-[12px] text-link hover:underline">
            Try a fault on this component →
          </Link>
        )}
      </div>
    </section>
  );
}

function MembersSection({ idx, id, onSelect }: { idx: DocIndex; id: string; onSelect: (id: string) => void }) {
  const counts = useMemo(() => descendantCounts(idx), [idx]);
  const groups = useMemo(() => groupMembers(idx, id, counts), [idx, id, counts]);
  const total = groups.reduce((n, g) => n + g.members.length, 0);
  return (
    <section aria-label="Members">
      <h4 className={sectionHeading}>
        Members <span className="tnum font-normal">({total})</span>
      </h4>
      <div className="mt-1 space-y-1">
        {groups.map((g, i) => (
          <LazyDetails
            key={g.key}
            defaultOpen={i === 0 || (i === 1 && g.key !== "rest") || total <= 12}
            summaryClassName="text-[12px] text-ink"
            summary={
              <>
                {g.label} <span className="tnum text-faint">· {g.members.length}</span>
              </>
            }
          >
            <div className="mt-0.5 max-h-[200px] overflow-y-auto">
              <WindowedList
                items={g.members}
                itemKey={(c) => c.id}
                estimate={22}
                render={(c) => (
                  <div className="flex items-baseline gap-2 py-px text-[12.5px]">
                    <button type="button" onClick={() => onSelect(c.id)} className="min-w-0 truncate text-left text-link hover:underline" title={c.id}>
                      {c.name || c.id}
                    </button>
                    {c.kind && <span className="shrink-0 text-[11px] text-faint">{c.kind}</span>}
                    {(counts.get(c.id) ?? 0) > 0 && <span className="tnum ml-auto shrink-0 text-[11px] text-faint">{counts.get(c.id)} inside</span>}
                  </div>
                )}
              />
            </div>
          </LazyDetails>
        ))}
      </div>
    </section>
  );
}

export function ComponentPanel({
  doc,
  graph,
  componentId,
  focusInterface,
  color,
  onSelect,
  onSelectInterface,
  onClose,
  onZoom,
  ontologyHref,
}: {
  doc: Document;
  graph: Graph;
  componentId: string;
  focusInterface?: string | null;
  color: string;
  onSelect: (id: string) => void;
  onSelectInterface: (id: string) => void;
  onClose: () => void;
  /** Opens the component's child ontology inline (§16.6); without it, refinements only link. */
  onZoom?: (componentId: string) => void;
  /** The workspace href of another ontology at a revision (defaults to /o/<id>?rev=). */
  ontologyHref?: (ontology: string, rev?: string) => string;
}) {
  const ws = useWorkspace();
  const workspaceDoc = useDocument();
  // A zoomed child model isn't the workspace's: its flows and runs belong to its own workspace.
  const inWorkspace = workspaceDoc.data === doc;
  const idx = useDocIndex(doc);
  const comp: Component | undefined = idx.componentsById.get(componentId);
  const ifaces = idx.interfacesByComponent.get(componentId) ?? NONE;
  // Members in a stable order (by id), whatever order the source lists them in.
  const children = idx.childrenByParent.get(componentId) ?? NONE;
  const outgoing = useMemo(() => graph.edges.filter((e) => e.from === componentId), [graph, componentId]);
  const incoming = useMemo(() => graph.edges.filter((e) => e.to === componentId), [graph, componentId]);
  const relations = useMemo(
    () => [...outgoing.map((edge) => ({ dir: "out" as const, edge })), ...incoming.map((edge) => ({ dir: "in" as const, edge }))],
    [outgoing, incoming],
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusInterface) {
      document.getElementById(`iface-${focusInterface}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
    } else {
      scrollRef.current?.scrollTo({ top: 0 });
    }
  }, [componentId, focusInterface]);

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [componentId]);

  if (!comp) return <div className="p-4 text-muted">Unknown component {componentId}.</div>;
  const name = (id: string) => nameOf(idx, id);
  const descendants = componentScope(idx, comp.id).size - 1;

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <div className="sticky top-0 z-10 border-b border-line bg-panel px-4 py-3">
        <div className="flex items-start gap-2">
          <span className="mt-1.5 h-3 w-3 shrink-0 rounded-sm" style={{ background: color }} aria-hidden />
          <div className="min-w-0 flex-1">
            <h3 ref={headingRef} tabIndex={-1} className="text-[15px] font-semibold text-ink outline-none">
              {comp.name || comp.id}
            </h3>
            <div className="font-mono text-[11px] text-faint">{comp.id}</div>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close component panel">
            ✕
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {comp.kind && <Badge tone="info">{comp.kind}</Badge>}
          {comp.layer && <Badge>layer {comp.layer}</Badge>}
          {comp.state && <Badge tone="violet">◉ stateful</Badge>}
          {children.length === 0 ? <Badge>leaf</Badge> : <Badge>{children.length} members</Badge>}
          {comp.refined_by?.length ? <Badge tone="accent">⊕ refined</Badge> : null}
          {comp.tags?.map((t) => (
            <Badge key={t}>#{t}</Badge>
          ))}
        </div>
      </div>
      <div className="space-y-4 px-4 py-3">
        {(comp.summary || comp.description) && (
          <div>
            {comp.summary && <p className="text-[13px] text-ink">{comp.summary}</p>}
            {comp.description && <p className="mt-1 text-[12.5px] text-muted">{comp.description}</p>}
          </div>
        )}
        {inWorkspace ? (
          <>
            <FlowsThroughSection doc={doc} idx={idx} comp={comp} members={descendants} />
            <IfThisFails doc={doc} idx={idx} comp={comp} rev={ws.rev} hasInterfaces={ifaces.length > 0} />
            <FidelitySection idx={idx} id={comp.id} rev={ws.rev} />
          </>
        ) : (
          <div className="text-[12px] text-faint">This is a refinement. Open it as its own workspace to see its flows, faults and fidelity.</div>
        )}
        {comp.refined_by?.length ? (
          <RefinementSection refs={comp.refined_by} onZoom={onZoom ? () => onZoom(comp.id) : undefined} ontologyHref={ontologyHref ?? defaultOntologyHref} />
        ) : null}
        <dl className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1 text-[12.5px]">
          {comp.parent && (
            <>
              <dt className="text-faint">parent</dt>
              <dd>
                <button type="button" onClick={() => onSelect(comp.parent!)} className="text-link hover:underline">
                  {name(comp.parent)}
                </button>
              </dd>
            </>
          )}
          <dt className="text-faint">sources</dt>
          <dd className="flex flex-col">
            {comp.sources?.length ? comp.sources.map((s, i) => (
                <ClaimScope key={i} claim={comp.summary || comp.description || comp.name || comp.id}>
                  <SourceRef source={s} />
                </ClaimScope>
              )) : <span className="text-faint">none recorded</span>}
          </dd>
          {(outgoing.length > 0 || incoming.length > 0) && (
            <>
              <dt className="text-faint">relations</dt>
              <dd className="max-h-[260px] overflow-y-auto">
                <WindowedList
                  items={relations}
                  itemKey={(r) => `${r.dir}:${r.edge.id}`}
                  estimate={20}
                  render={({ dir, edge: e }) =>
                    dir === "out" ? (
                      <div className="py-px text-[12px]">
                        <span className="text-faint">{e.derived ? e.kind : `${e.kind} (link)`} →</span>{" "}
                        <button type="button" onClick={() => onSelect(e.to)} className="text-link hover:underline">
                          {name(e.to)}
                        </button>
                        {e.label && <span className="text-faint"> · {e.label}</span>}
                      </div>
                    ) : (
                      <div className="py-px text-[12px]">
                        <span className="text-faint">← {e.derived ? (e.kind === "emits" ? "emitted by" : "called by") : `${e.kind} (link) from`}</span>{" "}
                        <button type="button" onClick={() => onSelect(e.from)} className="text-link hover:underline">
                          {name(e.from)}
                        </button>
                      </div>
                    )
                  }
                />
              </dd>
            </>
          )}
        </dl>
        {children.length > 0 && <MembersSection idx={idx} id={comp.id} onSelect={onSelect} />}
        {comp.attributes && Object.keys(comp.attributes).length > 0 && (
          <div>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Attributes</h4>
            <JsonView value={comp.attributes} maxHeight={140} />
          </div>
        )}
        {comp.state && (
          <div>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Initial state</h4>
            <JsonView value={comp.state.initial ?? {}} maxHeight={220} />
            {comp.state.schema && (
              <details className="mt-1">
                <summary className="cursor-pointer text-[11.5px] text-link">State schema</summary>
                <JsonView value={comp.state.schema} className="mt-1" maxHeight={180} />
              </details>
            )}
          </div>
        )}
        <div>
          <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
            Interfaces <span className="text-faint">({ifaces.length})</span>
          </h4>
          {ifaces.length === 0 ? (
            <div className="text-[12px] text-faint">This component provides no interfaces{children.length ? "; its members do." : "."}</div>
          ) : (
            <WindowedList
              items={ifaces as Interface[]}
              itemKey={ifaceId}
              estimate={260}
              rowClassName="pb-3"
              ensure={focusInterface ? ifaces.findIndex((i) => ifaceId(i) === focusInterface) : undefined}
              render={(i) => <InterfaceCard doc={doc} iface={i} onSelectInterface={onSelectInterface} flash={focusInterface === ifaceId(i)} />}
            />
          )}
        </div>
      </div>
    </div>
  );
}
