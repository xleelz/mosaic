"use client";

// The one long list (docs/ux-plan-2026-11.md, scale rule: no view renders rows nobody can see).
// It draws the rows near the viewport of whatever scrolls it, and short lists draw whole. Rows can
// have any height and can change it: each is measured once drawn, and `estimate` stands in until then.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { rowOffsets, rowWindow } from "@/lib/windowing";

/** At or below this many rows, a list draws them all. */
const WINDOW_OVER = 150;

function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if (o === "auto" || o === "scroll") return p;
  }
  return null;
}

export function WindowedList<T>({
  items,
  itemKey,
  render,
  estimate = 44,
  label,
  scroll = "parent",
  overscan = 8,
  ensure,
  scrollToKey,
  className,
  rowClassName,
}: {
  items: T[];
  itemKey: (item: T) => string;
  render: (item: T, index: number) => ReactNode;
  /** A row's height in px until it has been measured. */
  estimate?: number | ((item: T) => number);
  /** The accessible name of the list. */
  label?: string;
  /**
   * "parent": the nearest scrolling ancestor scrolls it, so the page has one scrollbar.
   * "self": the list scrolls itself, needs a height from `className`, and takes one tab stop so the
   * keyboard can scroll it (axe: scrollable-region-focusable).
   */
  scroll?: "parent" | "self";
  /** Rows drawn past each edge. */
  overscan?: number;
  /** Brings this index into view, when it changes (a deep link, a selection). */
  ensure?: number;
  /** The same, by key. */
  scrollToKey?: string;
  className?: string;
  rowClassName?: string;
}) {
  const windowed = items.length > WINDOW_OVER;
  const self = scroll === "self";
  const root = useRef<HTMLUListElement>(null);
  const [view, setView] = useState({ top: 0, height: 900 });
  const [measured, setMeasured] = useState<ReadonlyMap<string, number>>(() => new Map());

  const scroller = useCallback(() => (self ? root.current : root.current && scrollParent(root.current)), [self]);
  /** How far the scroller's top is past the list's top. Negative while the list sits below it. */
  const listScrolled = useCallback((list: HTMLElement, by: HTMLElement | null): number => {
    if (by === list) return list.scrollTop;
    return (by ? by.getBoundingClientRect().top : 0) - list.getBoundingClientRect().top;
  }, []);

  useEffect(() => {
    const el = root.current;
    if (!windowed || !el) return;
    const by = scroller();
    let frame = 0;
    const update = () => {
      frame = 0;
      const top = listScrolled(el, by);
      const height = by ? by.clientHeight : window.innerHeight;
      setView((v) => (v.top === top && v.height === height ? v : { top, height }));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    schedule();
    const target: HTMLElement | Window = by ?? window;
    target.addEventListener("scroll", schedule, { passive: true });
    const ro = new ResizeObserver(schedule);
    if (by) ro.observe(by);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      target.removeEventListener("scroll", schedule);
      ro.disconnect();
    };
  }, [windowed, scroller, listScrolled]);

  // One observer for the drawn rows; sizes are applied together, once a frame.
  const rows = useRef<ResizeObserver | null>(null);
  const pending = useRef(new Map<string, number>());
  const sizeFrame = useRef(0);
  useEffect(() => {
    if (!windowed) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const key = (e.target as HTMLElement).dataset.rowKey;
        if (key !== undefined) pending.current.set(key, (e.target as HTMLElement).offsetHeight);
      }
      if (sizeFrame.current) return;
      sizeFrame.current = requestAnimationFrame(() => {
        sizeFrame.current = 0;
        const next = pending.current;
        pending.current = new Map();
        setMeasured((m) => {
          let changed = false;
          for (const [k, h] of next) if (m.get(k) !== h) changed = true;
          return changed ? new Map([...m, ...next]) : m;
        });
      });
    });
    rows.current = ro;
    root.current?.querySelectorAll("[data-row-key]").forEach((el) => ro.observe(el));
    return () => {
      ro.disconnect();
      rows.current = null;
      cancelAnimationFrame(sizeFrame.current);
      sizeFrame.current = 0;
    };
  }, [windowed]);
  const attach = useCallback((el: HTMLElement | null) => {
    const ro = rows.current;
    if (!el || !ro) return;
    ro.observe(el);
    return () => ro.unobserve(el);
  }, []);

  const offsets = useMemo(
    () => rowOffsets(windowed ? items.length : 0, (i) => measured.get(itemKey(items[i])) ?? (typeof estimate === "function" ? estimate(items[i]) : estimate)),
    [windowed, items, itemKey, estimate, measured],
  );

  // A row out of view scrolls to the top. Rows above it are estimates until drawn, so measuring moves
  // it: keep following until it settles, or until someone scrolls for themselves.
  const keyIndex = useMemo(() => (scrollToKey === undefined ? -1 : items.findIndex((it) => itemKey(it) === scrollToKey)), [items, itemKey, scrollToKey]);
  const target = ensure !== undefined && ensure >= 0 ? ensure : keyIndex;
  const following = useRef({ on: false, moved: false });
  useEffect(() => {
    following.current = { on: target >= 0, moved: false };
  }, [target]);
  useEffect(() => {
    const el = root.current;
    const by = scroller();
    if (!windowed || !el || !by) return;
    const stop = () => {
      following.current.on = false;
    };
    by.addEventListener("wheel", stop, { passive: true });
    by.addEventListener("pointerdown", stop);
    by.addEventListener("keydown", stop);
    return () => {
      by.removeEventListener("wheel", stop);
      by.removeEventListener("pointerdown", stop);
      by.removeEventListener("keydown", stop);
    };
  }, [windowed, scroller]);
  useEffect(() => {
    const el = root.current;
    const by = scroller();
    if (!windowed || !el || !by || target < 0 || target >= items.length || !following.current.on) return;
    const rowTop = offsets[target] - listScrolled(el, by);
    if (!following.current.moved && rowTop >= 0 && rowTop <= by.clientHeight - 40) return;
    following.current.moved = true;
    if (Math.abs(rowTop) > 1) by.scrollTop += rowTop;
  }, [windowed, target, items.length, offsets, scroller, listScrolled]);

  const focusable = self ? { tabIndex: 0 } : {};
  if (!windowed) {
    return (
      <ul ref={root} aria-label={label} className={className} {...focusable}>
        {items.map((it, i) => (
          <li key={itemKey(it)} className={rowClassName}>
            {render(it, i)}
          </li>
        ))}
      </ul>
    );
  }
  const w = rowWindow(offsets, view.top, view.height, overscan);
  return (
    <ul ref={root} aria-label={label} className={className} {...focusable}>
      {w.before > 0 && <li aria-hidden style={{ height: w.before }} />}
      {items.slice(w.start, w.end).map((it, i) => {
        const key = itemKey(it);
        return (
          <li key={key} ref={attach} data-row-key={key} aria-posinset={w.start + i + 1} aria-setsize={items.length} className={rowClassName}>
            {render(it, w.start + i)}
          </li>
        );
      })}
      {w.after > 0 && <li aria-hidden style={{ height: w.after }} />}
    </ul>
  );
}
