"use client";

import { useState } from "react";
import type { EvidenceMechanism } from "@/lib/api/types";
import { mechanismSentence } from "@/lib/sim/wording";
import { FidelityMark } from "@/components/trust/marks";
import { cx } from "@/components/ui";

/**
 * "This run passed through 3 partial and 1 shell mechanism", with the list on demand: a run
 * through a shell shouldn't look like a run through a model. Renders nothing when there are none.
 */
export function MechanismWarning({ mechanisms, className }: { mechanisms: readonly EvidenceMechanism[]; className?: string }) {
  const [open, setOpen] = useState(false);
  if (mechanisms.length === 0) return null;
  return (
    <div className={cx("relative text-[11.5px]", className)}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex max-w-full items-center gap-1.5 rounded px-1 py-0.5 text-warn hover:bg-panel-2">
        <FidelityMark fidelity={mechanisms[0].fidelity} label={false} />
        <span className="truncate">{mechanismSentence(mechanisms)}</span>
        <span aria-hidden className="text-faint">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <ul className="run-float absolute left-0 top-full z-30 mt-1 max-h-[280px] w-[min(640px,90vw)] space-y-1 overflow-y-auto rounded-md border border-line p-2">
          {mechanisms.map((m) => (
            <li key={m.id} className="flex items-baseline gap-2">
              <FidelityMark fidelity={m.fidelity} className="w-[58px]" />
              <span className="min-w-0">
                <span className="text-ink">{m.name}</span>
                {m.note && <span className="text-faint">: {m.note}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
