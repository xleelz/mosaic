"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { ifaceComponent } from "@/lib/model/format";
import { useDocIndex } from "@/lib/hooks";
import { effectiveWorld, instanceGroups } from "@/lib/model/world";
import { ArchitectureMap, MapLegend, useColorScale, type ColorBy } from "@/components/map/ArchitectureMap";
import { ErrorBox, Label, Select, Spinner, cx } from "@/components/ui";
import { ArchitectureDiff } from "./ArchitectureDiff";
import { ComponentBrowser } from "./ComponentBrowser";
import { ComponentPanel } from "./ComponentPanel";
import { useDocument, useGraph, useWorkspace } from "./Workspace";
import { ZoomView, ontologyHref } from "./ZoomView";

export function ArchitectureTab() {
  const search = useSearchParams();
  if (search.get("commit") || search.get("after")) return <ArchitectureDiff />;
  return <ArchitectureMapTab />;
}

function ArchitectureMapTab() {
  const doc = useDocument();
  const graph = useGraph();
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selected = search.get("c");
  const focusIface = search.get("i");
  const zoom = search.get("zoom");
  const ws = useWorkspace();
  const refined = useMemo(() => new Set((doc.data?.components ?? []).filter((c) => c.refined_by?.length).map((c) => c.id)), [doc.data]);
  const setZoom = useCallback(
    (id: string | null) => {
      const q = new URLSearchParams(search.toString());
      if (id) q.set("zoom", id);
      else q.delete("zoom");
      const qs = q.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router, search],
  );
  const [colorBy, setColorBy] = useState<ColorBy>("layer");
  const [showMember, setShowMember] = useState(false);
  const [showBrowser, setShowBrowser] = useState(true);
  const idx = useDocIndex(doc.data);
  const scale = useColorScale(graph.data, colorBy);
  const fixtureId = search.get("fixture") ?? "";
  const world = useMemo(() => {
    if (!doc.data || !fixtureId || !(doc.data.fixtures ?? []).some((f) => f.id === fixtureId)) return null;
    const w = effectiveWorld(doc.data, [fixtureId]);
    return { topology: w.topology, groups: instanceGroups(doc.data, w.topology) };
  }, [doc.data, fixtureId]);
  const setFixture = useCallback(
    (id: string) => {
      const q = new URLSearchParams(search.toString());
      if (id) q.set("fixture", id);
      else q.delete("fixture");
      const qs = q.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router, search],
  );

  const select = useCallback(
    (id: string | null, iface?: string) => {
      const q = new URLSearchParams(search.toString());
      if (id) q.set("c", id);
      else q.delete("c");
      if (iface) q.set("i", iface);
      else q.delete("i");
      const qs = q.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router, search],
  );

  if (doc.error || graph.error) return <div className="p-4"><ErrorBox error={doc.error || graph.error} onRetry={() => { doc.reload(); graph.reload(); }} /></div>;
  if (!doc.data || !graph.data) return <Spinner label="Loading architecture" />;
  const node = selected ? graph.data.nodes.find((n) => n.id === selected) : undefined;
  if (zoom && refined.has(zoom)) {
    return <ZoomView key={`${ws.id}:${ws.rev}:${zoom}`} doc={doc.data} ontology={ws.id} component={zoom} onClose={() => setZoom(null)} />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line-soft px-4 py-2">
        <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Color components by">
          <Label>Color by</Label>
          {(["layer", "kind"] as const).map((c) => (
            <button
              key={c}
              type="button"
              role="radio"
              aria-checked={colorBy === c}
              onClick={() => setColorBy(c)}
              className={cx(
                "h-7 rounded-md border px-2 text-[12px]",
                colorBy === c ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink",
              )}
            >
              {c}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-[12px] text-muted">
          <input type="checkbox" checked={showMember} onChange={(e) => setShowMember(e.target.checked)} className="accent-[#ccff78]" />
          Show container ↔ member calls
        </label>
        <button
          type="button"
          aria-pressed={showBrowser}
          aria-controls="component-browser"
          onClick={() => setShowBrowser((v) => !v)}
          className={cx(
            "h-7 rounded-md border px-2 text-[12px]",
            showBrowser ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink",
          )}
        >
          ☰ Components · {doc.data.components.length}
        </button>
        {(doc.data.fixtures?.length ?? 0) > 0 && (
          <div className="flex items-center gap-1.5">
            <Label htmlFor="map-fixture">Fixture</Label>
            <Select id="map-fixture" value={fixtureId} onChange={(e) => setFixture(e.target.value)} className="h-7 max-w-[200px] text-[12px]">
              <option value="">none (one instance each)</option>
              {doc.data.fixtures!.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name || f.id}
                </option>
              ))}
            </Select>
            {world && (
              <span className="text-[11.5px] text-faint" title={Object.entries(world.topology).map(([c, i]) => `${c}: ${i.join(", ")}`).join("\n")}>
                {Object.entries(world.topology)
                  .map(([c, i]) => `${c} ×${i.length}`)
                  .join(" · ") || "no topology"}
              </span>
            )}
          </div>
        )}
        <div className="ml-auto">
          <MapLegend scale={scale} colorBy={colorBy} />
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        {showBrowser && idx && (
          <div id="component-browser" className="flex w-[250px] shrink-0 border-r border-line bg-panel/40">
            <ComponentBrowser idx={idx} selected={node?.id ?? null} onSelect={(id) => select(id)} className="w-full" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <ArchitectureMap
            graph={graph.data}
            colorBy={colorBy}
            selected={selected}
            onSelect={(id) => select(id)}
            showMemberEdges={showMember}
            focus={node?.id ?? null}
            collapsible
            instanceGroups={world?.groups}
            refined={refined}
            onZoom={(id) => setZoom(id)}
            ariaLabel={`Architecture map of ${doc.data.name ?? "the ontology"}. Click a component, or pick it in the component list, to inspect it.`}
          />
        </div>
        {node && (
          <aside aria-label={`Component ${node.name}`} className="w-[min(480px,42vw)] shrink-0 border-l border-line bg-panel">
            <ComponentPanel
              doc={doc.data}
              graph={graph.data}
              componentId={node.id}
              focusInterface={focusIface}
              color={scale.color(colorBy === "layer" ? node.layer : node.kind)}
              onSelect={(id) => select(id)}
              onSelectInterface={(iid) => select(ifaceComponent(iid), iid)}
              onClose={() => select(null)}
              onZoom={(id) => setZoom(id)}
              ontologyHref={(o, r) => ontologyHref(o, r)}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
