import type { Document, Interface, JsonValue, Latency, Source } from "@/lib/api/types";
import { docIndex } from "./docindex";

/** "path", "path:line" or "path:line-end", as model.Source.String() renders it. */
export function sourceString(s: Source): string {
  if (s.line && s.end_line) return `${s.path}:${s.line}-${s.end_line}`;
  if (s.line) return `${s.path}:${s.line}`;
  return s.path;
}

export function latencyString(l?: Latency): string {
  if (l === undefined) return "1 ms (default)";
  if (typeof l === "number") return `${l} ms`;
  if (typeof l === "string") return l;
  if (l.min === l.max) return `${l.min} ms`;
  return `${l.min}–${l.max} ms`;
}

export function ifaceId(i: Interface): string {
  return i.id || `${i.component}.${i.name}`;
}

/** The short name of an interface id: "authentication.authenticate" -> "authenticate". */
export function ifaceName(id: string): string {
  const i = id.indexOf(".");
  return i >= 0 ? id.slice(i + 1) : id;
}

export function ifaceComponent(id: string): string {
  const i = id.indexOf(".");
  return i >= 0 ? id.slice(0, i) : id;
}

/** If v is a "=cel" template string, returns the expression. */
export function celOf(v: unknown): string | null {
  if (typeof v === "string" && v.startsWith("=")) return v.slice(1).trim();
  return null;
}

export function formatMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms % 1000 === 0 ? 0 : 2)} s`;
  const m = Math.floor(ms / 60000);
  const s = ((ms % 60000) / 1000).toFixed(1);
  return `${m}m ${s}s`;
}

/**
 * Formats a duration given in ms, using the exact µs value (§13.1 item 16)
 * when it is under a millisecond.
 */
export function formatDuration(ms: number, us?: number): string {
  if (us !== undefined && us < 1000) return `${us} µs`;
  return formatMs(ms);
}

/** Formats a trace time, with µs precision when the run has it. */
export function formatTime(ms: number, us?: number): string {
  if (us !== undefined && us % 1000 !== 0) return `${(us / 1000).toFixed(3)} ms`;
  return formatMs(ms);
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").replace(/:\d\d(\.\d+)?Z$/, " UTC");
}

/** A one-line, truncated rendering of a JSON value for chips. */
export function jsonChip(v: JsonValue | undefined, max = 34): string {
  if (v === undefined) return "";
  let s: string;
  if (v === null) s = "null";
  else if (Array.isArray(v)) s = `[${v.length}]`;
  else if (typeof v === "object") {
    const keys = Object.keys(v);
    s = keys.length ? `{${keys.join(", ")}}` : "{}";
  } else if (typeof v === "string") s = JSON.stringify(v);
  else s = String(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

export function jsonInline(v: JsonValue | undefined, max = 60): string {
  if (v === undefined) return "∅";
  const s = JSON.stringify(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

export function componentName(doc: Document | undefined, id: string): string {
  return (doc && docIndex(doc).componentsById.get(id)?.name) || id;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function isPlainObject(v: unknown): v is Record<string, JsonValue> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Deep equality for JSON values. */
export function jsonEqual(a: JsonValue | undefined, b: JsonValue | undefined): boolean {
  if (a === b) return true;
  if (a === undefined || b === undefined || a === null || b === null) return false;
  if (Array.isArray(a)) {
    return Array.isArray(b) && a.length === b.length && a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (typeof a === "object") {
    if (typeof b !== "object" || Array.isArray(b)) return false;
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in b && jsonEqual(a[k], b[k]));
  }
  return false;
}

/** deepMerge as sim.go does it: maps merge recursively, anything else in over replaces base. */
export function deepMerge(base: JsonValue | undefined, over: JsonValue | undefined): JsonValue | undefined {
  if (over === undefined || over === null) return base === undefined ? undefined : structuredClone(base);
  if (!isPlainObject(base) || !isPlainObject(over)) return structuredClone(over);
  const out: Record<string, JsonValue> = structuredClone(base);
  for (const [k, v] of Object.entries(over)) {
    const merged = deepMerge(out[k], v);
    if (merged !== undefined) out[k] = merged;
  }
  return out;
}

/** The flow a scenario is grouped under: its flow, or its first step's flow (§11.7). */
export function scenarioFlow(s: { flow?: string; steps?: { flow?: string }[] }): string {
  return s.flow || s.steps?.[0]?.flow || "";
}
