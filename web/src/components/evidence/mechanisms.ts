// Pure logic for the Evidence tab: filters, per-area counts and what the numbers say.
// Kept free of React and "@/" imports so `pnpm test` can run it.

import type { EvidenceBlind, EvidenceMechanism, MechanismFidelity, MechanismGateStatus, Source } from "../../lib/api/types";
import type { FidelityCounts } from "../trust/fidelity";

export const GATE_MEANING: Record<MechanismGateStatus, string> = {
  ok: "With its interfaces disabled, a boundary expectation failed: the mechanism has an effect in the model. That doesn't show the effect matches the code.",
  weak: "Disabling it is noticed, but only by an abort, or not for each of its interfaces: part of it has no effect anything checks.",
  shell: "With its interfaces disabled, every boundary expectation still held: nothing depends on it.",
  uncovered: "Its interfaces exist, but no scenario's trace reaches one.",
  missing: "None of its listed interfaces exists in the model.",
  skipped: "Left out of the gate, with a stated reason.",
};

/** The statuses in the order the Evidence tab explains them. */
export const GATE_STATUSES: readonly MechanismGateStatus[] = ["ok", "weak", "shell", "uncovered", "missing", "skipped"];

/**
 * Whether the enumerator's reading and the gate's measure tell different stories, by the rule of
 * `check --mechanisms` (fidelityAgrees, DESIGN §13.1 item 38): modeled should measure ok, partial
 * ok or weak, shell shell or uncovered, and absent missing. Skipped and unmeasured mechanisms have
 * nothing to disagree with.
 */
export function gateDisagrees(fidelity: MechanismFidelity, gate: MechanismGateStatus | undefined): boolean {
  if (!gate || gate === "skipped") return false;
  switch (fidelity) {
    case "modeled":
      return gate !== "ok";
    case "partial":
      return gate !== "ok" && gate !== "weak";
    case "shell":
      return gate !== "shell" && gate !== "uncovered";
    case "absent":
      return gate !== "missing";
  }
}

export function disagreementText(fidelity: MechanismFidelity, gate: MechanismGateStatus): string {
  return `The enumerator read this as ${fidelity}, and the gate measured ${gate}. They disagree, so read the code before trusting either.`;
}

/** "path", "path:line" or "path:line-end", the shape of model.Source.String(), into a Source. */
export function parseCitation(citation: string): Source {
  const m = /^(.+?):(\d+)(?:-(\d+))?$/.exec(citation.trim());
  if (!m) return { path: citation.trim() };
  const src: Source = { path: m[1], line: Number(m[2]) };
  if (m[3]) src.end_line = Number(m[3]);
  return src;
}

export interface MechanismFilter {
  /** Empty: every fidelity. */
  fidelities: ReadonlySet<MechanismFidelity>;
  /** "": every kind. */
  kind: string;
  /** "": every area. */
  area: string;
  query: string;
  disagreeOnly: boolean;
}

function matchesWords(m: EvidenceMechanism, words: string[]): boolean {
  if (words.length === 0) return true;
  const hay = [m.id, m.name, m.area, m.kind, m.note, m.trigger, m.observable, m.fidelity, m.gate_status, ...m.citations, ...m.interfaces]
    .filter(Boolean)
    .join("\n")
    .toLowerCase();
  return words.every((w) => hay.includes(w));
}

export function searchWords(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/** The matching mechanisms, in the list's own order: most missed by an operator first. */
export function filterMechanisms(items: EvidenceMechanism[], f: MechanismFilter): EvidenceMechanism[] {
  const words = searchWords(f.query);
  return items.filter(
    (m) =>
      (f.fidelities.size === 0 || f.fidelities.has(m.fidelity)) &&
      (!f.kind || m.kind === f.kind) &&
      (!f.area || m.area === f.area) &&
      (!f.disagreeOnly || gateDisagrees(m.fidelity, m.gate_status)) &&
      matchesWords(m, words),
  );
}

export interface AreaSummary {
  area: string;
  counts: FidelityCounts;
  disagreements: number;
}

/** One summary per area, in the order the list first names them. */
export function summarizeAreas(items: EvidenceMechanism[]): AreaSummary[] {
  const byArea = new Map<string, AreaSummary>();
  for (const m of items) {
    let s = byArea.get(m.area);
    if (!s) {
      s = { area: m.area, counts: { modeled: 0, partial: 0, shell: 0, absent: 0, total: 0 }, disagreements: 0 };
      byArea.set(m.area, s);
    }
    s.counts[m.fidelity]++;
    s.counts.total++;
    if (gateDisagrees(m.fidelity, m.gate_status)) s.disagreements++;
  }
  return [...byArea.values()];
}

export function kindsOf(items: EvidenceMechanism[]): string[] {
  return [...new Set(items.map((m) => m.kind).filter(Boolean))].sort();
}

export interface GateSummary {
  /** Mechanisms the gate measured, skipped ones left out. */
  measured: number;
  ok: number;
  weak: number;
  skipped: number;
  /** No gate status at all. */
  unmeasured: number;
  disagreements: number;
}

export function summarizeGate(items: EvidenceMechanism[]): GateSummary {
  const s: GateSummary = { measured: 0, ok: 0, weak: 0, skipped: 0, unmeasured: 0, disagreements: 0 };
  for (const m of items) {
    if (!m.gate_status) s.unmeasured++;
    else if (m.gate_status === "skipped") s.skipped++;
    else {
      s.measured++;
      if (m.gate_status === "ok") s.ok++;
      if (m.gate_status === "weak") s.weak++;
    }
    if (gateDisagrees(m.fidelity, m.gate_status)) s.disagreements++;
  }
  return s;
}

/** A whole percent; small shares never round to a misleading 0% or 100%. */
export function percent(part: number, total: number): string {
  if (total <= 0) return "n/a";
  const p = (part / total) * 100;
  if (part > 0 && p < 1) return "<1%";
  if (part < total && p > 99) return ">99%";
  return `${Math.round(p)}%`;
}

/** "measured on r3", plus "not re-measured" when the viewed revision isn't that one. */
export function measuredNote(measuredOn: number, viewedRev: string): string {
  const label = `measured on r${measuredOn}`;
  return viewedRev === String(measuredOn) ? label : `${label}, not re-measured`;
}

/** "Blind benchmark: 30% of steps", or null when the blind measure holds no steps. */
export function blindFigure(blind: EvidenceBlind | undefined): string | null {
  if (!blind || blind.steps_total <= 0) return null;
  return `Blind benchmark: ${percent(blind.steps_passed, blind.steps_total)} of steps`;
}
