// Validate results kept across page loads, per revision. A revision is frozen,
// so its result only changes with the validator, and a day's expiry covers a
// daemon upgrade. A draft isn't kept: it has no hash, and it changes. Pure over
// a Storage-like object, so `pnpm test` can run it.

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const INDEX = "mosaic.validate.index";
const PREFIX = "mosaic.validate:";
const MAX_ENTRIES = 16;
const MAX_BYTES = 256 * 1024;
export const VALIDATION_TTL_MS = 24 * 60 * 60 * 1000;

function readIndex(store: StorageLike): string[] {
  try {
    const v: unknown = JSON.parse(store.getItem(INDEX) ?? "[]");
    return Array.isArray(v) ? v.filter((k): k is string => typeof k === "string") : [];
  } catch {
    return [];
  }
}

/** The stored result of a revision with this hash, or undefined. */
export function readValidation<T>(store: StorageLike, id: string, rev: string, hash: string, now: number): T | undefined {
  try {
    const raw = store.getItem(`${PREFIX}${id}:${rev}:${hash}`);
    if (!raw) return undefined;
    const v = JSON.parse(raw) as { at: number; result: T };
    return now - v.at < VALIDATION_TTL_MS ? v.result : undefined;
  } catch {
    return undefined;
  }
}

/** Stores a result, dropping the oldest past the bound. Storage trouble only loses the cache. */
export function writeValidation(store: StorageLike, id: string, rev: string, hash: string, result: unknown, now: number) {
  try {
    const raw = JSON.stringify({ at: now, result });
    if (raw.length > MAX_BYTES) return;
    const key = `${PREFIX}${id}:${rev}:${hash}`;
    store.setItem(key, raw);
    const index = [...readIndex(store).filter((k) => k !== key), key];
    while (index.length > MAX_ENTRIES) store.removeItem(index.shift()!);
    store.setItem(INDEX, JSON.stringify(index));
  } catch {
    // quota or privacy mode
  }
}
