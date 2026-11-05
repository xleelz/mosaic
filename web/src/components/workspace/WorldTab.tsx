"use client";

// The World tab: configs by area, and world setups (fixtures). A model can hold
// hundreds of configs, and a fixture's state thousands of JSON tokens, so both
// lists are windowed, areas and setups start closed, and JSON renders on demand.
// ?config=<id> and ?fixture=<id> open and scroll to one, for the command palette.

import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import type { Config, Document, Fixture, JsonValue, Topology } from "@/lib/api/types";
import { SHARED, configArea } from "@/lib/model/areas";
import { componentName, jsonEqual, jsonInline, plural } from "@/lib/model/format";
import { effectiveWorld, fixtureChain } from "@/lib/model/world";
import { configRows, type ConfigItem, type ConfigRow } from "@/lib/model/worldrows";
import { useDocIndex } from "@/lib/hooks";
import { ClaimScope } from "@/components/code/context";
import { JsonView } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, Panel, SourceRef, Spinner, cx, inputClass } from "@/components/ui";
import { WindowedList } from "@/components/WindowedList";
import { useDocument } from "./Workspace";

/** Past this many configs, areas start closed so the panel opens on an overview. */
const OPEN_ALL_UNDER = 40;
/** A config's deployed value differs from its code default (both present). */
export function configDiffers(c: Config): boolean {
  return c.value !== undefined && c.default !== undefined && !jsonEqual(c.value, c.default);
}

function Value({ label, v }: { label: string; v: JsonValue | undefined }) {
  return (
    <>
      <span className="sr-only">{label}: </span>
      {v === undefined ? <span className="text-faint">—</span> : <span className="break-all font-mono text-[11.5px] text-ink">{jsonInline(v, 48)}</span>}
    </>
  );
}

const COLUMNS = "grid grid-cols-[minmax(0,1fr)_minmax(64px,120px)_minmax(64px,120px)]";

const rowKey = (r: ConfigRow) => r.key;
// A config's height mostly follows whether it has a paragraph of summary.
const rowEstimate = (r: ConfigRow) => (r.type === "group" ? 32 : r.item.config.summary ? 76 : 44);

const TARGET = "bg-[#121b0d] outline outline-1 -outline-offset-1 outline-[#4d6b1f]";

function ConfigRowView({ item, target }: { item: ConfigItem; target: boolean }) {
  const { config: c, differs } = item;
  return (
    <div aria-current={target ? "true" : undefined} className={cx(COLUMNS, "border-t border-line-soft text-[12.5px]", target && TARGET)}>
      <div className="min-w-0 px-3 py-1.5">
        <div className="flex flex-wrap items-baseline gap-1.5">
          <span className="font-mono text-[12px] text-ink">{c.id}</span>
          {c.type && <span className="text-[11px] text-faint">{c.type}</span>}
          {differs && (
            <Badge tone="warn" title="The deployed value differs from the code default">
              differs
            </Badge>
          )}
          {c.tags?.map((t) => (
            <Badge key={t}>{t}</Badge>
          ))}
        </div>
        {c.summary && (
          <div className="line-clamp-2 text-[12px] text-muted" title={c.summary}>
            {c.summary}
          </div>
        )}
        {c.sources?.length ? (
          <ClaimScope claim={c.summary || c.id}>
            <div className="flex flex-wrap gap-x-2">
              {c.sources.map((s, i) => (
                <SourceRef key={i} source={s} />
              ))}
            </div>
          </ClaimScope>
        ) : null}
      </div>
      <div className={cx("px-3 py-1.5", differs && "bg-[#2a2213]/40")}>
        <Value label="Deployed" v={c.value} />
      </div>
      <div className="px-3 py-1.5">
        <Value label="Default" v={c.default} />
      </div>
    </div>
  );
}

