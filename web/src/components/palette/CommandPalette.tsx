"use client";

// Search over everything in the model (/ or Cmd-K). Results are the navigation. The index is
// flat strings built once per document, and only the rows in view are rendered.

import { useRouter } from "next/navigation";
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Document } from "@/lib/api/types";
import { useEvidence } from "@/lib/evidence";
import { useDocIndex, useQuery } from "@/lib/hooks";
import { cx, Kbd } from "@/components/ui";
import { FidelityMark } from "@/components/trust/marks";
import { OTHER_PAGES, TAB_GROUPS } from "@/components/workspace/tabs";
import { isTypingTarget } from "./keys";
import { Modal } from "./Modal";
import { KIND_LABEL, documentEntries, mechanismEntries, pageEntries, rowWindow, scrollToRow, searchPalette, type PaletteEntry } from "./search";
import { globalAction } from "./shortcuts";

export interface CommandPaletteProps {
  id: string;
  rev: string;
  dataRev: string;
  /** Builds an href inside the workspace that keeps ?rev. */
  href: (sub: string, extra?: Record<string, string>) => string;
}

const ROW_HEIGHT = 40;
const VISIBLE_ROWS = 10;
const VIEWPORT = ROW_HEIGHT * VISIBLE_ROWS;

/** The trigger for the workspace header and the dialog it opens. Mount once. */
export function CommandPalette(props: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (globalAction(ev, isTypingTarget(ev.target)) === "palette") {
        ev.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Search the model (/ or Cmd-K)"
        className="flex h-7 items-center gap-1.5 rounded-md border border-line bg-panel-2 px-2 text-[12px] text-muted hover:bg-panel-3 hover:text-ink"
      >
        Search <Kbd>/</Kbd>
      </button>
      {open && (
        <Modal
          label="Search the model"
          onClose={() => setOpen(false)}
          className="mx-auto mt-[12vh] w-[min(720px,calc(100vw-32px))] overflow-hidden rounded-lg border border-line bg-panel p-0 text-ink shadow-[0_16px_48px_rgba(0,0,0,0.6)] backdrop:bg-black/60"
        >
          <PaletteBody {...props} onClose={() => setOpen(false)} />
        </Modal>
      )}
    </>
  );
}

const pagesIndex = pageEntries([
  ...TAB_GROUPS.flat().flatMap((t) => [
    { sub: t.sub, label: t.label },
    ...(t.pages ?? []).filter((p) => p.sub !== t.sub).map((p) => ({ sub: p.sub, label: p.label, tab: t.label })),
  ]),
  ...OTHER_PAGES,
]);

const documentCache = new WeakMap<Document, PaletteEntry[]>();

