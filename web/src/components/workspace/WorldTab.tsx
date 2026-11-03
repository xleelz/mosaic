"use client";

import { useState } from "react";
import type { Config, Document, Fixture, JsonValue, Topology } from "@/lib/api/types";
import { componentName, jsonEqual, jsonInline } from "@/lib/model/format";
import { effectiveWorld, fixtureChain } from "@/lib/model/world";
import { JsonView } from "@/components/json";
import { Badge, Empty, ErrorBox, Panel, ProgressiveList, SourceRef, Spinner, cx, inputClass } from "@/components/ui";
import { useDocument } from "./Workspace";

/** A config's deployed value differs from its code default (both present). */
export function configDiffers(c: Config): boolean {
  return c.value !== undefined && c.default !== undefined && !jsonEqual(c.value, c.default);
}

function Value({ v }: { v: JsonValue | undefined }) {
  if (v === undefined) return <span className="text-faint">—</span>;
  return <span className="font-mono text-[11.5px] text-ink">{jsonInline(v, 48)}</span>;
}

function ConfigsPanel({ doc }: { doc: Document }) {
  const [filter, setFilter] = useState("");
  const [differsOnly, setDiffersOnly] = useState(false);
  const all = doc.configs ?? [];
  const list = all
    .filter((c) => !differsOnly || configDiffers(c))
    .filter((c) => !filter || c.id.includes(filter) || (c.summary ?? "").toLowerCase().includes(filter.toLowerCase()));
  const differing = all.filter(configDiffers).length;
  return (
    <Panel
      title={`Configs · ${all.length}`}
      bodyClassName="p-0"
      actions={
        all.length > 0 && (
          <>
            <label className="flex items-center gap-1.5 text-[11.5px] text-muted">
              <input type="checkbox" checked={differsOnly} onChange={(e) => setDiffersOnly(e.target.checked)} className="accent-[#ccff78]" />
              Differs only ({differing})
            </label>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter" aria-label="Filter configs" className={cx(inputClass, "h-7 w-36 text-[12px]")} />
          </>
        )
      }
    >
      {all.length === 0 ? (
        <div className="p-3">
          <Empty>The model has no configs.</Empty>
        </div>
      ) : (
        <table className="w-full text-[12.5px]">
          <thead className="bg-panel-2 text-left text-[11px] uppercase tracking-[0.06em] text-faint">
            <tr>
              <th className="px-3 py-1.5 font-semibold">Config</th>
              <th className="px-3 py-1.5 font-semibold">Deployed</th>
              <th className="px-3 py-1.5 font-semibold">Default</th>
            </tr>
          </thead>
          <ProgressiveList
            as="tbody"
            key={`${filter}:${differsOnly}`}
            items={list}
            step={150}
            render={(c) => (
              <tr key={c.id} className="border-t border-line-soft align-top">
                <td className="px-3 py-1.5">
                  <div className="flex flex-wrap items-baseline gap-1.5">
                    <span className="font-mono text-[12px] text-ink">{c.id}</span>
                    {c.type && <span className="text-[11px] text-faint">{c.type}</span>}
                    {configDiffers(c) && (
                      <Badge tone="warn" title="The deployed value differs from the code default">
                        differs
                      </Badge>
                    )}
                    {c.tags?.map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  </div>
                  {c.summary && <div className="text-[12px] text-muted">{c.summary}</div>}
                  {c.sources?.length ? (
                    <div className="flex flex-wrap gap-x-2">
                      {c.sources.map((s, i) => (
                        <SourceRef key={i} source={s} />
                      ))}
                    </div>
                  ) : null}
                </td>
                <td className={cx("px-3 py-1.5", configDiffers(c) && "bg-[#2a2213]/40")}>
                  <Value v={c.value} />
                </td>
                <td className="px-3 py-1.5">
                  <Value v={c.default} />
                </td>
              </tr>
            )}
          />
        </table>
      )}
      {all.length > 0 && list.length === 0 && <div className="p-3 text-center text-muted">No config matches.</div>}
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

function FixtureCard({ doc, f }: { doc: Document; f: Fixture }) {
  const chain = fixtureChain(doc, [f.id]);
  const eff = effectiveWorld(doc, [f.id]);
  const inherits = chain.order.length > 1;
  return (
    <li className="rounded-md border border-line bg-panel-2/50 px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium text-ink">{f.name || f.id}</span>
        <span className="font-mono text-[11px] text-faint">{f.id}</span>
        {chain.cycles.length > 0 && <Badge tone="bad">cycle: {chain.cycles.join(", ")}</Badge>}
        {chain.missing.length > 0 && <Badge tone="bad">unknown: {chain.missing.join(", ")}</Badge>}
      </div>
      {f.summary && <div className="text-[12.5px] text-muted">{f.summary}</div>}
      {f.extends?.length ? (
        <div className="mt-1 flex flex-wrap items-center gap-1 text-[12px]">
          <span className="text-faint">applies</span>
          {chain.order.map((id, i) => (
            <span key={id} className="flex items-center gap-1">
              {i > 0 && <span className="text-faint">→</span>}
              <span className={cx("font-mono text-[11.5px]", id === f.id ? "text-ink" : "text-violet")}>{id}</span>
            </span>
          ))}
        </div>
      ) : null}
      <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
        <Section title="Topology">
          <TopologyTable doc={doc} topology={f.topology ?? {}} />
        </Section>
        <Section title="Clock">
          {f.clock ? <span className="font-mono text-[11.5px] text-ink">{f.clock.epoch ?? `epoch_ms ${f.clock.epoch_ms ?? 0}`}</span> : <span className="text-[12px] text-faint">none</span>}
        </Section>
        <Section title="Config">
          {f.config && Object.keys(f.config).length ? (
            <ul className="space-y-0.5">
              {Object.entries(f.config).map(([k, v]) => (
                <li key={k} className="font-mono text-[11.5px]">
                  <span className="text-ink">{k}</span> <span className="text-faint">=</span> <span className="text-accent">{jsonInline(v, 48)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-[12px] text-faint">none</span>
          )}
        </Section>
        <Section title="State">
          {f.state && Object.keys(f.state).length ? <JsonView value={f.state} maxHeight={180} /> : <span className="text-[12px] text-faint">none</span>}
        </Section>
      </div>
      {inherits && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[12px] text-link">Effective world (extends applied)</summary>
          <div className="mt-1.5 grid grid-cols-1 gap-2 md:grid-cols-2">
            <Section title="Topology">
              <TopologyTable doc={doc} topology={eff.topology} />
            </Section>
            <Section title="Clock">
              {eff.clock ? <span className="font-mono text-[11.5px] text-ink">{eff.clock.epoch ?? `epoch_ms ${eff.clock.epoch_ms ?? 0}`}</span> : <span className="text-[12px] text-faint">none</span>}
            </Section>
            <Section title="Config">
              {Object.keys(eff.config).length ? <JsonView value={eff.config} maxHeight={180} /> : <span className="text-[12px] text-faint">none</span>}
            </Section>
            <Section title="State">
              {Object.keys(eff.state).length ? <JsonView value={eff.state} maxHeight={180} /> : <span className="text-[12px] text-faint">none</span>}
            </Section>
          </div>
        </details>
      )}
    </li>
  );
}

function FixturesPanel({ doc }: { doc: Document }) {
  const all = doc.fixtures ?? [];
  return (
    <Panel title={`Fixtures · ${all.length}`}>
      {all.length === 0 ? (
        <Empty>The model has no fixtures.</Empty>
      ) : (
        <ul className="space-y-2">
          {all.map((f) => (
            <FixtureCard key={f.id} doc={doc} f={f} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** Configs (§11.6) and fixtures (§11.7). */
export function WorldTab() {
  const doc = useDocument();
  if (doc.error) return <div className="p-4"><ErrorBox error={doc.error} onRetry={doc.reload} /></div>;
  if (!doc.data) return <Spinner label="Loading" />;
  return (
    <div className="mx-auto grid max-w-[1600px] grid-cols-1 items-start gap-3 p-4 xl:grid-cols-2">
      <ConfigsPanel doc={doc.data} />
      <FixturesPanel doc={doc.data} />
    </div>
  );
}
