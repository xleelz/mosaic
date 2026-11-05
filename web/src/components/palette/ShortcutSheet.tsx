"use client";

import { useEffect, useState } from "react";
import { Button, Kbd } from "@/components/ui";
import { isTypingTarget } from "./keys";
import { Modal } from "./Modal";
import { SHORTCUTS, globalAction } from "./shortcuts";

/** The ? button for the top bar and the sheet of every key. Mount once. */
export function ShortcutSheet() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (globalAction(ev, isTypingTarget(ev.target)) === "sheet") {
        ev.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Keyboard shortcuts (?)"
        aria-label="Keyboard shortcuts"
        className="flex h-6 w-6 items-center justify-center rounded-md border border-line bg-panel-2 font-mono text-[11px] text-muted hover:bg-panel-3 hover:text-ink"
      >
        ?
      </button>
      {open && (
        <Modal
          label="Keyboard shortcuts"
          onClose={() => setOpen(false)}
          className="m-auto max-h-[80dvh] w-[min(620px,calc(100vw-32px))] overflow-y-auto rounded-lg border border-line bg-panel p-4 text-ink shadow-[0_16px_48px_rgba(0,0,0,0.6)] backdrop:bg-black/60"
        >
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">Keyboard shortcuts</h2>
            <Button size="sm" variant="ghost" autoFocus onClick={() => setOpen(false)}>
              Close
            </Button>
          </div>
          <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            {SHORTCUTS.map((g) => (
              <section key={g.title}>
                <h3 className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-faint">{g.title}</h3>
                <dl className="space-y-1">
                  {g.rows.map((r) => (
                    <div key={r.does} className="flex items-baseline justify-between gap-3 text-[12.5px]">
                      <dt className="text-muted">{r.does}</dt>
                      <dd className="flex shrink-0 gap-1">
                        {r.keys.map((k) => (
                          <Kbd key={k}>{k}</Kbd>
                        ))}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
}
