"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Document, JsonObject, JsonValue } from "@/lib/api/types";
import { componentName, isPlainObject, jsonEqual, jsonInline } from "@/lib/model/format";
import { changedAt, laneComponent, laneInstance, leafChanged, runWrites, snapshotAt, touchedState, type Playback } from "@/lib/sim/playback";
import { cx } from "@/components/ui";

interface Leaf {
  /** Display path; keys may hold dots, so segs is the identity. */
  path: string;
  segs: string[];
  /** A unique React key (JSON of segs). */
  id: string;
  value: JsonValue;
}

function flatten(v: JsonValue, segs: string[], out: Leaf[], depth = 0) {
  if (isPlainObject(v) && Object.keys(v).length > 0 && depth < 4) {
    for (const k of Object.keys(v).sort()) flatten(v[k], [...segs, k], out, depth + 1);
  } else {
    out.push({ path: segs.length ? segs.join(".") : "(root)", segs, id: JSON.stringify(segs), value: v });
  }
}

function getPath(root: JsonValue | undefined, segs: string[]): JsonValue | undefined {
  let cur: JsonValue | undefined = root;
  for (const seg of segs) {
    if (!isPlainObject(cur)) return undefined;
    cur = cur[seg];
  }
  return cur;
}

/** True when one path is a prefix of the other (the leaf is, or is inside, or contains what changed). */
function matches(leaf: string[], changed: string[] | null): boolean {
  if (!changed || changed.length === 0) return false;
  const n = Math.min(leaf.length, changed.length);
  for (let i = 0; i < n; i++) if (leaf[i] !== changed[i]) return false;
  return true;
}

/** How many fields a component shows before "show all". */
const LEAF_CAP = 40;

function LeafRow({ leaf, hot, diff, initial }: { leaf: Leaf; hot: boolean; diff: boolean; initial?: JsonValue }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (hot) ref.current?.scrollIntoView({ block: "nearest" });
  }, [hot]);
  return (
    <div
      ref={ref}
      className={cx(
        "grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] items-baseline gap-2 rounded px-1.5 py-[2px] text-[11.5px]",
        hot ? "bg-[#1c2a10] ring-1 ring-[#6f8f3c]" : "",
      )}
      title={diff ? `initial: ${jsonInline(initial, 200)}` : undefined}
    >
      <span className="flex min-w-0 items-baseline gap-1 font-mono text-[#9fd2ff]">
        <span
          className={cx("inline-block h-1.5 w-1.5 shrink-0 rounded-full", diff ? "bg-accent" : "bg-transparent")}
          role={diff ? "img" : undefined}
          aria-label={diff ? "changed since the start" : undefined}
        />
        <span className="truncate">{leaf.path}</span>
      </span>
      <span className={cx("min-w-0 break-words font-mono", hot ? "font-semibold text-accent" : "text-ink")}>{jsonInline(leaf.value, 80)}</span>
    </div>
  );
}

