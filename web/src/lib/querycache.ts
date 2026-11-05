// The query cache's storage (lib/hooks.ts): a keyed map with a bounded LRU.
// Pure, so `pnpm test` can run it.
//
// It's bounded by weight, not by entries, because a document or a run can be
// many megabytes while a plan is a few KB. Two kinds of entry are never evicted:
// a fetch still in flight, so requests stay shared, and a key a mounted view
// holds with pin(), as that view would otherwise be left loading forever. So it
// can stay over its bound while those last, and it comes back down afterward.

export interface CacheEntry {
  done: boolean;
}

export interface QueryCacheOptions {
  /** The total weight kept once nothing pins it. */
  maxWeight: number;
  /** The weight of a key; 1 when absent. */
  weightOf?: (key: string) => number;
}

export class QueryCache<E extends CacheEntry> {
  // A Map iterates in insertion order, so the first key is the least recently used.
  private entries = new Map<string, E>();
  private pins = new Map<string, number>();
  private maxWeight: number;
  private weightOf: (key: string) => number;

  constructor(opts: QueryCacheOptions) {
    this.maxWeight = opts.maxWeight;
    this.weightOf = opts.weightOf ?? (() => 1);
  }

  /** Reads without changing the order, so it's safe during render. */
  get(key: string): E | undefined {
    return this.entries.get(key);
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  keys(): string[] {
    return Array.from(this.entries.keys());
  }

  get weight(): number {
    let w = 0;
    for (const k of this.entries.keys()) w += this.weightOf(k);
    return w;
  }

  /** Marks a key as the most recently used. */
  touch(key: string) {
    const e = this.entries.get(key);
    if (!e) return;
    this.entries.delete(key);
    this.entries.set(key, e);
  }

  set(key: string, entry: E) {
    this.entries.delete(key);
    this.entries.set(key, entry);
    this.evict();
  }

  delete(key: string) {
    this.entries.delete(key);
  }

  /** Holds a key against eviction until the returned function is called. */
  pin(key: string): () => void {
    this.pins.set(key, (this.pins.get(key) ?? 0) + 1);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      const n = (this.pins.get(key) ?? 1) - 1;
      if (n > 0) this.pins.set(key, n);
      else this.pins.delete(key);
    };
  }

  /**
   * Drops the least recently used settled, unpinned entries until the cache is
   * within its bound. Runs on writes and when a fetch settles, never on unpin:
   * a remount in the same tick (React's strict mode) must find its data.
   */
  evict() {
    let w = this.weight;
    if (w <= this.maxWeight) return;
    for (const [k, e] of this.entries) {
      if (w <= this.maxWeight) return;
      if (!e.done || this.pins.has(k)) continue;
      this.entries.delete(k);
      w -= this.weightOf(k);
    }
  }
}
