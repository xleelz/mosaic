"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { FIXTURE_MODE, errorMessage, getClient } from "@/lib/api";
import { requestOverrides } from "@/lib/api/fixtures";
import type { Document, EvidenceMechanism, Fault, JsonObject, JsonValue, Plan, Resolution, Scenario, SimulationRequest, SimulationRun, Topology } from "@/lib/api/types";
import { refinedComponents, resolutionOf } from "@/lib/model/hierarchy";
import { FaultTypes } from "@/lib/api/types";
import { deepMerge, formatDate, isPlainObject, jsonEqual, plural } from "@/lib/model/format";
import { planQueue, useDocIndex, useQuery } from "@/lib/hooks";
import {
  CALLED_GROUP,
  componentMechanisms,
  faultTargetOptions,
  filterOptions,
  flowTitle,
  nameOf,
  rankFlows,
  scenarioTitle,
  touchLabel,
  type DocIndex,
  type PickerOption,
} from "@/lib/model/docindex";
import { useEvidence } from "@/lib/evidence";
import { RunHeader, RunPlayback } from "@/components/playback/RunView";
import { Cel } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, Label, Notice, Panel, Select, Spinner, StatusBadge, cx, inputClass } from "@/components/ui";
import { WindowedList } from "@/components/WindowedList";
import { LazyDetails, scenarioMechanisms } from "./FlowsTab";
import { useDocument, useWorkspace } from "./Workspace";

interface FaultRow {
  key: number;
  target: string;
  type: string;
  code: string;
  status: string;
  latency_ms: string;
  calls: string;
}

function pretty(v: JsonValue | undefined): string {
  return v === undefined ? "" : JSON.stringify(v, null, 2);
}