export function StateLedger({ playback, cursor, doc }: { playback: Playback; cursor: number; doc?: Document }) {
  const snap = snapshotAt(playback, cursor);
  const e = playback.events[cursor];
  const changed = changedAt(e, playback.lanes[cursor]?.at);
  const initial = playback.initial;

  const ctxLeaves: Leaf[] = [];
  flatten(snap.ctx, [], ctxLeaves);
  const ctxEmpty = Object.keys(snap.ctx).length === 0;

  const frame = e?.span ?? 0;
  const vars: JsonObject | undefined = frame ? snap.vars[frame] : undefined;
  const varLeaves: Leaf[] = [];
  if (vars && Object.keys(vars).length) flatten(vars, [], varLeaves);
  const frameSpan = frame ? playback.spans.get(frame) : undefined;

  const touched = useMemo(() => touchedState(playback), [playback]);
  const writes = useMemo(() => runWrites(playback), [playback]);
  const [scope, setScope] = useState<"changed" | "touched">("changed");
  const [showOthers, setShowOthers] = useState(false);
  const [uncapped, setUncapped] = useState<ReadonlySet<string>>(() => new Set());
  const all = Array.from(new Set([...Object.keys(initial.state), ...Object.keys(snap.state)])).sort();
  const changedComps = all.filter((c) => writes.has(c));
  // Only what this run read or wrote; the rest of the ontology's stateful components fold away.
  const comps = scope === "changed" ? changedComps : all.filter((c) => touched.has(c));
  const others = all.filter((c) => !touched.has(c));
  const shown = scope === "touched" && showOthers ? [...comps, ...others] : comps;

  return (
    <div className="space-y-3 p-3">
      <p className="text-[11px] leading-snug text-faint">
        Replayed from the run&apos;s initial state by applying each <span className="font-mono">set</span> up to the cursor.{" "}
        <span className="rounded bg-[#1c2a10] px-1 text-accent ring-1 ring-[#6f8f3c]">Highlighted</span> fields change at this event;{" "}
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" /> marks state that differs from the start.
      </p>

      <section aria-label="ctx">
        <h4 className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
          ctx <span className="font-normal normal-case tracking-normal text-faint">shared by the whole run</span>
        </h4>
        {ctxEmpty ? (
          <div className="px-1.5 text-[11.5px] text-faint">empty</div>
        ) : (
          ctxLeaves.map((l) => <LeafRow key={l.id} leaf={l} hot={changed?.scope === "ctx" && matches(l.segs, changed.segs)} diff={false} />)
        )}
      </section>

      {varLeaves.length > 0 && frameSpan && (
        <section aria-label="vars">
          <h4 className="mb-1 flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
            vars <span className="truncate font-mono font-normal normal-case tracking-normal text-faint">{frameSpan.iface}</span>
          </h4>
          {varLeaves.map((l) => (
            <LeafRow key={l.id} leaf={l} hot={changed?.scope === "vars" && changed.span === frame && matches(l.segs, changed.segs)} diff={false} />
          ))}
        </section>
      )}

      <section aria-label="component state">
        <h4 className="mb-1 flex flex-wrap items-baseline gap-x-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
          component state
          <span className="flex items-center gap-1 font-normal normal-case tracking-normal" role="group" aria-label="Which state to show">
            {([
              ["changed", `changed in this run (${changedComps.length})`],
              ["touched", "everything it read"],
            ] as const).map(([k, label]) => (
              <button key={k} type="button" aria-pressed={scope === k} onClick={() => setScope(k)} className={cx("rounded px-1 py-px text-[11px]", scope === k ? "bg-panel-3 text-ink" : "text-faint hover:text-ink")}>
                {label}
              </button>
            ))}
          </span>
        </h4>
        {all.length === 0 && <div className="px-1.5 text-[11.5px] text-faint">No stateful components.</div>}
        {all.length > 0 && comps.length === 0 && <div className="px-1.5 text-[11.5px] text-faint">{scope === "changed" ? "This run changed no component state." : "This run read or wrote no component state."}</div>}
        <div className="space-y-2">
          {shown.map((c) => {
            const st = snap.state[c] ?? {};
            const init = initial.state[c] ?? {};
            const flat: Leaf[] = [];
            flatten(st, [], flat);
            const written = writes.get(c);
            const hotLeaf = (l: Leaf) => changed?.scope === "state" && changed.component === c && matches(l.segs, changed.segs);
            const inScope = scope === "changed" && written ? flat.filter((l) => hotLeaf(l) || leafChanged(written, l.segs)) : flat;
            // A component can hold thousands of fields: cap them, keeping the one changing now.
            const capped = !uncapped.has(c) && inScope.length > LEAF_CAP;
            const leaves = capped ? inScope.filter((l, i) => i < LEAF_CAP || hotLeaf(l)) : inScope;
            const isCur = e?.component === laneComponent(c) && (!laneInstance(c) || e?.instance === laneInstance(c));
            const anyDiff = !jsonEqual(st, init);
            return (
              <div key={c} className={cx("rounded-md border px-1 py-1", isCur ? "border-[#4d6b1f]" : "border-line-soft")}>
                <div className="flex items-baseline gap-1.5 px-1.5 pb-0.5 text-[12px]">
                  <span className="font-medium text-ink">{componentName(doc, laneComponent(c))}</span>
                  {laneInstance(c) && <span className="font-mono text-[11px] text-[#c8e88a]">@{laneInstance(c)}</span>}
                  <span className="font-mono text-[10.5px] text-faint">{laneComponent(c)}</span>
                  {anyDiff && <span className="ml-auto text-[10.5px] text-accent">changed</span>}
                </div>
                {Object.keys(st).length === 0 && scope === "touched" ? (
                  <div className="px-1.5 text-[11.5px] text-faint">{"{}"}</div>
                ) : (
                  leaves.map((l) => {
                    const iv = getPath(init, l.segs);
                    return (
                      <LeafRow
                        key={l.id}
                        leaf={l}
                        hot={hotLeaf(l)}
                        diff={!jsonEqual(iv, l.value)}
                        initial={iv}
                      />
                    );
                  })
                )}
                {capped && (
                  <button type="button" onClick={() => setUncapped((u) => new Set(u).add(c))} className="px-1.5 py-0.5 text-[11px] text-link hover:underline">
                    and {inScope.length - leaves.length} more
                  </button>
                )}
              </div>
            );
          })}
        </div>
        {scope === "touched" && others.length > 0 && (
          <button
            type="button"
            onClick={() => setShowOthers((v) => !v)}
            aria-expanded={showOthers}
            className="mt-2 flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] text-faint hover:bg-line-soft hover:text-muted"
            title="Stateful components this run never read or wrote"
          >
            <span className="inline-block w-3 text-center">{showOthers ? "▾" : "▸"}</span>
            {showOthers ? "Hide" : ""} {others.length} other component{others.length === 1 ? "" : "s"}
            <span className="text-faint">· untouched by this run</span>
          </button>
        )}
      </section>
    </div>
  );
}
