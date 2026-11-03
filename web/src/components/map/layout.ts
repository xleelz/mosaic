// Compound layout of the architecture map with ELK.
//
// Components nest by `parent`. Each container is laid out on its own
// (SEPARATE_CHILDREN): containers whose members talk to each other use the
// layered algorithm; containers whose members don't are packed into a grid
// (rectpacking). Edges are lifted to the lowest common ancestor, so a call
// from a nested module to an outside datastore shapes the layering between
// their top-level containers. Calls from a container to its own members don't
// shape the layout at all; they are drawn as short stubs.

import ELK, { type ElkNode, type ElkExtendedEdge } from "elkjs/lib/elk.bundled.js";
import type { Graph, GraphNode } from "@/lib/api/types";

export const LEAF_W = 184;
export const LEAF_H = 54;
export const HEADER_H = 34;

export interface LaidOutNode {
  id: string;
  node: GraphNode;
  /** Position relative to the parent container (or the root). */
  x: number;
  y: number;
  width: number;
  height: number;
  /** Absolute position on the canvas. */
  absX: number;
  absY: number;
  parent?: string;
  container: boolean;
  depth: number;
}

export interface MapLayout {
  nodes: LaidOutNode[];
  /** Parent chain lookup: id -> parent id. */
  parentOf: Map<string, string | undefined>;
}

const elk = new ELK();

export function ancestors(id: string, parentOf: Map<string, string | undefined>): string[] {
  const out: string[] = [];
  let cur = parentOf.get(id);
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    out.push(cur);
    seen.add(cur);
    cur = parentOf.get(cur);
  }
  return out;
}

/** True when a is an ancestor of b. */
export function isAncestor(a: string, b: string, parentOf: Map<string, string | undefined>): boolean {
  return ancestors(b, parentOf).includes(a);
}

export async function layoutGraph(graph: Graph): Promise<MapLayout> {
  const ids = new Set(graph.nodes.map((n) => n.id));
  const parentOf = new Map<string, string | undefined>();
  for (const n of graph.nodes) parentOf.set(n.id, n.parent && ids.has(n.parent) && n.parent !== n.id ? n.parent : undefined);
  // Break parent cycles defensively.
  for (const n of graph.nodes) {
    const seen = new Set([n.id]);
    let cur = parentOf.get(n.id);
    while (cur) {
      if (seen.has(cur)) {
        parentOf.set(n.id, undefined);
        break;
      }
      seen.add(cur);
      cur = parentOf.get(cur);
    }
  }
  const children = new Map<string | undefined, GraphNode[]>();
  for (const n of graph.nodes) {
    const p = parentOf.get(n.id);
    if (!children.has(p)) children.set(p, []);
    children.get(p)!.push(n);
  }

  // Lift edges to the lowest common ancestor.
  const lifted = new Map<string | undefined, Map<string, ElkExtendedEdge>>();
  for (const e of graph.edges) {
    if (!ids.has(e.from) || !ids.has(e.to) || e.from === e.to) continue;
    if (isAncestor(e.from, e.to, parentOf) || isAncestor(e.to, e.from, parentOf)) continue;
    const fromChain = [e.from, ...ancestors(e.from, parentOf)];
    const toChain = [e.to, ...ancestors(e.to, parentOf)];
    let lca: string | undefined = undefined;
    for (const a of fromChain.slice(1)) {
      if (toChain.includes(a)) {
        lca = a;
        break;
      }
    }
    const liftTo = (chain: string[]) => {
      // The chain element whose parent is the LCA.
      for (const c of chain) if (parentOf.get(c) === lca) return c;
      return chain[chain.length - 1];
    };
    const s = liftTo(fromChain);
    const t = liftTo(toChain);
    if (s === t) continue;
    if (!lifted.has(lca)) lifted.set(lca, new Map());
    const key = `${s}->${t}`;
    if (!lifted.get(lca)!.has(key)) lifted.get(lca)!.set(key, { id: `${lca ?? "root"}:${key}`, sources: [s], targets: [t] });
  }

  const build = (n: GraphNode): ElkNode => {
    const kids = children.get(n.id) ?? [];
    if (kids.length === 0) return { id: n.id, width: LEAF_W, height: LEAF_H };
    const edges = Array.from(lifted.get(n.id)?.values() ?? []);
    const packed = edges.length === 0;
    return {
      id: n.id,
      layoutOptions: packed
        ? {
            "elk.algorithm": "rectpacking",
            "elk.aspectRatio": kids.length > 6 ? "1.9" : "2.4",
            "elk.spacing.nodeNode": "12",
            "elk.padding": `[top=${HEADER_H + 6},left=14,bottom=14,right=14]`,
            "elk.rectpacking.trybox": "false",
          }
        : {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.spacing.nodeNode": "14",
            "elk.layered.spacing.nodeNodeBetweenLayers": "40",
            "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
            "elk.padding": `[top=${HEADER_H + 6},left=14,bottom=14,right=14]`,
          },
      children: kids.map(build),
      edges,
    };
  };

  const root: ElkNode = {
    id: "__root__",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.hierarchyHandling": "SEPARATE_CHILDREN",
      "elk.spacing.nodeNode": "28",
      "elk.layered.spacing.nodeNodeBetweenLayers": "72",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      "elk.padding": "[top=20,left=20,bottom=20,right=20]",
    },
    children: (children.get(undefined) ?? []).map(build),
    edges: Array.from(lifted.get(undefined)?.values() ?? []),
  };

  const res = await elk.layout(root);
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const out: LaidOutNode[] = [];
  const walk = (en: ElkNode, parent: string | undefined, depth: number, ox: number, oy: number) => {
    for (const c of en.children ?? []) {
      const node = byId.get(c.id);
      if (!node) continue;
      out.push({
        id: c.id,
        node,
        x: c.x ?? 0,
        y: c.y ?? 0,
        absX: ox + (c.x ?? 0),
        absY: oy + (c.y ?? 0),
        width: c.width ?? LEAF_W,
        height: c.height ?? LEAF_H,
        parent,
        container: (c.children?.length ?? 0) > 0,
        depth,
      });
      walk(c, c.id, depth + 1, ox + (c.x ?? 0), oy + (c.y ?? 0));
    }
  };
  walk(res, undefined, 0, 0, 0);
  return { nodes: out, parentOf };
}