function parseJson(text: string): { ok: true; value: JsonValue | undefined } | { ok: false; error: string } {
  if (!text.trim()) return { ok: true, value: undefined };
  try {
    return { ok: true, value: JSON.parse(text) as JsonValue };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

function JsonEditor({
  id,
  label,
  value,
  baseline,
  onChange,
  rows = 6,
  hint,
}: {
  id: string;
  label: React.ReactNode;
  value: string;
  baseline: string;
  onChange: (v: string) => void;
  rows?: number;
  hint?: string;
}) {
  const parsed = parseJson(value);
  const base = parseJson(baseline);
  const changed = parsed.ok && base.ok ? !jsonEqual(parsed.value ?? null, base.value ?? null) : value !== baseline;
  const lines = Math.min(16, Math.max(rows, value.split("\n").length));
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <label htmlFor={id} className="min-w-0 truncate text-[12px] text-ink">
          {label}
        </label>
        {changed && parsed.ok && <Badge tone="accent">override</Badge>}
        {!parsed.ok && <Badge tone="bad">invalid JSON</Badge>}
        {changed && (
          <button type="button" className="ml-auto text-[11px] text-link hover:underline" onClick={() => onChange(baseline)}>
            reset
          </button>
        )}
      </div>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        rows={lines}
        className={cx(
          "w-full resize-y rounded-md border bg-[#0c1116] px-2 py-1.5 font-mono text-[11.5px] leading-[1.45] text-ink",
          !parsed.ok ? "border-st-critical" : changed ? "border-[#4d6b1f]" : "border-line",
        )}
        aria-invalid={!parsed.ok}
        aria-describedby={!parsed.ok ? `${id}-err` : undefined}
      />
      {!parsed.ok && (
        <div id={`${id}-err`} className="text-[11px] text-bad">
          {parsed.error}
        </div>
      )}
      {hint && parsed.ok && <div className="text-[11px] text-faint">{hint}</div>}
    </div>
  );
}

/**
 * A searchable picker for lists too long for a native select: it renders a
 * short list of what matches, and says how many more there are. Enter picks the
 * highlighted option; Escape closes.
 */
function SearchPicker({
  id,
  value,
  valueLabel,
  options,
  onChange,
  placeholder,
  className,
  note,
  autoFocus,
}: {
  id: string;
  value: string;
  /** What to show when closed, if not the option's label. */
  valueLabel?: string;
  options: PickerOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  note?: React.ReactNode;
  autoFocus?: boolean;
}) {
  const [open, setOpen] = useState(!!autoFocus);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const { shown, total } = useMemo(() => (open ? filterOptions(options, query) : { shown: [], total: 0 }), [open, options, query]);
  const current = valueLabel ?? options.find((o) => o.value === value)?.label ?? value;
  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    setQuery("");
  };
  const listId = `${id}-list`;
  return (
    <div className={cx("relative", className)}>
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && shown[active] ? `${id}-opt-${active}` : undefined}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        value={open ? query : current}
        placeholder={open ? current || placeholder : placeholder}
        onFocus={(e) => {
          setOpen(true);
          setQuery("");
          setActive(0);
          e.target.select();
        }}
        onBlur={() => setOpen(false)}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setActive((a) => Math.min(a + 1, shown.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter" && open && shown[active]) {
            e.preventDefault();
            pick(shown[active].value);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        className={cx(inputClass, "w-full truncate font-mono text-[12px]")}
      />
      {open && (
        <div
          id={listId}
          role="listbox"
          // Keep focus in the input while the pointer is on the list.
          onMouseDown={(e) => e.preventDefault()}
          className="absolute left-0 top-full z-30 mt-1 max-h-[320px] w-full min-w-[320px] overflow-y-auto rounded-md border border-line bg-panel shadow-lg"
        >
          {note && <div className="border-b border-line-soft px-2 py-1 text-[11px] text-faint">{note}</div>}
          {shown.length === 0 && <div className="px-2 py-2 text-[12px] text-faint">Nothing matches.</div>}
          {shown.map((o, i) => (
            <div key={o.value || "__none"}>
              {o.group && o.group !== shown[i - 1]?.group && <div className="bg-panel-2/60 px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-[0.08em] text-faint">{o.group}</div>}
              <div
                id={`${id}-opt-${i}`}
                role="option"
                aria-selected={o.value === value}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(o.value)}
                className={cx("flex cursor-pointer items-baseline gap-2 px-2 py-1 text-[12px]", i === active ? "bg-panel-3 text-ink" : "text-muted")}
              >
                <span className="min-w-0 flex-1 truncate font-mono" title={o.label}>
                  {o.label}
                </span>
                {o.hint && <span className="max-w-[45%] shrink-0 truncate text-[11px] text-faint">{o.hint}</span>}
              </div>
            </div>
          ))}
          {total > shown.length && (
            <div className="px-2 py-1 text-[11px] text-faint">
              Showing {shown.length} of {total}: type to narrow.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StateRow({
  id,
  name,
  value,
  baseline,
  fromScenario,
  onChange,
}: {
  id: string;
  name: string;
  value: string;
  baseline: string;
  fromScenario: boolean;
  onChange: (v: string) => void;
}) {
  const changed = value !== baseline;
  return (
    <LazyDetails
      defaultOpen={changed}
      className="mb-1 rounded-md border border-line-soft bg-panel-2/30 px-2 py-1"
      summaryClassName="text-[12px] text-ink"
      summary={
        <>
          {name} <span className="font-mono text-[10.5px] text-faint">{id}</span>
          {changed && <span className="ml-1 text-[10.5px] text-accent">● override</span>}
          {fromScenario && <span className="ml-1 text-[10.5px] text-violet">scenario</span>}
        </>
      }
    >
      <div className="pt-1">
        <JsonEditor id={`state-${id}`} label={<span className="text-faint">state</span>} value={value} baseline={baseline} onChange={onChange} rows={4} />
      </div>
    </LazyDetails>
  );
}

/** Component state editors, collapsed and rendered on demand: a big model has hundreds. */
function StateEditors({
  plan,
  idx,
  scenario,
  baseline,
  edits,
  onEdit,
}: {
  plan: Plan;
  idx: DocIndex;
  scenario?: Scenario;
  baseline: (component: string) => string;
  edits: Record<string, string>;
  onEdit: (component: string, value: string) => void;
}) {
  const [filter, setFilter] = useState("");
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  const list = plan.state.filter((s) => {
    const hay = `${s.component} ${nameOf(idx, s.component)}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
  const edited = Object.keys(edits).length;
  const inScenario = Object.keys(scenario?.state ?? {}).length;
  return (
    <LazyDetails
      summaryClassName="text-[12px] text-ink"
      summary={
        <>
          Component state · {plan.state.length}
          {edited > 0 && <span className="ml-1 text-[11px] text-accent">{edited} edited</span>}
          {inScenario > 0 && <span className="ml-1 text-[11px] text-violet">{inScenario} set by the scenario</span>}
        </>
      }
    >
      <div className="mt-1 text-[11px] text-faint">Prefilled with the initial state{scenario?.state ? " and the scenario's overrides" : ""}. Edits merge into it.</div>
      {plan.state.length > 8 && (
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter components"
          aria-label="Filter stateful components"
          className={cx(inputClass, "my-1 w-full text-[12px]")}
        />
      )}
      <div className="max-h-[420px] overflow-y-auto">
        <WindowedList
          items={list}
          itemKey={(s) => s.component}
          estimate={30}
          render={(s) => (
            <StateRow
              id={s.component}
              name={nameOf(idx, s.component)}
              value={edits[s.component] ?? baseline(s.component)}
              baseline={baseline(s.component)}
              fromScenario={!!scenario?.state?.[s.component]}
              onChange={(v) => onEdit(s.component, v)}
            />
          )}
        />
      </div>
    </LazyDetails>
  );
}

function faultFromRow(r: FaultRow): Fault | null {
  if (!r.target || !r.type) return null;
  const f: Fault = { target: r.target, type: r.type };
  if (r.code.trim()) f.code = r.code.trim();
  if (r.status.trim() && Number.isFinite(Number(r.status))) f.status = Number(r.status);
  if (r.type === "latency" && r.latency_ms.trim() && Number.isFinite(Number(r.latency_ms))) f.latency_ms = Number(r.latency_ms);
  const calls = r.calls
    .split(/[\s,]+/)
    .map((x) => Number(x))
    .filter((x) => Number.isInteger(x) && x > 0);
  if (calls.length) f.calls = calls;
  return f;
}

function faultText(f: Fault): string {
  return [f.code && `code=${f.code}`, f.status && `status=${f.status}`, f.latency_ms && `+${f.latency_ms}ms`, f.calls?.length && `calls=${f.calls.join(",")}`]
    .filter(Boolean)
    .join(" ");
}

let faultKey = 1;

function blankFault(target: string): FaultRow {
  return { key: faultKey++, target, type: "unavailable", code: "", status: "", latency_ms: "", calls: "" };
}

/** Before the run: what the model says it doesn't know about this target's failure handling. */
function FailureHandlingNote({ target, idx, mechanisms }: { target: string; idx: DocIndex; mechanisms?: EvidenceMechanism[] }) {
  if (!target || !mechanisms) return null;
  const component = idx.interfacesById.get(target)?.component ?? target;
  if (!idx.componentsById.has(component)) return null;
  const gaps = componentMechanisms(idx, component, mechanisms).absentFailureHandling;
  if (gaps.length === 0) return null;
  return (
    <div className="mt-1.5 rounded border border-dashed border-line px-2 py-1 text-[11.5px] text-muted" title={gaps.map((m) => m.name).join("\n")}>
      Before you run: this area lists {plural(gaps.length, "failure-handling mechanism")} as absent from the model, such as {gaps[0].name}. The run can&apos;t show those.
    </div>
  );
}

/** "comp=a,b,c" lines -> a topology; bad lines are reported. */
export function parseTopology(text: string): { value: Topology; errors: string[] } {
  const value: Topology = {};
  const errors: string[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const eq = line.indexOf("=");
    const comp = eq > 0 ? line.slice(0, eq).trim() : "";
    if (!comp) {
      errors.push(`"${line}" is not comp=a,b,c`);
      continue;
    }
    value[comp] = line
      .slice(eq + 1)
      .split(/[\s,]+/)
      .filter(Boolean);
  }
  return { value, errors };
}

/** "id=value" lines -> config overrides; a value is JSON, or else a string. */
export function parseConfig(text: string): { value: JsonObject; errors: string[] } {
  const value: JsonObject = {};
  const errors: string[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const eq = line.indexOf("=");
    const id = eq > 0 ? line.slice(0, eq).trim() : "";
    if (!id) {
      errors.push(`"${line}" is not id=value`);
      continue;
    }
    const v = line.slice(eq + 1).trim();
    try {
      value[id] = JSON.parse(v) as JsonValue;
    } catch {
      value[id] = v;
    }
  }
  return { value, errors };
}

const isRFC3339 = (s: string) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(s) && !Number.isNaN(Date.parse(s));

function SimulateForm({ doc, plan, flowId, scenario, rev, initialFault }: { doc: Document; plan: Plan; flowId: string; scenario?: Scenario; rev: string; initialFault?: string }) {
  const ws = useWorkspace();
  const evidence = useEvidence(ws.id, rev);
  const idx = useDocIndex(doc);
  const flow = idx.flowsById.get(flowId);

  // Baselines: what the engine would use with no request overrides.
  const baseInput = useMemo(() => pretty(deepMerge(flow?.entry?.input, scenario?.input)), [flow, scenario]);
  // Pretty-printed on demand: a big model has hundreds of states, and few get opened.
  const baseState = useMemo(() => {
    const byComponent = new Map(plan.state.map((s) => [s.component, s]));
    return (component: string) => pretty(deepMerge(byComponent.get(component)?.initial ?? {}, scenario?.state?.[component]) ?? {});
  }, [plan, scenario]);
  const baseSeed = scenario?.seed !== undefined ? String(scenario.seed) : "";

  const [choices, setChoices] = useState<Record<string, string>>({});
  const [faults, setFaults] = useState<FaultRow[]>(() => (initialFault ? [blankFault(initialFault)] : []));
  // Fault targets start from what a default run calls; the first fault asks for that run.
  const [wantCalls, setWantCalls] = useState(!!initialFault);
  const defaultRun = useQuery(wantCalls ? `default-calls:${ws.id}:${ws.dataRev}:${flowId}:${scenario?.id ?? ""}` : null, async (c) => {
    const r = await c.runSimulation(ws.id, scenario ? { rev, scenario: scenario.id, save: false } : { rev, flow: flowId, save: false });
    return r.summary.calls;
  });
  const [inputText, setInputText] = useState(baseInput);
  const [stateEdits, setStateEdits] = useState<Record<string, string>>({});
  const [seed, setSeed] = useState(baseSeed);
  const [expectText, setExpectText] = useState("");
  const [fixtures, setFixtures] = useState<string[]>([]);
  const [topologyText, setTopologyText] = useState("");
  const [configText, setConfigText] = useState("");
  const [epoch, setEpoch] = useState("");
  const refined = useMemo(() => refinedComponents(doc), [doc]);
  const [resolution, setResolution] = useState<Record<string, Resolution>>(() =>
    Object.fromEntries(refined.map((c) => [c.id, resolutionOf(scenario?.resolution, c.id)])),
  );
  const [save, setSave] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [run, setRun] = useState<SimulationRun | null>(null);
  // mosaicd returns an id even for unsaved runs, but only saved ones can be fetched again.
  const [runSaved, setRunSaved] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);

  const parsedInput = parseJson(inputText);
  const parsedStates = Object.fromEntries(Object.entries(stateEdits).map(([c, t]) => [c, parseJson(t)]));
  const topology = parseTopology(topologyText);
  const config = parseConfig(configText);
  const epochBad = epoch.trim() !== "" && !isRFC3339(epoch.trim());
  const invalid =
    !parsedInput.ok ||
    Object.values(parsedStates).some((p) => !p.ok) ||
    (seed.trim() !== "" && !/^-?\d+$/.test(seed.trim())) ||
    topology.errors.length > 0 ||
    config.errors.length > 0 ||
    epochBad ||
    faults.some((r) => !r.target);

  const buildRequest = (): SimulationRequest => {
    // A scenario knows what it runs; the selected flow is only where it was picked from.
    const req: SimulationRequest = scenario ? { rev, scenario: scenario.id } : { rev, flow: flowId };
    if (!FIXTURE_MODE) req.save = save;
    const ch = Object.fromEntries(Object.entries(choices).filter(([, v]) => v));
    if (Object.keys(ch).length) req.choices = ch;
    const fs = faults.map(faultFromRow).filter((f): f is Fault => f !== null);
    if (fs.length) req.faults = fs;
    const baseIn = parseJson(baseInput);
    if (parsedInput.ok && baseIn.ok && !jsonEqual(parsedInput.value ?? null, baseIn.value ?? null) && parsedInput.value !== undefined) {
      req.input = parsedInput.value;
    }
    const st: Record<string, JsonObject> = {};
    for (const [c, p] of Object.entries(parsedStates)) {
      const b = parseJson(baseState(c));
      if (p.ok && b.ok && isPlainObject(p.value) && !jsonEqual(p.value, b.value ?? null)) st[c] = p.value as JsonObject;
    }
    if (Object.keys(st).length) req.state = st;
    if (seed.trim() !== "" && seed.trim() !== baseSeed) req.seed = Number(seed.trim());
    const ex = expectText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (ex.length) req.expect = ex;
    if (fixtures.length) req.fixtures = fixtures;
    if (Object.keys(topology.value).length) req.topology = topology.value;
    if (Object.keys(config.value).length) req.config = config.value;
    if (epoch.trim() && !epochBad) req.clock = { epoch: epoch.trim() };
    // Only choices that differ from the scenario's (default black_box) go in the request.
    const res = Object.fromEntries(Object.entries(resolution).filter(([c, v]) => v !== resolutionOf(scenario?.resolution, c)));
    if (Object.keys(res).length) req.resolution = res;
    return req;
  };

  const req = buildRequest();
  const overrides = requestOverrides(req);

  const doRun = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await getClient().runSimulation(ws.id, req);
      setRun(r);
      setRunSaved(req.save !== false);
      setCollapsed(true);
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (err) {
      setError(err);
    } finally {
      setRunning(false);
    }
  };

  const targetOptions = useMemo(() => faultTargetOptions(plan.faultable, defaultRun.data, plan.entry, idx), [plan, defaultRun.data, idx]);
  const calledCount = targetOptions.filter((o) => o.group === CALLED_GROUP).length;
  const targetsNote = defaultRun.loading
    ? "Running the flow once with defaults, to see what it calls..."
    : defaultRun.error
      ? `No default run to start from (${errorMessage(defaultRun.error)}), so this is everything it could reach.`
      : calledCount > 0
        ? `Starting from the ${calledCount} targets a default run calls. Type to search all ${plan.faultable.length}.`
        : undefined;
  const mechanisms = evidence.evidence?.mechanisms?.items;

  const runButton = (
    <Button variant="primary" onClick={doRun} disabled={running || invalid} className="h-9 px-4 text-[14px]">
      {running ? "Running…" : "▶ Run simulation"}
    </Button>
  );

  return (
    <div className="space-y-3">
      {collapsed && run ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2">
          <span className="text-[12px] text-faint">Configured</span>
          <span className="text-[12.5px] text-ink">
            {scenario ? scenario.name || scenario.id : `ad hoc · ${flow?.name || flowId}`}
          </span>
          {overrides.length > 0 ? <Badge tone="accent">overrides: {overrides.join(", ")}</Badge> : <Badge>no overrides</Badge>}
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" onClick={() => setCollapsed(false)}>
              Edit configuration
            </Button>
            {runButton}
          </div>
        </div>
      ) : (
        <>
          <div className="sticky top-0 z-20 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2.5">
            {runButton}
            <div className="flex items-center gap-2">
              <Label htmlFor="seed">Seed</Label>
              <input id="seed" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={baseSeed || "1"} inputMode="numeric" className={cx(inputClass, "w-24 tnum", seed.trim() !== "" && !/^-?\d+$/.test(seed.trim()) && "border-st-critical")} />
            </div>
            {!FIXTURE_MODE && (
              <label className="flex items-center gap-1.5 text-[12px] text-muted">
                <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} className="accent-[#ccff78]" />
                Save the run
              </label>
            )}
            <div className="min-w-0 flex-1 text-[12px] text-faint">
              {overrides.length ? (
                <>
                  Overrides: <span className="text-ink">{overrides.join(", ")}</span>
                </>
              ) : scenario ? (
                "No overrides: runs the scenario as written."
              ) : (
                "Ad hoc run of the flow with defaults and generated input."
              )}
            </div>
            {FIXTURE_MODE && (overrides.length > 0 || !scenario) && (
              <Badge tone="warn" title="Fixture mode can only replay recorded scenario runs">
                needs mosaicd
              </Badge>
            )}
            {run && (
              <Button size="sm" variant="ghost" onClick={() => setCollapsed(true)}>
                Collapse
              </Button>
            )}
          </div>

          <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-3">
            <Panel title={`Open decisions · ${plan.choices.length}`}>
              {plan.choices.length === 0 ? (
                <div className="text-[12px] text-faint">No open decisions are reachable from this flow.</div>
              ) : (
                <div className="max-h-[420px] overflow-y-auto">
                  <WindowedList
                    items={plan.choices}
                    itemKey={(c) => c.key}
                    estimate={64}
                    rowClassName="pb-2.5"
                    render={(c) => {
                    const fromScenario = scenario?.choices?.[c.key];
                    const fallback = fromScenario ? `scenario: ${fromScenario}` : `default: ${c.default ?? c.options[0]}`;
                    const id = `choice-${c.key}`;
                    return (
                      <div>
                        <label htmlFor={id} className="mb-0.5 block font-mono text-[11.5px] text-ink">
                          {c.key}
                        </label>
                        {c.title && <div className="text-[11px] text-faint">{c.title}</div>}
                        <Select id={id} value={choices[c.key] ?? ""} onChange={(e) => setChoices((m) => ({ ...m, [c.key]: e.target.value }))} className="mt-0.5 w-full">
                          <option value="">— no override ({fallback}) —</option>
                          {c.options.map((o) => (
                            <option key={o} value={o}>
                              {o}
                              {o === c.default ? "  ★ default" : ""}
                              {o === fromScenario ? "  (scenario)" : ""}
                            </option>
                          ))}
                        </Select>
                      </div>
                    );
                    }}
                  />
                </div>
              )}
              <div className="mt-4 border-t border-line-soft pt-3">
                <Label htmlFor="expect">Expectations</Label>
                {scenario?.expect?.length ? (
                  <ul className="mb-2 mt-1 space-y-0.5">
                    {scenario.expect.map((e, i) => (
                      <li key={i} className="flex items-baseline gap-1.5 text-[12px]">
                        <span className="text-faint">▸</span>
                        <Cel>{e}</Cel>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="mb-1 mt-0.5 text-[11.5px] text-faint">{scenario ? "The scenario has none." : "Ad hoc runs have none unless you add some."}</div>
                )}
                <textarea
                  id="expect"
                  value={expectText}
                  onChange={(e) => setExpectText(e.target.value)}
                  rows={2}
                  spellCheck={false}
                  placeholder={"Extra CEL, one per line, e.g.\nresult.ok && retries <= 1"}
                  className="w-full rounded-md border border-line bg-[#0c1116] px-2 py-1.5 font-mono text-[11.5px] text-ink placeholder:text-faint"
                />
              </div>
            </Panel>

            <Panel
              title={`Faults · ${(scenario?.faults?.length ?? 0) + faults.length}`}
              actions={
                <Button
                  size="sm"
                  onClick={() => {
                    setWantCalls(true);
                    setFaults((fs) => [...fs, blankFault("")]);
                  }}
                  disabled={plan.faultable.length === 0}
                >
                  + Add fault
                </Button>
              }
            >
              {scenario?.faults?.length ? (
                <div className="mb-2">
                  <div className="mb-1 text-[11px] text-faint">From the scenario (always applied)</div>
                  <ul className="space-y-0.5">
                    {scenario.faults.map((f, i) => (
                      <li key={i} className="rounded border border-line-soft bg-panel-2/50 px-2 py-1 font-mono text-[11.5px]">
                        <span className="text-[#f5b294]">⚡ {f.type}</span> <span className="text-ink">{f.target}</span> <span className="text-faint">{faultText(f)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {faults.length === 0 ? (
                <div className="text-[12px] text-faint">
                  {plan.faultable.length} faultable targets. Add a fault to make a component or interface unavailable, fail, slow down or hang.
                </div>
              ) : (
                <div className="space-y-2">
                  {faults.map((r, i) => {
                    const upd = (patch: Partial<FaultRow>) => setFaults((fs) => fs.map((x) => (x.key === r.key ? { ...x, ...patch } : x)));
                    const p = `fault-${r.key}`;
                    return (
                      <fieldset key={r.key} className="rounded-md border border-line bg-panel-2/40 p-2">
                        <legend className="sr-only">Fault {i + 1}</legend>
                        <div className="grid grid-cols-[1fr_auto] gap-1.5">
                          <div>
                            <label htmlFor={`${p}-target`} className="text-[10.5px] text-faint">
                              target
                            </label>
                            <SearchPicker
                              id={`${p}-target`}
                              value={r.target}
                              options={targetOptions}
                              onChange={(target) => upd({ target })}
                              placeholder="Search what to fail"
                              note={targetsNote}
                              autoFocus={!r.target}
                            />
                          </div>
                          <div>
                            <label htmlFor={`${p}-type`} className="text-[10.5px] text-faint">
                              type
                            </label>
                            <Select id={`${p}-type`} value={r.type} onChange={(e) => upd({ type: e.target.value })} className="w-full">
                              {FaultTypes.map((t) => (
                                <option key={t} value={t}>
                                  {t}
                                </option>
                              ))}
                            </Select>
                          </div>
                        </div>
                        <div className="mt-1.5 grid grid-cols-[1.3fr_0.8fr_0.9fr_0.9fr_auto] items-end gap-1.5">
                          <div>
                            <label htmlFor={`${p}-code`} className="text-[10.5px] text-faint">
                              code
                            </label>
                            <input id={`${p}-code`} value={r.code} onChange={(e) => upd({ code: e.target.value })} placeholder={r.type === "unavailable" ? "unavailable" : r.type === "error" ? "upstream_error" : ""} className={cx(inputClass, "w-full font-mono text-[12px]")} />
                          </div>
                          <div>
                            <label htmlFor={`${p}-status`} className="text-[10.5px] text-faint">
                              status
                            </label>
                            <input id={`${p}-status`} value={r.status} onChange={(e) => upd({ status: e.target.value.replace(/[^\d]/g, "") })} inputMode="numeric" placeholder={r.type === "unavailable" ? "503" : ""} className={cx(inputClass, "w-full tnum")} />
                          </div>
                          <div>
                            <label htmlFor={`${p}-lat`} className="text-[10.5px] text-faint">
                              latency_ms
                            </label>
                            <input id={`${p}-lat`} value={r.latency_ms} onChange={(e) => upd({ latency_ms: e.target.value.replace(/[^\d]/g, "") })} inputMode="numeric" disabled={r.type !== "latency"} placeholder={r.type === "latency" ? "500" : "—"} className={cx(inputClass, "w-full tnum disabled:opacity-40")} />
                          </div>
                          <div>
                            <label htmlFor={`${p}-calls`} className="text-[10.5px] text-faint">
                              calls
                            </label>
                            <input id={`${p}-calls`} value={r.calls} onChange={(e) => upd({ calls: e.target.value.replace(/[^\d,\s]/g, "") })} placeholder="all" title="1-based invocations of the target, e.g. 1,3" className={cx(inputClass, "w-full font-mono text-[12px]")} />
                          </div>
                          <Button size="sm" variant="ghost" onClick={() => setFaults((fs) => fs.filter((x) => x.key !== r.key))} aria-label={`Remove fault ${i + 1}`} className="h-8">
                            ✕
                          </Button>
                        </div>
                        <FailureHandlingNote target={r.target} idx={idx} mechanisms={mechanisms} />
                      </fieldset>
                    );
                  })}
                </div>
              )}
            </Panel>

            <Panel title="Input & state overrides">
              <div className="space-y-3">
                <JsonEditor
                  id="input-override"
                  label={
                    <>
                      entry input <span className="font-mono text-[11px] text-faint">{plan.entry}</span>
                    </>
                  }
                  value={inputText}
                  baseline={baseInput}
                  onChange={setInputText}
                  rows={3}
                  hint="Merged over input generated from the request schema; strings starting with = are CEL."
                />
                <StateEditors
                  plan={plan}
                  idx={idx}
                  scenario={scenario}
                  baseline={baseState}
                  edits={stateEdits}
                  onEdit={(c, v) =>
                    setStateEdits((m) => {
                      const next = { ...m };
                      if (v === baseState(c)) delete next[c];
                      else next[c] = v;
                      return next;
                    })
                  }
                />
              </div>
            </Panel>
          </div>

          <WorldPanel
            doc={doc}
            scenario={scenario}
            fixtures={fixtures}
            setFixtures={setFixtures}
            topologyText={topologyText}
            setTopologyText={setTopologyText}
            topologyErrors={topology.errors}
            configText={configText}
            setConfigText={setConfigText}
            configErrors={config.errors}
            epoch={epoch}
            setEpoch={setEpoch}
            epochBad={epochBad}
          />

          {refined.length > 0 && (
            <ResolutionPanel doc={doc} scenario={scenario} value={resolution} onChange={(c, v) => setResolution((m) => ({ ...m, [c]: v }))} />
          )}

        </>
      )}

      {error ? <ErrorBox error={error} /> : null}

      {run && (
        <div ref={resultRef} className="scroll-mt-2 space-y-2">
          <RunHeader
            run={run}
            scenarioName={scenario?.name}
            actions={
              run.id && runSaved ? (
                <Link href={ws.href(`runs/${encodeURIComponent(run.id)}`)} className="rounded border border-line px-1.5 py-0.5 text-link hover:bg-panel-2">
                  Open full view
                </Link>
              ) : null
            }
          />
          <div className="flex h-[calc(100dvh-10.5rem)] min-h-[640px] flex-col">
            <RunPlayback key={`${run.id}:${run.created_at}`} run={run} ontology={ws.id} className="min-h-0 flex-1" />
          </div>
        </div>
      )}
    </div>
  );
}

/** §14.5: per refined component, its contract (black box) or its child model (refined). */
function ResolutionPanel({
  doc,
  scenario,
  value,
  onChange,
}: {
  doc: Document;
  scenario?: Scenario;
  value: Record<string, Resolution>;
  onChange: (component: string, v: Resolution) => void;
}) {
  const refined = refinedComponents(doc);
  const opened = refined.filter((c) => value[c.id] === "refined").length;
  return (
    <Panel title={`Resolution · ${opened} of ${refined.length} refined`}>
      <div className="mb-2 text-[11.5px] text-faint">
        A black box runs the component&apos;s contract and latency; refined runs its child model in its place, loaded from the store by{" "}
        <span className="font-mono">refined_by</span>. Child components appear as <span className="font-mono">&lt;component&gt;/&lt;child&gt;</span>.
      </div>
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
        {refined.map((c) => {
          const fromScenario = scenario?.resolution?.[c.id];
          const cur = value[c.id] ?? "black_box";
          return (
            <li key={c.id} className="rounded-md border border-line-soft bg-panel-2/40 px-2 py-1.5">
              <div className="flex items-baseline gap-1.5">
                <span className="text-[12.5px] text-ink">{c.name || c.id}</span>
                <span className="font-mono text-[10.5px] text-faint">{c.id}</span>
                {fromScenario && <span className="ml-auto text-[10.5px] text-violet">scenario: {fromScenario}</span>}
              </div>
              <div className="font-mono text-[10.5px] text-faint">
                ⤢ {c.refined_by!.map((r) => `${r.ontology}${r.revision ? `@${r.revision}` : ""}`).join(", ")}
              </div>
              <div className="mt-1 flex gap-1" role="radiogroup" aria-label={`Resolution of ${c.name || c.id}`}>
                {(["black_box", "refined"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    role="radio"
                    aria-checked={cur === v}
                    onClick={() => onChange(c.id, v)}
                    className={cx(
                      "h-7 rounded-md border px-2 text-[12px]",
                      cur === v ? "border-accent bg-[#1c2a10] text-accent" : "border-line bg-panel-2 text-muted hover:text-ink",
                    )}
                  >
                    {v === "black_box" ? "■ black box" : "⤢ refined"}
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

const areaClass =
  "w-full rounded-md border bg-[#0c1116] px-2 py-1.5 font-mono text-[11.5px] text-ink placeholder:text-faint";

/** Run-request world overrides (§13.1 item 6): world setups (fixtures), topology, config and clock. */
function WorldPanel(p: {
  doc: Document;
  scenario?: Scenario;
  fixtures: string[];
  setFixtures: (f: string[]) => void;
  topologyText: string;
  setTopologyText: (v: string) => void;
  topologyErrors: string[];
  configText: string;
  setConfigText: (v: string) => void;
  configErrors: string[];
  epoch: string;
  setEpoch: (v: string) => void;
  epochBad: boolean;
}) {
  const all = p.doc.fixtures ?? [];
  const configs = p.doc.configs ?? [];
  const toggle = (id: string) => p.setFixtures(p.fixtures.includes(id) ? p.fixtures.filter((x) => x !== id) : [...p.fixtures, id]);
  return (
    <Panel title="World setup (fixture) · topology, config, clock">
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-4">
        <div>
          <Label>World setup (fixture)</Label>
          {p.scenario?.fixtures?.length ? (
            <div className="mb-1 mt-0.5 text-[11px] text-faint">
              Scenario applies <span className="font-mono text-ink">{p.scenario.fixtures.join(", ")}</span> first.
            </div>
          ) : null}
          {all.length === 0 ? (
            <div className="mt-0.5 text-[12px] text-faint">The model has no world setups (fixtures).</div>
          ) : (
            <div className="mt-1 max-h-[180px] overflow-y-auto">
              <WindowedList
                label="World setups to apply, in order"
                items={all}
                itemKey={(f) => f.id}
                estimate={22}
                render={(f) => {
                  const i = p.fixtures.indexOf(f.id);
                  return (
                    <label className="flex items-baseline gap-1.5 pb-0.5 text-[12px] text-ink">
                      <input type="checkbox" checked={i >= 0} onChange={() => toggle(f.id)} className="accent-[#ccff78]" />
                      <span className="font-mono">{f.id}</span>
                      {i >= 0 && <span className="tnum text-[10.5px] text-accent">#{i + 1}</span>}
                      {f.summary && <span className="truncate text-[11px] text-faint">{f.summary}</span>}
                    </label>
                  );
                }}
              />
            </div>
          )}
        </div>
        <div>
          <Label htmlFor="topology-override">Topology overrides</Label>
          <textarea
            id="topology-override"
            value={p.topologyText}
            onChange={(e) => p.setTopologyText(e.target.value)}
            rows={3}
            spellCheck={false}
            placeholder={"One per line: component=a,b,c\ne.g. cassandra-node=n1,n2,n3"}
            className={cx(areaClass, "mt-0.5", p.topologyErrors.length ? "border-st-critical" : "border-line")}
          />
          {p.topologyErrors.map((e) => (
            <div key={e} className="text-[11px] text-bad">
              {e}
            </div>
          ))}
        </div>
        <div>
          <Label htmlFor="config-override">Config overrides</Label>
          <textarea
            id="config-override"
            value={p.configText}
            onChange={(e) => p.setConfigText(e.target.value)}
            rows={3}
            spellCheck={false}
            placeholder={`One per line: id=value (JSON, else a string)${configs[0] ? `\ne.g. ${configs[0].id}=${JSON.stringify(configs[0].value ?? configs[0].default ?? "")}` : ""}`}
            className={cx(areaClass, "mt-0.5", p.configErrors.length ? "border-st-critical" : "border-line")}
          />
          {p.configErrors.map((e) => (
            <div key={e} className="text-[11px] text-bad">
              {e}
            </div>
          ))}
          {configs.length > 0 && (
            <div className="text-[11px] text-faint">
              {configs.length} configs: <span className="font-mono">{configs.slice(0, 6).map((c) => c.id).join(", ")}{configs.length > 6 ? ", …" : ""}</span>
            </div>
          )}
        </div>
        <div>
          <Label htmlFor="clock-epoch">Clock epoch</Label>
          <input
            id="clock-epoch"
            value={p.epoch}
            onChange={(e) => p.setEpoch(e.target.value)}
            placeholder={p.scenario?.clock?.epoch ?? "2026-10-30T00:00:00Z"}
            spellCheck={false}
            className={cx(inputClass, "mt-0.5 w-full font-mono text-[12px]", p.epochBad && "border-st-critical")}
            aria-invalid={p.epochBad}
          />
          <div className={cx("text-[11px]", p.epochBad ? "text-bad" : "text-faint")}>{p.epochBad ? "Not an RFC 3339 time." : "RFC 3339; now = epoch + virtual ms."}</div>
        </div>
      </div>
    </Panel>
  );
}

function RecentRuns() {
  const ws = useWorkspace();
  const runs = useQuery(`runs:${ws.id}`, (c) => c.listRuns(ws.id, 20));
  if (runs.loading) return <Spinner label="Loading runs" />;
  if (runs.error) return <ErrorBox error={runs.error} onRetry={runs.reload} />;
  const list = runs.data?.runs ?? [];
  if (list.length === 0) return <Empty>No saved runs yet.</Empty>;
  return (
    <ul className="divide-y divide-line-soft">
      {list.map((r) => (
        <li key={r.id}>
          <Link href={ws.href(`runs/${encodeURIComponent(r.id)}`)} className="flex items-center gap-2 px-1 py-1.5 text-[12px] hover:bg-panel-2">
            <StatusBadge status={r.summary.status} />
            <span className="min-w-0 flex-1 truncate text-ink">{r.scenario || `ad hoc · ${r.flow}`}</span>
            {r.summary.steps && r.summary.steps.length > 0 && <Badge tone="info">{plural(r.summary.steps.length, "step")}</Badge>}
            {r.summary.assertions.length > 0 && (
              <span className={r.summary.passed ? "text-muted" : "text-bad"} title={r.summary.passed ? "Its own expectations hold: a self-check, not proof" : "Its own expectations don't hold"}>
                {r.summary.passed ? "✓" : "✗"}
              </span>
            )}
            <span className="tnum text-faint">{formatDate(r.created_at)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function SimulateTab() {
  const ws = useWorkspace();
  const doc = useDocument();
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const flows = useMemo(() => doc.data?.flows.filter((f) => f.entry) ?? [], [doc.data]);
  const scenarioParam = search.get("scenario") ?? "";
  const idx = useDocIndex(doc.data);
  const scenarioDoc = scenarioParam ? idx?.scenariosById.get(scenarioParam) : undefined;
  // A scenario can touch several flows: keep the one it was picked from.
  const flowParam = search.get("flow");
  const scenarioFlows = scenarioDoc ? idx?.flowsOfScenario.get(scenarioDoc.id) : undefined;
  const flowId = (flowParam && scenarioFlows?.includes(flowParam) ? flowParam : scenarioFlows?.[0]) || flowParam || flows[0]?.id || "";
  const flowOptions = useMemo<PickerOption[]>(() => {
    if (!idx) return [];
    return rankFlows(flows, idx).map((f) => {
      const t = flowTitle(f);
      return { value: f.id, label: t.from === "id" ? "Unnamed flow" : t.text, hint: f.id };
    });
  }, [flows, idx]);
  const scenarioOptions = useMemo<PickerOption[]>(() => {
    const touches = idx?.touchesByFlow.get(flowId) ?? [];
    const option = (s: Scenario, hint?: string): PickerOption => {
      const t = scenarioTitle(s);
      return { value: s.id, label: t.from === "id" ? "Unnamed scenario" : t.text, hint: hint || s.id };
    };
    const out: PickerOption[] = [{ value: "", label: "None: ad hoc run of the flow" }, ...touches.map((t) => option(t.scenario, touchLabel(t)))];
    // Picked elsewhere, and touching no flow here: still show what's selected.
    if (scenarioDoc && !touches.some((t) => t.scenario.id === scenarioDoc.id)) out.splice(1, 0, option(scenarioDoc));
    return out;
  }, [idx, flowId, scenarioDoc]);
  const plan = useQuery(flowId ? `plan:${ws.id}:${ws.dataRev}:${flowId}` : null, (c) => planQueue(() => c.getPlan(ws.id, flowId, ws.rev)));
  const [showRuns, setShowRuns] = useState(false);

  const setParams = (patch: Record<string, string | null>) => {
    const q = new URLSearchParams(search.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v) q.set(k, v);
      else q.delete(k);
    }
    router.replace(`${pathname}?${q.toString()}`, { scroll: false });
  };

  // Drop a scenario that belongs to another flow.
  useEffect(() => {
    if (scenarioParam && doc.data && !scenarioDoc) setParams({ scenario: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioParam, doc.data, scenarioDoc]);

  if (doc.error) return <div className="p-4"><ErrorBox error={doc.error} onRetry={doc.reload} /></div>;
  if (!doc.data) return <Spinner label="Loading" />;
  if (flows.length === 0) return <div className="p-4"><Empty>No flow with an entry to simulate.</Empty></div>;

  const flowDoc = idx?.flowsById.get(flowId);

  return (
    <div className="space-y-3 p-3">
      {FIXTURE_MODE && (
        <Notice tone="warn" title="Fixture mode">
          Running a scenario without overrides replays its recorded run (generated by the real engine). Ad hoc flow runs and any
          override need a live mosaicd; the form still shows the exact request it would send.
        </Notice>
      )}
      <div className="rounded-lg border border-line bg-panel px-3 py-2.5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex w-[320px] max-w-full flex-col gap-0.5">
            <Label htmlFor="sim-flow">Flow</Label>
            <SearchPicker id="sim-flow" value={flowId} valueLabel={flowDoc ? (flowTitle(flowDoc).from === "id" ? `Unnamed flow (${flowId})` : flowTitle(flowDoc).text) : flowId} options={flowOptions} onChange={(v) => setParams({ flow: v, scenario: null, fault: null })} placeholder="Search flows" />
          </div>
          <div className="flex w-[360px] max-w-full flex-col gap-0.5">
            <Label htmlFor="sim-scenario">Scenario</Label>
            <SearchPicker id="sim-scenario" value={scenarioDoc?.id ?? ""} options={scenarioOptions} onChange={(v) => setParams({ flow: flowId, scenario: v || null })} placeholder="Search scenarios" />
          </div>
          <div className="ml-auto flex items-center gap-2 text-[12px] text-faint">
            revision <span className="font-mono text-ink">{ws.rev === "draft" || ws.rev === "latest" ? ws.rev : `r${ws.rev}`}</span>
            <Button size="sm" variant="ghost" onClick={() => setShowRuns((s) => !s)} aria-expanded={showRuns}>
              {showRuns ? "Hide" : "Recent"} runs
            </Button>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1 text-[12px] text-muted">
          {scenarioDoc ? (
            <>
              {!scenarioFlows?.length && (
                <p className="mr-1 basis-full text-faint">This scenario&apos;s steps call interfaces directly and touch no flow. The run uses the scenario; the flow above only fills the form&apos;s lists.</p>
              )}
              {scenarioDoc.description && <p className="mr-1 line-clamp-2 max-w-4xl basis-full" title={scenarioDoc.description}>{scenarioDoc.description}</p>}
              {scenarioMechanisms(scenarioDoc).map((m) => (
                <Badge key={m.label} tone={m.tone} className="max-w-full truncate">
                  {m.label}
                </Badge>
              ))}
              {scenarioMechanisms(scenarioDoc).length === 0 && <span className="text-faint">Runs the flow with its defaults and checks expectations.</span>}
            </>
          ) : flowDoc?.description ? (
            <p className="line-clamp-2 max-w-4xl" title={flowDoc.description}>
              {flowDoc.description}
            </p>
          ) : (
            <span className="text-faint">No description in the model.</span>
          )}
        </div>
      </div>
      {showRuns && (
        <Panel title="Recent runs" className="max-h-[300px]" bodyClassName="overflow-auto p-2">
          <RecentRuns />
        </Panel>
      )}
      {plan.loading && <Spinner label="Loading the flow's plan" />}
      {plan.error ? <ErrorBox error={plan.error} onRetry={plan.reload} /> : null}
      {plan.data && (
        <SimulateForm
          key={`${flowId}:${scenarioDoc?.id ?? ""}:${ws.rev}:${search.get("fault") ?? ""}`}
          initialFault={search.get("fault") ?? undefined}
          doc={doc.data}
          plan={plan.data}
          flowId={flowId}
          scenario={scenarioDoc}
          rev={ws.rev}
        />
      )}
    </div>
  );
}
