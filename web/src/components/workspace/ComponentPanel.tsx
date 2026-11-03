"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Component, Document, Graph, Interface, JsonValue, OntologyRef } from "@/lib/api/types";
import { refRev } from "@/lib/model/hierarchy";
import { nameOf } from "@/lib/model/docindex";
import { useDocIndex } from "@/lib/hooks";
import { ifaceId, latencyString } from "@/lib/model/format";
import { resolveSchema, schemaFields, schemaRefId } from "@/lib/model/schema";
import { StepList, StoreView } from "@/components/behavior/StepList";
import { JsonView } from "@/components/json";
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
        <span className="ml-auto text-[11px] text-faint" title="Simulated latency">
          ⏲ {latencyString(iface.latency_ms)}
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
              <SourceRef key={i} source={s} />
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
          <Button size="sm" variant="primary" onClick={onZoom} className="ml-auto" title="Open the child ontology inline">
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
                Open ontology →
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const NONE: never[] = [];

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
  const idx = useDocIndex(doc);
  const comp: Component | undefined = idx.componentsById.get(componentId);
  const ifaces = idx.interfacesByComponent.get(componentId) ?? NONE;
  // Members in a stable order (by id), whatever order the source lists them in.
  const children = idx.childrenByParent.get(componentId) ?? NONE;
  const outgoing = useMemo(() => graph.edges.filter((e) => e.from === componentId), [graph, componentId]);
  const incoming = useMemo(() => graph.edges.filter((e) => e.to === componentId), [graph, componentId]);
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
          {children.length > 0 && (
            <>
              <dt className="text-faint">members</dt>
              <dd className="flex flex-wrap gap-x-2">
                {children.map((c) => (
                  <button key={c.id} type="button" onClick={() => onSelect(c.id)} className="text-link hover:underline">
                    {c.name || c.id}
                  </button>
                ))}
              </dd>
            </>
          )}
          <dt className="text-faint">sources</dt>
          <dd className="flex flex-col">
            {comp.sources?.length ? comp.sources.map((s, i) => <SourceRef key={i} source={s} />) : <span className="text-faint">none recorded</span>}
          </dd>
          {(outgoing.length > 0 || incoming.length > 0) && (
            <>
              <dt className="text-faint">relations</dt>
              <dd className="space-y-0.5">
                {outgoing.map((e) => (
                  <div key={e.id} className="text-[12px]">
                    <span className="text-faint">{e.derived ? e.kind : `${e.kind} (link)`} →</span>{" "}
                    <button type="button" onClick={() => onSelect(e.to)} className="text-link hover:underline">
                      {name(e.to)}
                    </button>
                    {e.label && <span className="text-faint"> · {e.label}</span>}
                  </div>
                ))}
                {incoming.map((e) => (
                  <div key={e.id} className="text-[12px]">
                    <span className="text-faint">← {e.derived ? (e.kind === "emits" ? "emitted by" : "called by") : `${e.kind} (link) from`}</span>{" "}
                    <button type="button" onClick={() => onSelect(e.from)} className="text-link hover:underline">
                      {name(e.from)}
                    </button>
                  </div>
                ))}
              </dd>
            </>
          )}
        </dl>
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
            <div className="space-y-3">
              {ifaces.map((i) => (
                <InterfaceCard key={ifaceId(i)} doc={doc} iface={i} onSelectInterface={onSelectInterface} flash={focusInterface === ifaceId(i)} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