function PaletteBody({ id, rev, dataRev, href, onClose }: CommandPaletteProps & { onClose: () => void }) {
  const router = useRouter();
  // The document is shared with every tab; this only fetches if the current page hasn't.
  const doc = useQuery<Document>(`doc:${id}:${dataRev}`, (c) => c.getDocument(id, rev));
  const idx = useDocIndex(doc.data);
  const { evidence } = useEvidence(id, rev);
  const items = evidence?.mechanisms?.items;

  const entries = useMemo(() => {
    let inDoc: PaletteEntry[] = [];
    if (doc.data && idx) {
      const have = documentCache.get(doc.data);
      inDoc = have ?? documentEntries(doc.data, idx);
      if (!have) documentCache.set(doc.data, inDoc);
    }
    return [...pagesIndex, ...inDoc, ...mechanismEntries(items ?? [])];
  }, [doc.data, idx, items]);

  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const results = useMemo(() => searchPalette(entries, deferred), [entries, deferred]);

  const [active, setActive] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const listId = useId();

  // A new result list starts from the top.
  const [shownFor, setShownFor] = useState(results);
  if (shownFor !== results) {
    setShownFor(results);
    setActive(0);
    setScrollTop(0);
  }
  useEffect(() => {
    if (list.current) list.current.scrollTop = 0;
  }, [results]);

  const go = (e: PaletteEntry | undefined) => {
    if (!e) return;
    onClose();
    router.push(href(e.sub, e.params));
  };

  const moveTo = (row: number) => {
    const next = Math.max(0, Math.min(results.length - 1, row));
    setActive(next);
    const el = list.current;
    if (!el) return;
    const top = scrollToRow(next, el.scrollTop, VIEWPORT, ROW_HEIGHT);
    if (top !== el.scrollTop) {
      el.scrollTop = top;
      setScrollTop(top);
    }
  };

  const onKeyDown = (ev: React.KeyboardEvent) => {
    if (ev.key === "ArrowDown") moveTo(active + 1);
    else if (ev.key === "ArrowUp") moveTo(active - 1);
    else if (ev.key === "PageDown") moveTo(active + VISIBLE_ROWS);
    else if (ev.key === "PageUp") moveTo(active - VISIBLE_ROWS);
    else if (ev.key === "Enter") go(results[active]);
    else return;
    ev.preventDefault();
  };

  const win = rowWindow(scrollTop, VIEWPORT, ROW_HEIGHT, results.length);
  const optionId = (row: number) => `${listId}-${row}`;
  const hasQuery = deferred.trim().length > 0;

  return (
    <div>
      <input
        autoFocus
        type="text"
        role="combobox"
        aria-expanded
        aria-controls={listId}
        aria-activedescendant={results.length ? optionId(active) : undefined}
        aria-autocomplete="list"
        aria-label="Search components, interfaces, flows, scenarios, configs and mechanisms"
        placeholder="Search components, interfaces, flows, scenarios, configs, mechanisms"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        className="h-11 w-full border-b border-line bg-transparent px-3 text-[14px] text-ink outline-none placeholder:text-faint focus-visible:outline-none"
      />
      <div
        ref={list}
        id={listId}
        role="listbox"
        aria-label="Results"
        tabIndex={-1}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        className="relative overflow-y-auto"
        style={{ height: results.length ? Math.min(VIEWPORT, results.length * ROW_HEIGHT) : undefined }}
      >
        <div style={{ height: results.length * ROW_HEIGHT }}>
          {results.slice(win.start, win.end).map((e, i) => {
            const row = win.start + i;
            return (
              <div
                key={`${e.kind}:${e.id}`}
                id={optionId(row)}
                role="option"
                aria-selected={row === active}
                aria-posinset={row + 1}
                aria-setsize={results.length}
                onMouseMove={() => row !== active && setActive(row)}
                onClick={() => go(e)}
                className={cx("absolute inset-x-0 flex cursor-pointer items-center gap-2.5 px-3", row === active ? "bg-panel-3" : "")}
                style={{ top: row * ROW_HEIGHT, height: ROW_HEIGHT }}
              >
                <span className="w-[72px] shrink-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-faint">{KIND_LABEL[e.kind]}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] leading-tight text-ink">{e.title}</span>
                  {e.detail && <span className="block truncate text-[11px] leading-tight text-faint">{e.detail}</span>}
                </span>
                {e.fidelity && <FidelityMark fidelity={e.fidelity} />}
              </div>
            );
          })}
        </div>
      </div>
      {results.length === 0 && hasQuery && <div className="px-3 py-4 text-center text-[12.5px] text-muted">Nothing in this model matches &quot;{deferred.trim()}&quot;.</div>}
      <div role="status" className="flex items-center justify-between gap-3 border-t border-line-soft px-3 py-1.5 text-[11px] text-faint">
        <span className="tnum">
          {doc.error
            ? "The model couldn't be read, so only pages are searched."
            : !doc.data
              ? "Loading the model…"
              : hasQuery
                ? `${results.length} ${results.length === 1 ? "result" : "results"}`
                : `${entries.length - pagesIndex.length} things to search`}
        </span>
        <span className="flex items-center gap-1">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd> move <Kbd>Enter</Kbd> open <Kbd>Esc</Kbd> close
        </span>
      </div>
    </div>
  );
}
