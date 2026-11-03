"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getClient } from "@/lib/api";
import type { Document, Flow, Plan, Scenario } from "@/lib/api/types";
import { ifaceComponent, ifaceName, plural } from "@/lib/model/format";
import { FLOW_GROUPINGS, defaultFlowGrouping, flowMatches, groupFlows, nameOf, type DocIndex, type FlowGrouping } from "@/lib/model/docindex";
import { planQueue, useDocIndex, useQuery } from "@/lib/hooks";
import { Cel, JsonView, Tpl } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, Label, Panel, ProgressiveList, Select, SourceRef, Spinner, cx, inputClass } from "@/components/ui";
import { FlowsChanged } from "./FlowsChanged";
import { useDocument, useWorkspace } from "./Workspace";

function groupByComponent(ids: string[]): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const id of ids) {
    const c = ifaceComponent(id);
    if (!m.has(c)) m.set(c, []);
    if (id.includes(".")) m.get(c)!.push(id);
  }
  return m;
}

export function scenarioMechanisms(s: Scenario): { label: string; tone: "info" | "warn" | "violet" | "bad" | "neutral" }[] {
  const out: { label: string; tone: "info" | "warn" | "violet" | "bad" | "neutral" }[] = [];
  if (s.input !== undefined) out.push({ label: "input", tone: "info" });
  if (s.choices && Object.keys(s.choices).length) out.push({ label: `${Object.keys(s.choices).length} choice`, tone: "warn" });
  if (s.state && Object.keys(s.state).length) out.push({ label: `state: ${Object.keys(s.state).join(", ")}`, tone: "violet" });
  if (s.faults?.length) out.push({ label: `⚡ ${plural(s.faults.length, "fault")}`, tone: "bad" });
  if (s.seed !== undefined) out.push({ label: `seed ${s.seed}`, tone: "neutral" });
  if (s.steps?.length) out.push({ label: plural(s.steps.length, "step"), tone: "info" });
  if (s.fixtures?.length) out.push({ label: `fixtures: ${s.fixtures.join(", ")}`, tone: "violet" });
  if (s.topology && Object.keys(s.topology).length) out.push({ label: `topology: ${Object.keys(s.topology).join(", ")}`, tone: "violet" });
  if (s.config && Object.keys(s.config).length) out.push({ label: `config: ${Object.keys(s.config).join(", ")}`, tone: "violet" });
  if (s.clock?.epoch || s.clock?.epoch_ms) out.push({ label: `clock ${s.clock.epoch ?? s.clock.epoch_ms}`, tone: "neutral" });
  if (s.mocks?.length) out.push({ label: plural(s.mocks.length, "mock"), tone: "warn" });
  return out;
}

