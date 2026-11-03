// The real client: calls mosaicd through the server-side proxy route
// /api/mosaic/:path* -> ${MOSAIC_SERVER}/:path* (src/app/api/mosaic/[...path]).
// The browser never holds a token; the proxy adds it from MOSAIC_TOKEN.

import { ApiError, type MosaicClient } from "./client";
import {
  normalizeCommitDetail,
  normalizeCommits,
  normalizeDiff,
  normalizeGraph,
  normalizeImpact,
  normalizeReport,
  normalizeRevisions,
  normalizeRun,
  normalizeRuns,
  normalizeValidation,
} from "./normalize";
import type {
  CommitDetail,
  ComposeRunDetail,
  ComposeRunList,
  ComposeTree,
  CommitList,
  Diff,
  Document,
  ErrorBody,
  Graph,
  Health,
  Impact,
  OntologyDetail,
  OntologyList,
  JsonValue,
  Plan,
  ReplayList,
  ReplayRun,
  RevisionList,
  RevSelector,
  RunList,
  SimulationRequest,
  SimulationRun,
  SystemUpdate,
  SystemVersion,
  TestReport,
  Validation,
} from "./types";

const enc = encodeURIComponent;

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export class HttpClient implements MosaicClient {
  readonly mode = "server" as const;
  readonly target: string;
  private readonly base: string;

  constructor(base = "/api/mosaic/v1") {
    this.base = base;
    this.target = base;
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetch(`${this.base}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
      });
    } catch (err) {
      throw new ApiError(0, {
        code: "unreachable",
        message: `mosaicd is unreachable: ${err instanceof Error ? err.message : String(err)}`,
      });
    }
    const text = await res.text();
    let data: unknown = undefined;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        if (!res.ok) {
          throw new ApiError(res.status, {
            code: res.status >= 500 ? "unreachable" : "bad_response",
            message: text.slice(0, 200) || res.statusText,
          });
        }
        throw new ApiError(res.status, { code: "bad_response", message: "response is not JSON" });
      }
    }
    if (!res.ok) {
      const detail = (data as ErrorBody | undefined)?.error;
      if (res.status === 401) {
        throw new ApiError(401, {
          code: detail?.code ?? "unauthorized",
          message: `${detail?.message ?? "mosaicd rejected the request"}. mosaicd requires a bearer token: set MOSAIC_TOKEN (to mosaicd's --token) in the web server's environment and restart it.`,
        });
      }
      throw new ApiError(res.status, detail ?? { code: "http_error", message: res.statusText || `HTTP ${res.status}` });
    }
    return data as T;
  }

  health() {
    return this.request<Health>("GET", "/health");
  }

  systemVersion(refresh?: boolean) {
    return this.request<SystemVersion>("GET", `/system/version${query({ refresh: refresh ? 1 : undefined })}`);
  }

  systemUpdate() {
    return this.request<SystemUpdate>("POST", "/system/update");
  }

  async listOntologies(): Promise<OntologyList> {
    const list = await this.request<OntologyList>("GET", "/ontologies");
    return { ontologies: list.ontologies ?? [] };
  }

  getOntology(id: string) {
    return this.request<OntologyDetail>("GET", `/ontologies/${enc(id)}`);
  }

  getDocument(id: string, rev?: RevSelector) {
    return this.request<Document>("GET", `/ontologies/${enc(id)}/document${query({ rev })}`);
  }

  async getGraph(id: string, rev?: RevSelector): Promise<Graph> {
    return normalizeGraph(await this.request<Graph>("GET", `/ontologies/${enc(id)}/graph${query({ rev })}`));
  }

  async listRevisions(id: string): Promise<RevisionList> {
    return normalizeRevisions(await this.request<RevisionList>("GET", `/ontologies/${enc(id)}/revisions`));
  }

  async diff(id: string, from?: RevSelector, to?: RevSelector): Promise<Diff> {
    return normalizeDiff(await this.request<Diff>("GET", `/ontologies/${enc(id)}/diff${query({ from, to })}`));
  }

  async validate(id: string, rev?: RevSelector): Promise<Validation> {
    return normalizeValidation(await this.request<Validation>("POST", `/ontologies/${enc(id)}/validate${query({ rev })}`));
  }

  getPlan(id: string, flow: string, rev?: RevSelector) {
    return this.request<Plan>("GET", `/ontologies/${enc(id)}/flows/${enc(flow)}/plan${query({ rev })}`);
  }

  async listRuns(id: string, limit?: number): Promise<RunList> {
    return normalizeRuns(await this.request<RunList>("GET", `/ontologies/${enc(id)}/simulations${query({ limit })}`));
  }

  async runSimulation(id: string, req: SimulationRequest): Promise<SimulationRun> {
    return normalizeRun(await this.request<SimulationRun>("POST", `/ontologies/${enc(id)}/simulations`, req));
  }

  async getRun(runId: string): Promise<SimulationRun> {
    return normalizeRun(await this.request<SimulationRun>("GET", `/simulations/${enc(runId)}`));
  }

  async runTests(id: string, rev?: RevSelector): Promise<TestReport> {
    return normalizeReport(await this.request<TestReport>("POST", `/ontologies/${enc(id)}/test${query({ rev })}`));
  }

  async listCommits(id: string): Promise<CommitList> {
    return normalizeCommits(await this.request<CommitList>("GET", `/ontologies/${enc(id)}/commits`));
  }

  async getCommit(id: string, sha: string): Promise<CommitDetail> {
    return normalizeCommitDetail(await this.request<CommitDetail>("GET", `/ontologies/${enc(id)}/commits/${enc(sha)}`));
  }

  async impact(id: string, from: RevSelector, to: RevSelector): Promise<Impact> {
    return normalizeImpact(await this.request<Impact>("GET", `/ontologies/${enc(id)}/impact${query({ from, to })}`));
  }

  async listComposeRuns(): Promise<ComposeRunList> {
    const l = await this.request<ComposeRunList>("GET", "/compose/runs");
    return { root: l.root, runs: l.runs ?? [] };
  }

  getComposeTree(task: string) {
    return this.request<ComposeTree>("GET", `/compose/runs/${enc(task)}/tree`);
  }

  async getComposeRun(task: string): Promise<ComposeRunDetail> {
    const d = await this.request<ComposeRunDetail>("GET", `/compose/runs/${enc(task)}`);
    return { run: d.run, requests: d.requests ?? [], turns: d.turns ?? {} };
  }

  getComposeArtifact(task: string, key: string) {
    return this.request<JsonValue>("GET", `/compose/runs/${enc(task)}/artifacts/${key.split("/").map(enc).join("/")}`);
  }

  async listReplays(): Promise<ReplayList> {
    const l = await this.request<ReplayList>("GET", "/replays");
    return { dir: l.dir, replays: l.replays ?? [] };
  }

  async runReplay(id: string, name: string, rev?: RevSelector): Promise<ReplayRun> {
    const r = await this.request<ReplayRun>("POST", `/ontologies/${enc(id)}/replays/${enc(name)}${query({ rev })}`);
    return { ...r, failures: r.failures ?? [], run: normalizeRun(r.run) };
  }
}
