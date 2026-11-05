"use client";

import type { ReactNode } from "react";
import type { Document, SimEvent } from "@/lib/api/types";
import { componentName, formatDuration, formatMs, formatTime } from "@/lib/model/format";
import { eventLabel, eventTone, setLabel, TONE_ICON, type EventTone, type Playback } from "@/lib/sim/playback";
import { JsonView } from "@/components/json";
import { ClaimScope } from "@/components/code/context";
import { Badge, SourceRef, cx, type Tone } from "@/components/ui";

const toneBadge: Record<EventTone, Tone> = {
  call: "info",
  ok: "neutral",
  error: "bad",
  fault: "bad",
  retry: "violet",
  timeout: "warn",
  late: "warn",
  async: "info",
  note: "neutral",
  set: "neutral",
  choice: "warn",
  warning: "warn",
  queue: "warn",
  parallel: "info",
  step: "accent",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-faint">{title}</h4>
      {children}
    </div>
  );
}

function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[86px_1fr] gap-x-2 gap-y-0.5 text-[12px]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-faint">{k}</dt>
          <dd className="min-w-0 break-words text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** "POST /v1/x" for an HTTP request envelope with a `method` (optional) and/or `path`. */
function httpLine(input: unknown): string | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const o = input as Record<string, unknown>;
  const method = typeof o.method === "string" && o.method ? o.method.toUpperCase() : "";
  const path = typeof o.path === "string" && o.path.startsWith("/") ? o.path : "";
  if (!method) return null;
  return path ? `${method} ${path}` : method;
}

