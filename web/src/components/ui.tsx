"use client";

import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { errorMessage, isFixtureUnsupported } from "@/lib/api";
import type { Source } from "@/lib/api/types";
import { sourceString } from "@/lib/model/format";
import { useOpenSource } from "@/components/code/context";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "default" | "ghost" | "danger";

export function Button({
  variant = "default",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        size === "sm" ? "h-7 px-2 text-xs" : "h-8 px-3 text-[13px]",
        variant === "primary" && "border-accent bg-accent text-accent-ink hover:bg-[#d9ff9a]",
        variant === "default" && "border-line bg-panel-2 text-ink hover:bg-panel-3",
        variant === "ghost" && "border-transparent bg-transparent text-muted hover:bg-panel-2 hover:text-ink",
        variant === "danger" && "border-[#5c2a2a] bg-[#2a1517] text-bad hover:bg-[#341a1d]",
        className,
      )}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        "h-8 rounded-md border border-line bg-panel-2 px-2 text-[13px] text-ink hover:border-[#3a4a57] disabled:opacity-50",
        className,
      )}
    >
      {children}
    </select>
  );
}

export const inputClass =
  "h-8 rounded-md border border-line bg-panel-2 px-2 text-[13px] text-ink placeholder:text-faint hover:border-[#3a4a57]";

export function Label({ children, htmlFor, className }: { children: ReactNode; htmlFor?: string; className?: string }) {
  return (
    <label htmlFor={htmlFor} className={cx("text-2xs font-medium uppercase tracking-[0.08em] text-faint", className)}>
      {children}
    </label>
  );
}

export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cx("flex min-h-0 flex-col rounded-lg border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex min-h-9 shrink-0 items-center justify-between gap-2 border-b border-line-soft px-3 py-1.5">
          {title && <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">{title}</h2>}
          {actions && <div className="flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cx("min-h-0 flex-1", bodyClassName ?? "p-3")}>{children}</div>
    </section>
  );
}

export type Tone = "neutral" | "ok" | "bad" | "warn" | "info" | "accent" | "violet";

const toneClass: Record<Tone, string> = {
  neutral: "border-line bg-panel-2 text-muted",
  ok: "border-[#1f4d2a] bg-[#11251a] text-ok",
  bad: "border-[#5c2a2a] bg-[#2a1517] text-bad",
  warn: "border-[#5a4520] bg-[#2a2213] text-warn",
  info: "border-[#24445a] bg-[#122230] text-link",
  accent: "border-[#4d6b1f] bg-[#1c2a10] text-accent",
  violet: "border-[#3d3766] bg-[#1d1a33] text-violet",
};

/** A badge's classes, for elements that look like one (such as a button). */
export function badgeClass(tone: Tone = "neutral", className?: string): string {
  return cx(
    "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded border px-1.5 text-[11px] font-medium leading-none",
    toneClass[tone],
    className,
  );
}

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={badgeClass(tone, className)}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  if (status === "ok") return <Badge tone="ok">✓ ok</Badge>;
  if (status === "error") return <Badge tone="bad">✗ error</Badge>;
  if (status === "aborted") return <Badge tone="warn">⊘ aborted</Badge>;
  return <Badge>{status}</Badge>;
}

export function PassBadge({ passed }: { passed: boolean }) {
  return passed ? <Badge tone="ok">✓ pass</Badge> : <Badge tone="bad">✗ fail</Badge>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line bg-panel-2 px-1 font-mono text-[10px] text-muted">
      {children}
    </kbd>
  );
}

/**
 * A code citation. Inside a CodeViewerProvider (the workspace) it is a button
 * that opens the file at the model's commit in the code viewer; elsewhere,
 * plain text.
 */
