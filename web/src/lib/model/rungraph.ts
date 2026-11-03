import type { Graph } from "../api/types";

/**
 * The part of a component graph a simulation run touches: the components in `involved`, their
 * ancestor containers (so the map keeps its nesting), and the edges between kept components.
 * A kept node is a leaf when none of its children are kept.
 *
 * The run view draws this instead of the whole graph for large ontologies: a map of hundreds
 * of transformed nodes costs the browser far more than the few dozen a run uses (WebKit gives
 * each one its own compositing layer), and the components outside the run are dimmed anyway.
 */
export function runGraph(graph: Graph, involved: Set<string>): Graph {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const keep = new Set<string>();
  for (const id of involved) {
    let cur: string | undefined = id;
    while (cur && byId.has(cur) && !keep.has(cur)) {
      keep.add(cur);
      cur = byId.get(cur)!.parent;
    }
  }
  const hasKeptChild = new Set<string>();
  for (const id of keep) {
    const p = byId.get(id)!.parent;
    if (p && keep.has(p)) hasKeptChild.add(p);
  }
  return {
    nodes: graph.nodes.filter((n) => keep.has(n.id)).map((n) => ({ ...n, leaf: !hasKeptChild.has(n.id) })),
    edges: graph.edges.filter((e) => keep.has(e.from) && keep.has(e.to)),
  };
}
