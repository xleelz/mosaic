// How far to trust a model: the data every trust display reads (docs/ux-plan-2026-11.md).

"use client";

import { ApiError } from "@/lib/api/client";
import type { Evidence, EvidenceMechanism, MechanismFidelity, RevSelector } from "@/lib/api/types";
import { countFidelity, type FidelityCounts } from "@/components/trust/fidelity";
import { useQuery } from "@/lib/hooks";

export { countFidelity, type FidelityCounts };

export interface EvidenceState {
  /** null: answered, and none is stored ("Not benchmarked"). undefined: not known yet. */
  evidence: Evidence | null | undefined;
  loading: boolean;
  error: unknown;
}

/** Evidence for a revision. A 404 is an answer, not an error. */
export function useEvidence(id: string, rev?: RevSelector): EvidenceState {
  const q = useQuery<Evidence | null>(`evidence:${id}:${rev ?? "latest"}`, async (c) => {
    try {
      return await c.getEvidence(id, rev);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
  return { evidence: q.data, loading: q.loading, error: q.error };
}

/** interface id -> the mechanisms that list it. */
export function mechanismsByInterface(items: EvidenceMechanism[]): Map<string, EvidenceMechanism[]> {
  const out = new Map<string, EvidenceMechanism[]>();
  for (const m of items) {
    for (const i of m.interfaces) {
      const list = out.get(i);
      if (list) list.push(m);
      else out.set(i, [m]);
    }
  }
  return out;
}

/** The mechanisms a run passed through that aren't fully modeled, worst first. */
export function weakMechanismsOnRun(items: EvidenceMechanism[], calledInterfaces: Iterable<string>): EvidenceMechanism[] {
  const called = new Set(calledInterfaces);
  const rank: Record<MechanismFidelity, number> = { shell: 0, absent: 1, partial: 2, modeled: 3 };
  return items
    .filter((m) => m.fidelity !== "modeled" && m.interfaces.some((i) => called.has(i)))
    .sort((a, b) => rank[a.fidelity] - rank[b.fidelity]);
}
