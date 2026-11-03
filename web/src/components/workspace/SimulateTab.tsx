"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { FIXTURE_MODE, getClient } from "@/lib/api";
import { requestOverrides } from "@/lib/api/fixtures";
import type { Document, Fault, JsonObject, JsonValue, Plan, Resolution, Scenario, SimulationRequest, SimulationRun, Topology } from "@/lib/api/types";
import { refinedComponents, resolutionOf } from "@/lib/model/hierarchy";
import { FaultTypes } from "@/lib/api/types";
import { deepMerge, formatDate, isPlainObject, jsonEqual, scenarioFlow } from "@/lib/model/format";
import { planQueue, useDocIndex, useQuery } from "@/lib/hooks";
import { nameOf } from "@/lib/model/docindex";
import { RunHeader, RunPlayback } from "@/components/playback/RunView";
import { Cel } from "@/components/json";
import { Badge, Button, Empty, ErrorBox, Label, Notice, Panel, Select, Spinner, StatusBadge, cx, inputClass } from "@/components/ui";
import { scenarioMechanisms } from "./FlowsTab";
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

function SimulateForm({ doc, plan, flowId, scenario, rev }: { doc: Document; plan: Plan; flowId: string; scenario?: Scenario; rev: string }) {
  const ws = useWorkspace();
  const idx = useDocIndex(doc);
  const flow = idx.flowsById.get(flowId);

  // Baselines: what the engine would use with no request overrides.
  const baseInput = useMemo(() => pretty(deepMerge(flow?.entry?.input, scenario?.input)), [flow, scenario]);
  const baseState = useMemo(() => {
    const out: Record<string, string> = {};
    for (const s of plan.state) {
      out[s.component] = pretty(deepMerge(s.initial ?? {}, scenario?.state?.[s.component]) ?? {});
    }
    return out;
  }, [plan, scenario]);
  const baseSeed = scenario?.seed !== undefined ? String(scenario.seed) : "";

  const [choices, setChoices] = useState<Record<string, string>>({});
  const [faults, setFaults] = useState<FaultRow[]>([]);
  const [inputText, setInputText] = useState(baseInput);
  const [stateText, setStateText] = useState<Record<string, string>>(baseState);
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
  const parsedStates = Object.fromEntries(Object.entries(stateText).map(([c, t]) => [c, parseJson(t)]));
  const topology = parseTopology(topologyText);
  const config = parseConfig(configText);
  const epochBad = epoch.trim() !== "" && !isRFC3339(epoch.trim());
  const invalid =
    !parsedInput.ok ||
    Object.values(parsedStates).some((p) => !p.ok) ||
    (seed.trim() !== "" && !/^-?\d+$/.test(seed.trim())) ||
    topology.errors.length > 0 ||
    config.errors.length > 0 ||
    epochBad;

  const buildRequest = (): SimulationRequest => {
    // A multi-step scenario without a flow is grouped under its first step's flow; don't send that.
    const req: SimulationRequest = scenario && !scenario.flow ? { rev } : { rev, flow: flowId };
    if (scenario) req.scenario = scenario.id;
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
      const b = parseJson(baseState[c] ?? "");
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

  const faultComps = plan.faultable.filter((f) => !f.includes("."));
  const faultIfaces = plan.faultable.filter((f) => f.includes("."));
  const name = (id: string) => nameOf(idx, id);

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
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
            <Panel title={`Choice points · ${plan.choices.length}`}>
              {plan.choices.length === 0 ? (
                <div className="text-[12px] text-faint">No choice points are reachable from this flow.</div>
              ) : (
                <div className="space-y-2.5">
                  {plan.choices.map((c) => {
                    const fromScenario = scenario?.choices?.[c.key];
                    const fallback = fromScenario ? `scenario: ${fromScenario}` : `default: ${c.default ?? c.options[0]}`;
                    const id = `choice-${c.key}`;
                    return (
                      <div key={c.key}>
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
                  })}
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
                  onClick={() => setFaults((fs) => [...fs, { key: faultKey++, target: faultIfaces[0] ?? plan.faultable[0] ?? "", type: "unavailable", code: "", status: "", latency_ms: "", calls: "" }])}
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
                  {faults.map((r, idx) => {
                    const upd = (patch: Partial<FaultRow>) => setFaults((fs) => fs.map((x) => (x.key === r.key ? { ...x, ...patch } : x)));
                    const p = `fault-${r.key}`;
                    return (
                      <fieldset key={r.key} className="rounded-md border border-line bg-panel-2/40 p-2">
                        <legend className="sr-only">Fault {idx + 1}</legend>
                        <div className="grid grid-cols-[1fr_auto] gap-1.5">
                          <div>
                            <label htmlFor={`${p}-target`} className="text-[10.5px] text-faint">
                              target
                            </label>
                            <Select id={`${p}-target`} value={r.target} onChange={(e) => upd({ target: e.target.value })} className="w-full font-mono text-[12px]">
                              <optgroup label="Interfaces">
                                {faultIfaces.map((t) => (
                                  <option key={t} value={t}>
                                    {t}
                                  </option>
                                ))}
                              </optgroup>
                              <optgroup label="Components (every interface)">
                                {faultComps.map((t) => (
                                  <option key={t} value={t}>
                                    {t} · {name(t)}
                                  </option>
                                ))}
                              </optgroup>
                            </Select>
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
                          <Button size="sm" variant="ghost" onClick={() => setFaults((fs) => fs.filter((x) => x.key !== r.key))} aria-label={`Remove fault ${idx + 1}`} className="h-8">
                            ✕
                          </Button>
                        </div>
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
                  hint="Merged over fake data generated from the request schema; strings starting with = are CEL."
                />
                <div className="space-y-1.5">
                  <div className="text-[11px] text-faint">Component state (prefilled with the initial state{scenario?.state ? " and the scenario's overrides" : ""}). Edits merge into it.</div>
                  {plan.state.map((s) => {
                    const changed = (() => {
                      const a = parseJson(stateText[s.component] ?? "");
                      const b = parseJson(baseState[s.component] ?? "");
                      return a.ok && b.ok && !jsonEqual(a.value ?? null, b.value ?? null);
                    })();
                    return (
                      <details key={s.component} className="rounded-md border border-line-soft bg-panel-2/30 px-2 py-1" open={changed || undefined}>
                        <summary className="cursor-pointer text-[12px] text-ink">
                          {name(s.component)} <span className="font-mono text-[10.5px] text-faint">{s.component}</span>
                          {changed && <span className="ml-1 text-[10.5px] text-accent">● override</span>}
                          {scenario?.state?.[s.component] && <span className="ml-1 text-[10.5px] text-violet">scenario</span>}
                        </summary>
                        <div className="pt-1">
                          <JsonEditor
                            id={`state-${s.component}`}
                            label={<span className="text-faint">state</span>}
                            value={stateText[s.component] ?? ""}
                            baseline={baseState[s.component] ?? ""}
                            onChange={(v) => setStateText((m) => ({ ...m, [s.component]: v }))}
                            rows={4}
                          />
                        </div>
                      </details>
                    );
                  })}
                </div>
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

          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2.5">
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
            <div className="text-[12px] text-faint">
              {overrides.length ? (
                <>
                  Overrides: <span className="text-ink">{overrides.join(", ")}</span>
                </>
              ) : scenario ? (
                "No overrides: runs the scenario as written."
              ) : (
                "Ad hoc run of the flow with defaults."
              )}
            </div>
            {FIXTURE_MODE && (overrides.length > 0 || !scenario) && (
              <Badge tone="warn" title="Fixture mode can only replay recorded scenario runs">
                needs mosaicd
              </Badge>
            )}
            <div className="ml-auto flex items-center gap-2">
              {run && (
                <Button size="sm" variant="ghost" onClick={() => setCollapsed(true)}>
                  Collapse
                </Button>
              )}
              {runButton}
            </div>
          </div>
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

/** §14.5: per refined component, its contract (black box) or its child ontology (refined). */
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
        A black box runs the component&apos;s contract and latency; refined runs its child ontology in its place, loaded from the store by{" "}
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

/** Run-request world overrides (§13.1 item 6): fixtures, topology, config and clock. */
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
    <Panel title="World · fixtures, topology, config, clock">
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-4">
        <div>
          <Label>Fixtures</Label>
          {p.scenario?.fixtures?.length ? (
            <div className="mb-1 mt-0.5 text-[11px] text-faint">
              Scenario applies <span className="font-mono text-ink">{p.scenario.fixtures.join(", ")}</span> first.
            </div>
          ) : null}
          {all.length === 0 ? (
            <div className="mt-0.5 text-[12px] text-faint">The model has no fixtures.</div>
          ) : (
            <ul className="mt-1 space-y-0.5" aria-label="Fixtures to apply, in order">
              {all.map((f) => {
                const i = p.fixtures.indexOf(f.id);
                return (
                  <li key={f.id}>
                    <label className="flex items-baseline gap-1.5 text-[12px] text-ink">
                      <input type="checkbox" checked={i >= 0} onChange={() => toggle(f.id)} className="accent-[#ccff78]" />
                      <span className="font-mono">{f.id}</span>
                      {i >= 0 && <span className="tnum text-[10.5px] text-accent">#{i + 1}</span>}
                      {f.summary && <span className="truncate text-[11px] text-faint">{f.summary}</span>}
                    </label>
                  </li>
                );
              })}
            </ul>
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
            {r.summary.steps && r.summary.steps.length > 0 && <Badge tone="info">{r.summary.steps.length} steps</Badge>}
            {r.summary.assertions.length > 0 && (
              <span className={r.summary.passed ? "text-ok" : "text-bad"}>{r.summary.passed ? "✓" : "✗"}</span>
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
  const flows = doc.data?.flows.filter((f) => f.entry) ?? [];
  const scenarioParam = search.get("scenario") ?? "";
  const idx = useDocIndex(doc.data);
  const scenarioDoc = scenarioParam ? idx?.scenariosById.get(scenarioParam) : undefined;
  const flowId = (scenarioDoc && scenarioFlow(scenarioDoc)) || search.get("flow") || flows[0]?.id || "";
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

  const scenarios = idx?.scenariosByFlow.get(flowId) ?? [];

  return (
    <div className="space-y-3 p-3">
      {FIXTURE_MODE && (
        <Notice tone="warn" title="Fixture mode">
          Running a scenario without overrides replays its recorded run (generated by the real engine). Ad hoc flow runs and any
          override need a live mosaicd; the form still shows the exact request it would send.
        </Notice>
      )}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-panel px-3 py-2.5">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor="sim-flow">Flow</Label>
          <Select id="sim-flow" value={flowId} onChange={(e) => setParams({ flow: e.target.value, scenario: null })} className="min-w-[220px]">
            {flows.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name || f.id}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-0.5">
          <Label htmlFor="sim-scenario">Scenario</Label>
          <Select id="sim-scenario" value={scenarioDoc?.id ?? ""} onChange={(e) => setParams({ flow: flowId, scenario: e.target.value || null })} className="min-w-[300px]">
            <option value="">— none: ad hoc run of the flow —</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name || s.id}
                {s.steps?.length ? ` · ${s.steps.length} steps` : ""}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 text-[12px] text-muted">
          {scenarioDoc ? (
            <>
              {scenarioDoc.description && <span className="mr-1">{scenarioDoc.description}</span>}
              {scenarioMechanisms(scenarioDoc).map((m) => (
                <Badge key={m.label} tone={m.tone}>
                  {m.label}
                </Badge>
              ))}
              {scenarioMechanisms(scenarioDoc).length === 0 && <span className="text-faint">Runs the flow with its defaults and checks expectations.</span>}
            </>
          ) : (
            idx?.flowsById.get(flowId)?.description
          )}
        </div>
        <div className="flex items-center gap-2 text-[12px] text-faint">
          revision <span className="font-mono text-ink">{ws.rev === "draft" || ws.rev === "latest" ? ws.rev : `r${ws.rev}`}</span>
          <Button size="sm" variant="ghost" onClick={() => setShowRuns((s) => !s)} aria-expanded={showRuns}>
            {showRuns ? "Hide" : "Recent"} runs
          </Button>
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
          key={`${flowId}:${scenarioDoc?.id ?? ""}:${ws.rev}`}
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
