"use client";

// The Flows tab with ?commit=<sha>: the flows the commit created, modified,
// removed or affected, each with a diff of its definition and of its reach.

import Link from "next/link";
import { useState } from "react";
import type { Change, CommitDetail, Document, Flow, FlowImpact, JsonValue, Plan } from "@/lib/api/types";
import { ifaceComponent, plural } from "@/lib/model/format";
import { parseReason } from "@/lib/model/impact";
import { useDocIndex, useQuery } from "@/lib/hooks";
import { ChangeView } from "@/components/diff";
import { JsonView } from "@/components/json";
import { Badge, Empty, ErrorBox, Panel, Spinner, cx } from "@/components/ui";
import { shortSha, useCommitDetail, useWorkspace } from "./Workspace";

type Group = "added" | "modified" | "removed" | "affected";

const GROUPS: { key: Group; title: string; hint: string; tone: "ok" | "warn" | "bad" | "info" }[] = [
  { key: "added", title: "Flows created", hint: "New flow definitions.", tone: "ok" },
  { key: "modified", title: "Flows modified", hint: "The flow's own definition changed.", tone: "warn" },
  { key: "removed", title: "Flows removed", hint: "Definitions that no longer exist.", tone: "bad" },
  { key: "affected", title: "Flows affected", hint: "The definition is unchanged, but the flow reaches changed entities.", tone: "info" },
];

function usePlan(rev: number, flow: string, enabled: boolean) {
  const ws = useWorkspace();
  return useQuery(enabled && rev ? `plan:${ws.id}:${rev}:${flow}` : null, (c) => c.getPlan(ws.id, flow, String(rev)));
}

function ReachDiff({ before, after }: { before?: Plan; after?: Plan }) {
  const b = new Set(before?.interfaces ?? []);
  const a = new Set(after?.interfaces ?? []);
  const added = Array.from(a).filter((x) => !b.has(x)).sort();
  const removed = Array.from(b).filter((x) => !a.has(x)).sort();
  if (!added.length && !removed.length) return <div className="text-[12px] text-faint">The flow reaches the same {plural(a.size, "interface")}.</div>;
  return (
    <div className="flex flex-wrap gap-1">
      {added.map((i) => (
        <span key={i} className="rounded border border-[#1f4d2a] bg-[#11251a] px-1 font-mono text-[11px] text-ok">
          + {i}
        </span>
      ))}
      {removed.map((i) => (
        <span key={i} className="rounded border border-[#5c2a2a] bg-[#2a1517] px-1 font-mono text-[11px] text-bad line-through">
          − {i}
        </span>
      ))}
    </div>
  );
}

const BASIS: Record<NonNullable<FlowImpact["basis"]>, { label: string; tone: "ok" | "neutral"; title: string }> = {
  traces: {
    label: "exercised by scenarios",
    tone: "ok",
    title: "Scenario runs of this flow actually went through the changed entities listed here.",
  },
  static: {
    label: "static reach",
    tone: "neutral",
    title:
      "Found by static reachability over the call graph, not by running scenarios. Static reach over-approximates: it counts every path the flow could take, so the flow may never actually hit these changes.",
  },
};

export function BasisBadge({ basis }: { basis?: FlowImpact["basis"] }) {
  if (!basis) return null;
  const b = BASIS[basis];
  return (
    <Badge tone={b.tone} title={b.title} className="cursor-help">
      {b.label}
    </Badge>
  );
}

