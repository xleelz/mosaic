// What in a model cites a file. The code viewer uses it to answer "what else
// cites this file?" and "how much of it is cited?", and the World tab uses it
// to place a config in the area of the components citing the same file.
//
// Only type imports here: node --test runs this file with type stripping.

import type { Document, JsonValue, Source } from "../api/types";

export interface Citation {
  kind: "component" | "interface" | "link" | "flow" | "config";
  /** The citing entity. */
  id: string;
  /** What the citation says, in the words of the model. */
  claim: string;
  /** The component the entity sits on; the viewer links to it. */
  component?: string;
  source: Source;
}

function isSource(v: unknown): v is Source {
  return !!v && typeof v === "object" && typeof (v as Source).path === "string";
}

/** Every `source` of a behavior's steps, however they nest, with the step's title. */
function stepSources(v: JsonValue | undefined, emit: (s: Source, title?: string) => void) {
  if (Array.isArray(v)) {
    for (const x of v) stepSources(x, emit);
    return;
  }
  if (!v || typeof v !== "object") return;
  const step = v as Record<string, JsonValue>;
  if (isSource(step.source)) emit(step.source, typeof step.title === "string" ? step.title : undefined);
  for (const k of Object.keys(step)) {
    const x = step[k];
    // A `set` holds state values, which aren't citations even when they look like one.
    if (k !== "source" && k !== "set" && x && typeof x === "object") stepSources(x, emit);
  }
}

/** Citations by file path. Repo is matched in citationsOf, as a source may leave it out. */
export function buildCitationIndex(doc: Document): Map<string, Citation[]> {
  const out = new Map<string, Citation[]>();
  const add = (c: Citation) => {
    const l = out.get(c.source.path);
    if (l) l.push(c);
    else out.set(c.source.path, [c]);
  };
  for (const c of doc.components ?? []) {
    const claim = c.summary || c.name || c.id;
    for (const source of c.sources ?? []) add({ kind: "component", id: c.id, claim, component: c.id, source });
  }
  for (const i of doc.interfaces ?? []) {
    const id = i.id || `${i.component}.${i.name}`;
    const claim = i.summary || id;
    for (const source of i.sources ?? []) add({ kind: "interface", id, claim, component: i.component, source });
    stepSources(i.behavior as unknown as JsonValue, (source, title) => add({ kind: "interface", id, claim: title || claim, component: i.component, source }));
  }
  for (const l of doc.links ?? []) {
    const id = l.id || `${l.from}-${l.to}`;
    for (const source of l.sources ?? []) add({ kind: "link", id, claim: l.summary || l.label || id, component: l.from, source });
  }
  for (const f of doc.flows ?? []) {
    const claim = f.name || f.id;
    for (const source of f.sources ?? []) add({ kind: "flow", id: f.id, claim, source });
    for (const s of f.steps ?? []) if (s.source) add({ kind: "flow", id: f.id, claim: s.title || claim, component: s.component, source: s.source });
  }
  for (const c of doc.configs ?? []) {
    for (const source of c.sources ?? []) add({ kind: "config", id: c.id, claim: c.summary || c.id, source });
  }
  return out;
}

const cache = new WeakMap<Document, Map<string, Citation[]>>();

/** The index of a document, built on first use. */
export function citationIndex(doc: Document): Map<string, Citation[]> {
  let idx = cache.get(doc);
  if (!idx) {
    idx = buildCitationIndex(doc);
    cache.set(doc, idx);
  }
  return idx;
}

/** Citations of one file, by line; a citation of the whole file comes first. */
export function citationsOf(doc: Document, path: string, repo?: string): Citation[] {
  const list = citationIndex(doc).get(path) ?? [];
  return list
    .filter((c) => !repo || !c.source.repo || c.source.repo === repo)
    .slice()
    .sort((a, b) => (a.source.line ?? 0) - (b.source.line ?? 0) || (a.source.end_line ?? 0) - (b.source.end_line ?? 0) || a.id.localeCompare(b.id));
}

export interface FileCoverage {
  citations: number;
  /** Distinct entities citing the file. */
  entities: number;
  /** Lines inside at least one cited range. */
  citedLines: number;
  totalLines: number;
  /** Citations with no line, which say nothing about how much is cited. */
  wholeFile: number;
}

/** How much of a file falls in a cited range. Cited isn't the same as modeled correctly. */
export function fileCoverage(citations: Citation[], totalLines: number): FileCoverage {
  const ranges: [number, number][] = [];
  let wholeFile = 0;
  for (const c of citations) {
    const { line, end_line } = c.source;
    if (!line) {
      wholeFile++;
      continue;
    }
    const first = Math.max(1, Math.min(line, totalLines));
    ranges.push([first, Math.max(first, Math.min(end_line ?? first, totalLines))]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  let citedLines = 0;
  let upTo = 0;
  for (const [a, b] of ranges) {
    if (b <= upTo) continue;
    citedLines += b - Math.max(a, upTo + 1) + 1;
    upTo = b;
  }
  return { citations: citations.length, entities: new Set(citations.map((c) => `${c.kind}:${c.id}`)).size, citedLines, totalLines, wholeFile };
}

/** The number of lines a viewer shows for a file's text: a final newline doesn't start a line. */
export function lineCount(content: string): number {
  if (!content) return 0;
  const n = content.split("\n").length;
  return content.endsWith("\n") ? n - 1 : n;
}
