"use client";

// The Atlas: breadcrumb, canvas, and the lists a click opens. State that should survive a reload
// (scope, lens, flow, selection) lives in the URL and is owned by the Map tab.

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import type { Document, Evidence, EvidenceMechanism, Scenario } from "@/lib/api/types";
import { ROOT_SCOPE, buildView, isActorPlace, matchCounts, placeLabel, sameScope, scopeFor, type AtlasBox, type AtlasModel, type AtlasScope, type MoreItem } from "@/lib/model/atlas";
import { faultScenarios, stateWriters } from "@/lib/model/atlasFlows";
import { boxFidelity, dataDecor, dataForBox, failureDecor, faultsForBox, flowDecor, placeMechanisms, type Counts, type Lens, type LensDecor } from "@/lib/model/atlasLens";
import type { DocIndex } from "@/lib/model/docindex";
import { nameOf } from "@/lib/model/docindex";
import { plural } from "@/lib/model/format";
import { FidelityMark, FidelityStrip } from "@/components/trust/marks";
import { countFidelity } from "@/components/trust/fidelity";
import { ProgressiveList, cx } from "@/components/ui";
import { useWorkspace } from "@/components/workspace/Workspace";
import { AtlasMap } from "./AtlasMap";

export interface AtlasPaneProps {
  doc: Document;
  idx: DocIndex;
  model: AtlasModel;
  scope: AtlasScope;
  evidence: Evidence | null | undefined;
  /** The evidence answer is in, or failed: drawing won't reshuffle when it lands. */
  evidenceSettled: boolean;
  lens: Lens;
  flowId: string | null;
  allConnections: boolean;
  /** Components matching the list's filter; null when it isn't filtered. */
  matching: ReadonlySet<string> | null;
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Goes to a scope, optionally selecting a component there. */
  onNavigate: (scope: AtlasScope, select?: string | null) => void;
}

type Drawer =
  | { kind: "more"; title: string; items: MoreItem[] }
  | { kind: "faults"; title: string; items: Scenario[] }
  | { kind: "data"; title: string; box: AtlasBox }
  | { kind: "mechanisms"; title: string; items: EvidenceMechanism[]; note?: string };

