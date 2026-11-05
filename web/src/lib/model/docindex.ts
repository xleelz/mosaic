// Indexes over a document, built once per document object, and the pure
// grouping helpers the Flows tab and the component browser use. Large
// ontologies hold hundreds of components and thousands of scenarios, so
// lookups go through maps instead of `find` and `filter` scans.
//
// Only type imports here: node --test runs this file with type stripping.

import type { Component, Document, EvidenceMechanism, Fault, Flow, Interface, Scenario, Step } from "../api/types";

export interface DocIndex {
  componentsById: Map<string, Component>;
  interfacesById: Map<string, Interface>;
  /** Interfaces of each component, in document order. */
  interfacesByComponent: Map<string, Interface[]>;
  flowsById: Map<string, Flow>;
  scenariosById: Map<string, Scenario>;
  /** Every scenario that touches each flow (see FlowTouch), in document order. */
  scenariosByFlow: Map<string, Scenario[]>;
  /** How each scenario touches each flow, in document order. */
  touchesByFlow: Map<string, FlowTouch[]>;
  /** The flows each scenario touches. Absent for a scenario whose steps only call interfaces no flow enters. */
  flowsOfScenario: Map<string, string[]>;
  /** Scenarios that touch no flow. */
  unfiledScenarios: Scenario[];
  /** Scenarios with a fault on each target, as the fault names it (a component or an interface). */
  scenariosByFaultTarget: Map<string, Scenario[]>;
  /** Members of each component, sorted by id. Top-level components are under "". */
  childrenByParent: Map<string, Component[]>;
  /** The top-level ancestor of each component (itself when it has no known parent). */
  topLevel: Map<string, string>;
  /** attributes.area, else attributes.owner, of the component or its nearest ancestor that has one. */
  area: Map<string, string>;
}

const ROOT = "";

