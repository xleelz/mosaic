"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useDeferredValue, useEffect, useMemo, useState, type ReactNode } from "react";
import { getClient } from "@/lib/api";
import type { ChoicePoint, Document, Flow, Plan, Scenario, SimulationRequest } from "@/lib/api/types";
import { ifaceComponent, ifaceName, plural } from "@/lib/model/format";
import {
  FLOW_GROUPINGS,
  SUBGROUP_OVER,
  defaultFlowGrouping,
  derivedFlowLine,
  flowScenarioCount,
  flowScenarios,
  flowTitle,
  groupFlows,
  mainFlows,
  nameOf,
  rankFlows,
  scenarioTitle,
  searchFlows,
  subgroupFlows,
  touchLabel,
  type DocIndex,
  type FlowGrouping,
  type FlowTouch,
} from "@/lib/model/docindex";
import { planQueue, useDocIndex, useQuery } from "@/lib/hooks";
import { Cel, JsonView, Tpl } from "@/components/json";
import { ClaimScope } from "@/components/code/context";
import { WindowedList } from "@/components/WindowedList";
import { ClaimMark } from "@/components/trust/marks";
import { Badge, Button, Empty, ErrorBox, Label, Panel, Select, SourceRef, Spinner, cx, inputClass } from "@/components/ui";
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
  if (s.fixtures?.length) out.push({ label: `world setup (fixture): ${s.fixtures.join(", ")}`, tone: "violet" });
  if (s.topology && Object.keys(s.topology).length) out.push({ label: `topology: ${Object.keys(s.topology).join(", ")}`, tone: "violet" });
  if (s.config && Object.keys(s.config).length) out.push({ label: `config: ${Object.keys(s.config).join(", ")}`, tone: "violet" });
  if (s.clock?.epoch || s.clock?.epoch_ms) out.push({ label: `clock ${s.clock.epoch ?? s.clock.epoch_ms}`, tone: "neutral" });
  if (s.mocks?.length) out.push({ label: plural(s.mocks.length, "mock"), tone: "warn" });
  return out;
}

/** A disclosure that doesn't render its content until first opened. */
export function LazyDetails({ summary, defaultOpen, className, summaryClassName, children }: { summary: ReactNode; defaultOpen?: boolean; className?: string; summaryClassName?: string; children: ReactNode }) {
  const [opened, setOpened] = useState(!!defaultOpen);
  return (
    <details className={className} open={defaultOpen || undefined} onToggle={(e) => e.currentTarget.open && setOpened(true)}>
      <summary className={cx("cursor-pointer", summaryClassName)}>{summary}</summary>
      {opened && children}
    </details>
  );
}

/** Starts a run and opens it. */
export function RunButton({ request, label = "▶ Run", primary }: { request: Omit<SimulationRequest, "rev">; label?: string; primary?: boolean }) {
  const ws = useWorkspace();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await getClient().runSimulation(ws.id, { ...request, rev: ws.rev });
      router.push(ws.href(`runs/${encodeURIComponent(r.id)}`));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };
  return (
    <>
      <Button size="sm" variant={primary ? "primary" : "default"} onClick={run} disabled={busy}>
        {busy ? "Running…" : label}
      </Button>
      {error ? <ErrorBox error={error} className="mt-2 basis-full" /> : null}
    </>
  );
}

/** A scenario's title. With no name or description it says so, and the id stays an id. */
export function ScenarioName({ s, className }: { s: Scenario; className?: string }) {
  const t = scenarioTitle(s);
  return t.from === "id" ? <span className={cx("font-normal italic text-muted", className)}>Unnamed scenario</span> : <span className={className}>{t.text}</span>;
}

function FlowName({ flow, className }: { flow: Flow; className?: string }) {
  const t = flowTitle(flow);
  return t.from === "id" ? <span className={cx("font-normal italic text-muted", className)}>Unnamed flow</span> : <span className={className}>{t.text}</span>;
}

