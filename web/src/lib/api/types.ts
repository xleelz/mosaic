// TypeScript mirror of mosaicd's wire types (docs/DESIGN.md §6).
//
// Field names follow the Go `json:"..."` tags exactly. Sources:
//   pkg/api/types.go               wire envelopes
//   internal/model/model.go        Document and its entities
//   internal/model/analysis.go     Plan, ChoicePoint, StateInfo, Graph
//   internal/model/validate.go     Issue
//   internal/sim/sim.go            Request, Summary, Event, Outcome, Error, Assertion
//
// Conventions:
//   - `omitempty` fields are optional (`?`).
//   - time.Time is an RFC 3339 string.
//   - json.RawMessage and `any` are JsonValue.
//   - Go nil slices without `omitempty` encode as null; the clients normalize
//     the top-level lists they return so callers can treat them as arrays.

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

/** A revision selector: "draft", "latest" or a revision number. */
export type RevSelector = string;

export const RevDraft = "draft";
export const RevLatest = "latest";
/** The empty model before the first revision (accepted by /impact). */
export const RevBase = "base";

// ---------------------------------------------------------------- model.go

/** model.Source. The server always encodes the object form. */
export interface Source {
  repo?: string;
  path: string;
  line?: number;
  end_line?: number;
  sha?: string;
}

/** model.StateSpec */
export interface StateSpec {
  schema?: JsonObject;
  initial?: JsonObject;
}

/** model.Component */
export interface Component {
  id: string;
  name?: string;
  kind?: string;
  parent?: string;
  layer?: string;
  summary?: string;
  description?: string;
  sources?: Source[];
  tags?: string[];
  attributes?: JsonObject;
  state?: StateSpec;
  /** Bounds the calls each instance serves at once (§11.4). */
  capacity?: CapacitySpec;
  /** The child ontologies that refine this component (§14.3, §14.11). */
  refined_by?: OntologyRef[];
}

/** model.OntologyRef: a child ontology, by stored id, at an optional revision selector. */
export interface OntologyRef {
  ontology: string;
  revision?: string;
}

/** model.RefinesRef: the parent component a refinement document refines (§14.11). */
export interface RefinesRef {
  ontology: string;
  component: string;
  revision?: string;
}

/** model.ImportRef (§14.6) */
export interface ImportRef {
  ontology: string;
  revision?: string;
  as?: string;
}

/** §14.5: a component's resolution in a run. */
export type Resolution = "black_box" | "refined";

/** model.CapacitySpec (§11.4) */
export interface CapacitySpec {
  concurrency: number;
  /** Absent means unbounded; 0 means a call finding every slot busy fails at once. */
  queue_limit?: number;
  queue_timeout_ms?: number;
}

/** A number, or a "=cel" template evaluated when the step runs (§13.1). */
export type IntOrExpr = number | string;

/** model.ErrorSpec */
export interface ErrorSpec {
  code: string;
  status?: number;
  retryable?: boolean;
  summary?: string;
}

/** model.Latency: a whole number of ms when min == max, else {min, max}, or (§11.3) an "=cel" string. */
export type Latency = number | { min: number; max: number } | string;

/** model.RetrySpec */
export interface RetrySpec {
  /** A number, or a "=cel" expression. */
  max_attempts?: number | string;
  backoff_ms?: number;
  multiplier?: number;
  max_backoff_ms?: number;
  codes?: string[];
  when?: string;
  title?: string;
  detail?: string;
  source?: Source;
}

/** model.OnError: "propagate", "continue", or a list of steps. */
export type OnError = "propagate" | "continue" | string | Step[];

/** model.Step: one behavior instruction carrying at most one action. */
export interface Step {
  title?: string;
  detail?: string;
  source?: Source;
  when?: string;

  set?: { [path: string]: JsonValue };

  call?: string;
  input?: JsonValue;
  fill?: boolean;
  as?: string;
  timeout_ms?: IntOrExpr;
  retry?: RetrySpec;
  on_error?: OnError;
  targets?: string[];