/** Remounted (by key) when `target` changes, so a deep link starts from a clean search. */
function ConfigsPanel({ doc, target }: { doc: Document; target: string | null }) {
  const idx = useDocIndex(doc);
  const [query, setQuery] = useState("");
  const [differsOnly, setDiffersOnly] = useState(false);
  const [byArea, setByArea] = useState(true);
  const items = useMemo<ConfigItem[]>(() => (doc.configs ?? []).map((config) => ({ config, area: configArea(doc, idx, config), differs: configDiffers(config) })), [doc, idx]);
  const allAreas = useMemo(() => Array.from(new Set(items.map((it) => it.area))), [items]);
  const targetItem = target ? items.find((it) => it.config.id === target) : undefined;
  const [opened, setOpened] = useState<ReadonlySet<string> | null>(() => (targetItem && items.length > OPEN_ALL_UNDER ? new Set([targetItem.area]) : null));
  const open = useMemo(() => opened ?? new Set(items.length <= OPEN_ALL_UNDER ? allAreas : []), [opened, items.length, allAreas]);
  const groupable = allAreas.length > 1;
  const { rows, matches } = useMemo(
    () => configRows(items, { query, differsOnly, groupByArea: byArea && groupable, open, last: SHARED }),
    [items, query, differsOnly, byArea, groupable, open],
  );
  const differing = useMemo(() => items.filter((it) => it.differs).length, [items]);
  const toggle = (area: string) => {
    const next = new Set(open);
    if (!next.delete(area)) next.add(area);
    setOpened(next);
  };
  const allOpen = allAreas.every((a) => open.has(a));
  const filtered = !!query.trim() || differsOnly;
  return (
    <Panel
      title={filtered ? `Configs · ${matches} of ${items.length}` : `Configs · ${items.length}`}
      className="h-[75vh] xl:h-full"
      bodyClassName="flex min-h-0 flex-col p-0"
      actions={
        items.length > 0 && (
          <>
            {differing > 0 && (
              <label className="flex items-center gap-1.5 whitespace-nowrap text-[11.5px] text-muted">
                <input type="checkbox" checked={differsOnly} onChange={(e) => setDiffersOnly(e.target.checked)} className="accent-[#ccff78]" />
                Differs only ({differing})
              </label>
            )}
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search configs"
              aria-label="Search configs by name, summary, type or file"
              className={cx(inputClass, "h-7 w-40 text-[12px]")}
            />
          </>
        )
      }
    >
      {items.length === 0 ? (
        <div className="p-3">
          <Empty>The model has no configs.</Empty>
        </div>
      ) : (
        <>
          {groupable && (
            <div className="flex shrink-0 items-center gap-2 border-b border-line-soft px-3 py-1 text-[11.5px] text-muted">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={byArea} onChange={(e) => setByArea(e.target.checked)} className="accent-[#ccff78]" />
                Group by area
              </label>
              {byArea && !query.trim() && (
                <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setOpened(new Set(allOpen ? [] : allAreas))}>
                  {allOpen ? "Close all" : "Open all"}
                </Button>
              )}
            </div>
          )}
          {target && !targetItem && <div className="shrink-0 border-b border-line-soft px-3 py-1 text-[12px] text-muted">This revision has no config {target}.</div>}
          <div aria-hidden className={cx(COLUMNS, "shrink-0 bg-panel-2 text-left text-[11px] font-semibold uppercase tracking-[0.06em] text-faint")}>
            <div className="px-3 py-1.5">Config</div>
            <div className="px-3 py-1.5">Deployed</div>
            <div className="px-3 py-1.5">Default</div>
          </div>
          {matches === 0 ? (
            <div className="p-3 text-center text-muted">No config matches.</div>
          ) : (
            <WindowedList
              items={rows}
              itemKey={rowKey}
              estimate={rowEstimate}
              label="Configs"
              scrollToKey={targetItem ? target! : undefined}
              scroll="self"
              className="min-h-0 flex-1 overflow-auto"
              render={(r) =>
                r.type === "group" ? (
                  <button
                    type="button"
                    onClick={() => toggle(r.area)}
                    aria-expanded={r.open}
                    disabled={!!query.trim()}
                    className="flex w-full items-center gap-2 border-t border-line-soft bg-panel-2/60 px-3 py-1.5 text-left text-[12.5px] hover:bg-panel-2 disabled:hover:bg-panel-2/60"
                  >
                    <span className="text-faint" aria-hidden>
                      {r.open ? "▾" : "▸"}
                    </span>
                    <span className="min-w-0 truncate font-medium text-ink">{r.area}</span>
                    <span className="tnum text-[11.5px] text-faint">{r.count}</span>
                    {r.differing > 0 && <span className="tnum text-[11px] text-warn">{r.differing} differ{r.differing === 1 ? "s" : ""}</span>}
                  </button>
                ) : (
                  <ConfigRowView item={r.item} target={r.item === targetItem} />
                )
              }
            />
          )}
        </>
      )}
    </Panel>
  );
}

