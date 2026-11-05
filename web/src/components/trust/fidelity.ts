// The vocabulary for fidelity (docs/ux-plan-2026-11.md), as data: one word and one meaning each.
//
// Only type imports here: node --test runs this file with type stripping.

import type { EvidenceMechanism, MechanismFidelity } from "../../lib/api/types";

/** Best to worst, the order every strip and legend uses. */
export const FIDELITY_ORDER: readonly MechanismFidelity[] = ["modeled", "partial", "shell", "absent"];

export const FIDELITY_MEANING: Record<MechanismFidelity, string> = {
  modeled: "Modeled: the model does what the code does here",
  partial: "Partial: the main path only",
  shell: "Shell: the model claims this, but doesn't do it",
  absent: "Absent: known to exist in the code, not in this model",
};

export type FidelityCounts = Record<MechanismFidelity, number> & { total: number };

export function emptyCounts(): FidelityCounts {
  return { modeled: 0, partial: 0, shell: 0, absent: 0, total: 0 };
}

export function countFidelity(items: readonly Pick<EvidenceMechanism, "fidelity">[]): FidelityCounts {
  const c = emptyCounts();
  for (const m of items) {
    c[m.fidelity]++;
    c.total++;
  }
  return c;
}

/** "108 modeled, 177 partial, 36 shell, 131 absent", leaving out any at zero. "No mechanisms" when empty. */
export function fidelitySentence(c: FidelityCounts): string {
  const parts = FIDELITY_ORDER.filter((f) => c[f] > 0).map((f) => `${c[f]} ${f}`);
  return parts.length ? parts.join(", ") : "No mechanisms";
}