  if?: string;
  then?: Step[];
  else?: Step[];

  choice?: string;
  options?: { [option: string]: Step[] };
  default?: string;

  return?: JsonValue;
  fail?: JsonValue;
  emit?: string;
  /** Milliseconds, or a "=cel" expression. */
  wait?: number | string;

  /** A literal list, or a "=cel" expression yielding a list or a map. The item is bound to `as`. */
  foreach?: JsonValue;
  index?: string;
  steps?: Step[];
  /** Iteration cap; the engine defaults to 100 and allows at most 1000. */
  max?: number;

  /** Leaves the enclosing foreach. */
  break?: boolean;
  /** Skips to the enclosing foreach's next item. */
  continue?: boolean;

  /** §11.2: a literal list or map, or "=cel"; each item runs `steps`. */
  parallel?: JsonValue;
  /** §11.2: the alternative form, a fixed list of step lists. */
  branches?: Step[][];
  join?: JoinSpec;
  stagger_ms?: IntOrExpr;
  as_result?: string;
  on_insufficient?: ErrorSpec;

  /** §11.5: deliver `input` to every subscriber of the topic. */
  publish?: string;
  delivery?: "sync" | "async" | string;

  /** §11.1: an instance name or "=cel" for call, emit and publish. */
  on?: string;
  /** §11.3 timers for emit and publish. */
  after_ms?: IntOrExpr;
  every_ms?: IntOrExpr;
  count?: IntOrExpr;
  /** §11.3: a deadline relative to the call's start. */
  deadline_ms?: IntOrExpr;
}

/** model.JoinSpec (§11.2): a whole number, "all" (default), "any", or "=cel". */
export interface JoinSpec {
  need?: number | string;
}

export const StoreOps = ["get", "put", "update", "delete", "query", "incr"] as const;
export type StoreOp = (typeof StoreOps)[number];

/** model.StoreSpec: a declarative datastore operation on state.<table>, rows keyed by string id. */
export interface StoreSpec {
  table: string;
  op: StoreOp | string;
  /** Template: the row id. */
  key?: JsonValue;
  /** Template: the row (put), a patch (update) or deltas (incr). */
  value?: JsonValue;
  /** CEL over row and key: a filter (get, query) or a condition (writes). */
  where?: string;
  /** Template: what a get miss returns instead of failing. */
  default?: JsonValue;
  /** Declared error code for a miss. */
  not_found?: string;
  /** Declared error code for a failed write condition. */
  conflict?: string;
}

/** model.Interface. Its id is "<component>.<name>". */
export interface Interface {
  id?: string;
  component: string;
  name: string;
  kind?: string;
  summary?: string;
  description?: string;
  sources?: Source[];
  attributes?: JsonObject;
  /** An inline JSON Schema, or a schema id. */
  request?: JsonValue;
  /** An inline JSON Schema, or a schema id. */
  response?: JsonValue;
  errors?: ErrorSpec[];
  latency_ms?: Latency;
  behavior?: Step[];
  /** Used when there is no behavior: the interface performs this operation on its component's state. */
  store?: StoreSpec;
  /** Topics this interface receives (§11.5). */
  subscribe?: string[];
  /** On a refinement's boundary interface: "<parent component>.<interface>" (§14.11). */
  implements?: string;
  /** Where latency_ms comes from (§14.3). */
  latency_source?: { refined?: string; pinned?: string };
}

/** model.Link */
export interface Link {
  id: string;
  from: string;
  to: string;
  kind?: string;
  label?: string;
  protocol?: string;
  summary?: string;
  sources?: Source[];
  attributes?: JsonObject;
}

/** model.Schema */
export interface Schema {
  id: string;
  summary?: string;
  schema: JsonObject;
}

/** model.FlowEntry */
export interface FlowEntry {
  caller: string;
  interface: string;
  input?: JsonValue;
  repeat?: Repeat;
  /** The instance the entry runs on (§11.1): a name or "=cel". */
  on?: string;
  /** A deadline relative to the entry's start (§11.3). */
  deadline_ms?: number;
}

