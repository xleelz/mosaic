// The command palette's index and search. Pure and flat, so a keystroke is a loop over strings
// already lowercased: about 8,000 entries take a few milliseconds.
//
// Only type imports here: node --test runs this file with type stripping.

import type { Document, EvidenceMechanism, MechanismFidelity } from "../../lib/api/types";
import type { DocIndex } from "../../lib/model/docindex";

export type PaletteKind = "page" | "component" | "interface" | "flow" | "scenario" | "mechanism" | "config" | "fixture";

export const KIND_LABEL: Record<PaletteKind, string> = {
  page: "Page",
  component: "Component",
  interface: "Interface",
  flow: "Flow",
  scenario: "Scenario",
  mechanism: "Mechanism",
  config: "Config",
  fixture: "World setup",
};

const KIND_ORDER: Record<PaletteKind, number> = { page: 0, component: 1, flow: 2, scenario: 3, mechanism: 4, interface: 5, config: 6, fixture: 7 };

export interface PaletteEntry {
  kind: PaletteKind;
  id: string;
  title: string;
  detail?: string;
  fidelity?: MechanismFidelity;
  /** Where it goes: a route under the model, and its query. */
  sub: string;
  params?: Record<string, string>;
  /** "Down" and "fails" also match this entry: a component that can fail, or a scenario with a fault. */
  canFail?: boolean;
  /** A scenario that injects a fault: ranked first for a failure query. */
  fault?: boolean;
  hay: string;
  titleLower: string;
  idLower: string;
}

function entry(e: Omit<PaletteEntry, "hay" | "titleLower" | "idLower">, ...more: (string | undefined)[]): PaletteEntry {
  const titleLower = e.title.toLowerCase();
  const idLower = e.id.toLowerCase();
  return { ...e, titleLower, idLower, hay: [titleLower, idLower, ...more.filter(Boolean).map((s) => s!.toLowerCase())].join(" ") };
}

const clip = (s: string | undefined, n: number) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Components, interfaces, flows, scenarios, configs and world setups. */
export function documentEntries(doc: Document, idx: DocIndex): PaletteEntry[] {
  const out: PaletteEntry[] = [];
  const compName = (id: string) => idx.componentsById.get(id)?.name || id;
  for (const c of doc.components ?? []) {
    const area = idx.area.get(c.id);
    const n = idx.interfacesByComponent.get(c.id)?.length ?? 0;
    const detail = [c.kind, area, n ? `${n} ${n === 1 ? "interface" : "interfaces"}` : ""].filter(Boolean).join(" · ");
    out.push(entry({ kind: "component", id: c.id, title: c.name || c.id, detail, sub: "map", params: { c: c.id }, canFail: true }, c.kind, area, clip(c.summary, 300), (c.tags ?? []).join(" ")));
  }
  for (const i of doc.interfaces ?? []) {
    const id = i.id || `${i.component}.${i.name}`;
    const comp = compName(i.component);
    out.push(entry({ kind: "interface", id, title: id, detail: clip(i.summary, 110) || comp, sub: "map", params: { c: i.component, i: id } }, comp, i.kind, clip(i.summary, 300)));
  }
  for (const f of doc.flows ?? []) {
    const n = idx.scenariosByFlow.get(f.id)?.length ?? 0;
    out.push(entry({ kind: "flow", id: f.id, title: f.name || f.id, detail: clip(f.description, 110) || `${n} ${n === 1 ? "scenario" : "scenarios"}`, sub: "flows", params: { flow: f.id } }, clip(f.description, 300), (f.tags ?? []).join(" "), f.entry?.interface));
  }
  for (const s of doc.scenarios ?? []) {
    const flow = s.flow || s.steps?.find((st) => st.flow)?.flow || "";
    const faults = s.faults ?? [];
    const faultWords = faults.map((x) => `${x.target} ${x.type} ${x.code ?? ""}`).join(" ");
    const params: Record<string, string> = { scenario: s.id };
    if (flow) params.flow = flow;
    const flowTitle = idx.flowsById.get(flow)?.name || flow;
    const detail = [faults.length ? `${faults.length} ${faults.length === 1 ? "fault" : "faults"}` : "", flowTitle].filter(Boolean).join(" · ");
    out.push(entry({ kind: "scenario", id: s.id, title: s.name || s.id, detail, sub: "simulate", params, canFail: faults.length > 0, fault: faults.length > 0 }, flow, flowTitle, clip(s.description, 300), faultWords));
  }
  for (const c of doc.configs ?? []) {
    out.push(entry({ kind: "config", id: c.id, title: c.id, detail: clip(c.summary, 110), sub: "world", params: { config: c.id } }, clip(c.summary, 300), (c.tags ?? []).join(" ")));
  }
  for (const f of doc.fixtures ?? []) {
    out.push(entry({ kind: "fixture", id: f.id, title: f.name || f.id, detail: clip(f.summary, 110), sub: "world", params: { fixture: f.id } }, clip(f.summary, 300), "fixture"));
  }
  return out;
}

