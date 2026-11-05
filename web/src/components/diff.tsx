"use client";

// Line diffs of entity JSON, shared by the Revisions tab and the commit views.

import { useMemo, useState, type ReactNode } from "react";
import type { Change, JsonValue } from "@/lib/api/types";
import { Badge, cx } from "@/components/ui";

export type DiffLine = { op: " " | "+" | "-"; text: string; a?: number; b?: number };

/** A line diff (LCS). Entities are small, so O(n·m) is fine; huge ones fall back to replace. */
export function lineDiff(a: string[], b: string[]): DiffLine[] {
  if (a.length * b.length > 4_000_000) {
    return [...a.map((t, i) => ({ op: "-" as const, text: t, a: i + 1 })), ...b.map((t, i) => ({ op: "+" as const, text: t, b: i + 1 }))];
  }
  const n = a.length;
  const m = b.length;
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ op: " ", text: a[i], a: i + 1, b: j + 1 });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ op: "-", text: a[i], a: i + 1 });
      i++;
    } else {
      out.push({ op: "+", text: b[j], b: j + 1 });
      j++;
    }
  }
  while (i < n) out.push({ op: "-", text: a[i], a: ++i });
  while (j < m) out.push({ op: "+", text: b[j], b: ++j });
  return out;
}

export function linesOf(v: JsonValue | undefined): string[] {
  return v === undefined ? [] : JSON.stringify(v, null, 2).split("\n");
}

/** Hides long unchanged runs, keeping 3 lines of context. */
export function withContext(lines: DiffLine[], ctx = 3): (DiffLine | { skip: number })[] {
  const keep = new Array(lines.length).fill(false);
  lines.forEach((l, i) => {
    if (l.op !== " ") for (let k = Math.max(0, i - ctx); k <= Math.min(lines.length - 1, i + ctx); k++) keep[k] = true;
  });
  const out: (DiffLine | { skip: number })[] = [];
  let skipped = 0;
  lines.forEach((l, i) => {
    if (keep[i]) {
      if (skipped) out.push({ skip: skipped });
      skipped = 0;
      out.push(l);
    } else skipped++;
  });
  if (skipped) out.push({ skip: skipped });
  return out;
}

/**
 * One entity change, collapsible, with a line diff of its JSON. The diff is only
 * computed once it's open, so a long list stays cheap. Pass `open` and `onToggle`
 * when the row can unmount while open (a windowed list).
 */
export function ChangeView({
  c,
  defaultOpen,
  open: controlled,
  onToggle,
  detail,
  as: Root = "li",
}: {
  c: Change;
  defaultOpen?: boolean;
  open?: boolean;
  onToggle?: () => void;
  /** Shown in the header: what changed, in words. */
  detail?: ReactNode;
  as?: "li" | "div";
}) {
  const [own, setOwn] = useState(defaultOpen ?? c.change === "modified");
  const open = controlled ?? own;
  const diff = useMemo(() => (open ? withContext(lineDiff(linesOf(c.before), linesOf(c.after))) : null), [c, open]);
  const tone = c.change === "added" ? "ok" : c.change === "removed" ? "bad" : "warn";
  return (
    <Root className="rounded-md border border-line bg-panel-2/40">
      <button
        type="button"
        onClick={() => (onToggle ? onToggle() : setOwn((o) => !o))}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-panel-2"
      >
        <span className="text-faint" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
        <Badge tone={tone}>{c.change === "added" ? "+ added" : c.change === "removed" ? "− removed" : "~ modified"}</Badge>
        <span className="text-[11px] text-faint">{c.kind}</span>
        <span className="min-w-0 truncate font-mono text-[12.5px] text-ink">{c.id}</span>
        {detail}
        {diff && (
          <span className="tnum ml-auto shrink-0 text-[11px]">
            <span className="text-ok">+{diff.filter((l) => "op" in l && l.op === "+").length}</span> <span className="text-bad">−{diff.filter((l) => "op" in l && l.op === "-").length}</span>
          </span>
        )}
      </button>
      {diff && (
        <pre aria-label={`JSON diff of ${c.id}`} className="max-h-[420px] overflow-auto border-t border-line-soft bg-[#0c1116] py-1 font-mono text-[11.5px] leading-[1.5]" tabIndex={0}>
          {diff.map((l, i) =>
            "skip" in l ? (
              <div key={i} className="px-2 text-faint">
                ⋯ {l.skip} unchanged lines
              </div>
            ) : (
              <div
                key={i}
                className={cx(
                  "grid grid-cols-[36px_36px_14px_1fr] px-1",
                  l.op === "+" && "bg-[#0f2416] text-[#b9f5c4]",
                  l.op === "-" && "bg-[#2a1214] text-[#ffc4c2]",
                  l.op === " " && "text-muted",
                )}
              >
                <span className="tnum select-none pr-1 text-right text-faint">{l.a ?? ""}</span>
                <span className="tnum select-none pr-1 text-right text-faint">{l.b ?? ""}</span>
                <span className="select-none">{l.op === " " ? "" : l.op}</span>
                <span className="whitespace-pre-wrap break-all">{l.text}</span>
              </div>
            ),
          )}
        </pre>
      )}
    </Root>
  );
}