/** model.Repeat: run the entry `count` passes, advancing the clock interval_ms between them. */
export interface Repeat {
  count: number;
  interval_ms?: number;
  /** Advances the clock before the first pass (§11.3). */
  initial_delay_ms?: number;
}

/** model.FlowStep */
export interface FlowStep {
  component: string;
  title: string;
  detail?: string;
  source?: Source;
}

/** model.Flow */
export interface Flow {
  id: string;
  name?: string;
  description?: string;
  entry?: FlowEntry;
  steps?: FlowStep[];
  sources?: Source[];
  tags?: string[];
}

export const FaultTypes = ["unavailable", "error", "latency", "timeout"] as const;
export type FaultType = (typeof FaultTypes)[number];

/** model.Fault */
export interface Fault {
  target: string;
  type: FaultType | string;
  code?: string;
  status?: number;
  message?: string;
  retryable?: boolean;
  latency_ms?: number;
  calls?: number[];
  /** Limits the fault to one instance (§11.1); absent means every instance. */
  instance?: string;
}

/** §11.1: component id -> instance names. */
export type Topology = { [component: string]: string[] };

/** model.Clock (§11.3) */
export interface Clock {
  /** RFC 3339. */
  epoch?: string;
  epoch_ms?: number;
}

/** model.ScenarioStep (§11.7) */
export interface ScenarioStep {
  flow?: string;
  interface?: string;
  caller?: string;
  input?: JsonValue;
  on?: string;
  choices?: { [key: string]: string };
  deadline_ms?: number;
  /** Absolute virtual start time; absent means when the previous step finished. */
  at_ms?: number;
  as?: string;
}

/** model.Mock (§11.8) */
export interface Mock {
  interface: string;
  instance?: string;
  when?: string;
  return?: JsonValue;
  fail?: JsonValue;
  calls?: number[];
}

/** model.Scenario. With `steps` (§11.7), `flow` is optional. */
export interface Scenario {
  id: string;
  flow?: string;
  name?: string;
  description?: string;
  seed?: number;
  input?: JsonValue;
  choices?: { [key: string]: string };
  state?: { [component: string]: JsonObject };
  faults?: Fault[];
  expect?: string[];
  fixtures?: string[];
  topology?: Topology;
  clock?: Clock;
  config?: JsonObject;
  steps?: ScenarioStep[];
  mocks?: Mock[];
  /** Per component path, black_box (default) or refined (§14.5). */
  resolution?: { [component: string]: Resolution };
}

/** model.Config (§11.6) */
export interface Config {
  id: string;
  type?: string;
  /** The deployed value. */
  value?: JsonValue;
  /** The code default. */
  default?: JsonValue;
  summary?: string;
  description?: string;
  sources?: Source[];
  attributes?: JsonObject;
  tags?: string[];
}

/** model.Fixture (§11.7): a named, shared starting world. */
export interface Fixture {
  id: string;
  name?: string;
  summary?: string;
  topology?: Topology;
  clock?: Clock;
  config?: JsonObject;
  state?: { [component: string]: JsonObject };
  /** Applied first, in order. */
  extends?: string[];
  attributes?: JsonObject;
}

/** model.DocSource */
export interface DocSource {
  repo?: string;
  sha?: string;
  url?: string;
}

/** model.Document: a whole ontology. */
export interface Document {
  schema_version: number;
  id?: string;
  name?: string;
  description?: string;
  source?: DocSource;
  components: Component[];
  interfaces: Interface[];
  links: Link[];
  schemas: Schema[];
  flows: Flow[];
  scenarios: Scenario[];
  configs?: Config[];
  fixtures?: Fixture[];
  /** §14.2: system, service, logic, runtime or machine (default system). */
  level?: string;
  refines?: RefinesRef;
  imports?: ImportRef[];
}

// ------------------------------------------------------------- validate.go

export type Severity = "error" | "warning";

/** model.Issue */
export interface Issue {
  path: string;
  message: string;
  severity: Severity | string;
}

// ------------------------------------------------------------- analysis.go

