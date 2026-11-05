"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Fragment, createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { CommitDetail, CommitList, Document, Graph, OntologyDetail, RevisionList } from "@/lib/api/types";
import { useQuery, useValidation, type QueryState } from "@/lib/hooks";
import { Badge, ErrorBox, Select, cx } from "@/components/ui";
import { CodeViewerProvider } from "@/components/code/CodeViewer";
import { CommandPalette } from "@/components/palette/CommandPalette";
import { MapSkeleton, OverviewSkeleton } from "@/components/overview/Skeletons";
import { latestOf, modelIdentity } from "@/components/overview/identity";
import { ModelPassport } from "@/components/trust/ModelPassport";
import { MAP_PARAMS, TAB_GROUPS, activeTab, routeSegment } from "./tabs";

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
  /**
   * On the run page, an element at the bottom of the hidden header overlay:
   * the run's title and meta lines render into it (through a portal), so they
   * hide and reveal with the rest of the header. Null elsewhere.
   */
  chromeSlot: HTMLElement | null;
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

  // Validating a large model takes seconds, and a revision is frozen: kept per revision hash.
  const dataHash = revisions.data?.revisions.find((r) => String(r.number) === dataRev)?.hash;
  const validation = useValidation(id, detail.data ? dataRev : null, dataHash);

  const base = `/o/${encodeURIComponent(id)}`;
  const href = useCallback(
    (sub: string, extra?: Record<string, string>) => {
      const q = new URLSearchParams();
      if (explicitRev) q.set("rev", explicitRev);
      for (const [k, v] of Object.entries(extra ?? {})) q.set(k, v);
      const qs = q.toString();
      // "" is Overview now. A link built when it was the map, asking for something on the map, goes there.
      const route = sub || (Object.keys(extra ?? {}).some((k) => MAP_PARAMS.includes(k)) ? "map" : "");
      return `${base}${route ? `/${route}` : ""}${qs ? `?${qs}` : ""}`;
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

  const activeSub = routeSegment(pathname, base);
  const active = activeTab(activeSub);
  // The run page gives the run the whole viewport: the app bar, this header and
  // the run's title hide, and reveal as one overlay from the top edge.
  const focus = activeSub === "runs";
  const [chromeSlot, setChromeSlot] = useState<HTMLElement | null>(null);

  const ctx = useMemo<WorkspaceCtx>(
    () => ({ id, rev, dataRev, setRev, detail, revisions, href, chromeSlot: focus ? chromeSlot : null }),
    [id, rev, dataRev, setRev, detail, revisions, href, focus, chromeSlot],
  );
  const revs = revisions.data?.revisions ?? [];
  const latest = detail.data?.latest_revision ?? 0;
  const newest = latestOf(revs);
  const identity = modelIdentity(detail.data?.name, id, newest?.message);

  return (
    <Ctx.Provider value={ctx}>
      {focus && <ChromeHandle />}
      <div className={cx("flex flex-col", focus ? "h-dvh min-h-[480px]" : "h-[calc(100dvh-2.75rem)] min-h-[560px]")}>
        <div className={cx("shrink-0 border-b border-line", focus ? "run-chrome-ws bg-panel shadow-[0_8px_24px_rgba(0,0,0,0.45)]" : "bg-panel/60")}>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-2.5">
            <div className="flex min-w-0 items-baseline gap-2">
              <Link href="/" className="text-[12px] text-faint hover:text-ink">
                Models
              </Link>
              <span className="text-faint">/</span>
              <h1 className="truncate text-[16px] font-semibold text-ink" title={identity.staleNote}>
                {identity.title}
              </h1>
              <span className="font-mono text-[11px] text-faint">{id}</span>
            </div>
            <ModelPassport id={id} rev={rev} evidenceHref={href("evidence")} className="max-w-[min(640px,100%)]" />
            <div className="ml-auto flex items-center gap-2">
              {validation.data &&
                (validation.data.valid ? (
                  <Badge title={`The document at ${revLabel(rev)} matches the schema and its references resolve. This says nothing about whether the model is accurate.`}>Schema OK</Badge>
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
              <Select id="rev-select" value={rev} onChange={(e) => setRev(e.target.value)} className="h-7 max-w-[220px] text-[12px]">
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
              <CommandPalette id={id} rev={rev} dataRev={dataRev} href={href} />
            </div>
          </div>
          <nav aria-label="Workspace" className="mt-1.5 flex flex-wrap items-center gap-x-0.5 px-2">
            {TAB_GROUPS.filter((g) => g.length > 0).map((group, i) => (
              <Fragment key={group[0].sub}>
                {i > 0 && <span aria-hidden className="mx-2 h-4 w-px bg-line" />}
                {group.map((t) => {
                  const on = t === active;
                  return (
                    <Link
                      key={t.sub}
                      href={href(t.sub)}
                      aria-current={on ? "page" : undefined}
                      className={cx("relative rounded-t-md px-3 py-1.5 text-[13px] font-medium", on ? "text-ink" : "text-faint hover:text-ink")}
                    >
                      {t.label}
                      {on && <span className="absolute inset-x-2 -bottom-px h-[2px] rounded bg-accent" aria-hidden />}
                    </Link>
                  );
                })}
              </Fragment>
            ))}
            {active?.pages && (
              <div aria-label={`Inside ${active.label}`} role="group" className="ml-auto flex items-center gap-3 pr-2 text-[12px]">
                {active.pages.map((p) => (
                  <Link key={p.sub} href={href(p.sub)} aria-current={p.sub === activeSub ? "page" : undefined} className={p.sub === activeSub ? "text-ink" : "text-faint hover:text-ink"}>
                    {p.label}
                  </Link>
                ))}
              </div>
            )}
          </nav>
          {focus && <div ref={setChromeSlot} className="border-t border-line-soft px-4 py-2 empty:hidden" />}
        </div>
        <div className={cx("min-h-0 flex-1", focus ? "overflow-hidden" : "overflow-auto")}>
          {detail.error ? (
            <div className="p-4">
              <ErrorBox error={detail.error} onRetry={detail.reload} />
            </div>
          ) : detail.loading && !detail.data ? (
            activeSub === "map" ? <MapSkeleton /> : <OverviewSkeleton />
          ) : (
            <CodeViewerProvider>{children}</CodeViewerProvider>
          )}
        </div>
      </div>
    </Ctx.Provider>
  );
}

/**
 * The run page's hot zone along the top edge, with a visible handle. Hovering
 * the zone (or focusing anything in the header) reveals the header overlay;
 * the handle pins it open, and Escape unpins it. See .run-chrome-* in globals.css.
 */
function ChromeHandle() {
  const [pinned, setPinned] = useState(false);
  useEffect(() => {
    if (!pinned) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setPinned(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pinned]);
  return (
    <div className="run-chrome-zone fixed inset-x-0 top-0 z-[60] h-2.5" data-pinned={pinned || undefined}>
      <button
        type="button"
        onClick={() => setPinned((p) => !p)}
        aria-expanded={pinned}
        aria-label={pinned ? "Hide the header" : "Show the header"}
        title={pinned ? "Hide the header (Esc)" : "Show the header (or hover the top edge)"}
        className="absolute left-1/2 top-0 flex h-2.5 w-16 -translate-x-1/2 items-center justify-center rounded-b-md border border-t-0 border-line bg-panel-2 hover:bg-panel-3 focus-visible:h-4"
      >
        <span className="h-[2px] w-7 rounded bg-faint" aria-hidden />
      </button>
    </div>
  );
}
