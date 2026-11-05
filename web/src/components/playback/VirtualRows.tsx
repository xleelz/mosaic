"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "@/components/ui";

/** How many rows to draw past each edge. */
const OVERSCAN = 8;

/**
 * A fixed-height list that renders only the rows on screen, for anything that can pass about
 * 500 rows. `focus` keeps a row in view, and centers it when `focusKey` changes.
 */
export function VirtualRows({
  count,
  rowHeight,
  render,
  focus,
  focusKey,
  className,
  label,
  paddingBottom = 0,
}: {
  count: number;
  rowHeight: number;
  render: (index: number) => ReactNode;
  focus?: number;
  focusKey?: unknown;
  className?: string;
  label?: string;
  /** Room past the last row, for a floating panel that covers the bottom edge. */
  paddingBottom?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(0);
  const [height, setHeight] = useState(600);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setHeight(el.clientHeight));
    ro.observe(el);
    setHeight(el.clientHeight);
    return () => ro.disconnect();
  }, []);

  const centered = useRef<unknown>(Symbol("never"));
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || focus === undefined || focus < 0) return;
    const y = focus * rowHeight;
    const center = centered.current !== focusKey;
    centered.current = focusKey;
    const viewH = Math.max(rowHeight, el.clientHeight - paddingBottom);
    if (center) el.scrollTop = Math.max(0, y - viewH / 2);
    else if (y < el.scrollTop) el.scrollTop = y;
    else if (y + rowHeight > el.scrollTop + viewH) el.scrollTop = y + rowHeight - viewH;
    setTop(el.scrollTop);
  }, [focus, focusKey, rowHeight, paddingBottom]);

  const first = Math.max(0, Math.floor(top / rowHeight) - OVERSCAN);
  const last = Math.min(count - 1, Math.ceil((top + height) / rowHeight) + OVERSCAN);
  const rows: ReactNode[] = [];
  for (let i = first; i <= last; i++) {
    rows.push(
      <div key={i} role="listitem" className="absolute inset-x-0" style={{ top: i * rowHeight, height: rowHeight }}>
        {render(i)}
      </div>,
    );
  }
  return (
    <div ref={ref} tabIndex={0} role="list" aria-label={label} className={cx("relative overflow-y-auto", className)} onScroll={(ev) => setTop(ev.currentTarget.scrollTop)}>
      <div className="relative" style={{ height: count * rowHeight + paddingBottom }}>
        {rows}
      </div>
    </div>
  );
}
