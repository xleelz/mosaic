"use client";

// What changed between two versions of a model, for any (base, head) pair:
// a summary per area first, then the entities, then the JSON on demand. Revisions
// use it today. Draft and Compare can use it as is: nothing here knows it's
// looking at revisions.

import { useCallback, useMemo, useState } from "react";
import type { Change, Document, Impact } from "@/lib/api/types";
import { docIndex } from "@/lib/model/docindex";
import {
  changeAreaResolver,
  changeName,
  changedFields,
  citationsOnly,
  entityRows,
  kindsLine,
  summarizeDiff,
  type AreaSummary,
  type DiffSummary,
  type EntityRow,
} from "@/lib/model/diffsummary";
import { plural } from "@/lib/model/format";
import { useQuery } from "@/lib/hooks";
import { ChangeView } from "@/components/diff";
import { Button, Empty, ErrorBox, Spinner, cx, inputClass } from "@/components/ui";
import { WindowedList } from "@/components/WindowedList";

/** The scale rule: no view lists more than about 40 boxes. */
const AREA_LIMIT = 40;

function label(rev: string): string {
  return /^\d+$/.test(rev) ? `r${rev}` : rev;
}

function Count({ n, tone }: { n: number; tone: string }) {
  return <td className={cx("tnum px-2 py-1 text-right", n ? tone : "text-faint")}>{n || "·"}</td>;
}

