"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { formatDate } from "@/lib/model/format";
import { SemanticDiff } from "@/components/history/SemanticDiff";
import { Badge, Button, Empty, ErrorBox, Label, Panel, Select, Spinner, cx } from "@/components/ui";
import { authorName, shortSha, useWorkspace } from "./Workspace";

export function RevisionsTab() {
  const ws = useWorkspace();
  const revs = (ws.revisions.data?.revisions ?? []).slice().sort((a, b) => b.number - a.number);
  const latest = ws.detail.data?.latest_revision ?? 0;
  const search = useSearchParams();
  // Until someone picks a pair, open on the change most worth reading: the draft's
  // edits if it has any, else what the latest revision changed.
  const [picked, setPicked] = useState<{ from?: string; to?: string }>({ from: search.get("from") ?? undefined, to: search.get("to") ?? undefined });
  const dirty = !!ws.detail.data?.draft_dirty;
  const defaults = latest > 1 && !dirty ? { from: String(latest - 1), to: String(latest) } : { from: latest ? String(latest) : "draft", to: "draft" };
  const from = picked.from ?? defaults.from;
  const to = picked.to ?? defaults.to;
  const setFrom = (v: string) => setPicked({ from: v, to });
  const setTo = (v: string) => setPicked({ from, to: v });
  const pick = (f: string, t: string) => setPicked({ from: f, to: t });

  const options = (
    <>
      <option value="draft">draft</option>
      {revs.map((r) => (
        <option key={r.number} value={String(r.number)}>
          r{r.number}
        </option>
      ))}
    </>
  );
  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-1 gap-3 p-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <Panel title={`Revisions · ${revs.length}`}>
        {ws.revisions.loading && <Spinner label="Loading revisions" />}
        {ws.revisions.error ? <ErrorBox error={ws.revisions.error} onRetry={ws.revisions.reload} /> : null}
        {ws.revisions.data && revs.length === 0 && <Empty>No revisions yet. Create one with mosaic revision create.</Empty>}
        <ol className="space-y-2">
          <li className="rounded-md border border-dashed border-line px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[13px] font-semibold text-ink">draft</span>
              {ws.detail.data?.draft_dirty ? <Badge tone="warn">changed since r{latest}</Badge> : <Badge>same as latest</Badge>}
              <div className="ml-auto flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => ws.setRev("draft")} disabled={ws.rev === "draft"}>
                  Browse
                </Button>
                {latest > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => pick(String(latest), "draft")}>
                    Diff r{latest}→draft
                  </Button>
                )}
              </div>
            </div>
            <div className="text-[11.5px] text-faint">The working set. Entity writes edit it; a revision validates and freezes it.</div>
          </li>
          {revs.map((r) => {
            const current = ws.rev === String(r.number) || (ws.rev === "latest" && r.number === latest);
            return (
              <li key={r.number} className={cx("rounded-md border px-3 py-2", current ? "border-[#4d6b1f] bg-[#121b0d]" : "border-line")}>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[13px] font-semibold text-ink">r{r.number}</span>
                  {r.number === latest && <Badge tone="accent">latest</Badge>}
                  {current && <Badge tone="info">browsing</Badge>}
                  <div className="ml-auto flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => ws.setRev(String(r.number))} disabled={current}>
                      Browse
                    </Button>
                    {r.number > 1 && (
                      <Button size="sm" variant="ghost" onClick={() => pick(String(r.number - 1), String(r.number))}>
                        Diff r{r.number - 1}→r{r.number}
                      </Button>
                    )}
                  </div>
                </div>
                <div className="mt-0.5 text-[13px] text-ink">{r.message}</div>
                {r.source && (
                  <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px]">
                    <span className="text-faint">models commit</span>
                    <Link href={ws.href("commits", { sha: r.source.sha })} className="font-mono text-link hover:underline" title={`${r.source.repo} ${r.source.sha}`}>
                      {shortSha(r.source.sha)}
                    </Link>
                    {r.source.subject && <span className="min-w-0 truncate text-muted">{r.source.subject}</span>}
                    {r.source.author && <span className="text-faint">{authorName(r.source.author)}</span>}
                    {r.source.url && (
                      <a href={r.source.url} target="_blank" rel="noreferrer" className="text-link hover:underline">
                        ↗ {r.source.repo || "source"}
                      </a>
                    )}
                  </div>
                )}
                <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-faint">
                  <span>{r.author}</span>
                  <span>{formatDate(r.created_at)}</span>
                  <span className="font-mono" title={r.hash}>
                    {r.hash.slice(0, 10)}
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
      </Panel>

      <Panel
        title="Diff"
        actions={
          <div className="flex items-center gap-1.5">
            <Label htmlFor="diff-from">from</Label>
            <Select id="diff-from" value={from} onChange={(e) => setFrom(e.target.value)} className="h-7 text-[12px]">
              {options}
            </Select>
            <span className="text-faint">→</span>
            <Label htmlFor="diff-to">to</Label>
            <Select id="diff-to" value={to} onChange={(e) => setTo(e.target.value)} className="h-7 text-[12px]">
              {options}
            </Select>
          </div>
        }
      >
        <SemanticDiff key={`${ws.id}:${from}:${to}`} ontology={ws.id} base={from} head={to} />
      </Panel>
    </div>
  );
}