function ScenarioRow({ s, flow, touch, primary }: { s: Scenario; flow: Flow; touch?: FlowTouch; primary?: boolean }) {
  const ws = useWorkspace();
  const how = touch ? touchLabel(touch) : "";
  const title = scenarioTitle(s);
  return (
    <article className="rounded-md border border-line bg-panel-2/50 px-3 py-2.5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h4 className="text-[13px] font-semibold text-ink">
              <ScenarioName s={s} />
            </h4>
            <span className="font-mono text-[11px] text-faint">{s.id}</span>
            {how && <span className="text-[11px] text-muted">{how}</span>}
          </div>
          {s.description && title.from !== "description" && <p className="text-[12.5px] text-muted">{s.description}</p>}
          <div className="mt-1 flex flex-wrap gap-1">
            {scenarioMechanisms(s).map((m) => (
              <Badge key={m.label} tone={m.tone}>
                {m.label}
              </Badge>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <Link
            href={ws.href("simulate", { flow: flow.id, scenario: s.id })}
            className="inline-flex h-7 items-center rounded-md border border-line bg-panel-2 px-2 text-xs font-medium text-ink hover:bg-panel-3"
          >
            Configure
          </Link>
          <RunButton request={{ scenario: s.id }} primary={primary} />
        </div>
      </div>
      {(s.input !== undefined || s.choices || s.state || s.faults?.length || s.expect?.length) && (
        <LazyDetails className="mt-1.5" summary="Expectations and overrides" summaryClassName="text-[11.5px] text-link">
          {s.expect?.length ? (
            <ul className="mt-1 space-y-0.5">
              {s.expect.map((e, i) => (
                <li key={i} className="flex items-baseline gap-1.5">
                  <span className="text-faint" aria-hidden>
                    ▸
                  </span>
                  <Cel>{e}</Cel>
                </li>
              ))}
            </ul>
          ) : null}
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
                <dt className="text-faint">decisions</dt>
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
        </LazyDetails>
      )}
    </article>
  );
}

/** One line for a scenario: what search and the component panel list. */
export function CompactScenarioRow({ s, note }: { s: Scenario; note?: ReactNode }) {
  const title = scenarioTitle(s);
  return (
    <div className="flex items-start gap-2 rounded-md border border-line-soft bg-panel-2/40 px-2 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] text-ink">
          <ScenarioName s={s} />
          {title.from === "id" && <span className="ml-1.5 font-mono text-[11px] text-faint">{s.id}</span>}
        </div>
        {note && <div className="text-[11.5px] text-muted">{note}</div>}
      </div>
      <RunButton request={{ scenario: s.id }} />
    </div>
  );
}

const faultableCap = 40;

function FaultableChips({ plan }: { plan: Plan }) {
  const [all, setAll] = useState(false);
  const comps = useMemo(() => plan.faultable.filter((f) => !f.includes(".")), [plan]);
  const shown = all ? comps : comps.slice(0, faultableCap);
  return (
    <>
      <div className="flex flex-wrap gap-1">
        {shown.map((c) => (
          <span key={c} className="rounded border border-[#5c2a2a] bg-[#2a1517]/60 px-1.5 font-mono text-[11px] text-bad" title={`Every interface of ${c} can fail individually`}>
            ⚡ {c}
          </span>
        ))}
      </div>
      {comps.length > faultableCap && (
        <button type="button" className="mt-1 text-[11.5px] text-link hover:underline" onClick={() => setAll((a) => !a)}>
          {all ? "show fewer" : `and ${comps.length - faultableCap} more`}
        </button>
      )}
    </>
  );
}

function ReachRow({ component, ids, entry, name }: { component: string; ids: string[]; entry: string; name: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-1.5 py-0.5 text-[12px]">
      <span className="min-w-[150px] text-ink" title={component}>
        {name}
      </span>
      {ids.map((id) => (
        <span key={id} className={id === entry ? "rounded border border-[#4d6b1f] bg-[#1c2a10] px-1 font-mono text-[11px] text-accent" : "rounded border border-line bg-panel-2 px-1 font-mono text-[11px] text-muted"}>
          {ifaceName(id)}
          {id === entry ? " · entry" : ""}
        </span>
      ))}
    </div>
  );
}

/** The static plan: what a flow could reach, never proof that a run does. */
function CouldReach({ plan, idx }: { plan: Plan; idx: DocIndex }) {
  const reach = useMemo(() => Array.from(groupByComponent(plan.interfaces).entries()), [plan]);
  const faultComps = plan.faultable.filter((f) => !f.includes("."));
  const name = (id: string) => nameOf(idx, id);
  return (
    <LazyDetails
      className="rounded-lg border border-line bg-panel"
      summaryClassName="px-3 py-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted"
      summary={
        <>
          Could reach (static) · {plural(plan.interfaces.length, "interface")}, {plural(plan.components.length, "component")}
        </>
      }
    >
      <div className="space-y-3 border-t border-line-soft p-3">
        <p className="text-[12px] text-faint">Everything the model&apos;s declared calls could reach from this flow&apos;s entry. A run takes one path through it; this list is not what happens.</p>
        {plan.unknown?.length ? (
          <div className="rounded border border-[#5c2a2a] bg-[#2a1517] px-2 py-1 text-[12px] text-bad">
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
          <div className="rounded border border-[#5a4520] bg-[#221c10] px-2 py-1 text-[12px] text-warn">
            ⚠ Dynamic call sites without declared targets: {plan.dynamic.join("; ")}
          </div>
        ) : null}
        <div className="max-h-[420px] overflow-y-auto">
          <WindowedList
            items={reach}
            itemKey={([c]) => c}
            estimate={26}
            render={([c, ids]) => <ReachRow component={c} ids={ids} entry={plan.entry} name={name(c)} />}
          />
        </div>
        <div>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
            Faultable targets · {faultComps.length} components, {plan.faultable.length - faultComps.length} interfaces
          </h4>
          <FaultableChips plan={plan} />
        </div>
        <div>
          <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Stateful components · {plan.state.length}</h4>
          <div className="max-h-[320px] overflow-y-auto">
            <WindowedList
              items={plan.state}
              itemKey={(s) => s.component}
              estimate={24}
              render={(s) => (
                <LazyDetails
                  summaryClassName="text-[12px] text-ink"
                  summary={
                    <>
                      {name(s.component)} <span className="font-mono text-[11px] text-faint">{Object.keys(s.initial ?? {}).join(", ")}</span>
                    </>
                  }
                >
                  <JsonView value={s.initial ?? {}} className="mt-1" maxHeight={160} />
                </LazyDetails>
              )}
            />
          </div>
        </div>
      </div>
    </LazyDetails>
  );
}

function DecisionRow({ c }: { c: ChoicePoint }) {
  return (
    <div className="border-t border-line-soft py-1 first:border-t-0">
      <span className="font-mono text-[11.5px] text-ink">{c.key}</span>
      {c.title && <span className="ml-2 text-[11.5px] text-faint">{c.title}</span>}
      <span className="mt-0.5 flex flex-wrap gap-1">
        {c.options.map((o) => (
          <span key={o} className={o === c.default ? "rounded border border-[#5a4520] bg-[#2a2213] px-1 font-mono text-[11px] text-warn" : "rounded border border-line px-1 font-mono text-[11px] text-muted"}>
            {o}
            {o === c.default ? " · default" : ""}
          </span>
        ))}
      </span>
    </div>
  );
}

/** Choice points: what the model doesn't compute, so a person or a scenario picks. */
function OpenDecisions({ plan }: { plan: Plan }) {
  if (plan.choices.length === 0) return null;
  return (
    <Panel title={`Open decisions · ${plan.choices.length}`} actions={<ClaimMark kind="open-decision" />}>
      <div className="max-h-[360px] overflow-y-auto">
        <WindowedList items={plan.choices} itemKey={(c) => c.key} estimate={46} render={(c) => <DecisionRow c={c} />} />
      </div>
    </Panel>
  );
}

/** At or below this many flows, the tab lists every flow expanded as one page. */
export const SMALL_FLOWS = 30;

function FlowHeader({ flow, idx, heading }: { flow: Flow; idx: DocIndex; heading: boolean }) {
  const name = (id: string) => nameOf(idx, id);
  const derived = derivedFlowLine(flow, idx);
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      {heading && (
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 id={`flow-${flow.id}`} className="text-[17px] font-semibold text-ink">
            <FlowName flow={flow} />
          </h2>
          <span className="font-mono text-[11px] text-faint">{flow.id}</span>
          {flow.tags?.map((t) => (
            <Badge key={t}>#{t}</Badge>
          ))}
          <SimulateLink flow={flow} className="ml-auto" />
        </div>
      )}
      {!heading && <SimulateLink flow={flow} className="float-right ml-3" />}
      {flow.description ? (
        <p className={cx("max-w-4xl text-muted", heading && "mt-1")}>{flow.description}</p>
      ) : (
        <p className={cx("max-w-4xl text-[12.5px] text-faint", heading && "mt-1")}>No description in the model.{derived ? ` From its entry: ${derived}` : ""}</p>
      )}
      {flow.entry ? (
        <div className="mt-2 flex flex-wrap items-baseline gap-2 text-[12.5px]">
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
            <span className="flex items-baseline gap-1">
              <span className="shrink-0 text-faint">generated input, with</span> <Tpl value={flow.entry.input} />
            </span>
          )}
        </div>
      ) : (
        <div className="mt-2 text-warn">This flow has no entry, so it cannot be simulated.</div>
      )}
      {flow.sources?.length ? (
        <div className="mt-1 flex flex-wrap gap-x-3">
          {flow.sources.map((s, i) => (
            <ClaimScope key={i} claim={flow.description || flow.name || flow.id}>
              <SourceRef source={s} />
            </ClaimScope>
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
                {st.source && (
                  <ClaimScope claim={st.detail ? `${st.title}: ${st.detail}` : st.title}>
                    <SourceRef source={st.source} />
                  </ClaimScope>
                )}
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
      className={cx("inline-flex h-7 items-center rounded-md border border-line bg-panel-2 px-2.5 text-xs font-medium text-ink hover:bg-panel-3", className)}
    >
      Configure a run
    </Link>
  );
}

function ScenarioGroup({ title, hint, touches, flow, open }: { title: string; hint?: string; touches: FlowTouch[]; flow: Flow; open?: boolean }) {
  if (touches.length === 0) return null;
  return (
    <LazyDetails
      defaultOpen={open}
      className="rounded-md"
      summaryClassName="py-1 text-[12.5px] font-medium text-ink"
      summary={
        <>
          {title} <span className="tnum text-faint">· {touches.length}</span>
          {hint && <span className="ml-2 text-[11.5px] font-normal text-faint">{hint}</span>}
        </>
      }
    >
      <WindowedList
        items={touches}
        itemKey={(t) => t.scenario.id}
        estimate={96}
        rowClassName="pb-2"
        className="pt-1"
        render={(t) => <ScenarioRow s={t.scenario} flow={flow} touch={t} />}
      />
    </LazyDetails>
  );
}

/** What a flow's page leads with: what happens, then how it fails, then everything else. */
function WhatHappens({ flow, idx }: { flow: Flow; idx: DocIndex }) {
  const touches = idx.touchesByFlow.get(flow.id);
  const sc = useMemo(() => flowScenarios(touches ?? []), [touches]);
  const failures = sc.faults.length + sc.expectedErrors.length;
  return (
    <>
      <Panel title="What happens">
        {sc.happy ? (
          <>
            <ScenarioRow s={sc.happy.touch.scenario} flow={flow} touch={sc.happy.touch} primary />
            <p className="mt-1.5 text-[11.5px] text-faint">Picked by rule, not declared by the model: {sc.happy.why}.</p>
          </>
        ) : flow.entry ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="min-w-0 flex-1 text-[12.5px] text-muted">
              {touches?.length ? "Every scenario here is a failure or a refusal, so none shows the normal path." : "No scenario's steps touch this flow."} A run with the flow&apos;s defaults and generated input shows what the model does.
            </p>
            <RunButton request={{ flow: flow.id }} primary label="▶ Run with defaults" />
          </div>
        ) : (
          <p className="text-[12.5px] text-muted">No scenario touches this flow, and without an entry it can&apos;t run by itself.</p>
        )}
      </Panel>
      {touches?.length && touches.length > (sc.happy ? 1 : 0) ? (
        <Panel title={`Other scenarios · ${touches.length - (sc.happy ? 1 : 0)}`}>
          <div className="space-y-1">
            {failures > 0 && (
              <>
                <ScenarioGroup title="Injected faults" hint="what happens when a part fails" touches={sc.faults} flow={flow} open />
                <ScenarioGroup title="Refusals and expected errors" hint="the model fails by itself" touches={sc.expectedErrors} flow={flow} open={sc.faults.length === 0} />
              </>
            )}
            <ScenarioGroup title="Also start with this flow" touches={sc.starts} flow={flow} open={failures === 0} />
            <ScenarioGroup title="Reach this flow from another step" touches={sc.uses} flow={flow} open={failures === 0 && sc.starts.length === 0} />
          </div>
        </Panel>
      ) : null}
    </>
  );
}

/** A flow's scenarios and plan. Mounting it fetches the plan (through the shared plan queue). */
function FlowBody({ flow, idx }: { flow: Flow; idx: DocIndex }) {
  const ws = useWorkspace();
  const plan = useQuery(flow.entry ? `plan:${ws.id}:${ws.dataRev}:${flow.id}` : null, (c) => planQueue(() => c.getPlan(ws.id, flow.id, ws.rev)));
  return (
    <>
      <WhatHappens flow={flow} idx={idx} />
      {plan.loading && <Spinner label="Loading what it could reach" />}
      {plan.error ? <ErrorBox error={plan.error} onRetry={plan.reload} /> : null}
      {plan.data && <CouldReach plan={plan.data} idx={idx} />}
      {plan.data && <OpenDecisions plan={plan.data} />}
    </>
  );
}

/** One flow, fully expanded: what the tab shows for every flow of a small model. */
function FlowSection({ flow, idx }: { flow: Flow; idx: DocIndex }) {
  return (
    <section className="space-y-3" aria-labelledby={`flow-${flow.id}`}>
      <FlowHeader flow={flow} idx={idx} heading />
      <FlowBody flow={flow} idx={idx} />
    </section>
  );
}

/** A collapsed flow row; expanding it renders (and fetches) the detail. */
function FlowRow({ flow, idx, open, onToggle, section, reason, hits }: { flow: Flow; idx: DocIndex; open: boolean; onToggle: () => void; section?: string; reason?: string; hits?: Scenario[] }) {
  const count = flowScenarioCount(flow, idx);
  return (
    <div id={`flow-${flow.id}`} data-flow-row={flow.id} className={cx("scroll-mt-2 rounded-lg border bg-panel", open ? "border-[#3a4a57]" : "border-line")}>
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
          <span className="text-[13.5px] font-semibold text-ink">
            <FlowName flow={flow} />
          </span>
          <span className="font-mono text-[11px] text-faint">{flow.id}</span>
          {section && <span className="text-[11px] text-faint">in {section}</span>}
          {reason && <span className="text-[11px] text-faint">{reason}</span>}
          <span className="flex flex-wrap gap-1">
            {flow.tags?.map((t) => (
              <Badge key={t}>#{t}</Badge>
            ))}
          </span>
          {reason ? null : count > 0 ? (
            <span className="tnum ml-auto text-[11.5px] text-muted">{plural(count, "scenario")}</span>
          ) : (
            <span className="ml-auto text-[11.5px] text-faint" title="No scenario names this flow, or calls its entry in a step. Runs may still pass through it.">
              not in any scenario
            </span>
          )}
        </button>
      </h3>
      {hits?.length ? (
        <div className="border-t border-line-soft px-3 py-1 text-[11.5px] text-muted">
          Scenario match: {hits.slice(0, 3).map((s) => scenarioTitle(s).text).join("; ")}
          {hits.length > 3 ? `; and ${hits.length - 3} more` : ""}
        </div>
      ) : null}
      {open && (
        <div className="space-y-3 border-t border-line-soft p-3">
          <FlowHeader flow={flow} idx={idx} heading={false} />
          <FlowBody flow={flow} idx={idx} />
        </div>
      )}
    </div>
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

/** Scenarios a search found, with where they sit. Includes scenarios that touch no flow. */
function ScenarioHits({ scenarios, idx }: { scenarios: Scenario[]; idx: DocIndex }) {
  if (scenarios.length === 0) return null;
  return (
    <Panel title={`Scenarios · ${scenarios.length}`}>
      <div className="max-h-[320px] overflow-y-auto">
        <WindowedList
          items={scenarios}
          itemKey={(s) => s.id}
          estimate={52}
          rowClassName="pb-1"
          render={(s) => {
            const flows = idx.flowsOfScenario.get(s.id) ?? [];
            return (
              <CompactScenarioRow
                s={s}
                note={flows.length ? `touches ${flows.slice(0, 3).map((f) => idx.flowsById.get(f)?.name || f).join(", ")}${flows.length > 3 ? ` and ${flows.length - 3} more` : ""}` : "calls interfaces directly; no flow involved"}
              />
            );
          }}
        />
      </div>
    </Panel>
  );
}

function SmallFlows({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const flowParam = useSearchParams().get("flow");
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const found = useMemo(() => searchFlows(doc.flows, idx, deferred), [doc.flows, idx, deferred]);
  useEffect(() => {
    const target = flowParam || hashFlow();
    if (target) document.getElementById(`flow-${target}`)?.scrollIntoView({ block: "start" });
  }, [flowParam]);
  return (
    <div className="mx-auto max-w-[1400px] space-y-8 p-4">
      <div className="space-y-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={`Search ${plural(doc.flows.length, "flow")} and ${plural(doc.scenarios.length, "scenario")}`}
          aria-label="Search flows and scenarios"
          className={cx(inputClass, "w-full max-w-md text-[12.5px]")}
        />
        {deferred.trim() ? <ScenarioHits scenarios={found.scenarios} idx={idx} /> : null}
        {deferred.trim() && found.scenarios.length === 0 && found.flows.length === 0 ? <Empty>No flows or scenarios match.</Empty> : null}
      </div>
      {found.flows.map((f) => (
        <FlowSection key={f.id} flow={f} idx={idx} />
      ))}
    </div>
  );
}

const ALL = "*";
const MAIN = "main";
const SUB_ALL = "";

interface HeadRow {
  head: string;
  label: string;
  count: number;
}
type BrowserRow = Flow | HeadRow;
const isHead = (r: BrowserRow): r is HeadRow => "head" in r;

/** Sections in a rail, then the chosen section's flows as collapsed rows. */
function FlowBrowser({ doc, idx }: { doc: Document; idx: DocIndex }) {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const q = deferred.trim();

  const groupParam = search.get("group") as FlowGrouping | null;
  const auto = useMemo(() => defaultFlowGrouping(doc.flows, idx), [doc.flows, idx]);
  const grouping: FlowGrouping = groupParam && FLOW_GROUPINGS.some((g) => g.value === groupParam) ? groupParam : auto;
  const groups = useMemo(() => groupFlows(doc.flows, idx, grouping), [doc.flows, idx, grouping]);
  const mains = useMemo(() => mainFlows(doc.flows, idx), [doc.flows, idx]);
  const reasons = useMemo(() => new Map(mains.map((m) => [m.flow.id, m.reason])), [mains]);
  const found = useMemo(() => searchFlows(doc.flows, idx, q), [doc.flows, idx, q]);
  const foundIds = useMemo(() => new Set(found.flows.map((f) => f.id)), [found]);
  const matchCount = useMemo(() => new Map(groupFlows(found.flows, idx, grouping).map((g) => [g.key, g.flows.length])), [found, idx, grouping]);
  const totalMatches = found.flows.length;

  const flowId = search.get("flow");
  const sectionParam = search.get("section");
  const subParam = search.get("sub") ?? SUB_ALL;
  const section =
    sectionParam && sectionParam !== MAIN && (sectionParam === ALL || groups.some((g) => g.key === sectionParam))
      ? sectionParam
      : flowId && idx.flowsById.has(flowId) && !reasons.has(flowId)
        ? (groups.find((g) => g.flows.some((f) => f.id === flowId))?.key ?? groups[0].key)
        : q
          ? ALL
          : mains.length
            ? MAIN
            : groups[0].key;

  const navigate = useCallback(
    (patch: Record<string, string | null>, replace = false) => {
      const u = new URLSearchParams(search.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v) u.set(k, v);
        else u.delete(k);
      }
      const url = `${pathname}?${u.toString()}`;
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

  const inSection = useMemo(() => {
    if (section === MAIN) return mains.map((m) => m.flow);
    return rankFlows(section === ALL ? doc.flows : (groups.find((g) => g.key === section)?.flows ?? []), idx);
  }, [section, mains, doc.flows, groups, idx]);
  // A second level only for a real section: "All flows" has the rail itself as its level.
  const subgroups = useMemo(
    () => (section !== MAIN && section !== ALL && inSection.length > SUBGROUP_OVER ? subgroupFlows(inSection, idx, grouping) : []),
    [section, inSection, idx, grouping],
  );
  const sub = subgroups.some((g) => g.key === subParam) ? subParam : SUB_ALL;

  const shown = useMemo(() => {
    const pool = sub ? (subgroups.find((g) => g.key === sub)?.flows ?? []) : inSection;
    return q ? pool.filter((f) => foundIds.has(f.id)) : pool;
  }, [sub, subgroups, inSection, q, foundIds]);

  const rows = useMemo<BrowserRow[]>(() => {
    if (sub || !subgroups.length) return shown;
    const inShown = new Set(shown.map((f) => f.id));
    const out: BrowserRow[] = [];
    for (const g of subgroups) {
      const list = g.flows.filter((f) => inShown.has(f.id));
      if (!list.length) continue;
      out.push({ head: g.key, label: g.label, count: list.length });
      out.push(...list);
    }
    return out;
  }, [sub, subgroups, shown]);
  const openIndex = flowId ? rows.findIndex((r) => !isHead(r) && r.id === flowId) : -1;

  // Bring a linked or newly opened flow into view.
  useEffect(() => {
    if (flowId) document.getElementById(`flow-${flowId}`)?.scrollIntoView({ block: "nearest" });
  }, [flowId, section]);

  const rail = (key: string, label: string, n: number, total: number, depth = 0, active = section === key && !sub, onClick?: () => void) => (
    <li key={`${depth}:${key}`}>
      <button
        type="button"
        onClick={onClick ?? (() => navigate({ section: key, sub: null, flow: null }))}
        aria-current={active ? "true" : undefined}
        disabled={n === 0}
        className={cx(
          "flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left text-[12.5px] disabled:opacity-40",
          depth > 0 && "pl-5 text-[12px]",
          active ? "bg-[#1c2a10] text-accent" : "text-muted hover:bg-panel-2 hover:text-ink",
        )}
      >
        <span className="min-w-0 flex-1 truncate" title={label}>
          {label}
        </span>
        <span className="tnum shrink-0 text-[11px] text-faint">{n === total ? n : `${n}/${total}`}</span>
      </button>
    </li>
  );

  const heading = section === MAIN ? "Main flows" : section === ALL ? "All flows" : sub ? `${sectionLabel.get(section)} / ${subgroups.find((g) => g.key === sub)?.label}` : sectionLabel.get(section);

  return (
    <div className="flex h-full min-h-0">
      <nav aria-label="Flow sections" className="flex w-[260px] shrink-0 flex-col border-r border-line bg-panel/40">
        <div className="space-y-2 border-b border-line-soft p-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search flows and scenarios"
            title={`${doc.flows.length} flows and ${doc.scenarios.length} scenarios`}
            aria-label="Search flows and scenarios"
            className={cx(inputClass, "w-full text-[12.5px]")}
          />
          <div className="flex items-center gap-1.5">
            <Label htmlFor="flow-grouping">Group by</Label>
            <Select id="flow-grouping" value={grouping} onChange={(e) => navigate({ group: e.target.value, section: null, sub: null }, true)} className="h-7 min-w-0 flex-1 text-[12px]">
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
          {mains.length > 0 && !q && rail(MAIN, "Main flows (derived)", mains.length, mains.length)}
          {rail(ALL, "All flows", totalMatches, doc.flows.length)}
          <li className="mx-2 my-1 border-t border-line-soft" aria-hidden />
          {groups.flatMap((g) => {
            const row = rail(g.key, g.label, matchCount.get(g.key) ?? 0, g.flows.length);
            if (g.key !== section || !subgroups.length) return [row];
            return [
              row,
              ...subgroups.map((sg) => {
                const n = q ? sg.flows.filter((f) => foundIds.has(f.id)).length : sg.flows.length;
                return rail(sg.key, sg.label, n, sg.flows.length, 1, sub === sg.key, () => navigate({ section: g.key, sub: sg.key, flow: null }));
              }),
            ];
          })}
        </ul>
      </nav>
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1400px] space-y-3 p-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 className="text-[17px] font-semibold text-ink">{heading}</h2>
            <span className="text-[12px] text-faint">{q ? `${shown.length} of ${inSection.length} match “${q}”` : plural(shown.length, "flow")}</span>
            {q && section !== ALL && shown.length < totalMatches && (
              <button type="button" className="text-[12px] text-link hover:underline" onClick={() => navigate({ section: ALL, sub: null })}>
                show all {totalMatches} matches
              </button>
            )}
          </div>
          {section === MAIN ? (
            <p className="text-[12px] text-faint">Derived, not declared by the model: flows entered from outside it (a client or external caller) first, then those the most scenarios touch.</p>
          ) : (
            <p className="text-[12px] text-faint">Ordered by the same derived rule: entered from outside the model first, then by scenarios touching them.</p>
          )}
          {q ? <ScenarioHits scenarios={found.scenarios} idx={idx} /> : null}
          {shown.length === 0 ? (
            found.scenarios.length ? null : <Empty>No flows or scenarios match.</Empty>
          ) : (
            <WindowedList
              key={`${grouping}:${section}:${sub}:${q}`}
              items={rows}
              itemKey={(r) => (isHead(r) ? `head:${r.head}` : r.id)}
              ensure={openIndex}
              estimate={42}
              rowClassName="pb-1.5"
              render={(r) =>
                isHead(r) ? (
                  <h3 className="flex items-baseline gap-2 pb-0.5 pt-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">
                    <button type="button" className="hover:underline" onClick={() => navigate({ sub: r.head })}>
                      {r.label}
                    </button>
                    <span className="tnum font-normal text-faint">{r.count}</span>
                  </h3>
                ) : (
                  <FlowRow
                    flow={r}
                    idx={idx}
                    open={r.id === flowId}
                    section={section === ALL || section === MAIN ? sectionOf.get(r.id) : undefined}
                    reason={section === MAIN ? reasons.get(r.id) : undefined}
                    hits={q ? found.viaScenario.get(r.id) : undefined}
                    onToggle={() => navigate({ flow: r.id === flowId ? null : r.id, section, sub: sub || null })}
                  />
                )
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