export function AtlasPane({ doc, idx, model, scope, evidence, evidenceSettled, lens, flowId, allConnections, matching, selected, onSelect, onNavigate }: AtlasPaneProps) {
  const ws = useWorkspace();
  const [drawer, setDrawer] = useState<Drawer | null>(null);

  const pin = useMemo(() => (selected ? [selected] : []), [selected]);
  const view = useMemo(() => buildView(model, scope, { pin }), [model, scope, pin]);

  const mechanisms = evidence?.mechanisms?.items;
  const placement = useMemo(() => (mechanisms?.length ? placeMechanisms(model, idx, mechanisms) : null), [model, idx, mechanisms]);
  const hasEvidence = !!placement;

  const ghosts = useMemo(() => {
    const out = new Map<string, number>();
    if (placement) for (const [a, m] of placement.byArea) if (m.absent.length) out.set(a, m.absent.length);
    return out;
  }, [placement]);
  const fidelity = useMemo(() => {
    if (!placement || !mechanisms) return undefined;
    const out: Map<string, Counts> = boxFidelity(view, idx, mechanisms);
    // On the opening view an area's strip counts its whole list, gaps included.
    for (const b of view.boxes) {
      if (b.type !== "area" || !b.place) continue;
      const m = placement.byArea.get(b.place);
      if (m) out.set(b.id, m.counts);
      else out.delete(b.id);
    }
    return out;
  }, [placement, mechanisms, view, idx]);

  const faults = useMemo(() => (lens === "failure" ? faultScenarios(doc, idx) : null), [lens, doc, idx]);
  const writers = useMemo(() => {
    if (lens !== "data") return null;
    const stateful = Array.from(model.nodes.values()).filter((n) => n.stateful).map((n) => n.id);
    return stateWriters(stateful, model.calls, idx);
  }, [lens, model, idx]);
  const flow = useMemo(() => (lens === "flow" && flowId ? idx.flowsById.get(flowId) ?? null : null), [lens, flowId, idx]);
  const decor: LensDecor | null = useMemo(() => {
    if (faults) return failureDecor(view, faults);
    if (writers) return dataDecor(view, model, writers);
    if (flow) return flowDecor(view, flow, model.calls, idx);
    return null;
  }, [faults, writers, flow, view, model, idx]);

  const matches = useMemo(() => (matching ? matchCounts(view, matching) : null), [matching, view]);
  const colorOf = useCallback((place: string | undefined) => (place ? model.areaByKey.get(place)?.color : undefined) ?? "#5f6d78", [model]);

  const go = useCallback(
    (next: AtlasScope, select?: string | null) => {
      setDrawer(null);
      onNavigate(next, select);
    },
    [onNavigate],
  );

  const onEnter = useCallback((box: AtlasBox) => box.enter && go(box.enter), [go]);
  const openGhost = useCallback(
    (area: string) => {
      const m = placement?.byArea.get(area);
      if (m) setDrawer({ kind: "mechanisms", title: `${plural(m.absent.length, "mechanism")} not modeled in ${placeLabel(area)}`, items: m.absent });
    },
    [placement],
  );

  const onActivate = useCallback(
    (box: AtlasBox) => {
      if (box.type === "stub") {
        if (box.more) setDrawer({ kind: "more", title: box.label, items: box.more });
        else if (box.enter) go(box.enter);
        else if (box.component) go(scopeFor(model, box.component), box.component);
        return;
      }
      if (box.type === "more") {
        if (box.more) setDrawer({ kind: "more", title: box.label, items: box.more });
        else if (box.enter) go(box.enter);
        return;
      }
      if (faults) {
        setDrawer({ kind: "faults", title: `Fault scenarios on ${box.label}`, items: faultsForBox(box, faults) });
        return;
      }
      if (writers) {
        setDrawer({ kind: "data", title: `State in ${box.label}`, box });
        return;
      }
      if (box.component) {
        setDrawer(null);
        onSelect(box.component);
      } else if (box.enter) go(box.enter);
    },
    [faults, writers, go, model, onSelect],
  );

  const place = scope.place;
  const inArea = !!place && !isActorPlace(place);
  const here = inArea && placement ? placement.byArea.get(place!) : undefined;
  const moreStrays = !scope.place ? model.strays : [];
  const unplacedAbsent = placement ? placement.unplaced.filter((m) => m.fidelity === "absent") : [];
  const measuredOn = evidence?.mechanisms && evidence.mechanisms.measured_on_revision !== evidence.revision ? evidence.mechanisms.measured_on_revision : null;
  const shown = view.edges.filter((e) => e.strong).length;
  const hiddenEdges = view.edges.length - shown;
  const storeKey = `${ws.id}:${ws.dataRev}`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-soft px-3 py-1.5 text-[12px]">
        <nav aria-label="Where you are on the map" className="flex min-w-0 flex-wrap items-center gap-1">
          {view.crumbs.map((c, i) => {
            const last = i === view.crumbs.length - 1;
            return (
              <span key={`${c.label}:${i}`} className="flex items-center gap-1">
                {i > 0 && <span className="text-faint" aria-hidden>›</span>}
                {last ? (
                  <span aria-current="page" className="font-medium text-ink">{c.label}</span>
                ) : (
                  <button type="button" className="text-link hover:underline" onClick={() => go(c.scope, sameScope(c.scope, ROOT_SCOPE) ? null : undefined)}>
                    {c.label}
                  </button>
                )}
              </span>
            );
          })}
        </nav>
        <span className="tnum text-faint">{plural(view.boxes.length, "box", "boxes")}</span>
        {!allConnections && hiddenEdges > 0 && (
          <span className="tnum text-faint" title="The heaviest connections are drawn. Hover a box for the rest of its own, or choose all connections.">
            {shown} of {view.edges.length} connections
          </span>
        )}
        {here && here.absent.length > 0 && (
          <button
            type="button"
            onClick={() => openGhost(place!)}
            className="flex h-6 items-center gap-1.5 rounded border border-dashed border-muted/60 px-2 text-[11.5px] text-muted hover:border-ink hover:text-ink"
          >
            {plural(here.absent.length, "mechanism")} not modeled in {placeLabel(place!)}
            <span aria-hidden>›</span>
          </button>
        )}
        {!place && unplacedAbsent.length > 0 && (
          <button
            type="button"
            onClick={() => setDrawer({ kind: "mechanisms", title: `${plural(unplacedAbsent.length, "mechanism")} not modeled, and not placed on an area`, items: unplacedAbsent })}
            className="flex h-6 items-center gap-1.5 rounded border border-dashed border-muted/60 px-2 text-[11.5px] text-muted hover:border-ink hover:text-ink"
          >
            {plural(unplacedAbsent.length, "mechanism")} not modeled, no area
            <span aria-hidden>›</span>
          </button>
        )}
        {moreStrays.length > 0 && (
          <span className="text-faint" title={moreStrays.map((id) => nameOf(idx, id)).slice(0, 30).join("\n")}>
            {plural(moreStrays.length, "small top-level part")} under &quot;other&quot;
          </span>
        )}
        {hasEvidence && measuredOn !== null && <span className="text-faint">Fidelity measured on r{measuredOn}, not re-measured</span>}
      </div>
      <div className="relative min-h-0 flex-1">
        {evidenceSettled ? (
          <AtlasMap
            view={view}
            storeKey={storeKey}
            colorOf={colorOf}
            lens={lens}
            decor={decor}
            matches={matches}
            selected={selected}
            allConnections={allConnections}
            hasEvidence={hasEvidence}
            fidelity={fidelity}
            ghosts={ghosts}
            onActivate={onActivate}
            onEnter={onEnter}
            onGhost={openGhost}
            onClear={() => {
              setDrawer(null);
              onSelect(null);
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted">Laying out the map…</div>
        )}
        {drawer && (
          <AtlasDrawer
            drawer={drawer}
            model={model}
            idx={idx}
            writers={writers}
            evidenceHref={ws.href("evidence")}
            scenarioHref={(id) => ws.href("simulate", { scenario: id })}
            onClose={() => setDrawer(null)}
            onPick={(item) => {
              if (item.component) go(scopeFor(model, item.component), item.component);
              else if (item.scope) go(item.scope);
            }}
            onSelectComponent={(id) => go(scopeFor(model, id), id)}
          />
        )}
      </div>
    </div>
  );
}

function AtlasDrawer({
  drawer,
  model,
  idx,
  writers,
  evidenceHref,
  scenarioHref,
  onClose,
  onPick,
  onSelectComponent,
}: {
  drawer: Drawer;
  model: AtlasModel;
  idx: DocIndex;
  writers: ReadonlyMap<string, readonly string[]> | null;
  evidenceHref: string;
  scenarioHref: (id: string) => string;
  onClose: () => void;
  onPick: (item: MoreItem) => void;
  onSelectComponent: (id: string) => void;
}) {
  const rows = drawer.kind === "data" ? dataForBox(drawer.box, model, writers ?? new Map()) : [];
  return (
    <aside aria-label={drawer.title} className="absolute left-2 top-2 z-20 flex max-h-[calc(100%-1rem)] w-[min(420px,calc(100%-1rem))] flex-col rounded-lg border border-line bg-panel shadow-xl">
      <div className="flex shrink-0 items-start gap-2 border-b border-line-soft px-3 py-2">
        <h3 className="min-w-0 flex-1 text-[12.5px] font-semibold text-ink">{drawer.title}</h3>
        <button type="button" aria-label="Close" onClick={onClose} className="h-5 w-5 shrink-0 text-faint hover:text-ink">
          ×
        </button>
      </div>
      {drawer.kind === "mechanisms" && (
        <div className="shrink-0 border-b border-line-soft px-3 py-2 text-[11.5px] text-muted">
          <FidelityStrip counts={countFidelity(drawer.items)} className="mb-1.5" />
          Known to exist in the code, and not in this model. Don&apos;t read their absence from the map as absence from the system.{" "}
          <Link href={evidenceHref} className="text-link hover:underline">
            Open Evidence
          </Link>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto py-1 text-[12px]">
        {drawer.kind === "more" && (
          <ProgressiveList
            items={drawer.items}
            step={100}
            render={(item, i) => (
              <li key={`${item.label}:${i}`}>
                <button type="button" onClick={() => onPick(item)} className="flex w-full items-baseline gap-2 px-3 py-1 text-left text-ink hover:bg-panel-2">
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.detail && <span className="shrink-0 text-[10.5px] text-faint">{item.detail}</span>}
                </button>
              </li>
            )}
          />
        )}
        {drawer.kind === "faults" &&
          (drawer.items.length === 0 ? (
            <p className="px-3 py-2 text-muted">No scenario injects a fault here.</p>
          ) : (
            <ProgressiveList
              items={drawer.items}
              step={100}
              render={(s) => (
                <li key={s.id}>
                  <Link href={scenarioHref(s.id)} className="block px-3 py-1 text-ink hover:bg-panel-2">
                    <span className="block truncate">{s.name || s.id}</span>
                    {s.flow && <span className="block truncate text-[10.5px] text-faint">{s.flow}</span>}
                  </Link>
                </li>
              )}
            />
          ))}
        {drawer.kind === "data" &&
          (rows.length === 0 ? (
            <p className="px-3 py-2 text-muted">Nothing here holds state.</p>
          ) : (
            <ProgressiveList
              items={rows}
              step={100}
              render={(r) => (
                <li key={r.component} className="px-3 py-1">
                  <button type="button" onClick={() => onSelectComponent(r.component)} className="block max-w-full truncate text-left text-link hover:underline">
                    {nameOf(idx, r.component)}
                  </button>
                  <span className="block text-[11px] text-faint">
                    {r.writers.length === 0
                      ? "No writer found in behaviors (static)"
                      : `Written by ${r.writers.slice(0, 4).map((w) => nameOf(idx, w)).join(", ")}${r.writers.length > 4 ? ` + ${r.writers.length - 4} more` : ""}`}
                  </span>
                </li>
              )}
            />
          ))}
        {drawer.kind === "mechanisms" && (
          <ProgressiveList
            items={drawer.items}
            step={100}
            render={(m) => (
              <li key={m.id} className={cx("border-b border-line-soft px-3 py-1.5 last:border-0")}>
                <div className="flex items-center gap-1.5">
                  <FidelityMark fidelity={m.fidelity} label={false} title={m.note} />
                  <span className="min-w-0 flex-1 truncate text-ink" title={m.name}>{m.name}</span>
                </div>
                {m.note && <p className="mt-0.5 line-clamp-3 text-[11px] leading-snug text-muted">{m.note}</p>}
                {m.citations[0] && <p className="mt-0.5 truncate font-mono text-[10.5px] text-faint" title={m.citations.join("\n")}>{m.citations[0]}</p>}
              </li>
            )}
          />
        )}
      </div>
    </aside>
  );
}