/** model.ChoicePoint */
export interface ChoicePoint {
  key: string;
  interface: string;
  name: string;
  options: string[];
  default?: string;
  title?: string;
}

/** model.StateInfo */
export interface StateInfo {
  component: string;
  initial?: JsonObject;
  schema?: JsonObject;
}

/** model.Plan: what a flow can reach, and the controls a simulation can set. */
export interface Plan {
  flow: string;
  entry: string;
  caller: string;
  interfaces: string[];
  components: string[];
  choices: ChoicePoint[];
  state: StateInfo[];
  faultable: string[];
  scenarios: string[];
  dynamic?: string[];
  /** Entry or call targets that are not interfaces. */
  unknown?: string[];
}

/** model.GraphNode */
export interface GraphNode {
  id: string;
  name: string;
  kind?: string;
  parent?: string;
  layer?: string;
  summary?: string;
  interfaces: string[];
  leaf: boolean;
  stateful: boolean;
}

/** model.GraphEdge. Derived edges have kind "calls" or "emits". */
export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  kind: string;
  label?: string;
  interfaces?: string[];
  derived: boolean;
}

/** model.Graph */
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ------------------------------------------------------------------ sim.go

/** sim.Request. Scenario values apply first; the request's own values overlay them. */
export interface SimRequest {
  flow?: string;
  scenario?: string;
  seed?: number;
  input?: JsonValue;
  choices?: { [key: string]: string };
  state?: { [component: string]: JsonObject };
  faults?: Fault[];
  expect?: string[];
  /** §13.1 item 6 */
  fixtures?: string[];
  topology?: Topology;
  config?: JsonObject;
  clock?: Clock;
  /** Per component path, black_box or refined, over the scenario's (§14.5, §14.11). */
  resolution?: { [component: string]: Resolution };
}

/** sim.Error */
export interface SimError {
  code: string;
  message?: string;
  status?: number;
  retryable?: boolean;
  data?: JsonValue;
}

/** sim.Outcome */
export interface Outcome {
  ok: boolean;
  value?: JsonValue;
  error?: SimError;
}

/** sim.Assertion */
export interface Assertion {
  expr: string;
  passed: boolean;
  error?: string;
}

export type RunStatus = "ok" | "error" | "aborted";

/** sim.Summary */
export interface Summary {
  status: RunStatus | string;
  result: Outcome;
  duration_ms: number;
  /** §13.1 item 16: the exact duration in µs, in runs with sub-ms time. */
  duration_us?: number;
  events: number;
  calls: { [iface: string]: number };
  retries: number;
  faults: number;
  ctx: JsonObject;
  state: { [component: string]: JsonObject };
  initial_state: { [component: string]: JsonObject };
  assertions: Assertion[];
  passed: boolean;
  warnings: string[];
  seed: number;
  abort?: string;
  /** Only for flows whose entry repeats. */
  passes?: Pass[];
  /** §11.9: keyed "<interface>@<instance>". */
  calls_by_instance?: { [key: string]: number };
  /** §11.9: the step results of a multi-step scenario. */
  steps?: StepResult[];
  /** Queue waits. */
  queued?: number;
  /** Mocked calls. */
  mocks?: number;
  /** Sorted behavior step paths that ran. */
  executed?: string[];
}

/** One step of a multi-step scenario in Summary.steps (§13.1 item 9). */
export interface StepResult {
  as?: string;
  flow?: string;
  interface?: string;
  on?: string;
  result: Outcome;
  status: RunStatus | string;
  start_ms: number;
  duration_ms: number;
  /** §13.1 item 16, in runs with sub-ms time. */
  duration_us?: number;
}

/** parallel.end output: the as_result value (§11.2). */
export interface ParallelResult {
  ok: boolean;
  received: number;
  required: number;
  failed: number;
  duration_ms: number;
  results: {
    item?: JsonValue;
    index: number;
    ok: boolean;
    value?: JsonValue;
    error?: SimError;
    start_ms: number;
    end_ms: number;
    /** §13.1 item 16, in runs with sub-ms time. */
    start_us?: number;
    end_us?: number;
    late?: boolean;
  }[];
}

