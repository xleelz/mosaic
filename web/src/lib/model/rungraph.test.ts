// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Graph, GraphNode } from "../api/types";
import { runGraph } from "./rungraph.ts";

function node(id: string, parent?: string, leaf = true): GraphNode {
  return { id, name: id, parent, interfaces: [], leaf, stateful: false };
}

const graph: Graph = {
  nodes: [
    node("platform", undefined, false),
    node("api", "platform", false),
    node("router", "api"),
    node("auth", "api"),
    node("store", "platform"),
    node("web"),
    node("user"),
  ],
  edges: [
    { id: "e1", from: "user", to: "router", kind: "calls", derived: true },
    { id: "e2", from: "router", to: "store", kind: "calls", derived: true },
    { id: "e3", from: "web", to: "auth", kind: "calls", derived: true },
  ],
};

test("keeps the involved components and their ancestors, and only the edges between them", () => {
  const g = runGraph(graph, new Set(["user", "router", "store"]));
  assert.deepEqual(g.nodes.map((n) => n.id).sort(), ["api", "platform", "router", "store", "user"]);
  assert.deepEqual(g.edges.map((e) => e.id), ["e1", "e2"]);
});

test("a kept container with no kept children becomes a leaf", () => {
  const g = runGraph(graph, new Set(["api"]));
  const api = g.nodes.find((n) => n.id === "api")!;
  assert.equal(api.leaf, true);
  assert.equal(g.nodes.find((n) => n.id === "platform")!.leaf, false);
});

test("ids missing from the graph are ignored", () => {
  const g = runGraph(graph, new Set(["user", "no-such-component"]));
  assert.deepEqual(g.nodes.map((n) => n.id), ["user"]);
  assert.deepEqual(g.edges, []);
});
