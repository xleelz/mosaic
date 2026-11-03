"use client";

// §16.6 zoom: a refined component opens its child ontology inline, as a
// nested map. Children that are refined in turn zoom further; the crumbs
// walk back up.

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Document, OntologyRef } from "@/lib/api/types";
import { ifaceComponent, ifaceId } from "@/lib/model/format";
import { childRev } from "@/lib/model/hierarchy";
import { docIndex } from "@/lib/model/docindex";
import { useQuery } from "@/lib/hooks";
import { ArchitectureMap, MapLegend, useColorScale } from "@/components/map/ArchitectureMap";
import { Badge, Button, ErrorBox, Select, Spinner, cx } from "@/components/ui";
import { ComponentPanel } from "./ComponentPanel";

/** One zoom level: `component` of `from` opened as its refinement `ref`. */
interface Frame {
  from: string;
  fromName: string;
  component: string;
  componentName: string;
  refs: OntologyRef[];
  pick: number;
}

function frameOf(doc: Document, from: string, component: string): Frame | null {
  const c = docIndex(doc).componentsById.get(component);
  if (!c?.refined_by?.length) return null;
  return { from, fromName: doc.name || from, component, componentName: c.name || c.id, refs: c.refined_by, pick: 0 };
}

export function ontologyHref(ontology: string, rev?: string, extra?: Record<string, string>): string {
  const q = new URLSearchParams();
  if (rev) q.set("rev", rev);
  for (const [k, v] of Object.entries(extra ?? {})) q.set(k, v);
  const qs = q.toString();
  return `/o/${encodeURIComponent(ontology)}${qs ? `?${qs}` : ""}`;
}