/** sim.Pass: the outcome of one pass of a repeated flow entry. */
export interface Pass {
  pass: number;
  result: Outcome;
  start_ms: number;
  duration_ms: number;
  /** §13.1 item 16, in runs with sub-ms time. */
  duration_us?: number;
}

export const EventTypes = [
  "call.start",
  "call.end",
  "note",
  "set",
  "choice",
  "fault",
  "retry",
  "timeout",
  "emit",
  "warning",
  "queue",
  "publish",
  "parallel.start",
  "parallel.end",
  "step.start",
  "step.end",
  "deadline",
  "cancel",
  "restart",
  "rendezvous",
  "yield",
  "put",
  "receive",
  "kill",
] as const;
export type EventType = (typeof EventTypes)[number];

/** sim.Event: one entry of the trace. */
export interface SimEvent {
  seq: number;
  /** Virtual time in ms, floor(t_us / 1000). */
  t: number;
  /** §13.1 item 16: the exact time in µs, in runs with sub-ms time. */
  t_us?: number;
  type: EventType | string;
  span?: number;
  parent?: number;
  call?: number;
  component?: string;
  from?: string;
  to?: string;
  interface?: string;
  attempt?: number;
  async?: boolean;
  input?: JsonValue;
  output?: JsonValue;
  ok?: boolean;
  error?: SimError;
  duration_ms?: number;
  /** §13.1 item 16: the exact duration in µs, in runs with sub-ms time. */
  duration_us?: number;
  late?: boolean;
  title?: string;
  detail?: string;
  source?: Source;
  scope?: string;
  path?: string;
  old?: JsonValue;
  new?: JsonValue;
  key?: string;
  option?: string;
  origin?: string;
  fault?: string;
  backoff_ms?: number;
  message?: string;
  /** §11.1 */
  instance?: string;
  /** The call returned a scenario mock (§11.8). */
  mock?: boolean;
  /** On `queue`: the wait for a capacity slot. */
  wait_ms?: number;
  /** On `publish`. */
  topic?: string;
  /** The branch index inside a `parallel`. */
  branch?: number;
  /** On store `set` events: the table; `key` holds the raw row key (§13.1 item 11). */
  table?: string;
  /** On `yield`: the item's index in its stream (§13.1 item 18). `output` is the item. */
  index?: number;
}

// ---------------------------------------------------------- pkg/api/types.go

/** api.Health: GET /v1/health */
export interface Health {
  status: string;
  version: string;
  dolt: string;
}

/** api.SystemVersion: GET /v1/system/version */
export interface SystemVersion {
  version: string;
  /** The running build's commit ("" when unknown). */
  commit: string;
  /** The build had local changes. */
  dirty: boolean;
  branch: string;
  /** Such as origin/main. */
  upstream: string;
  /** "" when mosaicd has no --source-dir. */
  source_dir: string;
  update: UpdateStatus;
}

/** api.UpdateStatus */
export interface UpdateStatus {
  available: boolean;
  /** Why no update is possible, when unavailable. */
  reason?: string;
  /** Commits in HEAD..@{u}. */
  behind: number;
  /** Commits in @{u}..HEAD. */
  ahead: number;
  latest_commit: string;
  latest_subject: string;
  /** The last fetch (RFC 3339); null when never. */
  checked_at: string | null;
}

/** api.SystemUpdate: POST /v1/system/update */
export interface SystemUpdate {
  updated_to: string;
  from: string;
  /** mosaicd exits so that scripts/serve.sh rebuilds and restarts it and the UI. */
  restarting: boolean;
  note?: string;
}

/**
 * api.SourceFile: GET /v1/ontologies/{id}/source, a cited file's content at
 * the model's commit, fetched by mosaicd from GitHub.
 */
export interface SourceFile {
  repo: string;
  sha: string;
  path: string;
  content: string;
  /** A lowercase language name from the extension ("go", "cpp", ...), or "". */
  language_hint: string;
  /** Bytes. */
  size: number;
  /** The github.com blob URL, without a line anchor. */
  url: string;
}