function AreaTable({ summary, selected, onSelect, flowsKnown }: { summary: DiffSummary; selected: string | null; onSelect: (area: string | null) => void; flowsKnown: boolean }) {
  const [all, setAll] = useState(false);
  const shown = all ? summary.areas : summary.areas.slice(0, AREA_LIMIT);
  const anyCitations = summary.citations > 0;
  return (
    <>
      <table className="w-full text-[12.5px]">
        <caption className="sr-only">Changes per area</caption>
        <thead>
          <tr className="text-left text-[11px] text-faint">
            <th scope="col" className="px-2 py-1 font-medium">
              Area
            </th>
            <th scope="col" className="px-2 py-1 text-right font-medium">
              Added
            </th>
            <th scope="col" className="px-2 py-1 text-right font-medium">
              Changed
            </th>
            <th scope="col" className="px-2 py-1 text-right font-medium">
              Removed
            </th>
            {anyCitations && (
              <th scope="col" className="px-2 py-1 text-right font-medium" title="Only the line numbers of citations changed. The model didn't.">
                Citations moved
              </th>
            )}
            <th scope="col" className="px-2 py-1 text-right font-medium" title="Unchanged flows that reach something changed in this area. A flow can count in several areas.">
              Flows affected
            </th>
            <th scope="col" className="px-2 py-1 font-medium">
              <span className="sr-only">Kinds</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((a) => {
            const on = selected === a.area;
            return (
              <tr key={a.area} className={cx("border-t border-line-soft", on && "bg-panel-2")}>
                <th scope="row" className="max-w-[240px] px-2 py-1 text-left font-normal">
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => onSelect(on ? null : a.area)}
                    title={on ? "Show every area's entities" : `Show only ${a.area}'s entities`}
                    className={cx("block max-w-full truncate text-left hover:underline", on ? "font-medium text-accent" : "text-ink")}
                  >
                    {a.area}
                  </button>
                </th>
                <Count n={a.added} tone="text-ok" />
                <Count n={a.changed} tone="text-warn" />
                <Count n={a.removed} tone="text-bad" />
                {anyCitations && <Count n={a.citations} tone="text-muted" />}
                <td className="tnum px-2 py-1 text-right text-ink">{flowsKnown ? a.flowsAffected || <span className="text-faint">·</span> : <span className="text-faint">…</span>}</td>
                <td className="truncate px-2 py-1 text-[11.5px] text-faint">{kindsLine(a.kinds)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {summary.areas.length > shown.length && (
        <button type="button" onClick={() => setAll(true)} className="mt-1 px-2 text-[12px] text-link hover:underline">
          and {summary.areas.length - shown.length} more areas
        </button>
      )}
    </>
  );
}

const rowKey = (r: EntityRow) => r.key;
const rowEstimate = (r: EntityRow) => (r.type === "kind" ? 28 : 36);

function fieldsText(c: Change): string | null {
  if (c.change !== "modified") return null;
  if (citationsOnly(c)) return "citations moved";
  const f = changedFields(c);
  return f.length ? (f.length > 4 ? `${f.slice(0, 4).join(", ")}, and ${f.length - 4} more` : f.join(", ")) : null;
}

function EntityList({ changes, area }: { changes: Change[]; area: AreaSummary | null }) {
  const [query, setQuery] = useState("");
  const [hideCitations, setHideCitations] = useState(true);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo(() => entityRows(changes, { area, query, hideCitations }), [changes, area, query, hideCitations]);
  const anyCitations = useMemo(() => (area ? area.changes : changes).some(citationsOnly), [area, changes]);
  const toggle = useCallback((key: string) => {
    setOpen((o) => {
      const next = new Set(o);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }, []);
  const shown = rows.filter((r) => r.type === "change").length;
  return (
    <section aria-label="Changed entities">
      <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
          {area ? `${area.area}: ` : ""}
          {plural(shown, "entity", "entities")}
        </h3>
        {anyCitations && (
          <label className="flex items-center gap-1.5 text-[11.5px] text-muted">
            <input type="checkbox" checked={hideCitations} onChange={(e) => setHideCitations(e.target.checked)} className="accent-[#ccff78]" />
            Hide moved citations
          </label>
        )}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search entities"
          aria-label="Search changed entities"
          className={cx(inputClass, "ml-auto h-7 w-44 text-[12px]")}
        />
      </div>
      {rows.length === 0 ? (
        <Empty>No changed entity matches.</Empty>
      ) : (
        <WindowedList
          items={rows}
          itemKey={rowKey}
          estimate={rowEstimate}
          label="Changed entities"
          scroll="self"
          className="h-[60vh] overflow-auto rounded-md border border-line-soft"
          render={(r) =>
            r.type === "kind" ? (
              <div className="bg-panel-2/60 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
                {r.kind} · {r.count}
              </div>
            ) : (
              <EntityRowView change={r.change} open={open.has(r.key)} onToggle={() => toggle(r.key)} />
            )
          }
        />
      )}
    </section>
  );
}

function EntityRowView({ change, open, onToggle }: { change: Change; open: boolean; onToggle: () => void }) {
  const name = changeName(change);
  const fields = fieldsText(change);
  return (
    <div className="p-0.5">
      <ChangeView
        as="div"
        c={change}
        open={open}
        onToggle={onToggle}
        detail={
          <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted" title={[name, fields].filter(Boolean).join(" · ")}>
            {name}
            {name && fields ? " · " : ""}
            {fields && <span className="text-faint">{fields}</span>}
          </span>
        }
      />
    </div>
  );
}

export function SemanticDiff({ ontology, base, head }: { ontology: string; base: string; head: string }) {
  const diff = useQuery(`diff:${ontology}:${base}:${head}`, (c) => c.diff(ontology, base, head));
  // Separate, as it's slower: the summary shows first and the flow counts follow.
  const impact = useQuery<Impact>(`impact:${ontology}:${base}:${head}`, (c) => c.impact(ontology, base, head));
  const headDoc = useQuery<Document>(`doc:${ontology}:${head}`, (c) => c.getDocument(ontology, head));
  const [selected, setSelected] = useState<string | null>(null);

  const changes = diff.data?.changes;
  const flows = impact.data?.flows_affected;
  const summary = useMemo(() => {
    if (!changes || !headDoc.data) return null;
    return summarizeDiff(changes, flows ?? [], changeAreaResolver(headDoc.data, docIndex(headDoc.data)));
  }, [changes, flows, headDoc.data]);

  const error = diff.error || headDoc.error;
  if (error)
    return (
      <ErrorBox
        error={error}
        onRetry={() => {
          diff.reload();
          headDoc.reload();
        }}
      />
    );
  if (!summary || !changes) return <Spinner label="Comparing" />;
  const pair = `${label(base)} → ${label(head)}`;
  if (changes.length === 0)
    return <div className="text-[12.5px] text-muted">No changes between {label(base)} and {label(head)}.</div>;

  const area = selected ? (summary.areas.find((a) => a.area === selected) ?? null) : null;
  const static_ = summary.flowsStatic;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[12.5px] text-muted">
        <span className="font-mono text-[12px] text-faint">{pair}</span>
        <span className="tnum">
          <span className="text-ok">{summary.added} added</span>, <span className="text-warn">{summary.changed} changed</span>, <span className="text-bad">{summary.removed} removed</span>
          {summary.citations > 0 ? `, ${summary.citations} with only citations moved` : ""}
        </span>
        <span className="text-faint">·</span>
        {impact.error ? (
          <span className="text-faint" title="The impact request failed, so flows affected aren't known.">
            flows affected unknown{" "}
            <Button size="sm" variant="ghost" onClick={impact.reload}>
              Retry
            </Button>
          </span>
        ) : !flows ? (
          <span className="text-faint">counting flows affected…</span>
        ) : (
          <span
            className="tnum"
            title="Unchanged flows that reach a changed entity. Exercised: a simulated scenario went through it. Could reach: the static call graph allows it, which over-approximates."
          >
            {plural(summary.flowsAffected, "flow")} affected
            {summary.flowsAffected > 0 && (summary.flowsExercised > 0 || static_ > 0) ? ` (${[summary.flowsExercised ? `${summary.flowsExercised} exercised` : "", static_ ? `${static_} could reach, static` : ""].filter(Boolean).join(", ")})` : ""}
          </span>
        )}
      </div>
      <AreaTable summary={summary} selected={selected} onSelect={setSelected} flowsKnown={!!flows} />
      <EntityList key={selected ?? ""} changes={changes} area={area} />
    </div>
  );
}
