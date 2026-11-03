// The typed client interface shared by the real (mosaicd) and fixture clients.

import type {
  CommitDetail,
  ComposeRunDetail,
  ComposeRunList,
  ComposeTree,
  CommitList,
  Diff,
  Document,
  ErrorDetail,
  Graph,
  Health,
  Impact,
  Issue,
  OntologyDetail,
  OntologyList,
  Plan,
  JsonValue,
  ReplayList,
  ReplayRun,
  RevisionList,
  RevSelector,
  RunList,
  SimulationRequest,
  SimulationRun,
  SourceFile,
  SourceOptions,
  SystemUpdate,
  SystemVersion,
  TestReport,
  Validation,
} from "./types";

export type ClientMode = "server" | "fixtures";

export interface MosaicClient {
  readonly mode: ClientMode;
  /** Where requests go, for display. */
  readonly target: string;

  health(): Promise<Health>;
  /** The running build and whether its checkout can be updated; refresh fetches the upstream now. */
  systemVersion(refresh?: boolean): Promise<SystemVersion>;
  /** Fast-forwards mosaicd's checkout; under scripts/serve.sh mosaicd then restarts with the UI. */
  systemUpdate(): Promise<SystemUpdate>;
  listOntologies(): Promise<OntologyList>;
  getOntology(id: string): Promise<OntologyDetail>;
  getDocument(id: string, rev?: RevSelector): Promise<Document>;
  getGraph(id: string, rev?: RevSelector): Promise<Graph>;
  /** A cited file at the document's commit (or a citation's repo/sha), through mosaicd. */
  getSource(id: string, path: string, opts?: SourceOptions): Promise<SourceFile>;
  listRevisions(id: string): Promise<RevisionList>;
  diff(id: string, from?: RevSelector, to?: RevSelector): Promise<Diff>;
  validate(id: string, rev?: RevSelector): Promise<Validation>;
  getPlan(id: string, flow: string, rev?: RevSelector): Promise<Plan>;
  listRuns(id: string, limit?: number): Promise<RunList>;
  runSimulation(id: string, req: SimulationRequest): Promise<SimulationRun>;
  getRun(runId: string): Promise<SimulationRun>;
  runTests(id: string, rev?: RevSelector): Promise<TestReport>;
  /** Code commits, oldest first (docs/DESIGN.md §10). */
  listCommits(id: string): Promise<CommitList>;
  getCommit(id: string, sha: string): Promise<CommitDetail>;
  impact(id: string, from: RevSelector, to: RevSelector): Promise<Impact>;

  // Read-only local stores next to mosaicd (§16.6, internal/api/local.go).
  /** Every task of the compose run store. */
  listComposeRuns(): Promise<ComposeRunList>;
  /** The run tree containing a task, with stats. */
  getComposeTree(task: string): Promise<ComposeTree>;
  /** A task's run.json, the change requests addressed to it, and its agent sessions. */
  getComposeRun(task: string): Promise<ComposeRunDetail>;
  getComposeArtifact(task: string, key: string): Promise<JsonValue>;
  /** `check --explore` replay files. */
  listReplays(): Promise<ReplayList>;
  /** Runs a replay's scenario under its schedule; never saved. */
  runReplay(id: string, name: string, rev?: RevSelector): Promise<ReplayRun>;
}

/** A non-2xx response from mosaicd, or a transport failure (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly issues: Issue[];

  constructor(status: number, detail: ErrorDetail) {
    super(detail.message || detail.code);
    this.name = "ApiError";
    this.status = status;
    this.code = detail.code;
    this.issues = detail.issues ?? [];
  }
}

/** Raised by the fixture client for requests that need a live mosaicd. */
export class FixtureUnsupportedError extends ApiError {
  constructor(message: string) {
    super(501, { code: "fixture_unsupported", message });
    this.name = "FixtureUnsupportedError";
  }
}

export function isFixtureUnsupported(err: unknown): err is FixtureUnsupportedError {
  return err instanceof ApiError && err.code === "fixture_unsupported";
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.status ? `${err.message} (${err.code}, HTTP ${err.status})` : err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