export function SourceRef({ source, className }: { source: Source; className?: string }) {
  const open = useOpenSource();
  const s = sourceString(source);
  const title = source.repo ? `${source.repo} ${s}` : s;
  if (!open) {
    return (
      <span className={cx("font-mono text-[11px] text-link", className)} title={title}>
        {s}
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        open(source, e.currentTarget);
      }}
      title={`Open ${title} in the code viewer`}
      data-source-ref=""
      className={cx(
        "cursor-pointer break-all rounded-sm text-left font-mono text-[11px] text-link decoration-link/60 underline-offset-2 hover:underline",
        className,
      )}
    >
      {s}
    </button>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-4 text-muted">
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" aria-hidden />
      {label}…
    </div>
  );
}

export function ErrorBox({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const fixture = isFixtureUnsupported(error);
  return (
    <div
      role="alert"
      className={cx(
        "flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-[13px]",
        fixture ? "border-[#5a4520] bg-[#221c10] text-warn" : "border-[#5c2a2a] bg-[#211214] text-bad",
        className,
      )}
    >
      <div>
        <div className="font-semibold">{fixture ? "Not available in fixture mode" : "Request failed"}</div>
        <div className="text-ink/90">{errorMessage(error)}</div>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-line px-3 py-4 text-center text-muted">{children}</div>;
}

export function KV({ k, children }: { k: ReactNode; children: ReactNode }) {
  return (
    <>
      <dt className="text-faint">{k}</dt>
      <dd className="min-w-0 break-words text-ink">{children}</dd>
    </>
  );
}

export function Notice({ tone = "info", title, children }: { tone?: "info" | "warn"; title?: string; children: ReactNode }) {
  return (
    <div
      role="note"
      className={cx(
        "rounded-md border-l-2 px-3 py-2 text-[13px]",
        tone === "warn" ? "border-st-warning bg-[#211c10] text-ink" : "border-link bg-[#0f1c27] text-ink",
      )}
    >
      {title && <div className="mb-0.5 font-semibold">{title}</div>}
      <div className="text-muted">{children}</div>
    </div>
  );
}

/**
 * Renders a long list a page at a time: the first `step` items, then the next
 * page whenever the end comes within reach of the viewport (or on "Show
 * more"). Rows can have any height, so expanded rows are fine. `ensure` makes
 * sure an item index is rendered (a deep link to row 450). Give it a `key`
 * that changes with the list to start again from the top.
 */
export function ProgressiveList<T>({
  items,
  render,
  step = 100,
  ensure,
  className,
  as: Tag = "ul",
}: {
  items: T[];
  render: (item: T, index: number) => ReactNode;
  step?: number;
  ensure?: number;
  className?: string;
  as?: "ul" | "ol" | "div" | "tbody";
}) {
  const [limit, setLimit] = useState(step);
  const want = ensure !== undefined && ensure >= 0 ? Math.max(limit, Math.ceil((ensure + 1) / step) * step) : limit;
  const shown = Math.min(items.length, want);
  const more = shown < items.length;
  const sentinel = useRef<HTMLElement | null>(null);
  const setSentinel = (el: HTMLElement | null) => {
    sentinel.current = el;
  };
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !more) return;
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) setLimit(shown + step);
    }, { rootMargin: "600px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [more, shown, step]);
  const tail = (
    <>
      Showing {shown} of {items.length} ·{" "}
      <button type="button" className="text-link hover:underline" onClick={() => setLimit(shown + step)}>
        show more
      </button>
    </>
  );
  const tailClass = "list-none px-2 py-2 text-[12px] text-faint";
  return (
    <Tag className={className}>
      {items.slice(0, shown).map(render)}
      {more &&
        (Tag === "tbody" ? (
          <tr ref={setSentinel}>
            <td colSpan={99} className={tailClass}>
              {tail}
            </td>
          </tr>
        ) : Tag === "div" ? (
          <div ref={setSentinel} className={tailClass}>
            {tail}
          </div>
        ) : (
          <li ref={setSentinel} className={tailClass}>
            {tail}
          </li>
        ))}
    </Tag>
  );
}
