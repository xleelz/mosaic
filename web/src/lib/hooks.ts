"use client";

import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { getClient, type MosaicClient } from "@/lib/api";
import type { Document, Validation } from "@/lib/api/types";
import { docIndex, type DocIndex } from "@/lib/model/docindex";
import { QueryCache } from "@/lib/querycache";
import { readValidation, writeValidation } from "@/lib/validationcache";

// A small keyed query cache: reads are shared across tabs and remounts, and a
// reload drops the key. No external dependency needed for a read-mostly UI.
//
// It's a bounded LRU (lib/querycache.ts), so it doesn't grow with every run
// opened. What a mounted view uses, or a fetch in flight, is never evicted.

type Entry = { promise: Promise<unknown>; data?: unknown; error?: unknown; done: boolean };

/** A whole document, trace, graph or list of runs can be megabytes; everything else is small. */
const HEAVY = /^(doc|runs?|graph|source|diff|commit):/;
const cache = new QueryCache<Entry>({
  maxWeight: 512,
  // About 16 heavy entries, or fewer of them and some hundreds of plans.
  weightOf: (key) => (HEAVY.test(key) ? 32 : 1),
});
const listeners = new Set<() => void>();
let version = 0;

function notify() {
  version++;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

function start(key: string, fn: (c: MosaicClient) => Promise<unknown>): Entry {
  const entry: Entry = { promise: Promise.resolve(), done: false };
  entry.promise = fn(getClient()).then(
    (data) => {
      entry.data = data;
      entry.done = true;
      cache.evict();
      notify();
    },
    (error) => {
      entry.error = error;
      entry.done = true;
      cache.evict();
      notify();
    },
  );
  cache.set(key, entry);
  return entry;
}

export interface QueryState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Fetches `fn` once per `key` (null skips). */
export function useQuery<T>(key: string | null, fn: (c: MosaicClient) => Promise<T>): QueryState<T> {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useSyncExternalStore(subscribe, () => version, () => 0);

  useEffect(() => {
    if (!key) return;
    const unpin = cache.pin(key);
    if (cache.has(key)) cache.touch(key);
    else start(key, (c) => fnRef.current(c));
    return unpin;
  }, [key]);

  const reload = useCallback(() => {
    if (!key) return;
    cache.delete(key);
    start(key, (c) => fnRef.current(c));
    notify();
  }, [key]);

  const entry = key ? cache.get(key) : undefined;
  return {
    data: entry?.data as T | undefined,
    error: entry?.error,
    loading: !!key && (!entry || !entry.done),
    reload,
  };
}

/**
 * Like useQuery for a list of keyed fetches; each keeps its own state and
 * reload. A key dropped by invalidate() is fetched again on the next render.
 */
export function useQueries<T>(items: { key: string; fn: (c: MosaicClient) => Promise<T> }[]): QueryState<T>[] {
  useSyncExternalStore(subscribe, () => version, () => 0);
  const keys = items.map((it) => it.key).join("\n");
  useEffect(() => {
    const unpins = keys ? keys.split("\n").map((k) => cache.pin(k)) : [];
    return () => unpins.forEach((u) => u());
  }, [keys]);
  useEffect(() => {
    for (const it of items) if (!cache.has(it.key)) start(it.key, it.fn);
  });

  return items.map((it) => {
    const entry = cache.get(it.key);
    return {
      data: entry?.data as T | undefined,
      error: entry?.error,
      loading: !entry || !entry.done,
      reload: () => {
        cache.delete(it.key);
        start(it.key, it.fn);
        notify();
      },
    };
  });
}

/** Drops every cached key that starts with prefix. */
export function invalidate(prefix: string) {
  for (const k of cache.keys()) if (k.startsWith(prefix)) cache.delete(k);
  notify();
}

function localStore(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * The validate result of a revision. Validating the largest model takes
 * seconds and a revision is frozen, so it's kept across page loads per revision
 * hash (lib/validationcache.ts). Pass the resolved revision: "draft", which is
 * always fetched, or the number with its hash. Without a hash yet, it waits.
 */
export function useValidation(id: string, rev: string | null, hash: string | undefined): QueryState<Validation> {
  const draft = rev === "draft";
  return useQuery<Validation>(!rev ? null : draft ? `validate:${id}:draft` : hash ? `validate:${id}:${rev}:${hash}` : null, async (c) => {
    const store = !draft && hash ? localStore() : null;
    if (store && rev && hash) {
      const kept = readValidation<Validation>(store, id, rev, hash, Date.now());
      if (kept) return kept;
    }
    const result = await c.validate(id, rev ?? undefined);
    if (store && rev && hash) writeValidation(store, id, rev, hash, result, Date.now());
    return result;
  });
}

/**
 * Lookup maps over a document (components, interfaces and scenarios by id,
 * scenarios by flow, members by parent, top-level parent and area). Built
 * once per document object and shared by every component that asks.
 */
export function useDocIndex(doc: Document): DocIndex;
export function useDocIndex(doc: Document | undefined): DocIndex | undefined;
export function useDocIndex(doc: Document | undefined): DocIndex | undefined {
  return useMemo(() => (doc ? docIndex(doc) : undefined), [doc]);
}

/**
 * Runs at most `limit` tasks at once; the rest wait in order. Use it for
 * request fan-out (plans of many flows) so a page can't open hundreds of
 * requests at the same time.
 */
export function limiter(limit: number) {
  let active = 0;
  const queue: (() => void)[] = [];
  const next = () => {
    if (active >= limit) return;
    const go = queue.shift();
    if (go) {
      active++;
      go();
    }
  };
  return function run<T>(task: () => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      queue.push(() =>
        task()
          .then(resolve, reject)
          .finally(() => {
            active--;
            next();
          }),
      );
      next();
    });
  };
}

/** Plans are fetched through this, four at a time. */
export const planQueue = limiter(4);
