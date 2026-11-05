// The pure part of windowing: which rows and lanes a scroll position needs. A trace can pass
// 19,000 events and 75 lanes, so only what's on screen, plus a margin, ever reaches the DOM.
//
// Only type imports here: node --test runs this file with type stripping.

export interface RowBox {
  top: number;
  h: number;
}

/** The index of the first box ending after `y`. Boxes ascend by top; a hidden box has h 0. */
export function firstRowAt(rows: readonly RowBox[], y: number): number {
  let lo = 0;
  let hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].top + rows[mid].h > y) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** The index of the last box starting before `y`, or -1. */
export function lastRowBefore(rows: readonly RowBox[], y: number): number {
  let lo = 0;
  let hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].top < y) lo = mid + 1;
    else hi = mid;
  }
  return lo - 1;
}

export interface Viewport {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The region to draw for a viewport: the viewport plus a margin, clamped to the content. */
export function drawRegion(v: Viewport, contentW: number, contentH: number, marginX: number, marginY: number): Viewport {
  const x = Math.max(0, v.x - marginX);
  const y = Math.max(0, v.y - marginY);
  return {
    x,
    y,
    w: Math.max(0, Math.min(contentW, v.x + v.w + marginX) - x),
    h: Math.max(0, Math.min(contentH, v.y + v.h + marginY) - y),
  };
}

/** Whether a drawn region still covers a viewport, so scrolling needs no new render. */
export function covers(region: Viewport, v: Viewport, contentW: number, contentH: number): boolean {
  return (
    v.x >= region.x &&
    v.y >= region.y &&
    Math.min(contentW, v.x + v.w) <= region.x + region.w &&
    Math.min(contentH, v.y + v.h) <= region.y + region.h
  );
}

/** Pixel-binned ticks for a scrubber: for each bin, what to draw. Bounded by `bins`, not by events. */
export function binTicks<T extends string>(tones: readonly (T | null)[], bins: number, rank: (tone: T) => number): { bin: number; tone: T }[] {
  const n = tones.length;
  if (n === 0 || bins <= 0) return [];
  const best = new Map<number, T>();
  for (let i = 0; i < n; i++) {
    const tone = tones[i];
    if (tone === null) continue;
    const bin = n <= 1 ? 0 : Math.round((i / (n - 1)) * (bins - 1));
    const cur = best.get(bin);
    if (cur === undefined || rank(tone) < rank(cur)) best.set(bin, tone);
  }
  return Array.from(best, ([bin, tone]) => ({ bin, tone })).sort((a, b) => a.bin - b.bin);
}