/** Options of getSource: the revision, and an explicit repo/sha from a citation. */
export interface SourceOptions {
  rev?: RevSelector;
  repo?: string;
  sha?: string;
}

/** api.OntologySummary */
export interface OntologySummary {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  latest_revision: number;
  revision_count: number;
}

/** api.OntologyDetail: GET /v1/ontologies/{id} (the summary is embedded). */
export interface OntologyDetail extends OntologySummary {
  /** Keyed by singular kind: component, interface, link, schema, flow, scenario. */
  counts: { [kind: string]: number };
  draft_dirty: boolean;
  level?: string;
  refines?: RefinesRef;
}

/** api.OntologyList: GET /v1/ontologies */
export interface OntologyList {
  ontologies: OntologySummary[];
}

/** api.CreateOntology: POST /v1/ontologies */
export interface CreateOntology {
  id: string;
  name: string;
  description?: string;
}

/** api.UpdateOntology: PATCH /v1/ontologies/{id} */
export interface UpdateOntology {
  name?: string;
  description?: string;
}

/** api.Revision */
export interface Revision {
  number: number;
  hash: string;
  message: string;
  author: string;
  created_at: string;
  /** The code commit this revision models (docs/DESIGN.md §10). */
  source?: CommitSource;
}

/** api.CommitSource: the code commit an ontology revision models. */
export interface CommitSource {
  repo: string;
  sha: string;
  parent?: string;
  subject?: string;
  author?: string;
  /** RFC 3339. Go's omitempty never drops a time.Time, so a zero date arrives as "0001-01-01T00:00:00Z". */
  date?: string;
  url?: string;
}

/** api.Commit: a code commit known to an ontology, linked to the revision that models it. */
export interface Commit {
  sha: string;
  parent?: string;
  subject: string;
  author?: string;
  date: string;
  /** Paths changed relative to the parent. */
  files: string[];
  /** The revision whose source.sha is this commit; absent (0) when none. */
  revision?: number;
  /** That revision differs from the previous one. */
  changed: boolean;
  /** A browsable link to the commit, when the repository has one. */
  url?: string;
}

/** api.CommitList: GET /v1/ontologies/{id}/commits, oldest first. */
export interface CommitList {
  repo: string;
  commits: Commit[];
}

/** api.CommitDetail: GET /v1/ontologies/{id}/commits/{sha}. */
export interface CommitDetail {
  commit: Commit;
  /** The revision modelling the parent (or the latest earlier one); 0 if none. */
  before: number;
  /** The revision modelling this commit; 0 if none. */
  after: number;
  changes: Change[];
  impact: Impact | null;
}

/** api.ImportCommits: POST /v1/ontologies/{id}/commits. */
export interface ImportCommits {
  repo: string;
  commits: Commit[];
}

// ---------------------------------------------------------------- impact.go

/** model.ImpactSet: entity ids added, removed or modified between two documents. */
export interface ImpactSet {
  added: string[];
  removed: string[];
  modified: string[];
  /** Only citations changed (re-anchored lines): evidence moved, not a model change. */
  cited: string[];
}

/** model.FlowImpact: an unchanged flow whose reach contains changed entities. */
export interface FlowImpact {
  flow: string;
  /** Changed entities inside the flow's reach, as "<kind>:<id>". */
  reasons: string[];
  /**
   * How the reach was found: "traces" means scenario runs exercised it;
   * "static" means static reachability over the call graph, which
   * over-approximates. Absent from older servers.
   */
  basis?: "traces" | "static";
}

/** model.Impact: GET /v1/ontologies/{id}/impact?from=&to=, and CommitDetail.impact. */
export interface Impact {
  components: ImpactSet;
  interfaces: ImpactSet;
  links: ImpactSet;
  schemas: ImpactSet;
  flows: ImpactSet;
  scenarios: ImpactSet;
  configs: ImpactSet;
  fixtures: ImpactSet;
  flows_affected: FlowImpact[];
}

