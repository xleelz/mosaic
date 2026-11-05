// Which rows of a long list to draw (components/workspace/WindowedList.tsx).
// Rows can have any height: unmeasured ones count as an estimate. Pure, so
// `pnpm test` can run it.

/** offsets[i] is the top of row i, and the last entry is the total height. */
export function rowOffsets(count: number, heightOf: (index: number) => number): Float64Array {
  const out = new Float64Array(count + 1);
  for (let i = 0; i < count; i++) out[i + 1] = out[i] + heightOf(i);
  return out;
}

/** The row containing y: the last i with offsets[i] <= y, clamped to a row. */
export function rowAt(offsets: Float64Array, y: number): number {
  const count = offsets.length - 1;
  if (count <= 0) return 0;
  let lo = 0;
  let hi = count - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (offsets[mid] <= y) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export interface RowWindow {
  /** The first row to draw. */
  start: number;
  /** One past the last row to draw. */
  end: number;
  /** Empty space above and below the drawn rows, in px. */
  before: number;
  after: number;
}

export function rowWindow(offsets: Float64Array, scrollTop: number, viewport: number, overscan: number): RowWindow {
  const count = offsets.length - 1;
  if (count <= 0) return { start: 0, end: 0, before: 0, after: 0 };
  const total = offsets[count];
  // A list that shrank can leave scrollTop past its end until the browser clamps it.
  const top = Math.max(0, Math.min(scrollTop, Math.max(0, total - viewport)));
  const start = Math.max(0, rowAt(offsets, top) - overscan);
  const end = Math.min(count, rowAt(offsets, top + viewport) + 1 + overscan);
  return { start, end, before: offsets[start], after: total - offsets[end] };
}