export function ZoomView({ doc, ontology, component, onClose }: { doc: Document; ontology: string; component: string; onClose: () => void }) {
  const first = useMemo(() => frameOf(doc, ontology, component), [doc, ontology, component]);
  const [stack, setStack] = useState<Frame[]>(() => (first ? [first] : []));
  if (!first || stack.length === 0) {
    return (
      <div className="p-4">
        <ErrorBox error={new Error(`Component ${component} has no refined_by.`)} />
        <Button size="sm" className="mt-2" onClick={onClose}>
          Back to the map
        </Button>
      </div>
    );
  }
  const top = stack[stack.length - 1];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <nav aria-label="Zoom levels" className="flex shrink-0 flex-wrap items-center gap-x-1.5 gap-y-1 border-b border-line-soft bg-panel/60 px-4 py-1.5 text-[12px]">
        <button type="button" onClick={onClose} className="text-link hover:underline">
          {doc.name || ontology}
        </button>
        {stack.map((f, i) => {
          const last = i === stack.length - 1;
          return (
            <span key={`${i}:${f.component}`} className="inline-flex items-center gap-1.5">
              <span className="text-faint">›</span>
              {last ? (
                <span className="font-semibold text-ink">{f.componentName}</span>
              ) : (
                <button type="button" onClick={() => setStack((s) => s.slice(0, i + 1))} className="text-link hover:underline">
                  {f.componentName}
                </button>
              )}
              <span className="text-accent" aria-hidden>
                ⤢
              </span>
              <span className="font-mono text-[11px] text-muted">{f.refs[f.pick].ontology}</span>
            </span>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          {top.refs.length > 1 && (
            <Select
              aria-label="Refinement"
              value={String(top.pick)}
              onChange={(e) => setStack((s) => [...s.slice(0, -1), { ...top, pick: Number(e.target.value) }])}
              className="h-7 text-[12px]"
            >
              {top.refs.map((r, i) => (
                <option key={i} value={i}>
                  {r.ontology}
                  {r.revision ? ` @ ${r.revision}` : ""}
                </option>
              ))}
            </Select>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>
            ✕ Close zoom
          </Button>
        </div>
      </nav>
      <ChildLevel key={`${stack.length}:${top.refs[top.pick].ontology}`} frame={top} onZoom={(childDoc, childId, comp) => {
        const f = frameOf(childDoc, childId, comp);
        if (f) setStack((s) => [...s, f]);
      }} />
    </div>
  );
}

function ChildLevel({ frame, onZoom }: { frame: Frame; onZoom: (doc: Document, ontology: string, component: string) => void }) {
  const ref = frame.refs[frame.pick];
  const id = ref.ontology;
  const detail = useQuery(`detail:${id}`, (c) => c.getOntology(id));
  const rev = detail.data ? childRev(ref, detail.data.latest_revision) : null;
  const doc = useQuery(rev ? `doc:${id}:${rev}` : null, (c) => c.getDocument(id, rev!));
  const graph = useQuery(rev ? `graph:${id}:${rev}` : null, (c) => c.getGraph(id, rev!));
  const [selected, setSelected] = useState<string | null>(null);
  const scale = useColorScale(graph.data, "layer");
  const refined = useMemo(() => new Set((doc.data?.components ?? []).filter((c) => c.refined_by?.length).map((c) => c.id)), [doc.data]);
  const contract = useMemo(() => (doc.data?.interfaces ?? []).filter((i) => i.implements), [doc.data]);

  const err = detail.error || doc.error || graph.error;
  if (err) {
    return (
      <div className="p-4">
        <ErrorBox
          error={err}
          onRetry={() => {
            detail.reload();
            doc.reload();
            graph.reload();
          }}
        />
        <p className="mt-2 text-[12px] text-faint">
          The refinement is stored as the linked ontology <span className="font-mono">{id}</span>
          {ref.revision ? ` at ${ref.revision}` : ""}; it has to be in the store to zoom in.
        </p>
      </div>
    );
  }
  if (!doc.data || !graph.data || !rev) return <Spinner label={`Loading ${id}`} />;
  const node = selected ? graph.data.nodes.find((n) => n.id === selected) : undefined;
  const d = doc.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-soft px-4 py-1.5">
        <h2 className="text-[14px] font-semibold text-ink">{d.name || id}</h2>
        <Badge tone="accent">level {d.level || "system"}</Badge>
        <span className="text-[12px] text-faint">
          refines <span className="font-mono text-muted">{frame.from}</span> ·{" "}
          <span className="font-mono text-muted">{frame.component}</span> · rev <span className="font-mono text-muted">{rev === "draft" || rev === "latest" ? rev : `r${rev}`}</span>
        </span>
        {d.refines && (d.refines.ontology !== frame.from || d.refines.component !== frame.component) && (
          <Badge tone="warn" title="The child's refines doesn't name this component">
            refines {d.refines.ontology}.{d.refines.component}
          </Badge>
        )}
        <div className="ml-auto flex items-center gap-3">
          <MapLegend scale={scale} colorBy="layer" compact />
          <Link href={ontologyHref(id, rev)} className="rounded border border-line px-1.5 py-0.5 text-[12px] text-link hover:bg-panel-2">
            Open as its own workspace →
          </Link>
        </div>
      </div>
      {contract.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-line-soft px-4 py-1 text-[11.5px]" aria-label="Contract">
          <span className="text-faint">contract</span>
          {contract.map((i) => (
            <span key={ifaceId(i)} className="inline-flex items-center gap-1 rounded border border-line-soft bg-panel-2/60 px-1.5 py-0.5 font-mono">
              <span className="text-ink">{ifaceId(i)}</span>
              <span className="text-violet">⇡ {i.implements}</span>
            </span>
          ))}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <div className={cx("relative m-2 min-w-0 flex-1 overflow-hidden rounded-lg border-2 border-[#4d6b1f]")}>
          <ArchitectureMap
            graph={graph.data}
            colorBy="layer"
            selected={selected}
            onSelect={setSelected}
            focus={node?.id ?? null}
            collapsible
            refined={refined}
            onZoom={(cid) => onZoom(d, id, cid)}
            ariaLabel={`Architecture map of ${d.name || id}, the refinement of ${frame.componentName}`}
          />
        </div>
        {node && (
          <aside aria-label={`Component ${node.name}`} className="w-[min(440px,40vw)] shrink-0 border-l border-line bg-panel">
            <ComponentPanel
              doc={d}
              graph={graph.data}
              componentId={node.id}
              color={scale.color(node.layer)}
              onSelect={setSelected}
              onSelectInterface={(iid) => setSelected(ifaceComponent(iid))}
              onClose={() => setSelected(null)}
              onZoom={(cid) => onZoom(d, id, cid)}
              ontologyHref={(o, r) => ontologyHref(o, r)}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
