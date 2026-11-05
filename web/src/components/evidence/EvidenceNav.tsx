"use client";

// Evidence gathers everything that says how far to trust a model.

import Link from "next/link";
import { cx } from "@/components/ui";
import { useWorkspace } from "@/components/workspace/Workspace";

export type EvidenceSection = "mechanisms" | "tests" | "race-search";

const SECTIONS: { id: EvidenceSection; sub: string; label: string }[] = [
  { id: "mechanisms", sub: "evidence", label: "Passport & mechanisms" },
  { id: "tests", sub: "evidence/tests", label: "Self-checks" },
  { id: "race-search", sub: "evidence/race-search", label: "Race search" },
];

export function EvidenceNav({ active }: { active: EvidenceSection }) {
  const ws = useWorkspace();
  return (
    <nav aria-label="Evidence" className="flex flex-wrap gap-1">
      {SECTIONS.map((s) => (
        <Link
          key={s.id}
          href={ws.href(s.sub)}
          aria-current={s.id === active ? "page" : undefined}
          className={cx(
            "rounded-md border px-2.5 py-1 text-[12.5px] font-medium",
            s.id === active ? "border-line bg-panel-2 text-ink" : "border-transparent text-faint hover:text-ink",
          )}
        >
          {s.label}
        </Link>
      ))}
    </nav>
  );
}
