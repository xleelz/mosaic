"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import type { Commit, CommitDetail, Impact, Revision } from "@/lib/api/types";
import { formatDate, plural } from "@/lib/model/format";
import { ENTITY_KINDS, impactTotal, setSize } from "@/lib/model/impact";
import { Badge, Empty, ErrorBox, Label, Panel, Spinner, cx, inputClass } from "@/components/ui";
import { authorName, shortSha, useCommitDetail, useCommits, useWorkspace } from "./Workspace";

const linkButton =
  "inline-flex h-7 items-center rounded-md border border-line bg-panel-2 px-2 text-xs font-medium text-ink hover:bg-panel-3";

function ModelBadge({ c }: { c: Commit }) {
  if (!c.revision) return <Badge title="No revision models this commit">no revision</Badge>;
  return c.changed ? (
    <Badge tone="accent" title="The model differs from the previous revision">
      ◆ model changed
    </Badge>
  ) : (
    <Badge title="The revision for this commit is identical to the previous one">no model change</Badge>
  );
}

function CommitRow({ c, selected, onSelect }: { c: Commit; selected: boolean; onSelect: () => void }) {
  const ws = useWorkspace();
  return (
    <li>
      <div
        className={cx(
          "rounded-md border px-3 py-2",
          selected ? "border-[#4d6b1f] bg-[#121b0d]" : "border-line hover:border-[#3a4a57] hover:bg-panel-2/60",
        )}
      >
        <div className="flex items-center gap-2">
          {c.url ? (
            <a href={c.url} target="_blank" rel="noreferrer" className="font-mono text-[12px] text-link hover:underline" title={`Open ${c.sha}`}>
              {shortSha(c.sha)}
            </a>
          ) : (
            <span className="font-mono text-[12px] text-faint" title={c.sha}>
              {shortSha(c.sha)}
            </span>
          )}
          <button type="button" onClick={onSelect} aria-current={selected ? "true" : undefined} className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-ink hover:underline">
            {c.subject}
          </button>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
          <span>{authorName(c.author)}</span>
          <span>{formatDate(c.date)}</span>
          <span>{plural(c.files.length, "file")}</span>
          <ModelBadge c={c} />
          {c.revision ? (
            <Link href={ws.href("", { rev: String(c.revision) })} className="font-mono text-link hover:underline" title={`Browse revision ${c.revision}`}>
              r{c.revision}
            </Link>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export function ImpactSummary({ impact }: { impact: Impact }) {
  const rows = ENTITY_KINDS.filter((k) => setSize(impact[k.key]) > 0);
  const cited = ENTITY_KINDS.reduce((n, k) => n + (impact[k.key].cited?.length ?? 0), 0);
  return (
    <div className="space-y-2">
      {cited > 0 ? (
        <div className="text-[12.5px] text-muted" title="These entities only had their code citations re-anchored to new line numbers; the model did not change.">
          {plural(cited, "entity", "entities")} with citations re-anchored (no model change)
        </div>
      ) : null}
      {rows.length === 0 ? (
        <div className="text-[12.5px] text-muted">No model changes.</div>
      ) : (
        <table className="w-full max-w-[460px] text-[12.5px]">
          <thead>
            <tr className="text-left text-[11px] text-faint">
              <th className="py-1 font-medium">kind</th>
              <th className="py-1 text-right font-medium text-ok">added</th>
              <th className="py-1 text-right font-medium text-warn">modified</th>
              <th className="py-1 text-right font-medium text-bad">removed</th>
            </tr>
          </thead>
          <tbody className="tnum">
            {rows.map((k) => {
              const s = impact[k.key];
              return (
                <tr key={k.key} className="border-t border-line-soft">
                  <td className="py-1 text-ink">{k.key}</td>
                  <td className="py-1 text-right">{s.added.length || <span className="text-faint">·</span>}</td>
                  <td className="py-1 text-right">{s.modified.length || <span className="text-faint">·</span>}</td>
                  <td className="py-1 text-right">{s.removed.length || <span className="text-faint">·</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="text-[12.5px] text-muted">
        {impact.flows_affected.length ? (
          <>
            <span className="font-semibold text-ink">{plural(impact.flows_affected.length, "flow")} affected</span> (unchanged, but
            {impact.flows_affected.length === 1 ? " it reaches" : " they reach"} changed entities):{" "}
            <span className="font-mono text-[12px] text-ink">{impact.flows_affected.map((f) => f.flow).join(", ")}</span>
          </>
        ) : (
          "No other flows are affected."
        )}
      </div>
    </div>
  );
}

function DetailView({ d, revision }: { d: CommitDetail; revision?: Revision }) {
  const ws = useWorkspace();
  const c = d.commit;
  const url = c.url || (revision?.source?.sha === c.sha ? revision.source.url : undefined);
  const changedComponents = d.impact ? setSize(d.impact.components) + d.impact.interfaces.added.length + d.impact.interfaces.removed.length + d.impact.interfaces.modified.length : 0;
  const changedFlows = d.impact ? setSize(d.impact.flows) + d.impact.flows_affected.length : 0;
  return (
    <div className="space-y-4">
      <header>
        <h3 className="text-[16px] font-semibold text-ink">{c.subject}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
          {url ? (
            <a href={url} target="_blank" rel="noreferrer" className="font-mono text-link hover:underline" title="Open the commit">
              {c.sha} ↗
            </a>
          ) : (
            <span className="font-mono text-ink">{c.sha}</span>
          )}
          <span>{c.author}</span>
          <span>{formatDate(c.date)}</span>
          {c.parent && (
            <span>
              parent{" "}
              <Link href={ws.href("commits", { sha: c.parent })} className="font-mono text-link hover:underline">
                {shortSha(c.parent)}
              </Link>
            </span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
          <ModelBadge c={c} />
          <span className="text-faint">revisions</span>
          {d.before ? (
            <Link href={ws.href("", { rev: String(d.before) })} className="font-mono text-link hover:underline">
              r{d.before}
            </Link>
          ) : (
            <span className="text-faint">none</span>
          )}
          <span className="text-faint">→</span>
          {d.after ? (
            <Link href={ws.href("", { rev: String(d.after) })} className="font-mono text-link hover:underline">
              r{d.after}
            </Link>
          ) : (
            <span className="text-faint">none</span>
          )}
        </div>
        {d.after > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Link href={ws.href("", { commit: c.sha })} className={linkButton}>
              View architecture before/after{changedComponents ? ` · ${changedComponents}` : ""}
            </Link>
            <Link href={ws.href("flows", { commit: c.sha })} className={linkButton}>
              View flows changed{changedFlows ? ` · ${changedFlows}` : ""}
            </Link>
            {d.before > 0 && (
              <Link href={ws.href("revisions", { from: String(d.before), to: String(d.after) })} className={linkButton}>
                Entity diff r{d.before}→r{d.after}
              </Link>
            )}
          </div>
        )}
      </header>

      <section>
        <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Impact</h4>
        {d.impact ? (
          <ImpactSummary impact={d.impact} />
        ) : (
          <div className="text-[12.5px] text-muted">No revision models this commit, so there is nothing to compare.</div>
        )}
        {d.impact && impactTotal(d.impact) === 0 && d.after > 0 && (
          <div className="mt-1 text-[12px] text-faint">The commit changes no modeled code: r{d.after} is identical to r{d.before}.</div>
        )}
      </section>

      <section>
        <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">Changed files · {c.files.length}</h4>
        {c.files.length === 0 ? (
          <div className="text-[12.5px] text-muted">No files recorded.</div>
        ) : (
          <ul className="max-h-[320px] overflow-auto rounded-md border border-line-soft bg-[#0c1116] py-1 font-mono text-[12px]">
            {c.files.map((f) => (
              <li key={f} className="truncate px-2.5 py-0.5 text-ink" title={f}>
                {f}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function CommitsTab() {
  const ws = useWorkspace();
  const commits = useCommits();
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [q, setQ] = useState("");

  const list = useMemo(() => (commits.data?.commits ?? []).slice().reverse(), [commits.data]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return list.filter(
      (c) =>
        (!onlyChanged || c.changed) &&
        (!needle ||
          c.sha.startsWith(needle) ||
          c.subject.toLowerCase().includes(needle) ||
          (c.author ?? "").toLowerCase().includes(needle) ||
          c.files.some((f) => f.toLowerCase().includes(needle))),
    );
  }, [list, onlyChanged, q]);

  const selectedSha = search.get("sha");
  const selected = selectedSha ? list.find((c) => c.sha === selectedSha || c.sha.startsWith(selectedSha)) : undefined;
  const detail = useCommitDetail(selected?.sha ?? null);
  const revision = (ws.revisions.data?.revisions ?? []).find((r) => r.number === selected?.revision);

  const select = useCallback(
    (sha: string) => {
      const p = new URLSearchParams(search.toString());
      p.set("sha", sha);
      router.replace(`${pathname}?${p.toString()}`, { scroll: false });
    },
    [pathname, router, search],
  );

  const changedCount = list.filter((c) => c.changed).length;

  return (
    <div className="mx-auto grid h-full max-w-[1400px] grid-cols-1 gap-3 p-4 xl:grid-cols-[minmax(0,480px)_minmax(0,1fr)]">
      <Panel
        title={`Commits · ${list.length}`}
        className="xl:max-h-full"
        bodyClassName="flex min-h-0 flex-col p-3"
        actions={commits.data?.repo ? <span className="font-mono text-[11px] text-faint">{commits.data.repo}</span> : undefined}
      >
        <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <Label htmlFor="commit-search" className="sr-only">
            Search commits
          </Label>
          <input
            id="commit-search"
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search sha, subject, author or file"
            className={cx(inputClass, "min-w-0 flex-1")}
          />
          <label className="flex items-center gap-1.5 text-[12px] text-muted">
            <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} className="accent-[#ccff78]" />
            Only commits that change the model ({changedCount})
          </label>
        </div>
        {commits.loading && <Spinner label="Loading commits" />}
        {commits.error ? <ErrorBox error={commits.error} onRetry={commits.reload} /> : null}
        {commits.data && list.length === 0 && (
          <Empty>
            No commits imported. Run <span className="font-mono">mosaic commits import --repo PATH --range A..B</span>.
          </Empty>
        )}
        {commits.data && list.length > 0 && shown.length === 0 && <Empty>No commits match.</Empty>}
        <ol className="min-h-0 flex-1 space-y-1.5 overflow-auto" aria-label="Commits, newest first">
          {shown.map((c) => (
            <CommitRow key={c.sha} c={c} selected={selected?.sha === c.sha} onSelect={() => select(c.sha)} />
          ))}
        </ol>
      </Panel>

      <Panel title={selected ? `Commit ${shortSha(selected.sha)}` : "Commit"} bodyClassName="min-h-0 overflow-auto p-4">
        {!selected ? (
          <Empty>{selectedSha ? `Unknown commit ${selectedSha}.` : "Select a commit to see what it changed in the model."}</Empty>
        ) : detail.error ? (
          <ErrorBox error={detail.error} onRetry={detail.reload} />
        ) : !detail.data ? (
          <Spinner label="Loading commit" />
        ) : (
          <DetailView d={detail.data} revision={revision} />
        )}
      </Panel>
    </div>
  );
}
