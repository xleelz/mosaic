"use client";

// The top bar's version chip: the running commit, "N new commits" when the
// checkout is behind its upstream, and a popover to check now or update and
// restart (GET /v1/system/version, POST /v1/system/update, docs/DESIGN.md §6).

import { useEffect, useRef, useState } from "react";
import { errorMessage, getClient } from "@/lib/api";
import type { SystemVersion } from "@/lib/api/types";
import { useQuery } from "@/lib/hooks";
import { ago, chipLabel, shortSha, waitForCommit } from "@/lib/update";
import { Button, KV, badgeClass } from "./ui";

const KEY = "system-version";
/** The daemon fetches at most every 10 minutes; re-read it as often. */
const REREAD_MS = 10 * 60 * 1000;

type Phase =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "updating" }
  | { kind: "restarting"; to: string }
  | { kind: "done"; message: string }
  | { kind: "failed"; message: string };

export function UpdateChip() {
  const q = useQuery<SystemVersion>(KEY, (c) => c.systemVersion());
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [fresh, setFresh] = useState<SystemVersion | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const reload = q.reload;

  useEffect(() => {
    const id = setInterval(reload, REREAD_MS);
    return () => clearInterval(id);
  }, [reload]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const v = fresh ?? q.data;
  const busy = phase.kind === "checking" || phase.kind === "updating" || phase.kind === "restarting";
  // The health badge already reports an unreachable daemon.
  if (!v && phase.kind !== "restarting") return null;

  async function checkNow() {
    setPhase({ kind: "checking" });
    try {
      setFresh(await getClient().systemVersion(true));
      setPhase({ kind: "idle" });
    } catch (err) {
      setPhase({ kind: "failed", message: errorMessage(err) });
    }
  }

  async function update() {
    setPhase({ kind: "updating" });
    try {
      const res = await getClient().systemUpdate();
      if (!res.restarting) {
        setPhase({ kind: "done", message: res.note ?? "Updated; restart mosaicd and the web UI to run it." });
        setFresh(await getClient().systemVersion());
        return;
      }
      setPhase({ kind: "restarting", to: res.updated_to });
      const result = await waitForCommit({ target: res.updated_to, fetchVersion: () => getClient().systemVersion() });
      if (result === "ready") {
        window.location.reload();
        return;
      }
      setPhase({
        kind: "failed",
        message: `mosaicd didn't come back at ${shortSha(res.updated_to)} within 3 minutes. Check scripts/serve.sh's output, then reload the page.`,
      });
    } catch (err) {
      setPhase({ kind: "failed", message: errorMessage(err) });
    }
  }

  const label = v ? chipLabel(v) : null;
  const behind = phase.kind === "restarting" ? "updating…" : label?.behind;
  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title={v?.update.available ? "An update is available" : "mosaic version"}
        className={badgeClass(behind ? "info" : "neutral", "cursor-pointer font-mono hover:text-ink")}
      >
        {label?.commit ?? "…"}
        {behind && <span className="font-sans">· {behind}</span>}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="mosaic version"
          className="absolute right-0 top-7 z-50 w-80 rounded-md border border-line bg-panel p-3 text-[12px] shadow-[0_8px_24px_rgba(0,0,0,0.45)]"
        >
          {v && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <KV k="running">
                <span className="font-mono">{v.commit ? shortSha(v.commit) : "unknown"}</span>
                {v.dirty && <span className="text-faint"> (built with local changes)</span>}
              </KV>
              {v.branch && (
                <KV k="branch">
                  <span className="font-mono">{v.branch}</span>
                  {v.upstream && <span className="text-faint"> → {v.upstream}</span>}
                </KV>
              )}
              {v.update.latest_commit && (
                <KV k="upstream">
                  <span className="font-mono">{shortSha(v.update.latest_commit)}</span> {v.update.latest_subject}
                </KV>
              )}
              {v.source_dir && (
                <KV k="status">
                  {v.update.behind} behind, {v.update.ahead} ahead
                </KV>
              )}
              <KV k="checked">{ago(v.update.checked_at)}</KV>
            </dl>
          )}
          {v && !v.update.available && v.update.reason && phase.kind !== "restarting" && (
            <p className="mt-2 text-muted">{v.update.reason}</p>
          )}
          {phase.kind === "restarting" && <p className="mt-2 text-link">Updating…, restarting. The page reloads when mosaicd is back.</p>}
          {phase.kind === "done" && <p className="mt-2 text-ok">{phase.message}</p>}
          {phase.kind === "failed" && <p className="mt-2 text-bad">{phase.message}</p>}
          <div className="mt-3 flex items-center justify-end gap-2">
            <Button size="sm" variant="ghost" disabled={busy} onClick={checkNow}>
              {phase.kind === "checking" ? "Checking…" : "Check now"}
            </Button>
            <Button size="sm" variant="primary" disabled={busy || !v?.update.available} onClick={update}>
              {phase.kind === "updating" || phase.kind === "restarting" ? "Updating…" : "Update and restart"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
