// Self-update helpers for the top bar's version chip (docs/DESIGN.md §6:
// GET /v1/system/version, POST /v1/system/update). Pure, so they can be tested.

import type { SystemVersion } from "./api/types";

export function shortSha(sha: string): string {
  return sha.slice(0, 7);
}

/** The chip's text: the short commit, and "N new commits" when behind. */
export function chipLabel(v: SystemVersion): { commit: string; behind: string | null } {
  const commit = v.commit ? shortSha(v.commit) : v.version || "unknown";
  const n = v.update.behind;
  return { commit, behind: n > 0 ? `${n} new commit${n === 1 ? "" : "s"}` : null };
}

/** How long ago `iso` was, coarsely ("just now", "4 min ago", "2 h ago"). */
export function ago(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export interface WaitOptions {
  /** Asks the daemon for its version; throws while it is down. */
  fetchVersion: () => Promise<SystemVersion>;
  /** The commit the restarted daemon must report. */
  target: string;
  timeoutMs?: number;
  intervalMs?: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
  /** Stops waiting (resolves "aborted") when it returns true. */
  aborted?: () => boolean;
}

export const RESTART_TIMEOUT_MS = 3 * 60 * 1000;

/**
 * Polls until the daemon answers with `target` as its commit: "ready", or
 * "timeout" after timeoutMs (default 3 minutes). Errors (the daemon or the UI
 * server restarting) are retried.
 */
export async function waitForCommit(o: WaitOptions): Promise<"ready" | "timeout" | "aborted"> {
  const now = o.now ?? Date.now;
  const sleep = o.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const deadline = now() + (o.timeoutMs ?? RESTART_TIMEOUT_MS);
  const interval = o.intervalMs ?? 2000;
  for (;;) {
    if (o.aborted?.()) return "aborted";
    try {
      const v = await o.fetchVersion();
      if (v.commit && v.commit === o.target) return "ready";
    } catch {
      // still restarting
    }
    if (now() >= deadline) return "timeout";
    await sleep(interval);
  }
}
