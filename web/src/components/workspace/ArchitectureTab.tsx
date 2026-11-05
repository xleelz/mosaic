"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ifaceComponent } from "@/lib/model/format";
import { useDocIndex } from "@/lib/hooks";
import { useEvidence } from "@/lib/evidence";
import { ROOT_SCOPE, atlasEligible, buildAtlas, buildView, isActorPlace, parseScope, scopeFor, scopeParams, type AtlasScope } from "@/lib/model/atlas";
import { LENSES, parseLens, type Lens } from "@/lib/model/atlasLens";
import { ancestors } from "@/lib/model/docindex";
import { effectiveWorld, instanceGroups } from "@/lib/model/world";
import { ArchitectureMap, MapLegend, useColorScale, type ColorBy, type MapHighlight } from "@/components/map/ArchitectureMap";
import { AtlasPane } from "@/components/map/AtlasPane";
import { FidelityLegend } from "@/components/trust/marks";
import { ErrorBox, Label, Select, Spinner, cx, inputClass } from "@/components/ui";
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

function ToggleChip({ on, onClick, children, title, role = "radio" }: { on: boolean; onClick: () => void; children: React.ReactNode; title?: string; role?: "radio" | "button" }) {
  return (
    <button
      type="button"
      role={role === "radio" ? "radio" : undefined}
      aria-checked={role === "radio" ? on : undefined}
      aria-pressed={role === "button" ? on : undefined}
      title={title}
      onClick={onClick}
      className={cx("h-7 rounded-md border px-2 text-[12px]", on ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink")}
    >
      {children}
    </button>
  );
}

/** Picks a flow by name. It shows a short list of matches, since a model can hold hundreds. */
function FlowPicker({ flows, value, onChange }: { flows: { id: string; name?: string }[]; value: string | null; onChange: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const current = value ? flows.find((f) => f.id === value) : undefined;
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const found = flows.filter((f) => words.every((w) => `${f.name ?? ""} ${f.id}`.toLowerCase().includes(w)));
  return (
    <div className="relative">
      <input
        type="search"
        value={open ? query : current?.name || current?.id || ""}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onBlur={() => setOpen(false)}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={`Choose one of ${flows.length} flows`}
        aria-label="Flow to highlight"
        className={cx(inputClass, "h-7 w-[240px] text-[12px]")}
      />
      {open && (
        <ul className="absolute left-0 top-8 z-30 max-h-[300px] w-[340px] overflow-y-auto rounded-md border border-line bg-panel py-1 text-[12px] shadow-xl">
          {found.slice(0, 40).map((f) => (
            <li key={f.id}>
              <button
                type="button"
                onMouseDown={(ev) => {
                  ev.preventDefault();
                  onChange(f.id);
                  setOpen(false);
                }}
                className="block w-full truncate px-2 py-1 text-left text-ink hover:bg-panel-2"
                title={f.id}
              >
                {f.name || f.id}
              </button>
            </li>
          ))}
          {found.length > 40 && <li className="px-2 py-1 text-faint">and {found.length - 40} more. Type to narrow.</li>}
          {found.length === 0 && <li className="px-2 py-1 text-faint">No flow matches.</li>}
        </ul>
      )}
    </div>
  );
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
  const landOn = search.get("select");
  const ws = useWorkspace();
  const evidence = useEvidence(ws.id, ws.rev);
  const refined = useMemo(() => new Set((doc.data?.components ?? []).filter((c) => c.refined_by?.length).map((c) => c.id)), [doc.data]);

  const replaceQuery = useCallback(
    (values: Record<string, string | null | undefined>, history: "replace" | "push" = "replace") => {
      const q = new URLSearchParams(search.toString());
      for (const [k, v] of Object.entries(values)) {
        if (v) q.set(k, v);
        else q.delete(k);
      }
      const qs = q.toString();
      const url = `${pathname}${qs ? `?${qs}` : ""}`;
      if (history === "push") router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [pathname, router, search],
  );

  const setZoom = useCallback((id: string | null) => replaceQuery({ zoom: id }), [replaceQuery]);
  const [pickedColor, setPickedColor] = useState<ColorBy>("layer");
  const [showMember, setShowMember] = useState(false);
  const [showBrowser, setShowBrowser] = useState(true);
  const [matching, setMatching] = useState<ReadonlySet<string> | null>(null);
  const idx = useDocIndex(doc.data);
  const hasAreas = (idx?.area.size ?? 0) > 0;
  const colorBy: ColorBy = hasAreas ? "area" : pickedColor;
  const scale = useColorScale(graph.data, colorBy, idx?.area);
  const fixtureId = search.get("fixture") ?? "";
  const world = useMemo(() => {
    if (!doc.data || !fixtureId || !(doc.data.fixtures ?? []).some((f) => f.id === fixtureId)) return null;
    const w = effectiveWorld(doc.data, [fixtureId]);
    return { topology: w.topology, groups: instanceGroups(doc.data, w.topology) };
  }, [doc.data, fixtureId]);
  const setFixture = useCallback((id: string) => replaceQuery({ fixture: id }), [replaceQuery]);

  // The Atlas: large models with areas open on it. Everything else keeps the compound map.
  const eligible = !!idx && atlasEligible(idx);
  const model = useMemo(() => (eligible && doc.data && graph.data && idx ? buildAtlas(doc.data, graph.data, idx) : null), [eligible, doc.data, graph.data, idx]);
  const everything = search.get("view") === "everything";
  const atlas = model && !everything ? model : null;

  const areaParam = search.get("area");
  const inParam = search.get("in");
  const roleParam = search.get("role");
  const restParam = search.get("rest");
  const scope: AtlasScope = useMemo(() => {
    if (!atlas) return ROOT_SCOPE;
    if (!areaParam && selected && atlas.nodes.has(selected)) return scopeFor(atlas, selected);
    return parseScope(atlas, { area: areaParam, in: inParam, role: roleParam, rest: restParam });
  }, [atlas, areaParam, inParam, roleParam, restParam, selected]);

  const lens: Lens = parseLens(search.get("lens"));
  const flowId = search.get("flow");
  const allConnections = search.get("connections") === "all";

  const navigate = useCallback(
    (next: AtlasScope, select?: string | null) => {
      const values: Record<string, string | null | undefined> = { ...scopeParams(next) };
      if (select !== undefined) {
        values.c = select;
        values.i = null;
      }
      replaceQuery(values, "push");
    },
    [replaceQuery],
  );

  /** A selection from the list, a panel or a palette goes to wherever the component is drawn. */
  const select = useCallback(
    (id: string | null, iface?: string) => {
      const values: Record<string, string | null | undefined> = { c: id, i: iface ?? null };
      let moved = false;
      if (atlas) {
        // Stay in this view when it draws the component. Closing a selection stays put too.
        moved = !!id && atlas.nodes.has(id) && !buildView(atlas, scope, { pin: [id] }).boxes.some((b) => b.component === id);
        Object.assign(values, scopeParams(moved ? scopeFor(atlas, id!) : scope));
      }
      replaceQuery(values, moved ? "push" : "replace");
    },
    [atlas, scope, replaceQuery],
  );

  // ?select=<component>: how the palette and other tabs land on a component.
  useEffect(() => {
    if (!landOn || !graph.data || !doc.data) return;
    const known = graph.data.nodes.some((n) => n.id === landOn);
    const values: Record<string, string | null | undefined> = { select: null };
    if (known) {
      values.c = landOn;
      values.i = null;
      if (atlas) Object.assign(values, scopeParams(scopeFor(atlas, landOn)));
    }
    replaceQuery(values);
  }, [landOn, graph.data, doc.data, atlas, replaceQuery]);

  // Esc closes the side panel, unless something on top of it (a dialog, the code viewer) or a text
  // field has the key: those mark it handled, or own it.
  useEffect(() => {
    if (!selected) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape" || ev.defaultPrevented) return;
      const el = ev.target as HTMLElement | null;
      if (el?.closest?.("input, textarea, select, [contenteditable=true], [role=dialog], .cm-editor")) return;
      if (document.querySelector("[role=dialog]")) return;
      select(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, select]);

  // The compound map has no area view, so ?area= and the list's filter dim what's outside them.
  const compoundArea = !atlas && areaParam && idx && Array.from(idx.area.values()).includes(areaParam) ? areaParam : null;
  const highlight: MapHighlight | undefined = useMemo(() => {
    if ((!matching && !compoundArea) || !idx) return undefined;
    const ids = matching ?? Array.from(idx.area, ([id, a]) => (a === compoundArea ? id : "")).filter(Boolean);
    const involved = new Set<string>();
    for (const id of ids) {
      if (matching && compoundArea && idx.area.get(id) !== compoundArea) continue;
      involved.add(id);
      for (const a of ancestors(idx, id)) involved.add(a);
    }
    return { involved };
  }, [matching, compoundArea, idx]);

  if (doc.error || graph.error) return <div className="p-4"><ErrorBox error={doc.error || graph.error} onRetry={() => { doc.reload(); graph.reload(); }} /></div>;
  if (!doc.data || !graph.data || !idx) return <Spinner label="Loading the map" />;
  const node = selected ? graph.data.nodes.find((n) => n.id === selected) : undefined;
  if (zoom && refined.has(zoom)) {
    return <ZoomView key={`${ws.id}:${ws.rev}:${zoom}`} doc={doc.data} ontology={ws.id} component={zoom} onClose={() => setZoom(null)} />;
  }

  const lensMeaning = LENSES.find((l) => l.value === lens)!.meaning;
  const hasMechanisms = (evidence.evidence?.mechanisms?.items.length ?? 0) > 0;
  const panelColor = node
    ? atlas
      ? atlas.areaByKey.get(atlas.placeOf.get(node.id) ?? "")?.color ?? "#5f6d78"
      : scale.color(colorBy === "area" ? idx.area.get(node.id) : colorBy === "layer" ? node.layer : node.kind)
    : "";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line-soft px-4 py-2">
        {model && (
          <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Map view">
            <ToggleChip on={!everything} onClick={() => replaceQuery({ view: null })}>Areas</ToggleChip>
            <ToggleChip on={everything} title="Every component on one map" onClick={() => replaceQuery({ view: "everything" })}>Everything</ToggleChip>
          </div>
        )}
        {atlas && (
          <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Lens">
            <Label>Lens</Label>
            {LENSES.map((l) => (
              <ToggleChip key={l.value} on={lens === l.value} title={l.meaning} onClick={() => replaceQuery({ lens: l.value === "area" ? null : l.value })}>
                {l.label}
              </ToggleChip>
            ))}
          </div>
        )}
        {atlas && lens === "flow" && <FlowPicker flows={doc.data.flows ?? []} value={flowId} onChange={(id) => replaceQuery({ flow: id })} />}
        {atlas && (
          <ToggleChip role="button" on={allConnections} title="Draw every connection, not only the strong ones" onClick={() => replaceQuery({ connections: allConnections ? null : "all" })}>
            All connections
          </ToggleChip>
        )}
        {!atlas && !hasAreas && (
          <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Color components by">
            <Label>Color by</Label>
            {(["layer", "kind"] as const).map((c) => (
              <ToggleChip key={c} on={colorBy === c} onClick={() => setPickedColor(c)}>
                {c}
              </ToggleChip>
            ))}
          </div>
        )}
        {!atlas && (
          <label className="flex items-center gap-1.5 text-[12px] text-muted">
            <input type="checkbox" checked={showMember} onChange={(e) => setShowMember(e.target.checked)} className="accent-[#ccff78]" />
            Show container ↔ member calls
          </label>
        )}
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
        {!atlas && (doc.data.fixtures?.length ?? 0) > 0 && (
          <div className="flex items-center gap-1.5">
            <Label htmlFor="map-fixture">World setup (fixture)</Label>
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
          {atlas ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
              <span>{lensMeaning}</span>
              {hasMechanisms && lens === "area" && <FidelityLegend />}
            </div>
          ) : (
            <MapLegend scale={scale} colorBy={colorBy} />
          )}
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        {showBrowser && (
          <div id="component-browser" className="flex w-[250px] shrink-0 border-r border-line bg-panel/40">
            <ComponentBrowser
              idx={idx}
              selected={node?.id ?? null}
              onSelect={(id) => select(id)}
              className="w-full"
              onMatches={setMatching}
              onArea={atlas ? (area) => navigate({ place: area }) : undefined}
              activeArea={atlas && scope.place && !isActorPlace(scope.place) ? scope.place : compoundArea}
            />
          </div>
        )}
        <div className="min-w-0 flex-1">
          {atlas ? (
            <AtlasPane
              doc={doc.data}
              idx={idx}
              model={atlas}
              scope={scope}
              evidence={evidence.evidence}
              evidenceSettled={evidence.evidence !== undefined || !!evidence.error}
              lens={lens}
              flowId={flowId}
              allConnections={allConnections}
              matching={matching}
              selected={selected}
              onSelect={(id) => select(id)}
              onNavigate={navigate}
            />
          ) : (
            <ArchitectureMap
              graph={graph.data}
              colorBy={colorBy}
              areaOf={hasAreas ? idx.area : undefined}
              selected={selected}
              onSelect={(id) => select(id)}
              showMemberEdges={showMember}
              focus={node?.id ?? null}
              collapsible
              highlight={highlight}
              instanceGroups={world?.groups}
              refined={refined}
              onZoom={(id) => setZoom(id)}
              ariaLabel={`Map of ${doc.data.name ?? "the model"}. Click a component, or pick it in the component list, to inspect it.`}
            />
          )}
        </div>
        {node && (
          <aside aria-label={`Component ${node.name}`} className="w-[min(480px,42vw)] shrink-0 border-l border-line bg-panel">
            <ComponentPanel
              doc={doc.data}
              graph={graph.data}
              componentId={node.id}
              focusInterface={focusIface}
              color={panelColor}
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
