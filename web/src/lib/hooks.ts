"use client";

import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { getClient, type MosaicClient } from "@/lib/api";
import type { Document } from "@/lib/api/types";
import { docIndex, type DocIndex } from "@/lib/model/docindex";

// A small keyed query cache: reads are shared across tabs and remounts, and a
// reload drops the key. No external dependency needed for a read-mostly UI.

type Entry = { promise: Promise<unknown>; data?: unknown; error?: unknown; done: boolean };
const cache = new Map<string, Entry>();
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
      notify();
    },
    (error) => {
      entry.error = error;
      entry.done = true;
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
    if (key && !cache.has(key)) start(key, (c) => fnRef.current(c));
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

/** Drops every cached key that starts with prefix. */
export function invalidate(prefix: string) {
  for (const k of Array.from(cache.keys())) if (k.startsWith(prefix)) cache.delete(k);
  notify();
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
