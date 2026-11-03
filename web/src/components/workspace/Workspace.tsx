"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import type { CommitDetail, CommitList, Document, Graph, OntologyDetail, RevisionList } from "@/lib/api/types";
import { useQuery, type QueryState } from "@/lib/hooks";
import { Badge, ErrorBox, Select, Spinner, cx } from "@/components/ui";

export interface WorkspaceCtx {
  id: string;
  /** The selected revision: "draft", "latest" or a number. */
  rev: string;
  /**
   * The cache key for data at rev: "latest" resolved to its number, so the
   * document, graph and plans are cached once per revision and shared with
   * views that ask by number (run playback, commit views). Requests still
   * send rev.
   */
  dataRev: string;
  setRev: (rev: string) => void;
  detail: QueryState<OntologyDetail>;
  revisions: QueryState<RevisionList>;
  /** Builds an href inside the workspace that keeps ?rev. */
  href: (sub: string, extra?: Record<string, string>) => string;
}

const Ctx = createContext<WorkspaceCtx | null>(null);

export function useWorkspace(): WorkspaceCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useWorkspace outside the workspace");
  return c;
}

/** The document at the selected revision. */
export function useDocument(): QueryState<Document> {
  const { id, rev, dataRev } = useWorkspace();
  return useQuery(`doc:${id}:${dataRev}`, (c) => c.getDocument(id, rev));
}

export function useGraph(): QueryState<Graph> {
  const { id, rev, dataRev } = useWorkspace();
  return useQuery(`graph:${id}:${dataRev}`, (c) => c.getGraph(id, rev));
}

/** The ontology's code commits, oldest first. */
export function useCommits(): QueryState<CommitList> {
  const { id } = useWorkspace();
  return useQuery(`commits:${id}`, (c) => c.listCommits(id));
}

export function useCommitDetail(sha: string | null): QueryState<CommitDetail> {
  const { id } = useWorkspace();
  return useQuery(sha ? `commit:${id}:${sha}` : null, (c) => c.getCommit(id, sha!));
}

export function shortSha(sha: string): string {
  return sha.slice(0, 7);
}

/** "Ada Lovelace <ada@example.com>" -> "Ada Lovelace". */
export function authorName(a: string | undefined): string {
  return (a ?? "").replace(/\s*<[^>]*>\s*$/, "") || a || "";
}

const TABS: { sub: string; label: string }[] = [
  { sub: "", label: "Architecture" },
  { sub: "flows", label: "Flows" },
  { sub: "world", label: "Configs & fixtures" },
  { sub: "simulate", label: "Simulate" },
  { sub: "commits", label: "Commits" },
  { sub: "revisions", label: "Revisions" },
  { sub: "tests", label: "Tests" },
  { sub: "explore", label: "Exploration" },
];

export function revLabel(rev: string): string {
  if (rev === "draft" || rev === "latest") return rev;
  return `r${rev}`;
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const search = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const detail = useQuery(`detail:${id}`, (c) => c.getOntology(id));
  const revisions = useQuery(`revisions:${id}`, (c) => c.listRevisions(id));

  const explicitRev = search.get("rev");
  const rev = explicitRev || (detail.data && detail.data.latest_revision === 0 ? "draft" : "latest");

  const dataRev = rev === "latest" && detail.data?.latest_revision ? String(detail.data.latest_revision) : rev;

  const validation = useQuery(detail.data ? `validate:${id}:${rev}` : null, (c) => c.validate(id, rev));

  const base = `/o/${encodeURIComponent(id)}`;
  const href = useCallback(
    (sub: string, extra?: Record<string, string>) => {
      const q = new URLSearchParams();
      if (explicitRev) q.set("rev", explicitRev);
      for (const [k, v] of Object.entries(extra ?? {})) q.set(k, v);
      const qs = q.toString();
      return `${base}${sub ? `/${sub}` : ""}${qs ? `?${qs}` : ""}`;
    },
    [base, explicitRev],
  );

  const setRev = useCallback(
    (r: string) => {
      const q = new URLSearchParams(search.toString());
      q.set("rev", r);
      router.replace(`${pathname}?${q.toString()}`, { scroll: false });
    },
    [pathname, router, search],
  );

  const ctx = useMemo<WorkspaceCtx>(() => ({ id, rev, dataRev, setRev, detail, revisions, href }), [id, rev, dataRev, setRev, detail, revisions, href]);

  const activeSub = pathname.replace(base, "").replace(/^\//, "").split("/")[0];
  const revs = revisions.data?.revisions ?? [];
  const latest = detail.data?.latest_revision ?? 0;

  return (
    <Ctx.Provider value={ctx}>
      <div className="flex h-[calc(100dvh-2.75rem)] min-h-[560px] flex-col">
        <div className="shrink-0 border-b border-line bg-panel/60">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-2.5">
            <div className="flex min-w-0 items-baseline gap-2">
              <Link href="/" className="text-[12px] text-faint hover:text-ink">
                Ontologies
              </Link>
              <span className="text-faint">/</span>
              <h1 className="truncate text-[16px] font-semibold text-ink">{detail.data?.name || id}</h1>
              <span className="font-mono text-[11px] text-faint">{id}</span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              {validation.data &&
                (validation.data.valid ? (
                  <Badge tone="ok" title={`Validated ${revLabel(rev)}`}>
                    ✓ valid
                  </Badge>
                ) : (
                  <Badge tone="bad" title={validation.data.issues.map((i) => `${i.path}: ${i.message}`).join("\n")}>
                    ✗ {validation.data.issues.filter((i) => i.severity === "error").length} issues
                  </Badge>
                ))}
              {validation.data && validation.data.issues.some((i) => i.severity === "warning") && (
                <Badge tone="warn">⚠ {validation.data.issues.filter((i) => i.severity === "warning").length} warnings</Badge>
              )}
              {detail.data?.draft_dirty && <Badge tone="warn">draft changed</Badge>}
              <label htmlFor="rev-select" className="text-[11px] text-faint">
                Revision
              </label>
              <Select id="rev-select" value={rev} onChange={(e) => setRev(e.target.value)} className="h-7 text-[12px]">
                <option value="latest" disabled={latest === 0}>
                  latest{latest ? ` (r${latest})` : ""}
                </option>
                <option value="draft">draft</option>
                {revs
                  .slice()
                  .sort((a, b) => b.number - a.number)
                  .map((r) => (
                    <option key={r.number} value={String(r.number)}>
                      r{r.number} · {r.message.slice(0, 40)}
                    </option>
                  ))}
              </Select>
            </div>
          </div>
          <nav aria-label="Workspace" className="mt-1.5 flex gap-0.5 px-2">
            {TABS.map((t) => {
              const active = t.sub === activeSub || (t.sub === "simulate" && activeSub === "runs");
              return (
                <Link
                  key={t.sub}
                  href={href(t.sub)}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "relative rounded-t-md px-3 py-1.5 text-[13px] font-medium",
                    active ? "text-ink" : "text-faint hover:text-ink",
                  )}
                >
                  {t.label}
                  {active && <span className="absolute inset-x-2 -bottom-px h-[2px] rounded bg-accent" aria-hidden />}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {detail.error ? (
            <div className="p-4">
              <ErrorBox error={detail.error} onRetry={detail.reload} />
            </div>
          ) : detail.loading && !detail.data ? (
            <Spinner label="Loading ontology" />
          ) : (
            children
          )}
        </div>
      </div>
    </Ctx.Provider>
  );
}