function byId(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function interfaceId(i: Interface): string {
  return i.id || `${i.component}.${i.name}`;
}

/**
 * How a scenario touches a flow:
 * - "runs": the scenario names the flow, or starts with it;
 * - "step": a later step runs the flow;
 * - "calls-entry": a step calls the interface the flow enters by, without naming the flow.
 */
export type TouchHow = "runs" | "step" | "calls-entry";

export interface FlowTouch {
  scenario: Scenario;
  how: TouchHow;
  /** The 1-based step that first touches the flow, in a multi-step scenario. */
  step?: number;
  /** How many steps the scenario has. */
  stepCount: number;
}

const HOW_RANK: Record<TouchHow, number> = { runs: 0, step: 1, "calls-entry": 2 };

/** The flows one scenario touches, each with its strongest touch. */
function scenarioTouches(s: Scenario, flowsByEntry: Map<string, string[]>): Map<string, FlowTouch> {
  const stepCount = s.steps?.length ?? 0;
  const out = new Map<string, FlowTouch>();
  const add = (flow: string, how: TouchHow, step?: number) => {
    const have = out.get(flow);
    if (!have || HOW_RANK[how] < HOW_RANK[have.how]) out.set(flow, { scenario: s, how, step, stepCount });
  };
  if (s.flow) add(s.flow, "runs");
  (s.steps ?? []).forEach((st, i) => {
    if (st.flow) add(st.flow, i === 0 ? "runs" : "step", i + 1);
    if (st.interface) for (const f of flowsByEntry.get(st.interface) ?? []) add(f, "calls-entry", i + 1);
  });
  return out;
}

function ownArea(c: Component | undefined): string | undefined {
  const a = c?.attributes;
  if (!a) return undefined;
  for (const k of ["area", "owner"]) {
    const v = a[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return undefined;
}

function push<K, V>(m: Map<K, V[]>, k: K, v: V) {
  const l = m.get(k);
  if (l) l.push(v);
  else m.set(k, [v]);
}

export function buildDocIndex(doc: Document): DocIndex {
  const componentsById = new Map<string, Component>();
  for (const c of doc.components ?? []) componentsById.set(c.id, c);

  const interfacesById = new Map<string, Interface>();
  const interfacesByComponent = new Map<string, Interface[]>();
  for (const i of doc.interfaces ?? []) {
    interfacesById.set(interfaceId(i), i);
    push(interfacesByComponent, i.component, i);
  }

  const flowsById = new Map<string, Flow>();
  const flowsByEntry = new Map<string, string[]>();
  for (const f of doc.flows ?? []) {
    flowsById.set(f.id, f);
    if (f.entry) push(flowsByEntry, f.entry.interface, f.id);
  }

  const scenariosById = new Map<string, Scenario>();
  const scenariosByFlow = new Map<string, Scenario[]>();
  const touchesByFlow = new Map<string, FlowTouch[]>();
  const flowsOfScenario = new Map<string, string[]>();
  const unfiledScenarios: Scenario[] = [];
  const scenariosByFaultTarget = new Map<string, Scenario[]>();
  for (const s of doc.scenarios ?? []) {
    scenariosById.set(s.id, s);
    const touches = scenarioTouches(s, flowsByEntry);
    if (touches.size === 0) unfiledScenarios.push(s);
    else flowsOfScenario.set(s.id, Array.from(touches.keys()));
    for (const [f, t] of touches) {
      push(scenariosByFlow, f, s);
      push(touchesByFlow, f, t);
    }
    for (const target of new Set((s.faults ?? []).map((f) => f.target))) push(scenariosByFaultTarget, target, s);
  }

  const childrenByParent = new Map<string, Component[]>();
  for (const c of componentsById.values()) {
    const p = c.parent && c.parent !== c.id && componentsById.has(c.parent) ? c.parent : ROOT;
    push(childrenByParent, p, c);
  }
  for (const l of childrenByParent.values()) l.sort(byId);

  // Walk down from the roots so every component is visited once; a parent
  // cycle (no root) falls back to the component itself.
  const topLevel = new Map<string, string>();
  const area = new Map<string, string>();
  const walk = (c: Component, top: string, inherited: string | undefined) => {
    if (topLevel.has(c.id)) return;
    topLevel.set(c.id, top);
    const a = ownArea(c) ?? inherited;
    if (a) area.set(c.id, a);
    for (const k of childrenByParent.get(c.id) ?? []) walk(k, top, a);
  };
  for (const c of childrenByParent.get(ROOT) ?? []) walk(c, c.id, undefined);
  for (const c of componentsById.values()) if (!topLevel.has(c.id)) walk(c, c.id, undefined);

  return {
    componentsById,
    interfacesById,
    interfacesByComponent,
    flowsById,
    scenariosById,
    scenariosByFlow,
    touchesByFlow,
    flowsOfScenario,
    unfiledScenarios,
    scenariosByFaultTarget,
    childrenByParent,
    topLevel,
    area,
  };
}

const cache = new WeakMap<Document, DocIndex>();

/** The index of a document, built on first use and shared by every caller holding the same document. */
export function docIndex(doc: Document): DocIndex {
  let idx = cache.get(doc);
  if (!idx) {
    idx = buildDocIndex(doc);
    cache.set(doc, idx);
  }
  return idx;
}

/** A component's display name, or its id. */
export function nameOf(idx: DocIndex, id: string): string {
  return idx.componentsById.get(id)?.name || id;
}

// ---- Flow sections ------------------------------------------------------

export type FlowGrouping = "feature" | "area" | "parent";

export const FLOW_GROUPINGS: { value: FlowGrouping; label: string }[] = [
  { value: "feature", label: "Feature tag" },
  { value: "area", label: "Area / owner" },
  { value: "parent", label: "Top-level component" },
];

export interface FlowGroup {
  /** Stable key for the URL (?section=). */
  key: string;
  label: string;
  flows: Flow[];
}

export const OTHER = "Other";
const FEATURE = "feature:";

/** The flow's feature tags without the prefix. */
export function featureTags(flow: Flow): string[] {
  return (flow.tags ?? []).filter((t) => t.startsWith(FEATURE) && t.length > FEATURE.length).map((t) => t.slice(FEATURE.length));
}

/**
 * The component a flow enters: the entry interface's component, else the
 * caller. Callers are often external actors shared by many flows, so the
 * entered component tells flows apart better.
 */
export function entryComponents(flow: Flow, idx: DocIndex): string[] {
  const e = flow.entry;
  if (!e) return [];
  const out: string[] = [];
  const iface = idx.interfacesById.get(e.interface);
  const target = iface?.component ?? (e.interface.includes(".") ? e.interface.slice(0, e.interface.indexOf(".")) : undefined);
  if (target && idx.componentsById.has(target)) out.push(target);
  if (e.caller && idx.componentsById.has(e.caller) && e.caller !== target) out.push(e.caller);
  return out;
}

/** The section keys of one flow under a grouping (a flow with several feature tags is in several sections). */
export function flowSectionKeys(flow: Flow, idx: DocIndex, by: FlowGrouping): string[] {
  if (by === "feature") {
    const f = featureTags(flow);
    return f.length ? f : [OTHER];
  }
  const comps = entryComponents(flow, idx);
  if (by === "area") {
    for (const c of comps) {
      const a = idx.area.get(c);
      if (a) return [a];
    }
    return [OTHER];
  }
  const top = comps.length ? idx.topLevel.get(comps[0]) : undefined;
  return [top ?? OTHER];
}

/** Flows split into sections, largest first, then by name; "Other" always last. Flows keep document order inside a section. */
export function groupFlows(flows: Flow[], idx: DocIndex, by: FlowGrouping): FlowGroup[] {
  const m = new Map<string, Flow[]>();
  for (const f of flows) for (const k of flowSectionKeys(f, idx, by)) push(m, k, f);
  const label = (k: string) => (by === "parent" && k !== OTHER ? nameOf(idx, k) : k);
  return Array.from(m.entries())
    .map(([key, fl]) => ({ key, label: label(key), flows: fl }))
    .sort((a, b) => {
      if ((a.key === OTHER) !== (b.key === OTHER)) return a.key === OTHER ? 1 : -1;
      return b.flows.length - a.flows.length || a.label.localeCompare(b.label);
    });
}

/** Feature tags when most flows have one; else area when most entry components have one; else the top-level component. */
export function defaultFlowGrouping(flows: Flow[], idx: DocIndex): FlowGrouping {
  if (flows.length === 0) return "feature";
  const half = flows.length / 2;
  if (flows.filter((f) => featureTags(f).length > 0).length > half) return "feature";
  if (flows.filter((f) => flowSectionKeys(f, idx, "area")[0] !== OTHER).length > half) return "area";
  return "parent";
}

/** True when the flow's name, id or a tag contains every word of the query (case-insensitive). */
export function flowMatches(flow: Flow, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = [flow.id, flow.name ?? "", ...(flow.tags ?? [])].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

// ---- Search ---------------------------------------------------------------

function queryWords(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

const scenarioHay = new WeakMap<Scenario, string>();

function hayOfScenario(s: Scenario): string {
  let hay = scenarioHay.get(s);
  if (hay === undefined) {
    const faults = (s.faults ?? []).flatMap((f) => [f.target, f.type, f.code ?? "", f.message ?? ""]);
    hay = [s.id, s.name ?? "", s.description ?? "", ...faults].join(" ").toLowerCase();
    scenarioHay.set(s, hay);
  }
  return hay;
}

/** True when the scenario's id, name, description or faults contain every word of the query. */
export function scenarioMatches(s: Scenario, query: string): boolean {
  const words = queryWords(query);
  if (!words.length) return true;
  const hay = hayOfScenario(s);
  return words.every((w) => hay.includes(w));
}

export interface FlowSearch {
  /** Flows that match themselves or through a scenario, in the order given. */
  flows: Flow[];
  /** Matching scenarios per flow, for flows reached that way. */
  viaScenario: Map<string, Scenario[]>;
  /** Every matching scenario, including those that touch no flow. */
  scenarios: Scenario[];
}

/** What a search on the Flows page finds: flows, and scenarios with the flows they touch. */
export function searchFlows(flows: Flow[], idx: DocIndex, query: string): FlowSearch {
  if (!queryWords(query).length) return { flows, viaScenario: new Map(), scenarios: [] };
  const scenarios: Scenario[] = [];
  const viaScenario = new Map<string, Scenario[]>();
  for (const s of idx.scenariosById.values()) {
    if (!scenarioMatches(s, query)) continue;
    scenarios.push(s);
    for (const f of idx.flowsOfScenario.get(s.id) ?? []) push(viaScenario, f, s);
  }
  return { flows: flows.filter((f) => flowMatches(f, query) || viaScenario.has(f.id)), viaScenario, scenarios };
}

// ---- What a flow's page leads with ----------------------------------------

export type ScenarioClass = "fault" | "expected-error" | "normal";

const EXPECTS_ERROR = /!\s*(steps\.[\w-]+\.)?result\.ok|(^|\W)result\.ok\s*==\s*false|(^|\.)result\.error\b/;
const NAMED_FAILURE = /refus|reject|fail|error|dead|dies|crash|timeout|timed.out|invalid|abort|unavailable|denied|overflow|exhaust/;
const NAMED_HAPPY = /happy|normal|basic|success|end.to.end|completes?\b|completion/;

/**
 * What a scenario sets out to show: a failure it injects, a failure the model
 * produces by itself (a refusal or edge case), or neither. Derived from its
 * faults, its expectations and its words, so it's a reading, not a declaration.
 */
export function scenarioClass(s: Scenario): ScenarioClass {
  if (s.faults?.length || s.mocks?.some((m) => m.fail !== undefined)) return "fault";
  if (s.steps?.some((st) => "kill" in st)) return "fault";
  if (s.expect?.some((e) => EXPECTS_ERROR.test(e))) return "expected-error";
  if (NAMED_FAILURE.test(`${s.id} ${s.name ?? ""}`.toLowerCase())) return "expected-error";
  return "normal";
}

function overrideCount(s: Scenario): number {
  return [s.state, s.config, s.choices, s.topology].filter((o) => o && Object.keys(o).length > 0).length + (s.mocks?.length ? 1 : 0);
}

export interface HappyPath {
  touch: FlowTouch;
  /** Why this one was picked, to show beside it: the pick is derived. */
  why: string;
}

/**
 * The scenario most likely to show a flow's normal path: no faults, no expected
 * errors, then named as such, then closest to the flow, then fewest overrides.
 * Null when every scenario is a failure, or none touches the flow.
 */
export function happyPath(touches: FlowTouch[]): HappyPath | null {
  let best: { touch: FlowTouch; score: number; named: boolean } | null = null;
  for (const t of touches) {
    const s = t.scenario;
    if (scenarioClass(s) !== "normal") continue;
    const named = NAMED_HAPPY.test(`${s.id} ${s.name ?? ""}`.toLowerCase());
    const score = (named ? 100 : 0) + (2 - HOW_RANK[t.how]) * 10 - overrideCount(s) * 2 - Math.min(t.stepCount, 5) + (s.name ? 1 : 0);
    if (!best || score > best.score) best = { touch: t, score, named };
  }
  if (!best) return null;
  return { touch: best.touch, why: best.named ? "no faults or expected errors, and named as the normal path" : "no faults or expected errors, and the fewest overrides" };
}

export interface FlowScenarios {
  happy: HappyPath | null;
  /** Inject a fault. */
  faults: FlowTouch[];
  /** Refusals and edge cases the model produces without a fault. */
  expectedErrors: FlowTouch[];
  /** Other scenarios that start with this flow. */
  starts: FlowTouch[];
  /** Other scenarios that reach this flow from a later step, or call its entry. */
  uses: FlowTouch[];
}

export function flowScenarios(touches: FlowTouch[]): FlowScenarios {
  const happy = happyPath(touches);
  const out: FlowScenarios = { happy, faults: [], expectedErrors: [], starts: [], uses: [] };
  for (const t of touches) {
    if (t === happy?.touch) continue;
    const c = scenarioClass(t.scenario);
    if (c === "fault") out.faults.push(t);
    else if (c === "expected-error") out.expectedErrors.push(t);
    else if (t.how === "runs") out.starts.push(t);
    else out.uses.push(t);
  }
  return out;
}

/** How a touch reads on a scenario row; empty when the scenario simply runs the flow. */
export function touchLabel(t: FlowTouch): string {
  if (t.how === "step") return `this flow is step ${t.step} of ${t.stepCount}`;
  if (t.how === "calls-entry") return `step ${t.step} of ${t.stepCount} calls its entry`;
  return t.stepCount > 1 ? `starts here, ${t.stepCount} steps` : "";
}

export interface Titled {
  text: string;
  /** "id" means nothing better exists: show it as an unnamed entity, not as a title. */
  from: "name" | "description" | "id";
}

function titleOf(e: { id: string; name?: string; description?: string }): Titled {
  if (e.name?.trim()) return { text: e.name.trim(), from: "name" };
  const d = e.description?.trim();
  if (d) {
    const first = /^.*?[.!?](\s|$)/.exec(d)?.[0].trim() ?? d;
    return { text: first.length > 90 ? `${first.slice(0, 87)}...` : first, from: "description" };
  }
  return { text: e.id, from: "id" };
}

export const scenarioTitle = (s: Scenario): Titled => titleOf(s);
export const flowTitle = (f: Flow): Titled => titleOf(f);

/** A line for a flow with no description, from what the model does hold. Empty without an entry. */
export function derivedFlowLine(flow: Flow, idx: DocIndex): string {
  if (!flow.entry) return "";
  return `${nameOf(idx, flow.entry.caller)} calls ${flow.entry.interface}.`;
}

// ---- Importance -----------------------------------------------------------

const OUTSIDE_KINDS = new Set(["client", "external", "user", "actor"]);

/** True when a flow is entered from outside the model: a client or external caller, or one it doesn't hold. */
export function enteredFromOutside(flow: Flow, idx: DocIndex): boolean {
  if (!flow.entry) return false;
  const caller = idx.componentsById.get(flow.entry.caller);
  return !caller || OUTSIDE_KINDS.has((caller.kind ?? "").toLowerCase());
}

/** Scenarios touching a flow. */
export function flowScenarioCount(flow: Flow, idx: DocIndex): number {
  return idx.touchesByFlow.get(flow.id)?.length ?? 0;
}

function byImportance(idx: DocIndex) {
  return (a: Flow, b: Flow) => {
    const out = Number(enteredFromOutside(b, idx)) - Number(enteredFromOutside(a, idx));
    return out || flowScenarioCount(b, idx) - flowScenarioCount(a, idx);
  };
}

/** Flows by importance, keeping document order among equals. */
export function rankFlows(flows: Flow[], idx: DocIndex): Flow[] {
  return flows.slice().sort(byImportance(idx));
}

export interface MainFlow {
  flow: Flow;
  /** Why it's here: importance is derived, so it says so. */
  reason: string;
}

/** The flows to start from: entered from outside and exercised by a scenario, else the most exercised. */
export function mainFlows(flows: Flow[], idx: DocIndex, limit = 12): MainFlow[] {
  const exercised = flows.filter((f) => flowScenarioCount(f, idx) > 0);
  return rankFlows(exercised, idx)
    .slice(0, limit)
    .map((flow) => {
      const n = flowScenarioCount(flow, idx);
      const count = `${n} scenario${n === 1 ? "" : "s"}`;
      return { flow, reason: enteredFromOutside(flow, idx) ? `entered from outside the model, ${count}` : count };
    });
}

/** A group with more flows than this gets a second level. */
export const SUBGROUP_OVER = 100;

const MAX_SUBGROUPS = 40;

function fold(m: Map<string, Flow[]>, label: (k: string) => string): FlowGroup[] {
  // Single flows don't make a level: they go together in "Other".
  const other: Flow[] = [];
  const out: FlowGroup[] = [];
  for (const [key, flows] of m) {
    if (flows.length < 2 || key === OTHER) other.push(...flows);
    else out.push({ key, label: label(key), flows });
  }
  out.sort((a, b) => b.flows.length - a.flows.length || a.label.localeCompare(b.label));
  if (other.length) out.push({ key: OTHER, label: OTHER, flows: other });
  return out;
}

/**
 * The second level of a big group: by the entered component's top-level
 * component, or, when the group already is one, by its direct member. When that
 * doesn't divide the group, by the first word of the flow id.
 */
export function subgroupFlows(flows: Flow[], idx: DocIndex, by: FlowGrouping): FlowGroup[] {
  const byComponent = new Map<string, Flow[]>();
  for (const f of flows) {
    const c = entryComponents(f, idx)[0];
    if (!c) {
      push(byComponent, OTHER, f);
      continue;
    }
    if (by !== "parent") {
      push(byComponent, idx.topLevel.get(c) ?? c, f);
      continue;
    }
    const chain = [c, ...ancestors(idx, c)];
    push(byComponent, chain.length > 1 ? chain[chain.length - 2] : c, f);
  }
  const groups = fold(byComponent, (k) => nameOf(idx, k));
  const useful = groups.length > 1 && groups.length <= MAX_SUBGROUPS && groups[0].flows.length < flows.length * 0.8;
  if (useful) return groups;
  const byWord = new Map<string, Flow[]>();
  for (const f of flows) push(byWord, f.id.split(/[-_.:/]/)[0] || OTHER, f);
  return fold(byWord, (k) => k);
}

// ---- A component's flows, faults and fidelity -----------------------------

const callerCache = new WeakMap<Document, Map<string, string[]>>();

function collectCalls(steps: Step[] | undefined, add: (target: string) => void) {
  for (const st of steps ?? []) {
    if (st.call) add(st.call);
    if (st.emit) add(st.emit);
    for (const t of st.targets ?? []) add(t);
    collectCalls(st.then, add);
    collectCalls(st.else, add);
    collectCalls(st.steps, add);
    for (const o of Object.values(st.options ?? {})) collectCalls(o, add);
    for (const b of st.branches ?? []) collectCalls(b, add);
    if (Array.isArray(st.on_error)) collectCalls(st.on_error, add);
  }
}

/** Callers of each interface, from every behavior's declared calls, emits and targets. */
function callersOf(doc: Document): Map<string, string[]> {
  const have = callerCache.get(doc);
  if (have) return have;
  const built = new Map<string, string[]>();
  for (const i of doc.interfaces ?? []) {
    const id = interfaceId(i);
    collectCalls(i.behavior, (t) => push(built, t, id));
  }
  callerCache.set(doc, built);
  return built;
}

/** A component and everything inside it. */
export function componentScope(idx: DocIndex, id: string): Set<string> {
  const scope = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const c = stack.pop()!;
    if (scope.has(c)) continue;
    scope.add(c);
    for (const k of idx.childrenByParent.get(c) ?? []) stack.push(k.id);
  }
  return scope;
}

/** The interfaces a component and its members provide. */
export function scopeInterfaces(idx: DocIndex, scope: ReadonlySet<string>): string[] {
  const out: string[] = [];
  for (const c of scope) for (const i of idx.interfacesByComponent.get(c) ?? []) out.push(interfaceId(i));
  return out;
}

export interface FlowsThrough {
  /** Flows that enter this component or a member. */
  enters: Flow[];
  /** Flows whose declared calls could reach it: static, so not proof that a run does. */
  reaches: Flow[];
}

/** The flows through a component (with its members), most important first. */
export function flowsThrough(doc: Document, idx: DocIndex, id: string): FlowsThrough {
  const scope = componentScope(idx, id);
  const callers = callersOf(doc);
  const reach = new Set<string>();
  const stack = scopeInterfaces(idx, scope);
  while (stack.length) {
    const i = stack.pop()!;
    if (reach.has(i)) continue;
    reach.add(i);
    for (const c of callers.get(i) ?? []) stack.push(c);
  }
  const enters: Flow[] = [];
  const reaches: Flow[] = [];
  for (const f of idx.flowsById.values()) {
    if (!f.entry) continue;
    const entered = idx.interfacesById.get(f.entry.interface)?.component;
    if (entered !== undefined && scope.has(entered)) enters.push(f);
    else if (reach.has(f.entry.interface) || f.steps?.some((s) => scope.has(s.component))) reaches.push(f);
  }
  return { enters: rankFlows(enters, idx), reaches: rankFlows(reaches, idx) };
}

export interface FaultScenario {
  scenario: Scenario;
  /** The scenario's faults on this component or its members. */
  faults: Fault[];
}

function faultComponent(idx: DocIndex, target: string): string {
  const iface = idx.interfacesById.get(target);
  if (iface) return iface.component;
  if (idx.componentsById.has(target)) return target;
  const dot = target.indexOf(".");
  return dot > 0 ? target.slice(0, dot) : target;
}

/** Scenarios that inject a fault on a component's interfaces or its members', those on the component itself first. */
export function faultScenarios(idx: DocIndex, id: string): FaultScenario[] {
  const scope = componentScope(idx, id);
  const out = new Map<string, FaultScenario>();
  for (const [target, list] of idx.scenariosByFaultTarget) {
    if (!scope.has(faultComponent(idx, target))) continue;
    for (const s of list) {
      if (out.has(s.id)) continue;
      out.set(s.id, { scenario: s, faults: (s.faults ?? []).filter((f) => scope.has(faultComponent(idx, f.target))) });
    }
  }
  const own = (x: FaultScenario) => (x.faults.some((f) => faultComponent(idx, f.target) === id) ? 0 : 1);
  return Array.from(out.values()).sort((a, b) => own(a) - own(b) || a.scenario.id.localeCompare(b.scenario.id));
}

export interface MemberGroup {
  key: "entered" | "infrastructure" | "containers" | "rest";
  label: string;
  members: Component[];
}

const INFRASTRUCTURE_KINDS = new Set(["service", "datastore", "database", "queue", "external", "client", "cache", "engine"]);

/**
 * A component's members with what matters first: those flows enter, then
 * services, stores and stateful parts, then containers by size, then the rest.
 */
export function groupMembers(idx: DocIndex, id: string, counts = descendantCounts(idx)): MemberGroup[] {
  const entered = new Map<string, number>();
  for (const f of idx.flowsById.values()) {
    const c = f.entry ? idx.interfacesById.get(f.entry.interface)?.component : undefined;
    if (!c) continue;
    for (const a of [c, ...ancestors(idx, c)]) entered.set(a, (entered.get(a) ?? 0) + 1);
  }
  const groups: Record<MemberGroup["key"], Component[]> = { entered: [], infrastructure: [], containers: [], rest: [] };
  for (const c of idx.childrenByParent.get(id) ?? []) {
    if (entered.has(c.id)) groups.entered.push(c);
    else if (c.state || INFRASTRUCTURE_KINDS.has((c.kind ?? "").toLowerCase())) groups.infrastructure.push(c);
    else if ((counts.get(c.id) ?? 0) > 0) groups.containers.push(c);
    else groups.rest.push(c);
  }
  groups.entered.sort((a, b) => (entered.get(b.id) ?? 0) - (entered.get(a.id) ?? 0));
  groups.containers.sort((a, b) => (counts.get(b.id) ?? 0) - (counts.get(a.id) ?? 0));
  const labels: Record<MemberGroup["key"], string> = { entered: "Flows enter here", infrastructure: "Services, stores and state", containers: "Groups", rest: "Other members" };
  return (Object.keys(groups) as MemberGroup["key"][]).filter((k) => groups[k].length).map((key) => ({ key, label: labels[key], members: groups[key] }));
}

export interface ComponentMechanisms {
  /** Mechanisms that list an interface of this component or its members. */
  own: EvidenceMechanism[];
  /** Absent mechanisms of the areas this component belongs to. They have no interfaces, so they attach through the area. */
  absent: EvidenceMechanism[];
  /** Those absent mechanisms that are about handling failure. */
  absentFailureHandling: EvidenceMechanism[];
  /** The mechanism areas the component maps to. */
  areas: string[];
}

const FAILURE_WORDS = /\b(fail|fails|failure|failures|failover|error|errors|retry|retries|timeout|timeouts|crash|crashes|dead|recover|recovery|fault|faults|unavailable|abort|aborts)\b/;

/** True for a mechanism about handling failure: kind "retry", or failure words in its name, trigger or observable. */
export function isFailureHandling(m: EvidenceMechanism): boolean {
  return m.kind === "retry" || FAILURE_WORDS.test(`${m.name} ${m.trigger ?? ""} ${m.observable ?? ""}`.toLowerCase());
}

/**
 * A component's mechanisms. A mechanism's area is its list's own, which can
 * differ from the component's: use the component's area where a list has that
 * name, and otherwise the areas of the mechanisms on its interfaces.
 */
export function componentMechanisms(idx: DocIndex, id: string, items: EvidenceMechanism[]): ComponentMechanisms {
  const ifaces = new Set(scopeInterfaces(idx, componentScope(idx, id)));
  const own = items.filter((m) => m.interfaces.some((i) => ifaces.has(i)));
  const area = idx.area.get(id);
  const areas = area && items.some((m) => m.area === area) ? [area] : Array.from(new Set(own.map((m) => m.area))).sort();
  const absent = items.filter((m) => m.fidelity === "absent" && areas.includes(m.area));
  return { own, absent, absentFailureHandling: absent.filter(isFailureHandling), areas };
}

// ---- Pickers and windows ---------------------------------------------------

export interface PickerOption {
  value: string;
  label: string;
  hint?: string;
  group?: string;
}

/** Options containing every word of the query, those starting with it first, at most `limit`, with the total that matched. */
export function filterOptions(options: PickerOption[], query: string, limit = 60): { shown: PickerOption[]; total: number } {
  const words = queryWords(query);
  if (!words.length) return { shown: options.slice(0, limit), total: options.length };
  const start: PickerOption[] = [];
  const rest: PickerOption[] = [];
  for (const o of options) {
    const label = o.label.toLowerCase();
    const hay = `${o.value} ${label} ${(o.hint ?? "").toLowerCase()}`;
    if (!words.every((w) => hay.includes(w))) continue;
    (label.startsWith(words[0]) || o.value.toLowerCase().startsWith(words[0]) ? start : rest).push(o);
  }
  const all = start.concat(rest);
  return { shown: all.slice(0, limit), total: all.length };
}

export const CALLED_GROUP = "Called in a default run";
export const REACHABLE_GROUP = "Could reach (static)";
export const COMPONENT_GROUP = "Whole components (every interface)";

/**
 * Fault targets to pick from, starting with what a default run actually calls
 * (most calls first, the entry last, since failing it only fails the request),
 * then what the plan says could be reached, then whole components.
 */
export function faultTargetOptions(faultable: string[], calls: { [iface: string]: number } | undefined, entry: string | undefined, idx: DocIndex): PickerOption[] {
  const known = new Set(faultable);
  const called = Object.entries(calls ?? {})
    .filter(([i]) => known.has(i))
    .sort((a, b) => Number(a[0] === entry) - Number(b[0] === entry) || b[1] - a[1] || a[0].localeCompare(b[0]));
  const seen = new Set(called.map(([i]) => i));
  const out: PickerOption[] = called.map(([value, n]) => ({
    value,
    label: value,
    group: CALLED_GROUP,
    hint: value === entry ? `the entry, ${n}x` : `${n}x`,
  }));
  for (const t of faultable) {
    if (seen.has(t)) continue;
    if (t.includes(".")) out.push({ value: t, label: t, group: REACHABLE_GROUP });
  }
  for (const t of faultable) if (!t.includes(".")) out.push({ value: t, label: t, hint: nameOf(idx, t), group: COMPONENT_GROUP });
  return out;
}

// ---- Component browser ----------------------------------------------------

export type ComponentGrouping = "tree" | "area";

export interface ComponentRow {
  /** Unique row key. */
  key: string;
  /** A component id, or null for a group heading. */
  id: string | null;
  label: string;
  depth: number;
  /** Members (tree) or items (group) under this row, counting all descendants. */
  count: number;
  expandable: boolean;
  expanded: boolean;
  /** Matches the filter itself (as opposed to being shown as an ancestor of a match). */
  match: boolean;
}

function componentMatches(c: Component, words: string[]): boolean {
  if (!words.length) return true;
  const hay = `${c.id} ${c.name ?? ""} ${c.kind ?? ""} ${(c.tags ?? []).join(" ")}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** Descendant counts per component (members of members included). */
export function descendantCounts(idx: DocIndex): Map<string, number> {
  const out = new Map<string, number>();
  const count = (id: string, seen: Set<string>): number => {
    const have = out.get(id);
    if (have !== undefined) return have;
    if (seen.has(id)) return 0;
    seen.add(id);
    let n = 0;
    for (const k of idx.childrenByParent.get(id) ?? []) n += 1 + count(k.id, seen);
    out.set(id, n);
    return n;
  };
  for (const id of idx.componentsById.keys()) count(id, new Set());
  return out;
}

/**
 * The visible rows of the component browser. In tree mode components nest by
 * parent; in area mode they sit flat under their area (or owner) heading.
 * `expanded` holds open component ids, or "area:<name>" for area headings. A
 * non-empty filter shows every match with its ancestors open.
 */
export function componentRows(idx: DocIndex, by: ComponentGrouping, expanded: ReadonlySet<string>, filter: string, counts = descendantCounts(idx)): ComponentRow[] {
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  const filtering = words.length > 0;
  const rows: ComponentRow[] = [];
  const label = (c: Component) => c.name || c.id;

  if (by === "area") {
    const groups = new Map<string, Component[]>();
    for (const c of idx.componentsById.values()) if (componentMatches(c, words)) push(groups, idx.area.get(c.id) ?? OTHER, c);
    const keys = Array.from(groups.keys()).sort((a, b) => (a === OTHER ? 1 : b === OTHER ? -1 : a.localeCompare(b)));
    for (const k of keys) {
      const list = groups.get(k)!.sort((a, b) => label(a).localeCompare(label(b)));
      const open = filtering || expanded.has(`area:${k}`);
      rows.push({ key: `area:${k}`, id: null, label: k, depth: 0, count: list.length, expandable: true, expanded: open, match: false });
      if (open) for (const c of list) rows.push({ key: c.id, id: c.id, label: label(c), depth: 1, count: counts.get(c.id) ?? 0, expandable: false, expanded: false, match: filtering });
    }
    return rows;
  }

  // Tree: with a filter, keep matches and their ancestors.
  let keep: Set<string> | null = null;
  if (filtering) {
    keep = new Set();
    for (const c of idx.componentsById.values()) {
      if (!componentMatches(c, words)) continue;
      let cur: Component | undefined = c;
      while (cur && !keep.has(cur.id)) {
        keep.add(cur.id);
        cur = cur.parent ? idx.componentsById.get(cur.parent) : undefined;
      }
    }
  }
  const visit = (parent: string, depth: number, seen: Set<string>) => {
    const kids = (idx.childrenByParent.get(parent) ?? []).slice().sort((a, b) => label(a).localeCompare(label(b)));
    for (const c of kids) {
      if (keep && !keep.has(c.id)) continue;
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      const members = idx.childrenByParent.get(c.id)?.length ?? 0;
      const open = members > 0 && (filtering || expanded.has(c.id));
      rows.push({ key: c.id, id: c.id, label: label(c), depth, count: counts.get(c.id) ?? 0, expandable: members > 0, expanded: open, match: !filtering || componentMatches(c, words) });
      if (open) visit(c.id, depth + 1, seen);
    }
  };
  const seen = new Set<string>();
  visit(ROOT, 0, seen);
  // Components caught in a parent cycle have no root; list them at the top level.
  for (const c of idx.componentsById.values()) {
    if (seen.has(c.id) || (keep && !keep.has(c.id)) || !inParentCycle(idx, c.id)) continue;
    seen.add(c.id);
    rows.push({ key: c.id, id: c.id, label: label(c), depth: 0, count: counts.get(c.id) ?? 0, expandable: false, expanded: false, match: true });
  }
  return rows;
}

/** True when following parents from the component loops instead of reaching a top-level component. */
export function inParentCycle(idx: DocIndex, id: string): boolean {
  const seen = new Set<string>();
  let cur: string | undefined = id;
  while (cur) {
    if (seen.has(cur)) return true;
    seen.add(cur);
    const p: string | undefined = idx.componentsById.get(cur)?.parent;
    cur = p && p !== cur && idx.componentsById.has(p) ? p : undefined;
  }
  return false;
}

/** The ancestors of a component, nearest first. */
export function ancestors(idx: DocIndex, id: string): string[] {
  const out: string[] = [];
  const seen = new Set([id]);
  let cur = idx.componentsById.get(id)?.parent;
  while (cur && idx.componentsById.has(cur) && !seen.has(cur)) {
    out.push(cur);
    seen.add(cur);
    cur = idx.componentsById.get(cur)?.parent;
  }
  return out;
}