function TopologyTable({ doc, topology }: { doc: Document; topology: Topology }) {
  const entries = Object.entries(topology).sort(([a], [b]) => a.localeCompare(b));
  if (!entries.length) return <div className="text-[12px] text-faint">none</div>;
  return (
    <table className="text-[12px]">
      <tbody>
        {entries.map(([c, insts]) => (
          <tr key={c}>
            <td className="py-0.5 pr-3 text-ink">
              {componentName(doc, c)} <span className="font-mono text-[11px] text-faint">{c}</span>
            </td>
            <td className="py-0.5 font-mono text-[11.5px] text-accent">{(insts ?? []).join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-0.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-faint">{title}</h4>
      {children}
    </div>
  );
}

/** JSON behind a click. Small values get token colors; a big one is a single block of text. */
function JsonOnDemand({ value }: { value: JsonValue }) {
  const [open, setOpen] = useState(false);
  const text = useMemo(() => (open ? JSON.stringify(value, null, 2) : ""), [open, value]);
  const keys = value && typeof value === "object" ? Object.keys(value).length : 0;
  return (
    <div>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="text-[12px] text-link hover:underline">
        {open ? "▾ Hide JSON" : `▸ Show JSON · ${plural(keys, "key")}`}
      </button>
      {open &&
        (text.length <= 4096 ? (
          <JsonView value={value} maxHeight={180} className="mt-1" />
        ) : (
          <pre tabIndex={0} aria-label="JSON" style={{ maxHeight: 180 }} className="mt-1 overflow-auto rounded-md border border-line-soft bg-[#0c1116] px-2.5 py-2 font-mono text-[11.5px] leading-[1.5] text-muted">
            {text}
          </pre>
        ))}
    </div>
  );
}

function WorldFields({ doc, topology, clock, config, state }: { doc: Document; topology: Topology; clock: Fixture["clock"]; config: Fixture["config"]; state: JsonValue | undefined }) {
  const hasConfig = !!config && Object.keys(config).length > 0;
  const hasState = !!state && typeof state === "object" && Object.keys(state).length > 0;
  const hasTopology = Object.keys(topology).length > 0;
  if (!hasTopology && !clock && !hasConfig && !hasState) return <div className="mt-1.5 text-[12px] text-faint">This setup sets nothing itself.</div>;
  return (
    <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
      {hasTopology && (
        <Section title="Topology">
          <TopologyTable doc={doc} topology={topology} />
        </Section>
      )}
      {clock && (
        <Section title="Clock">
          <span className="font-mono text-[11.5px] text-ink">{clock.epoch ?? `epoch_ms ${clock.epoch_ms ?? 0}`}</span>
        </Section>
      )}
      {hasConfig && (
        <Section title="Config">
          <ul className="space-y-0.5">
            {Object.entries(config!).map(([k, v]) => (
              <li key={k} className="font-mono text-[11.5px]">
                <span className="text-ink">{k}</span> <span className="text-faint">=</span> <span className="break-all text-accent">{jsonInline(v, 48)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {hasState && (
        <Section title="State">
          <JsonOnDemand value={state!} />
        </Section>
      )}
    </div>
  );
}

function EffectiveWorld({ doc, id }: { doc: Document; id: string }) {
  const eff = useMemo(() => effectiveWorld(doc, [id]), [doc, id]);
  return <WorldFields doc={doc} topology={eff.topology} clock={eff.clock} config={eff.config} state={eff.state as unknown as JsonValue} />;
}

function FixtureCard({ doc, f, open, target, onToggle }: { doc: Document; f: Fixture; open: boolean; target: boolean; onToggle: () => void }) {
  const chain = useMemo(() => fixtureChain(doc, [f.id]), [doc, f.id]);
  const [showEffective, setShowEffective] = useState(false);
  const inherits = chain.order.length > 1;
  return (
    <div aria-current={target ? "true" : undefined} className={cx("border-t border-line-soft px-3 py-2", target && TARGET)}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full flex-wrap items-baseline gap-2 text-left">
        <span className="text-faint" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
        <span className="font-medium text-ink">{f.name || f.id}</span>
        {f.name && f.name !== f.id && <span className="font-mono text-[11px] text-faint">{f.id}</span>}
        {inherits && <span className="text-[11px] text-faint">extends {plural(chain.order.length - 1, "setup")}</span>}
        {chain.cycles.length > 0 && <Badge tone="bad">cycle: {chain.cycles.join(", ")}</Badge>}
        {chain.missing.length > 0 && <Badge tone="bad">unknown: {chain.missing.join(", ")}</Badge>}
      </button>
      {f.summary && <div className={cx("pl-4 text-[12.5px] text-muted", !open && "line-clamp-1")}>{f.summary}</div>}
      {open && (
        <div className="pl-4">
          {inherits && (
            <div className="mt-1 flex flex-wrap items-center gap-1 text-[12px]">
              <span className="text-faint">applies</span>
              {chain.order.map((id, i) => (
                <span key={id} className="flex items-center gap-1">
                  {i > 0 && <span className="text-faint">→</span>}
                  <span className={cx("font-mono text-[11.5px]", id === f.id ? "text-ink" : "text-violet")}>{id}</span>
                </span>
              ))}
            </div>
          )}
          <WorldFields doc={doc} topology={f.topology ?? {}} clock={f.clock} config={f.config} state={f.state as unknown as JsonValue} />
          {inherits && (
            <div className="mt-2">
              <button type="button" onClick={() => setShowEffective((v) => !v)} aria-expanded={showEffective} className="text-[12px] text-link hover:underline">
                {showEffective ? "▾" : "▸"} Effective world (extends applied)
              </button>
              {showEffective && <EffectiveWorld doc={doc} id={f.id} />}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const fixtureKey = (f: Fixture) => f.id;
const fixtureEstimate = (f: Fixture) => (f.summary ? 58 : 38);

/** Remounted (by key) when `target` changes, like ConfigsPanel. */
function FixturesPanel({ doc, target }: { doc: Document; target: string | null }) {
  const all = doc.fixtures;
  const known = !!target && !!all?.some((f) => f.id === target);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set(known ? [target] : []));
  const list = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return (all ?? []).filter((f) => {
      const hay = `${f.id} ${f.name ?? ""} ${f.summary ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [all, query]);
  const count = all?.length ?? 0;
  return (
    <Panel
      title={query.trim() ? `World setups (fixtures) · ${list.length} of ${count}` : `World setups (fixtures) · ${count}`}
      className="h-[75vh] xl:h-full"
      bodyClassName="flex min-h-0 flex-col p-0"
      actions={
        count > 8 && (
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search setups"
            aria-label="Search world setups"
            className={cx(inputClass, "h-7 w-40 text-[12px]")}
          />
        )
      }
    >
      {count === 0 ? (
        <div className="p-3">
          <Empty>The model has no world setups.</Empty>
        </div>
      ) : list.length === 0 ? (
        <div className="p-3 text-center text-muted">No setup matches.</div>
      ) : (
        <>
        {target && !known && <div className="shrink-0 border-b border-line-soft px-3 py-1 text-[12px] text-muted">This revision has no world setup {target}.</div>}
        <WindowedList
          items={list}
          itemKey={fixtureKey}
          estimate={fixtureEstimate}
          label="World setups"
          scrollToKey={known ? target! : undefined}
          scroll="self"
          className="min-h-0 flex-1 overflow-auto"
          render={(f) => (
            <FixtureCard
              doc={doc}
              f={f}
              open={open.has(f.id)}
              target={f.id === target}
              onToggle={() => {
                const next = new Set(open);
                if (!next.delete(f.id)) next.add(f.id);
                setOpen(next);
              }}
            />
          )}
        />
        </>
      )}
    </Panel>
  );
}

/** Configs (§11.6) and world setups, or fixtures (§11.7). */
export function WorldTab() {
  const doc = useDocument();
  const search = useSearchParams();
  const config = search.get("config");
  const fixture = search.get("fixture");
  if (doc.error) return <div className="p-4"><ErrorBox error={doc.error} onRetry={doc.reload} /></div>;
  if (!doc.data) return <Spinner label="Loading" />;
  return (
    <div className="mx-auto grid max-w-[1600px] grid-cols-1 gap-3 p-4 xl:h-full xl:grid-cols-2">
      <ConfigsPanel key={config ?? ""} doc={doc.data} target={config} />
      <FixturesPanel key={fixture ?? ""} doc={doc.data} target={fixture} />
    </div>
  );
}
