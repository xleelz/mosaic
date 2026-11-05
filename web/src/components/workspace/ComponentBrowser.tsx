"use client";

import { useEffect, useMemo, useState } from "react";
import { ancestors, componentRows, descendantCounts, type ComponentGrouping, type DocIndex } from "@/lib/model/docindex";
import { plural } from "@/lib/model/format";
import { ProgressiveList, cx, inputClass } from "@/components/ui";

/** Above this many components, the browser opens with every group collapsed. */
export const BROWSER_COLLAPSE_ABOVE = 50;

/**
 * A collapsible list of components: flat under each area, or a tree, with a
 * filter and member counts. Selecting a row opens its ancestors, so a component
 * picked on the map is always visible here. The map listens: `onMatches` reports
 * what the filter finds, and `onArea` reports an area picked in the list.
 */
export function ComponentBrowser({
  idx,
  selected,
  onSelect,
  className,
  onMatches,
  onArea,
  activeArea,
}: {
  idx: DocIndex;
  selected: string | null;
  onSelect: (id: string) => void;
  className?: string;
  /** The ids the filter matches; null when there's no filter. */
  onMatches?: (ids: ReadonlySet<string> | null) => void;
  /** An area's row was picked: the map should go there. */
  onArea?: (area: string) => void;
  /** The area the map is in, opened and marked here. */
  activeArea?: string | null;
}) {
  const total = idx.componentsById.size;
  const hasAreas = idx.area.size > 0;
  const [grouping, setGrouping] = useState<ComponentGrouping>(hasAreas ? "area" : "tree");
  const [filter, setFilter] = useState("");
  const counts = useMemo(() => descendantCounts(idx), [idx]);
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    if (total > BROWSER_COLLAPSE_ABOVE) return new Set();
    const all = new Set<string>();
    for (const [p, kids] of idx.childrenByParent) if (p && kids.length) all.add(p);
    for (const a of idx.area.values()) all.add(`area:${a}`);
    all.add("area:Other");
    return all;
  });

  // Open the selected component's ancestors (and its area) when the selection changes.
  const [openedFor, setOpenedFor] = useState<string | null>(null);
  if (selected !== openedFor) {
    setOpenedFor(selected);
    if (selected && idx.componentsById.has(selected)) {
      const need = [...ancestors(idx, selected), `area:${idx.area.get(selected) ?? "Other"}`].filter((k) => !expanded.has(k));
      if (need.length) setExpanded(new Set([...expanded, ...need]));
    }
  }

  // Follow the map into an area.
  const [openedArea, setOpenedArea] = useState<string | null>(null);
  if ((activeArea ?? null) !== openedArea) {
    setOpenedArea(activeArea ?? null);
    if (activeArea && !expanded.has(`area:${activeArea}`)) setExpanded(new Set([...expanded, `area:${activeArea}`]));
  }

  const rows = useMemo(() => componentRows(idx, grouping, expanded, filter, counts), [idx, grouping, expanded, filter, counts]);
  const filtering = filter.trim().length > 0;
  const matchIds = useMemo(() => (filtering ? new Set(rows.flatMap((r) => (r.match && r.id ? [r.id] : []))) : null), [filtering, rows]);
  useEffect(() => onMatches?.(matchIds), [matchIds, onMatches]);
  const selectedIndex = selected ? rows.findIndex((r) => r.id === selected) : -1;
  const toggle = (key: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  const groupKeys = () => (grouping === "area" ? rows.filter((r) => r.id === null).map((r) => r.key) : Array.from(idx.childrenByParent.keys()).filter(Boolean));
  const matches = filter.trim() ? rows.filter((r) => r.match && r.id).length : total;

  return (
    <nav aria-label="Components" className={cx("flex min-h-0 flex-col", className)}>
      <div className="space-y-1.5 border-b border-line-soft p-2">
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${total} components`}
          aria-label="Filter components"
          className={cx(inputClass, "h-7 w-full text-[12px]")}
        />
        <div className="flex items-center gap-1 text-[11.5px]">
          {hasAreas &&
            (["tree", "area"] as const).map((g) => (
              <button
                key={g}
                type="button"
                aria-pressed={grouping === g}
                onClick={() => setGrouping(g)}
                className={cx("h-6 rounded border px-1.5", grouping === g ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink")}
              >
                {g}
              </button>
            ))}
          <span className="ml-auto flex gap-1.5">
            <button type="button" className="text-link hover:underline" onClick={() => setExpanded(new Set([...expanded, ...groupKeys()]))}>
              expand
            </button>
            <button type="button" className="text-link hover:underline" onClick={() => setExpanded(new Set())}>
              collapse
            </button>
          </span>
        </div>
        {filter.trim() && <div className="text-[11px] text-faint">{plural(matches, "match", "matches")}</div>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        <ProgressiveList
          key={`${grouping}:${filter}`}
          items={rows}
          step={200}
          ensure={selectedIndex}
          className="text-[12.5px]"
          render={(r) => (
            <li key={r.key} className="flex items-center" style={{ paddingLeft: 4 + r.depth * 12 }}>
              {r.expandable ? (
                <button
                  type="button"
                  onClick={() => toggle(r.key)}
                  aria-expanded={r.expanded}
                  aria-label={`${r.expanded ? "Collapse" : "Expand"} ${r.label}`}
                  className="h-6 w-5 shrink-0 text-faint hover:text-ink"
                >
                  {r.expanded ? "▾" : "▸"}
                </button>
              ) : (
                <span className="w-5 shrink-0" aria-hidden />
              )}
              {r.id ? (
                <button
                  type="button"
                  onClick={() => onSelect(r.id!)}
                  aria-current={r.id === selected ? "true" : undefined}
                  title={r.id}
                  className={cx(
                    "flex min-w-0 flex-1 items-baseline gap-1.5 rounded px-1 py-0.5 text-left",
                    r.id === selected ? "bg-[#1c2a10] text-accent" : r.match ? "text-ink hover:bg-panel-2" : "text-faint hover:bg-panel-2",
                  )}
                >
                  <span className="truncate">{r.label}</span>
                  {r.count > 0 && <span className="tnum ml-auto shrink-0 pr-1 text-[10.5px] text-faint">{r.count}</span>}
                </button>
              ) : (
                <button
                  type="button"
                  aria-current={activeArea && r.key === `area:${activeArea}` ? "true" : undefined}
                  title={onArea ? `Go to ${r.label} on the map` : undefined}
                  onClick={() => (onArea ? onArea(r.label) : toggle(r.key))}
                  className={cx("flex min-w-0 flex-1 items-baseline gap-1.5 px-1 py-0.5 text-left font-medium hover:text-ink", activeArea && r.key === `area:${activeArea}` ? "text-accent" : "text-muted")}
                >
                  <span className="truncate">{r.label}</span>
                  <span className="tnum ml-auto shrink-0 pr-1 text-[10.5px] text-faint">{r.count}</span>
                </button>
              )}
            </li>
          )}
        />
      </div>
    </nav>
  );
}