function FlowItem({
  id,
  group,
  flow,
  change,
  reasons,
  basis,
  detail,
}: {
  id: string;
  group: Group;
  flow?: Flow;
  change?: Change;
  reasons?: string[];
  basis?: FlowImpact["basis"];
  detail: CommitDetail;
}) {
  const ws = useWorkspace();
  const [open, setOpen] = useState(false);
  const before = usePlan(detail.before, id, open && group !== "added");
  const after = usePlan(detail.after, id, open && group !== "removed");
  const sha = detail.commit.sha;
  const tone = group === "added" ? "ok" : group === "removed" ? "bad" : group === "modified" ? "warn" : "info";
  return (
    <li className="rounded-md border border-line bg-panel-2/40">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left hover:bg-panel-2">
        <span className="text-faint" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
        <span className="text-[13px] font-semibold text-ink">{flow?.name || id}</span>
        <span className="font-mono text-[11px] text-faint">{id}</span>
        <Badge tone={tone}>{group}</Badge>
        <BasisBadge basis={basis} />
        {reasons && <span className="ml-auto text-[11.5px] text-muted">{plural(reasons.length, "changed entity", "changed entities")} in reach</span>}
      </button>
      {reasons && (
        <div className="flex flex-wrap items-center gap-1 px-3 pb-2 pl-8">
          {reasons.map((r) => {
            const { kind, id: eid } = parseReason(r);
            const comp = kind === "interface" ? ifaceComponent(eid) : kind === "component" ? eid : null;
            const label = (
              <>
                <span className="text-faint">{kind}</span> {eid}
              </>
            );
            return comp ? (
              <Link
                key={r}
                href={ws.href("", { commit: sha, c: comp })}
                className="rounded border border-[#24445a] bg-[#122230] px-1 font-mono text-[11px] text-link hover:underline"
                title="Show it on the before/after map"
              >
                {label}
              </Link>
            ) : (
              <span key={r} className="rounded border border-line px-1 font-mono text-[11px] text-muted">
                {label}
              </span>
            );
          })}
        </div>
      )}
      {open && (
        <div className="space-y-3 border-t border-line-soft px-3 py-3">
          <section>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
              Definition{group === "affected" ? " (unchanged)" : ""}
            </h4>
            {change ? (
              <ul>
                <ChangeView c={change} defaultOpen />
              </ul>
            ) : flow ? (
              <JsonView value={flow as unknown as JsonValue} maxHeight={220} />
            ) : (
              <div className="text-[12px] text-faint">Not found in either revision.</div>
            )}
          </section>
          <section>
            <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
              Reach r{detail.before || "∅"} → r{detail.after}
            </h4>
            {before.error || after.error ? (
              <ErrorBox error={before.error || after.error} />
            ) : before.loading || after.loading ? (
              <Spinner label="Loading plans" />
            ) : (
              <ReachDiff before={before.data} after={after.data} />
            )}
          </section>
          {group !== "removed" && (
            <Link href={ws.href("flows", { rev: String(detail.after), flow: id })} className="inline-block text-[12px] text-link hover:underline">
              Open the flow at r{detail.after} →
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

export function FlowsChanged({ sha }: { sha: string }) {
  const ws = useWorkspace();
  const detail = useCommitDetail(sha);
  const d = detail.data;
  const afterDoc = useQuery<Document>(d?.after ? `doc:${ws.id}:${d.after}` : null, (c) => c.getDocument(ws.id, String(d!.after)));
  const beforeDoc = useQuery<Document>(d?.before ? `doc:${ws.id}:${d.before}` : null, (c) => c.getDocument(ws.id, String(d!.before)));
  const afterIdx = useDocIndex(afterDoc.data);
  const beforeIdx = useDocIndex(beforeDoc.data);

  const back = (
    <Link href={ws.href("flows")} className="text-[12px] text-link hover:underline">
      ← All flows
    </Link>
  );
  if (detail.error) return <div className="space-y-2 p-4">{back}<ErrorBox error={detail.error} onRetry={detail.reload} /></div>;
  if (!d) return <Spinner label="Loading commit" />;
  if (!d.impact)
    return (
      <div className="space-y-2 p-4">
        {back}
        <Empty>No revision models commit {shortSha(d.commit.sha)}, so no flows can be compared.</Empty>
      </div>
    );
  const imp = d.impact;
  const flowOf = (id: string) => afterIdx?.flowsById.get(id) ?? beforeIdx?.flowsById.get(id);
  const changeOf = (id: string) => d.changes.find((c) => c.kind === "flow" && c.id === id);
  const items: Record<Group, { id: string; reasons?: string[]; basis?: FlowImpact["basis"] }[]> = {
    added: imp.flows.added.map((id) => ({ id })),
    modified: imp.flows.modified.map((id) => ({ id })),
    removed: imp.flows.removed.map((id) => ({ id })),
    affected: imp.flows_affected.map((f) => ({ id: f.flow, reasons: f.reasons, basis: f.basis })),
  };
  const total = Object.values(items).reduce((n, l) => n + l.length, 0);

  return (
    <div className="mx-auto max-w-[1200px] space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {back}
        <h2 className="text-[15px] font-semibold text-ink">Flows changed by</h2>
        <Link href={ws.href("commits", { sha: d.commit.sha })} className="font-mono text-[13px] text-link hover:underline">
          {shortSha(d.commit.sha)}
        </Link>
        <span className="min-w-0 truncate text-[13px] text-ink">{d.commit.subject}</span>
        <span className="font-mono text-[12px] text-faint">
          r{d.before || "∅"} → r{d.after}
        </span>
        <Link href={ws.href("", { commit: d.commit.sha })} className="ml-auto text-[12px] text-link hover:underline">
          Architecture before/after →
        </Link>
      </div>
      {total === 0 && <Empty>This commit creates, modifies or affects no flows.</Empty>}
      {GROUPS.map((g) =>
        items[g.key].length === 0 && g.key === "removed" ? null : (
          <Panel key={g.key} title={`${g.title} · ${items[g.key].length}`} actions={<span className="text-[11px] text-faint">{g.hint}</span>}>
            {items[g.key].length === 0 ? (
              <div className={cx("text-[12.5px] text-faint")}>None.</div>
            ) : (
              <ul className="space-y-1.5">
                {items[g.key].map((it) => (
                  <FlowItem key={it.id} id={it.id} group={g.key} flow={flowOf(it.id)} change={changeOf(it.id)} reasons={it.reasons} basis={it.basis} detail={d} />
                ))}
              </ul>
            )}
          </Panel>
        ),
      )}
    </div>
  );
}