export const ImpactKinds = ["components", "interfaces", "links", "schemas", "flows", "scenarios", "configs", "fixtures"] as const;
export type ImpactKind = (typeof ImpactKinds)[number];

/** api.RevisionList: GET /v1/ontologies/{id}/revisions */
export interface RevisionList {
  revisions: Revision[];
}

/** api.CreateRevision: POST /v1/ontologies/{id}/revisions */
export interface CreateRevision {
  message: string;
  author?: string;
  source?: CommitSource;
  allow_empty?: boolean;
}

/** api.Items: entity lists. */
export interface Items {
  items: JsonValue[];
}

/** api.UpsertResult */
export interface UpsertResult {
  kind: string;
  ids: string[];
  issues: Issue[];
}

/** api.PutDocumentResult */
export interface PutDocumentResult {
  counts: { [kind: string]: number };
  valid: boolean;
  issues: Issue[];
}

export type ChangeType = "added" | "removed" | "modified";

/** api.Change */
export interface Change {
  kind: string;
  id: string;
  change: ChangeType | string;
  before?: JsonValue;
  after?: JsonValue;
}

/** api.Diff: GET /v1/ontologies/{id}/diff?from=&to= */
export interface Diff {
  from: string;
  to: string;
  changes: Change[];
}

/** api.Validation: POST /v1/ontologies/{id}/validate */
export interface Validation {
  revision: string;
  valid: boolean;
  issues: Issue[];
}

/** api.SimulationRequest: POST /v1/ontologies/{id}/simulations (sim.Request is embedded). */
export interface SimulationRequest extends SimRequest {
  /** draft (default) | latest | N */
  rev?: string;
  /** Default true. */
  save?: boolean;
}

/** api.SimulationRun: a stored or ad hoc run. */
export interface SimulationRun {
  id: string;
  ontology: string;
  /** "draft" or the revision number. */
  revision: string;
  /** For a multi-step scenario, the first step's flow. */
  flow: string;
  scenario?: string;
  created_at: string;
  request: SimRequest;
  summary: Summary;
  trace?: SimEvent[];
}

/** api.RunList: GET /v1/ontologies/{id}/simulations (runs without traces). */
export interface RunList {
  runs: SimulationRun[];
}

/** api.TestResult */
export interface TestResult {
  scenario: string;
  name: string;
  passed: boolean;
  status: string;
  assertions: Assertion[];
  abort?: string;
  error?: string;
  run_id?: string;
  /** The scenario's step count (§11.7). */
  steps?: number;
  /** Mocks declared by the scenario (§11.8). */
  mocks?: number;
  /** Calls the run mocked (summary.mocks). */
  mocked_calls?: number;
}

/** api.TestReport: POST /v1/ontologies/{id}/test */
export interface TestReport {
  revision: string;
  passed: boolean;
  total: number;
  failed: number;
  results: TestResult[];
}

/** api.ErrorDetail. Codes: bad_request, not_found, conflict, invalid, unauthorized, internal. */
export interface ErrorDetail {
  code: string;
  message: string;
  issues?: Issue[];
}

/** api.ErrorBody: every non-2xx response. */
export interface ErrorBody {
  error: ErrorDetail;
}

/** Entity collection names accepted by /ontologies/{id}/{kind}. */
export const EntityCollections = [
  "components",
  "interfaces",
  "links",
  "schemas",
  "flows",
  "scenarios",
  "configs",
  "fixtures",
] as const;
export type EntityCollection = (typeof EntityCollections)[number];

// ------------------------------------------------- local stores (§16.6)
// internal/api/local.go: read-only views of the compose run store
// (.mosaic/compose/runs, §14.11) and of `check --explore` replay files
// (.mosaic/replay, §15.5).

/** api.ComposeRunSummary */
export interface ComposeRunSummary {
  id: string;
  workflow: string;
  version?: string;
  parent?: string;
  tree_root: string;
  depth: number;
  state: string;
  reason?: string;
  created: string;
  updated: string;
}