export function mechanismEntries(items: readonly EvidenceMechanism[]): PaletteEntry[] {
  return items.map((m) =>
    entry({ kind: "mechanism", id: m.id, title: m.name || m.id, detail: clip(m.note, 110) || m.area, fidelity: m.fidelity, sub: "evidence", params: { q: m.id } }, m.area, m.kind, m.fidelity, clip(m.note, 300)),
  );
}

export function pageEntries(pages: readonly { sub: string; label: string; tab?: string }[]): PaletteEntry[] {
  return pages.map((p) => entry({ kind: "page", id: p.sub || "overview", title: p.label, detail: p.tab, sub: p.sub }, p.tab));
}

const FAILURE_WORDS = new Set(["down", "fail", "fails", "failing", "failure", "failures", "outage", "broken", "unavailable", "fault", "faults"]);

/** Exact, then prefix, then the whole phrase in the title, then every word in the title, then anywhere. */
function tier(e: PaletteEntry, q: string, words: string[]): number {
  if (e.titleLower === q || e.idLower === q) return 0;
  if (e.titleLower.startsWith(q) || e.idLower.startsWith(q)) return 1;
  if (e.titleLower.includes(q) || e.idLower.includes(q)) return 2;
  if (words.every((w) => e.titleLower.includes(w) || FAILURE_WORDS.has(w))) return 3;
  return 4;
}

/**
 * Entries holding every word of the query, best first. With no query, the pages. A failure word
 * ("local disk down") also matches what can fail, so long as another word matched literally.
 */
export function searchPalette(entries: readonly PaletteEntry[], query: string): PaletteEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return entries.filter((e) => e.kind === "page");
  const words = q.split(/\s+/);
  const failure = words.some((w) => FAILURE_WORDS.has(w));
  const hits: { e: PaletteEntry; rank: number }[] = [];
  for (const e of entries) {
    let ok = true;
    let literal = false;
    for (const w of words) {
      if (e.hay.includes(w)) literal = true;
      else if (!(e.canFail && FAILURE_WORDS.has(w))) {
        ok = false;
        break;
      }
    }
    if (!ok || !literal) continue;
    const base = tier(e, q, words);
    const rank = (failure && e.fault ? Math.max(0, base - 1) : base) * 10 + KIND_ORDER[e.kind];
    hits.push({ e, rank });
  }
  hits.sort((a, b) => a.rank - b.rank || a.e.title.length - b.e.title.length || (a.e.titleLower < b.e.titleLower ? -1 : 1));
  return hits.map((h) => h.e);
}

// ---- Windowing -------------------------------------------------------------

export interface RowWindow {
  /** First row to render. */
  start: number;
  /** One past the last row to render. */
  end: number;
}

/** Only the rows in view, with a little overscan. */
export function rowWindow(scrollTop: number, viewport: number, rowHeight: number, total: number, overscan = 4): RowWindow {
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight);
  const start = Math.max(0, first - overscan);
  const end = Math.min(total, first + Math.ceil(viewport / rowHeight) + overscan);
  return { start, end: Math.max(start, end) };
}

/** The scrollTop that shows a row, or the same value when it's already in view. */
export function scrollToRow(row: number, scrollTop: number, viewport: number, rowHeight: number): number {
  const top = row * rowHeight;
  if (top < scrollTop) return top;
  if (top + rowHeight > scrollTop + viewport) return top + rowHeight - viewport;
  return scrollTop;
}