function ScenarioRow({ s, flow }: { s: Scenario; flow: Flow }) {
  const ws = useWorkspace();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await getClient().runSimulation(ws.id, { rev: ws.rev, scenario: s.id });
      router.push(ws.href(`runs/${encodeURIComponent(r.id)}`));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };
  return (
    <li className="rounded-md border border-line bg-panel-2/50 px-3 py-2.5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h4 className="text-[13px] font-semibold text-ink">{s.name || s.id}</h4>
            <span className="font-mono text-[11px] text-faint">{s.id}</span>
          </div>
          {s.description && <p className="text-[12.5px] text-muted">{s.description}</p>}
          <div className="mt-1 flex flex-wrap gap-1">
            {scenarioMechanisms(s).map((m) => (
              <Badge key={m.label} tone={m.tone}>
                {m.label}
              </Badge>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <Link
            href={ws.href("simulate", { flow: flow.id, scenario: s.id })}
            className="inline-flex h-7 items-center rounded-md border border-line bg-panel-2 px-2 text-xs font-medium text-ink hover:bg-panel-3"
          >
            Configure
          </Link>
          <Button size="sm" variant="primary" onClick={run} disabled={busy}>
            {busy ? "Running…" : "▶ Run"}
          </Button>
        </div>
      </div>
      {(s.input !== undefined || s.choices || s.state || s.faults?.length) && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-[11.5px] text-link">Overrides</summary>
          <dl className="mt-1 grid grid-cols-[64px_1fr] gap-x-3 gap-y-1 text-[12px]">
            {s.input !== undefined && (
              <>
                <dt className="text-faint">input</dt>
                <dd>
                  <Tpl value={s.input} />
                </dd>
              </>
            )}
            {s.choices && (
              <>
                <dt className="text-faint">choices</dt>
                <dd className="space-y-0.5">
                  {Object.entries(s.choices).map(([k, v]) => (
                    <div key={k}>
                      <span className="font-mono text-[11.5px] text-ink">{k}</span> <span className="text-faint">=</span>{" "}
                      <span className="font-mono text-[11.5px] text-warn">{v}</span>
                    </div>
                  ))}
                </dd>
              </>
            )}
            {s.state && (
              <>
                <dt className="text-faint">state</dt>
                <dd>
                  <JsonView value={s.state} maxHeight={140} />
                </dd>
              </>
            )}
            {s.faults?.length ? (
              <>
                <dt className="text-faint">faults</dt>
                <dd className="space-y-0.5">
                  {s.faults.map((f, i) => (
                    <div key={i} className="font-mono text-[11.5px]">
                      <span className="text-bad">⚡ {f.type}</span> <span className="text-ink">{f.target}</span>
                      {f.code && <span className="text-muted"> code={f.code}</span>}
                      {f.status ? <span className="text-muted"> status={f.status}</span> : null}
                      {f.latency_ms ? <span className="text-muted"> +{f.latency_ms}ms</span> : null}
                      {f.calls?.length ? <span className="text-muted"> calls={f.calls.join(",")}</span> : null}
                    </div>
                  ))}
                </dd>
              </>
            ) : null}
          </dl>
        </details>
      )}
      {s.expect?.length ? (
        <div className="mt-2">
          <div className="mb-0.5 text-[11px] text-faint">expect</div>
          <ul className="space-y-0.5">
            {s.expect.map((e, i) => (
              <li key={i} className="flex items-baseline gap-1.5">
                <span className="text-faint" aria-hidden>
                  ▸
                </span>
                <Cel>{e}</Cel>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="mt-1 text-[11.5px] text-faint">No expectations.</div>
      )}
      {error ? <ErrorBox error={error} className="mt-2" /> : null}
    </li>
  );
}

function PlanView({ plan, idx }: { plan: Plan; idx: DocIndex }) {
  const reach = groupByComponent(plan.interfaces);
  const faultComps = plan.faultable.filter((f) => !f.includes("."));
  const name = (id: string) => nameOf(idx, id);
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <Panel title={`Reachable · ${plural(plan.interfaces.length, "interface")}, ${plural(plan.components.length, "component")}`}>
        <ul className="space-y-1 text-[12px]">
          {Array.from(reach.entries()).map(([c, ids]) => (
            <li key={c} className="flex flex-wrap items-baseline gap-1.5">
              <span className="min-w-[150px] text-ink">{name(c)}</span>
              {ids.map((id) => (
                <span key={id} className={id === plan.entry ? "rounded border border-[#4d6b1f] bg-[#1c2a10] px-1 font-mono text-[11px] text-accent" : "rounded border border-line bg-panel-2 px-1 font-mono text-[11px] text-muted"}>
                  {ifaceName(id)}
                  {id === plan.entry ? " · entry" : ""}
                </span>
              ))}
            </li>
          ))}
        </ul>
        {plan.unknown?.length ? (
          <div className="mt-2 rounded border border-[#5c2a2a] bg-[#2a1517] px-2 py-1 text-[12px] text-bad">
            ✗ Targets that are not interfaces:{" "}
            {plan.unknown.map((u, i) => (
              <span key={u}>
                {i ? ", " : ""}
                <span className="font-mono text-[11.5px]">{u}</span>
              </span>
            ))}
          </div>
        ) : null}
        {plan.dynamic?.length ? (
          <div className="mt-2 rounded border border-[#5a4520] bg-[#221c10] px-2 py-1 text-[12px] text-warn">
            ⚠ Dynamic call sites without declared targets: {plan.dynamic.join("; ")}
          </div>
        ) : null}
      </Panel>
      <div className="flex flex-col gap-3">
        <Panel title={`Choice points · ${plan.choices.length}`}>
          {plan.choices.length === 0 ? (
            <div className="text-[12px] text-faint">None reachable.</div>
          ) : (
            <table className="w-full text-[12px]">
              <tbody>
                {plan.choices.map((c) => (
                  <tr key={c.key} className="border-t border-line-soft first:border-t-0 align-baseline">
                    <td className="py-1 pr-3 font-mono text-[11.5px] text-ink">{c.key}</td>
                    <td className="py-1">
                      <span className="flex flex-wrap gap-1">
                        {c.options.map((o) => (
                          <span key={o} className={o === c.default ? "rounded border border-[#5a4520] bg-[#2a2213] px-1 font-mono text-[11px] text-warn" : "rounded border border-line px-1 font-mono text-[11px] text-muted"}>
                            {o}
                            {o === c.default ? " · default" : ""}
                          </span>
                        ))}
                      </span>
                      {c.title && <div className="text-[11.5px] text-faint">{c.title}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title={`Faultable targets · ${faultComps.length} components, ${plan.faultable.length - faultComps.length} interfaces`}>
          <div className="flex flex-wrap gap-1">
            {faultComps.map((c) => (
              <span key={c} className="rounded border border-[#5c2a2a] bg-[#2a1517]/60 px-1.5 font-mono text-[11px] text-bad" title={plan.faultable.filter((f) => f.startsWith(`${c}.`)).join("\n")}>
                ⚡ {c}
              </span>
            ))}
          </div>
          <div className="mt-1 text-[11px] text-faint">Each component&apos;s interfaces are also faultable individually; hover for the list.</div>
        </Panel>
        <Panel title={`Stateful components · ${plan.state.length}`}>
          <ul className="space-y-1">
            {plan.state.map((s) => (
              <li key={s.component}>
                <details>
                  <summary className="cursor-pointer text-[12px] text-ink">
                    {name(s.component)} <span className="font-mono text-[11px] text-faint">{Object.keys(s.initial ?? {}).join(", ")}</span>
                  </summary>
                  <JsonView value={s.initial ?? {}} className="mt-1" maxHeight={160} />
                </details>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

/** At or below this many flows, the tab lists every flow expanded, with its plan, as one page. */
export const SMALL_FLOWS = 30;

function FlowHeader({ flow, idx, heading }: { flow: Flow; idx: DocIndex; heading: boolean }) {
  const name = (id: string) => nameOf(idx, id);
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      {heading && (
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 id={`flow-${flow.id}`} className="text-[17px] font-semibold text-ink">
            {flow.name || flow.id}
          </h2>
          <span className="font-mono text-[11px] text-faint">{flow.id}</span>
          {flow.tags?.map((t) => (
            <Badge key={t}>#{t}</Badge>
          ))}
          <SimulateLink flow={flow} className="ml-auto" />
        </div>
      )}
      {!heading && <SimulateLink flow={flow} className="float-right ml-3" />}
      {flow.description && <p className={cx("max-w-4xl text-muted", heading && "mt-1")}>{flow.description}</p>}
      {flow.entry ? (
        <div className={cx("flex flex-wrap items-center gap-2 text-[12.5px]", (heading || flow.description) && "mt-2")}>
          <span className="text-faint">entry</span>
          <span className="text-ink">{name(flow.entry.caller)}</span>
          <span className="text-faint">→</span>
          <span className="font-mono text-accent">{flow.entry.interface}</span>
          {flow.entry.repeat && (
            <span className="rounded border border-line bg-panel-2 px-1 text-[11.5px] text-violet">
              ↻ repeats {flow.entry.repeat.count}×{flow.entry.repeat.interval_ms ? ` every ${flow.entry.repeat.interval_ms} ms` : ""}
            </span>
          )}
          {flow.entry.input !== undefined && (
            <span className="flex items-center gap-1">
              <span className="text-faint">input</span> <Tpl value={flow.entry.input} />
            </span>
          )}
        </div>
      ) : (
        <div className="mt-2 text-warn">This flow has no entry, so it cannot be simulated.</div>
      )}
      {flow.sources?.length ? (
        <div className="mt-1 flex flex-wrap gap-x-3">
          {flow.sources.map((s, i) => (
            <SourceRef key={i} source={s} />
          ))}
        </div>
      ) : null}
      {flow.steps?.length ? (
        <ol className="mt-3 space-y-1 border-t border-line-soft pt-2">
          {flow.steps.map((st, i) => (
            <li key={i} className="flex gap-2 text-[12.5px]">
              <span className="tnum w-5 shrink-0 text-right text-faint">{i + 1}</span>
              <div>
                <span className="font-medium text-ink">{st.title}</span> <span className="text-faint">· {name(st.component)}</span>
                {st.detail && <div className="text-muted">{st.detail}</div>}
                {st.source && <SourceRef source={st.source} />}
              </div>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function SimulateLink({ flow, className }: { flow: Flow; className?: string }) {
  const ws = useWorkspace();
  return (
    <Link
      href={ws.href("simulate", { flow: flow.id })}
      className={cx("inline-flex h-7 items-center rounded-md border border-accent bg-accent px-2.5 text-xs font-semibold text-accent-ink hover:bg-[#d9ff9a]", className)}
    >
      Simulate this flow
    </Link>
  );
}

/** A flow's plan and scenarios. Mounting it fetches the plan (through the shared plan queue). */
function FlowBody({ flow, idx }: { flow: Flow; idx: DocIndex }) {
  const ws = useWorkspace();
  const plan = useQuery(flow.entry ? `plan:${ws.id}:${ws.dataRev}:${flow.id}` : null, (c) => planQueue(() => c.getPlan(ws.id, flow.id, ws.rev)));
  const scenarios = idx.scenariosByFlow.get(flow.id) ?? [];
  return (
    <>
      {plan.loading && <Spinner label="Loading plan" />}
      {plan.error ? <ErrorBox error={plan.error} onRetry={plan.reload} /> : null}
      {plan.data && <PlanView plan={plan.data} idx={idx} />}
      <Panel title={`Scenarios · ${scenarios.length}`}>
        {scenarios.length === 0 ? (
          <Empty>No scenarios for this flow yet.</Empty>
        ) : (
          <ProgressiveList
            items={scenarios}
            step={60}
            className="grid grid-cols-1 gap-2 2xl:grid-cols-2"
            render={(s: Scenario) => <ScenarioRow key={s.id} s={s} flow={flow} />}
          />
        )}
      </Panel>
    </>
  );
}

/** One flow, fully expanded: what the tab shows for every flow of a small ontology. */
function FlowSection({ flow, idx }: { flow: Flow; idx: DocIndex }) {
  return (
    <section className="space-y-3" aria-labelledby={`flow-${flow.id}`}>
      <FlowHeader flow={flow} idx={idx} heading />
      <FlowBody flow={flow} idx={idx} />
    </section>
  );
}

/** A collapsed flow row; expanding it renders (and fetches) the detail. */
function FlowRow({ flow, idx, open, onToggle, section }: { flow: Flow; idx: DocIndex; open: boolean; onToggle: () => void; section?: string }) {
  const count = idx.scenariosByFlow.get(flow.id)?.length ?? 0;
  return (
    <li id={`flow-${flow.id}`} data-flow-row={flow.id} className={cx("scroll-mt-2 rounded-lg border bg-panel", open ? "border-[#3a4a57]" : "border-line")}>
      <h3>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-1 px-3 py-2 text-left hover:bg-panel-2/60"
        >
          <span className="w-3 shrink-0 text-faint" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
          <span className="text-[13.5px] font-semibold text-ink">{flow.name || flow.id}</span>
          <span className="font-mono text-[11px] text-faint">{flow.id}</span>
          {section && <span className="text-[11px] text-faint">in {section}</span>}
          <span className="flex flex-wrap gap-1">
            {flow.tags?.map((t) => (
              <Badge key={t}>#{t}</Badge>
            ))}
          </span>
          <span className="tnum ml-auto text-[11.5px] text-muted">{plural(count, "scenario")}</span>
        </button>
      </h3>
      {open && (
        <div className="space-y-3 border-t border-line-soft p-3">
          <FlowHeader flow={flow} idx={idx} heading={false} />
          <FlowBody flow={flow} idx={idx} />
        </div>
      )}
    </li>
  );
}

export function FlowsTab() {
  const commit = useSearchParams().get("commit");
  if (commit) return <FlowsChanged sha={commit} />;
  return <FlowsList />;
}

/** `#flow-<id>` from older links, as a flow id. */
function hashFlow(): string | null {
  if (typeof window === "undefined") return null;
  const m = /^#flow-(.+)$/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]) : null;
}

function FlowsList() {
  const doc = useDocument();
  const idx = useDocIndex(doc.data);
  if (doc.error) return <div className="p-4"><ErrorBox error={doc.error} onRetry={doc.reload} /></div>;
  if (!doc.data || !idx) return <Spinner label="Loading flows" />;
  if (doc.data.flows.length === 0) return <div className="p-4"><Empty>No flows in this revision.</Empty></div>;
  if (doc.data.flows.length <= SMALL_FLOWS) return <SmallFlows doc={doc.data} idx={idx} />;
  return <FlowBrowser doc={doc.data} idx={idx} />;
}

function SmallFlows({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const flowParam = useSearchParams().get("flow");
  useEffect(() => {
    const target = flowParam || hashFlow();
    if (target) document.getElementById(`flow-${target}`)?.scrollIntoView({ block: "start" });
  }, [flowParam]);
  return (
    <div className="mx-auto max-w-[1400px] space-y-8 p-4">
      {doc.flows.map((f) => (
        <FlowSection key={f.id} flow={f} idx={idx} />
      ))}
    </div>
  );
}

const ALL = "*";

/** Sections in a rail, then the chosen section's flows as collapsed rows. */
function FlowBrowser({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");

  const groupParam = search.get("group") as FlowGrouping | null;
  const auto = useMemo(() => defaultFlowGrouping(doc.flows, idx), [doc.flows, idx]);
  const grouping: FlowGrouping = groupParam && FLOW_GROUPINGS.some((g) => g.value === groupParam) ? groupParam : auto;
  const groups = useMemo(() => groupFlows(doc.flows, idx, grouping), [doc.flows, idx, grouping]);
  const matching = useMemo(() => (query.trim() ? groupFlows(doc.flows.filter((f) => flowMatches(f, query)), idx, grouping) : groups), [query, doc.flows, idx, grouping, groups]);
  const matchCount = useMemo(() => new Map(matching.map((g) => [g.key, g.flows.length])), [matching]);
  const totalMatches = query.trim() ? doc.flows.filter((f) => flowMatches(f, query)).length : doc.flows.length;

  const flowId = search.get("flow");
  const sectionParam = search.get("section");
  const section =
    sectionParam && (sectionParam === ALL || groups.some((g) => g.key === sectionParam))
      ? sectionParam
      : flowId && idx.flowsById.has(flowId)
        ? (groups.find((g) => g.flows.some((f) => f.id === flowId))?.key ?? groups[0].key)
        : query.trim()
          ? ALL
          : groups[0].key;

  const navigate = useCallback(
    (patch: Record<string, string | null>, replace = false) => {
      const q = new URLSearchParams(search.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v) q.set(k, v);
        else q.delete(k);
      }
      const url = `${pathname}?${q.toString()}`;
      if (replace) router.replace(url, { scroll: false });
      else router.push(url, { scroll: false });
    },
    [pathname, router, search],
  );

  // Older links point at #flow-<id>: turn them into ?flow=.
  useEffect(() => {
    const h = hashFlow();
    if (h && !flowId && idx.flowsById.has(h)) navigate({ flow: h }, true);
  }, [flowId, idx, navigate]);

  const sectionLabel = new Map(groups.map((g) => [g.key, g.label]));
  const sectionOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const g of groups) for (const f of g.flows) if (!m.has(f.id)) m.set(f.id, g.label);
    return m;
  }, [groups]);
  const inSection = section === ALL ? doc.flows : (groups.find((g) => g.key === section)?.flows ?? []);
  const shown = query.trim() ? inSection.filter((f) => flowMatches(f, query)) : inSection;
  const openIndex = flowId ? shown.findIndex((f) => f.id === flowId) : -1;

  // Bring a linked or newly opened flow into view.
  useEffect(() => {
    if (flowId) document.getElementById(`flow-${flowId}`)?.scrollIntoView({ block: "nearest" });
  }, [flowId, section]);

  const rail = (key: string, label: string, n: number, total: number) => (
    <li key={key}>
      <button
        type="button"
        onClick={() => navigate({ section: key, flow: null })}
        aria-current={section === key ? "true" : undefined}
        disabled={n === 0}
        className={cx(
          "flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left text-[12.5px] disabled:opacity-40",
          section === key ? "bg-[#1c2a10] text-accent" : "text-muted hover:bg-panel-2 hover:text-ink",
        )}
      >
        <span className="min-w-0 flex-1 truncate" title={label}>
          {label}
        </span>
        <span className="tnum shrink-0 text-[11px] text-faint">{n === total ? n : `${n}/${total}`}</span>
      </button>
    </li>
  );

  return (
    <div className="flex h-full min-h-0">
      <nav aria-label="Flow sections" className="flex w-[260px] shrink-0 flex-col border-r border-line bg-panel/40">
        <div className="space-y-2 border-b border-line-soft p-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${doc.flows.length} flows: name, id, tag`}
            aria-label="Search flows"
            className={cx(inputClass, "w-full text-[12.5px]")}
          />
          <div className="flex items-center gap-1.5">
            <Label htmlFor="flow-grouping">Group by</Label>
            <Select id="flow-grouping" value={grouping} onChange={(e) => navigate({ group: e.target.value, section: null }, true)} className="h-7 min-w-0 flex-1 text-[12px]">
              {FLOW_GROUPINGS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                  {g.value === auto ? " (default)" : ""}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <ul className="min-h-0 flex-1 space-y-px overflow-y-auto p-1.5">
          {rail(ALL, "All flows", totalMatches, doc.flows.length)}
          <li className="mx-2 my-1 border-t border-line-soft" aria-hidden />
          {groups.map((g) => rail(g.key, g.label, matchCount.get(g.key) ?? 0, g.flows.length))}
        </ul>
      </nav>
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1400px] space-y-3 p-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 className="text-[17px] font-semibold text-ink">{section === ALL ? "All flows" : sectionLabel.get(section)}</h2>
            <span className="text-[12px] text-faint">
              {query.trim() ? `${shown.length} of ${inSection.length} match “${query.trim()}”` : plural(inSection.length, "flow")}
            </span>
            {query.trim() && section !== ALL && shown.length < totalMatches && (
              <button type="button" className="text-[12px] text-link hover:underline" onClick={() => navigate({ section: ALL })}>
                show all {totalMatches} matches
              </button>
            )}
          </div>
          {shown.length === 0 ? (
            <Empty>No flows match.</Empty>
          ) : (
            <ProgressiveList
              key={`${grouping}:${section}:${query}`}
              items={shown}
              ensure={openIndex}
              className="space-y-1.5"
              render={(f: Flow) => (
                <FlowRow
                  key={f.id}
                  flow={f}
                  idx={idx}
                  open={f.id === flowId}
                  section={section === ALL ? sectionOf.get(f.id) : undefined}
                  onToggle={() => navigate({ flow: f.id === flowId ? null : f.id, section })}
                />
              )}
            />
          )}
        </div>
      </div>
    </div>
  );
}