/** api.ComposeRunList: GET /v1/compose/runs */
export interface ComposeRunList {
  root: string;
  runs: ComposeRunSummary[];
}

/** compose.AgentStats */
export interface ComposeAgentStats {
  sessions: number;
  num_turns: number;
  duration_ms: number;
  total_cost_usd: number;
}

/** compose.StageStats */
export interface ComposeStageStats {
  stage: string;
  wall_ms: number;
  branches?: number;
  agent?: ComposeAgentStats;
}

/** compose.RunStats */
export interface ComposeRunStats {
  wall_ms: number;
  agent: ComposeAgentStats;
  stages: ComposeStageStats[];
}

/** compose.ChangeRequest */
export interface ComposeChangeRequest {
  id: string;
  from_task: string;
  from_stage: string;
  target: { task: string; artifact?: string };
  body: JsonValue;
  state: string;
  recorded: string;
}

/** compose.TreeNode */
export interface ComposeTreeNode {
  id: string;
  workflow: string;
  version?: string;
  parent?: string;
  state: string;
  reason?: string;
  error?: string;
  depth: number;
  detached?: boolean;
  outputs?: string[];
  requests?: ComposeChangeRequest[];
  refusals?: { stage: string; reason: string; error: string }[];
  children?: ComposeTreeNode[];
  stats?: ComposeRunStats;
}

/** compose.Tree: GET /v1/compose/runs/{task}/tree */
export interface ComposeTree {
  root: ComposeTreeNode;
  tasks: number;
  descendants: number;
  max_depth: number;
  stats?: { wall_ms: number; agent: ComposeAgentStats };
}

/** compose.StageState */
export interface ComposeStageState {
  state: string;
  reason?: string;
  error?: string;
  visit?: number;
  routed_to?: string;
  routed?: { stage: string; reason: string; error?: string };
  started?: string;
  finished?: string;
  children?: string[];
  count?: number;
  branches?: { index: number; state: string; reason?: string; error?: string; stages: { [id: string]: ComposeStageState } }[];
  request?: string;
}

/** compose.RunRecord: run.json */
export interface ComposeRunRecord {
  id: string;
  workflow: string;
  version?: string;
  template_path?: string;
  template: JsonValue;
  inputs: { [name: string]: JsonValue };
  from_parent?: { [name: string]: string };
  parent?: string;
  tree_root: string;
  depth: number;
  origin?: { stage?: string; visit?: number; branch?: number; detached?: boolean };
  out_dir: string;
  state: string;
  reason?: string;
  error?: string;
  created: string;
  updated: string;
  stages: { [id: string]: ComposeStageState };
  artifacts: { [key: string]: { provenance: string; sha256: string; recorded: string } };
}

/** compose.SessionStats */
export interface ComposeSession {
  turn: number;
  attempt: number;
  visit?: number;
  session_id?: string;
  subtype?: string;
  is_error?: boolean;
  num_turns: number;
  duration_ms: number;
  total_cost_usd?: number;
}

/** api.ComposeRunDetail: GET /v1/compose/runs/{task} */
export interface ComposeRunDetail {
  run: ComposeRunRecord;
  requests: ComposeChangeRequest[];
  turns: { [stagePath: string]: { task: string; stage: string; attempts: ComposeSession[] } };
}

/** sim.Point: one choice point of a schedule. */
export interface SchedulePoint {
  kind: string;
  n: number;
  choice: number;
  at_ms?: number;
  label?: string;
}

/** api.ReplayFile: an explore.Replay with its file name (without .replay.json). */
export interface ReplayFile {
  name: string;
  modified: string;
  version: number;
  scenario: string;
  jitter_ms?: number;
  decisions: number[];
  points?: SchedulePoint[];
  failed?: string[];
}

/** api.ReplayList: GET /v1/replays */
export interface ReplayList {
  dir: string;
  replays: ReplayFile[];
}

/** api.ReplayRun: POST /v1/ontologies/{id}/replays/{name} (never saved). */
export interface ReplayRun {
  replay: ReplayFile;
  diverged?: string;
  failures: string[];
  run: SimulationRun;
}
