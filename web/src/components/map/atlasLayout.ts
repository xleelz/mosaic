// Layout of an Atlas view with ELK. It reads only the boxes and the strong connections, never the
// lens, filter or hover, so the same view lands in the same place on every visit. No force layouts.

import ELK, { type ElkNode } from "elkjs/lib/elk.bundled.js";
import type { AtlasBox, AtlasView } from "../../lib/model/atlas";

export interface BoxRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A box's size. Trust marks reserve their room only when evidence is stored. */
export function boxSize(box: AtlasBox, hasEvidence: boolean): { width: number; height: number } {
  const strip = hasEvidence ? 14 : 0;
  switch (box.type) {
    case "area":
      return { width: 276, height: 100 + (hasEvidence ? 42 : 0) };
    case "group":
      return { width: 216, height: 88 };
    case "more":
      return { width: 176, height: 50 };
    case "stub":
      return { width: 176, height: 34 };
    case "actor":
      return { width: 176, height: 46 };
    case "self":
      return { width: 196, height: 54 + strip };
    default:
      return box.enter ? { width: 216, height: 88 + strip } : { width: 196, height: 54 + strip };
  }
}

const elk = new ELK();

/** Boxes in connected ELK layers, the ones with no drawn connection in a grid below them. */
export async function layoutAtlas(view: AtlasView, hasEvidence: boolean): Promise<Map<string, BoxRect>> {
  const strong = view.edges.filter((e) => e.strong);
  const connected = new Set<string>();
  for (const e of strong) {
    connected.add(e.from);
    connected.add(e.to);
  }
  const layered = view.boxes.filter((b) => connected.has(b.id) || b.edge);
  const loose = view.boxes.filter((b) => !connected.has(b.id) && !b.edge);

  const root: ElkNode = {
    id: "__atlas__",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "26",
      "elk.layered.spacing.nodeNodeBetweenLayers": "84",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      "elk.separateConnectedComponents": "false",
      "elk.padding": "[top=20,left=20,bottom=20,right=20]",
    },
    children: layered.map((b) => ({
      id: b.id,
      ...boxSize(b, hasEvidence),
      layoutOptions: b.edge ? { "elk.layered.layering.layerConstraint": b.edge === "start" ? "FIRST_SEPARATE" : "LAST_SEPARATE" } : undefined,
    })),
    edges: strong.map((e) => ({ id: e.id, sources: [e.from], targets: [e.to] })),
  };
  const res = await elk.layout(root);
  const out = new Map<string, BoxRect>();
  let bottom = 0;
  let left = Infinity;
  let right = 0;
  for (const c of res.children ?? []) {
    const rect = { x: c.x ?? 0, y: c.y ?? 0, width: c.width ?? 0, height: c.height ?? 0 };
    out.set(c.id, rect);
    bottom = Math.max(bottom, rect.y + rect.height);
    left = Math.min(left, rect.x);
    right = Math.max(right, rect.x + rect.width);
  }

  // The rest in rows, no wider than what's above them unless they're all there is.
  const gap = 18;
  const startX = Number.isFinite(left) ? left : 20;
  const span = Math.max(right - startX, 980);
  let x = startX;
  let y = out.size ? bottom + 40 : 20;
  let rowH = 0;
  for (const b of loose) {
    const s = boxSize(b, hasEvidence);
    if (x > startX && x + s.width > startX + span) {
      x = startX;
      y += rowH + gap;
      rowH = 0;
    }
    out.set(b.id, { x, y, ...s });
    x += s.width + gap;
    rowH = Math.max(rowH, s.height);
  }
  return out;
}