export function Inspector({ playback, cursor, doc, onJump }: { playback: Playback; cursor: number; doc?: Document; onJump: (i: number) => void }) {
  const e: SimEvent | undefined = playback.events[cursor];
  if (!e) return <div className="p-3 text-muted">No events.</div>;
  const tone = eventTone(e);
  const span = e.span ? playback.spans.get(e.span) : undefined;
  const name = (c?: string) => (c ? componentName(doc, c) : "—");

  const facts: [string, ReactNode][] = [];
  facts.push(["virtual time", <span key="t" className="tnum">{formatTime(e.t, e.t_us)}</span>]);
  // timeout and deadline describe the caller; `to` is the callee (§13.1 item 11).
  const callerSide = e.type === "timeout" || e.type === "deadline";
  if (e.component) facts.push([callerSide ? "caller" : "component", <span key="c">{name(e.component)} <span className="font-mono text-[11px] text-faint">{e.component}</span></span>]);
  if (e.instance) facts.push([callerSide ? "caller instance" : "instance", <span key="inst" className="font-mono text-[11.5px] text-accent">{e.instance}</span>]);
  if (e.mock) facts.push(["mock", <Badge key="m" tone="violet">mock</Badge>]);
  if (e.topic) facts.push(["topic", <span key="tp" className="font-mono text-[11.5px]">{e.topic}</span>]);
  if (e.wait_ms !== undefined) facts.push(["waited", <span key="w" className="tnum text-warn">{formatMs(e.wait_ms)} for a capacity slot</span>]);
  if (e.branch !== undefined) facts.push(["branch", <span key="b" className="tnum">#{e.branch}</span>]);
  if (e.key && (e.type === "step.start" || e.type === "step.end")) facts.push(["step", <span key="st" className="font-mono text-[11.5px]">{e.key}</span>]);
  if (e.key && (e.type === "put" || e.type === "receive")) facts.push(["channel", <span key="ch" className="font-mono text-[11.5px]">{e.key}</span>]);
  if (e.wait_ms && (e.type === "put" || e.type === "receive")) facts.push(["waited", <span key="w" className="tnum">{e.wait_ms} ms</span>]);
  if (e.interface) facts.push(["interface", <span key="i" className="font-mono text-[11.5px]">{e.interface}</span>]);
  const http = httpLine(e.input);
  if (http && e.type === "call.start") facts.push(["request", <span key="req" className="font-mono text-[11.5px]">{http}</span>]);
  if (e.from && e.type !== "emit" && !callerSide) facts.push(["caller", name(e.from)]);
  if (e.to && e.type === "emit") facts.push(["to", name(e.to)]);
  if (callerSide) {
    // A timeout's span is the abandoned call; a deadline's is the caller's own frame.
    const callee = e.type === "timeout" && span && (!e.to || span.to.split("@")[0] === e.to) ? span.to : e.to;
    if (callee) facts.push(["callee", <span key="ce">{name(callee.split("@")[0])}{callee.includes("@") && <span className="font-mono text-[11px] text-accent"> @{callee.split("@")[1]}</span>}</span>]);
  }
  if (e.type === "set" && e.table) facts.push(["row", <span key="row" className="font-mono text-[11.5px]">{e.table} · {e.key}</span>]);
  if (e.attempt && e.attempt > 1) facts.push(["attempt", <span key="a" className="text-violet">↻ {e.attempt}</span>]);
  if (e.async) facts.push(["async", "yes, delivered after the top-level call tree"]);
  if (e.duration_ms !== undefined && (e.type === "call.end" || e.type === "timeout")) facts.push(["duration", <span key="d" className="tnum">{formatDuration(e.duration_ms, e.duration_us)} virtual</span>]);
  if (e.late) facts.push(["late", <span key="l" className="text-warn">{e.branch !== undefined ? "ran after the join completed; its work stands" : "finished after the caller timed out; its work stands"}</span>]);
  const ids = [e.span ? `span ${e.span}` : null, e.parent ? `parent ${e.parent}` : null, e.call ? `call ${e.call}` : null].filter(Boolean).join(" · ");
  if (ids) facts.push(["ids", <span key="ids" className="font-mono text-[11px] text-faint">{ids}</span>]);

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-start gap-2">
        <Badge tone={toneBadge[tone]} className="mt-0.5">
          {TONE_ICON[tone]} {e.type}
        </Badge>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold leading-snug text-ink">{eventLabel(e)}</div>
          <div className="tnum text-[11px] text-faint">
            event {e.seq} of {playback.events.length}
          </div>
        </div>
      </div>
      <Facts items={facts} />

      {e.type === "note" && (
        <Section title="Note">
          {e.title && <div className="text-[13px] font-medium text-ink">{e.title}</div>}
          {e.detail && <p className="text-[12.5px] leading-snug text-muted">{e.detail}</p>}
          {e.source && (
            <ClaimScope claim={e.detail ? `${e.title ?? "Note"}: ${e.detail}` : e.title}>
              <SourceRef source={e.source} />
            </ClaimScope>
          )}
        </Section>
      )}

      {e.type === "choice" && (
        <Section title="Choice">
          <Facts
            items={[
              ["key", <span key="k" className="font-mono text-[11.5px]">{e.key}</span>],
              ["option", <span key="o" className="font-mono text-warn">{e.option}</span>],
              [
                "origin",
                <span key="g">
                  {e.origin}
                  <span className="text-faint">
                    {e.origin === "scenario" ? " · set by the scenario or request" : e.origin === "expression" ? " · computed by the default expression" : " · the choice's default"}
                  </span>
                </span>,
              ],
            ]}
          />
        </Section>
      )}

      {e.type === "set" && (
        <Section title="Set">
          <div className="font-mono text-[12px] text-[#9fd2ff]">{setLabel(e)}</div>
          <div className="mt-1 grid grid-cols-[1fr_auto_1fr] items-start gap-1.5">
            <div>
              <div className="text-[10.5px] text-faint">old</div>
              {e.old === undefined ? <div className="text-[12px] text-faint">∅ unset</div> : <JsonView value={e.old} maxHeight={120} />}
            </div>
            <div className="pt-5 text-faint">→</div>
            <div>
              <div className="text-[10.5px] text-faint">new</div>
              <JsonView value={e.new === undefined ? null : e.new} maxHeight={120} className="border-[#4d6b1f]" />
            </div>
          </div>
        </Section>
      )}

      {e.type === "fault" && (
        <Section title="Fault">
          <Facts items={[["type", <span key="t" className="text-bad">⚡ {e.fault}</span>], ["message", e.message || "—"]]} />
        </Section>
      )}

      {e.type === "retry" && (
        <Section title="Retry">
          <Facts
            items={[
              ["next attempt", <span key="a" className="text-violet">↻ {e.attempt}</span>],
              ["after error", <span key="m" className="font-mono text-[11.5px]">{e.message}</span>],
              ["backoff", `${e.backoff_ms ?? 0} ms`],
            ]}
          />
          {(e.title || e.detail || e.source) && (
            <div className="mt-1.5 border-l-2 border-[#3d3766] pl-2">
              {e.title && <div className="text-[12.5px] font-medium text-ink">{e.title}</div>}
              {e.detail && <p className="text-[12px] text-muted">{e.detail}</p>}
              {e.source && (
                <ClaimScope claim={e.detail ? `${e.title ?? "Retry"}: ${e.detail}` : e.title}>
                  <SourceRef source={e.source} />
                </ClaimScope>
              )}
            </div>
          )}
        </Section>
      )}

      {e.type === "timeout" && (
        <Section title="Timeout">
          <p className="text-[12.5px] text-warn">{e.message}</p>
          <p className="text-[11.5px] text-faint">The caller sees {"{"}code: timeout, retryable: true{"}"}. A timeout doesn&apos;t roll back the callee&apos;s work.</p>
        </Section>
      )}

      {e.type === "publish" && playback.fanout.has(cursor) && (
        <Section title="Subscribers">
          {(playback.fanout.get(cursor) ?? []).length === 0 ? (
            <p className="text-[12px] text-faint">No subscriber calls follow.</p>
          ) : (
            <ul className="space-y-0.5">
              {(playback.fanout.get(cursor) ?? []).map((j) => (
                <li key={j}>
                  <button type="button" className="font-mono text-[11.5px] text-link hover:underline" onClick={() => onJump(j)}>
                    {playback.events[j].type === "emit" ? "⇢" : "→"} {playback.events[j].interface}
                    {playback.events[j].instance ? `@${playback.events[j].instance}` : ""}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {(e.type === "parallel.start" || e.type === "parallel.end" || e.type === "step.end" || e.type === "deadline" ||
        e.type === "yield" || e.type === "put" || e.type === "receive" || e.type === "kill") && e.output !== undefined && (
        <Section title={e.type === "parallel.end" ? "Join result" : e.type === "yield" ? `Item #${e.index ?? 0}` : e.type === "receive" ? "Received" : "Output"}>
          <JsonView value={e.output} maxHeight={220} />
        </Section>
      )}

      {e.type === "warning" && (
        <Section title="Warning">
          <p className="text-[12.5px] text-warn">{e.message}</p>
        </Section>
      )}

      {e.error && (
        <Section title="Error">
          <div className="rounded-md border border-[#5c2a2a] bg-[#1d1113] px-2 py-1.5">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-[12.5px] font-semibold text-bad">{e.error.code}</span>
              {e.error.status ? <span className="tnum text-[12px] text-muted">HTTP {e.error.status}</span> : null}
              {e.error.retryable && <Badge tone="violet">↻ retryable</Badge>}
            </div>
            {e.error.message && <div className="text-[12.5px] text-ink">{e.error.message}</div>}
            {e.error.data !== undefined && <JsonView value={e.error.data} className="mt-1" maxHeight={120} />}
          </div>
        </Section>
      )}

      {e.input !== undefined && (
        <Section title={e.type === "emit" ? "Message (generated)" : "Input (generated)"}>
          <JsonView value={e.input} />
        </Section>
      )}
      {e.type === "call.end" && !e.error && (
        <Section title="Output">
          <JsonView value={e.output === undefined ? null : e.output} />
        </Section>
      )}

      {span && (e.type === "call.start" || e.type === "call.end") && (
        <div className="flex flex-wrap gap-x-3 text-[11.5px]">
          {e.type === "call.end" && (
            <button type="button" className="text-link hover:underline" onClick={() => onJump(span.startIdx)}>
              ← jump to the request
            </button>
          )}
          {e.type === "call.start" && span.endIdx >= 0 && (
            <button type="button" className="text-link hover:underline" onClick={() => onJump(span.endIdx)}>
              jump to the {span.ok === false ? "error" : "response"} →
            </button>
          )}
        </div>
      )}
      {span && e.type !== "call.start" && e.type !== "call.end" && (
        <div className={cx("text-[11.5px] text-faint")}>
          inside {span.iface} <span className="text-faint">(span {span.span})</span>
        </div>
      )}
    </div>
  );
}
