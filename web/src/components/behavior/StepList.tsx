"use client";

import type { ReactNode } from "react";
import type { RetrySpec, Step, StoreSpec } from "@/lib/api/types";
import { celOf } from "@/lib/model/format";
import { Cel, Tpl } from "@/components/json";
import { ClaimScope } from "@/components/code/context";
import { SourceRef, cx } from "@/components/ui";

type Action = "call" | "if" | "choice" | "foreach" | "break" | "continue" | "set" | "return" | "fail" | "emit" | "wait" | "note";

function actionOf(s: Step): Action {
  if (s.set !== undefined) return "set";
  if (s.call) return "call";
  if (s.if) return "if";
  if (s.choice) return "choice";
  if (s.foreach !== undefined) return "foreach";
  if (s.break) return "break";
  if (s.continue) return "continue";
  if (s.return !== undefined) return "return";
  if (s.fail !== undefined) return "fail";
  if (s.emit) return "emit";
  if (s.wait !== undefined) return "wait";
  return "note";
}

const pillClass: Record<Action, string> = {
  call: "border-[#24445a] bg-[#122230] text-link",
  if: "border-[#3d3766] bg-[#1d1a33] text-violet",
  choice: "border-[#5a4520] bg-[#2a2213] text-warn",
  foreach: "border-[#3d3766] bg-[#1d1a33] text-violet",
  break: "border-line bg-panel-2 text-violet",
  continue: "border-line bg-panel-2 text-violet",
  set: "border-line bg-panel-2 text-muted",
  return: "border-[#1f4d2a] bg-[#11251a] text-ok",
  fail: "border-[#5c2a2a] bg-[#2a1517] text-bad",
  emit: "border-[#1d4a44] bg-[#0f2523] text-[#7fe0cf]",
  wait: "border-line bg-panel-2 text-faint",
  note: "border-line-soft bg-transparent text-faint",
};

function Pill({ action }: { action: Action }) {
  return (
    <span
      className={cx(
        "mt-[1px] inline-flex h-[18px] w-[60px] shrink-0 items-center justify-center rounded border font-mono text-[10.5px] font-semibold uppercase tracking-wide",
        pillClass[action],
      )}
    >
      {action}
    </span>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 py-[2px]">
      <span className="w-[68px] shrink-0 text-right text-[11px] text-faint">{k}</span>
      <div className="min-w-0 flex-1 text-[12px]">{children}</div>
    </div>
  );
}

function Nested({ label, badge, children }: { label: ReactNode; badge?: ReactNode; children: ReactNode }) {
  return (
    <div className="mt-1.5">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-muted">
        <span aria-hidden className="text-faint">└</span>
        {label}
        {badge}
      </div>
      <div className="ml-[7px] border-l border-line pl-3">{children}</div>
    </div>
  );
}

function IfaceRef({ id, onSelect }: { id: string; onSelect?: (id: string) => void }) {
  if (!onSelect) return <span className="font-mono text-[12px] text-ink">{id}</span>;
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className="font-mono text-[12px] text-ink underline decoration-line underline-offset-2 hover:text-link hover:decoration-link"
    >
      {id}
    </button>
  );
}

function RetryBlock({ r }: { r: RetrySpec }) {
  const max = r.max_attempts;
  const maxCel = celOf(max);
  return (
    <div className="mt-1 rounded-md border border-[#3d3766] bg-[#16142a] px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
        <span className="font-semibold text-violet">↻ retry</span>
        <span className="text-muted">up to</span>
        {maxCel !== null ? <Cel>{maxCel}</Cel> : <span className="lit">{max === undefined ? "1" : String(max)}</span>}
        <span className="text-muted">attempts</span>
        {r.backoff_ms ? (
          <span className="text-muted">
            · backoff <span className="lit">{r.backoff_ms} ms</span>
            {r.multiplier && r.multiplier !== 1 ? <> ×<span className="lit">{r.multiplier}</span></> : null}
            {r.max_backoff_ms ? <> ≤ <span className="lit">{r.max_backoff_ms} ms</span></> : null}
          </span>
        ) : (
          <span className="text-faint">· no backoff</span>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[12px]">
        <span className="text-faint">on</span>
        {r.codes?.length ? (
          r.codes.map((c) => (
            <span key={c} className="rounded border border-line bg-panel-2 px-1 font-mono text-[11px] text-ink">
              {c}
            </span>
          ))
        ) : (
          <span className="text-muted">any retryable error</span>
        )}
        {r.when && (
          <>
            <span className="ml-1 text-faint">when</span>
            <Cel>{r.when}</Cel>
          </>
        )}
      </div>
      {(r.title || r.detail || r.source) && (
        <div className="mt-1 border-t border-[#2b2650] pt-1 text-[12px]">
          {r.title && <div className="font-medium text-ink">{r.title}</div>}
          {r.detail && <div className="text-muted">{r.detail}</div>}
          {r.source && (
            <ClaimScope claim={r.detail ? `${r.title ?? "Retry"}: ${r.detail}` : r.title}>
              <SourceRef source={r.source} />
            </ClaimScope>
          )}
        </div>
      )}
    </div>
  );
}

function StepBody({ s, action, iface, onSelectInterface }: { s: Step; action: Action; iface?: string; onSelectInterface?: (id: string) => void }) {
  switch (action) {
    case "set":
      return (
        <div className="mt-0.5 space-y-0.5">
          {Object.entries(s.set ?? {})
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([path, v]) => (
              <div key={path} className="flex items-baseline gap-1.5 text-[12px]">
                <span className="shrink-0 font-mono text-[11.5px] text-[#9fd2ff]">{path}</span>
                <span className="text-faint">←</span>
                <span className="min-w-0">
                  <Tpl value={v} />
                </span>
              </div>
            ))}
        </div>
      );
    case "call": {
      const dyn = celOf(s.call);
      return (
        <div className="mt-0.5">
          <div className="flex flex-wrap items-baseline gap-1.5">
            {dyn !== null ? (
              <>
                <span className="text-[11px] text-faint">dynamic</span>
                <Cel>{dyn}</Cel>
              </>
            ) : (
              <IfaceRef id={s.call!} onSelect={onSelectInterface} />
            )}
            {s.as && (
              <span className="text-[11px] text-faint">
                → <span className="font-mono text-[#9fd2ff]">vars.{s.as}</span>
              </span>
            )}
          </div>
          {s.targets?.length ? (
            <Row k="targets">
              <span className="flex flex-wrap gap-1">
                {s.targets.map((t) => (
                  <IfaceRef key={t} id={t} onSelect={onSelectInterface} />
                ))}
              </span>
            </Row>
          ) : null}
          {s.input !== undefined && (
            <Row k={s.fill ? "input (fill)" : "input"}>
              <Tpl value={s.input} />
            </Row>
          )}
          {s.timeout_ms ? (
            <Row k="timeout">
              <span className="text-warn">⏱ {s.timeout_ms} ms</span>
            </Row>
          ) : null}
          {s.retry && <RetryBlock r={s.retry} />}
          <OnErrorView s={s} iface={iface} onSelectInterface={onSelectInterface} />
        </div>
      );
    }
    case "if":
      return (
        <div className="mt-0.5">
          <Cel>{s.if!}</Cel>
          <Nested label="then">
            <StepList steps={s.then ?? []} iface={iface} onSelectInterface={onSelectInterface} />
          </Nested>
          {s.else?.length ? (
            <Nested label="else">
              <StepList steps={s.else} iface={iface} onSelectInterface={onSelectInterface} />
            </Nested>
          ) : null}
        </div>
      );
    case "choice": {
      const options = Object.keys(s.options ?? {}).sort();
      const defCel = celOf(s.default);
      // Without a default, the engine takes the first option in sorted order.
      const def = defCel === null ? s.default || options[0] : undefined;
      return (
        <div className="mt-0.5">
          <div className="flex flex-wrap items-baseline gap-1.5">
            <span className="font-mono text-[12px] text-ink">{s.choice}</span>
            {iface && <span className="font-mono text-[11px] text-faint">key {iface}.{s.choice}</span>}
            {defCel !== null && (
              <span className="text-[11px] text-faint">
                default <Cel>{defCel}</Cel>
              </span>
            )}
          </div>
          {options.map((o) => (
            <Nested
              key={o}
              label={<span className="font-mono text-warn">{o}</span>}
              badge={
                o === def ? (
                  <span className="rounded border border-[#5a4520] px-1 text-[10px] font-medium text-warn">default</span>
                ) : null
              }
            >
              <StepList steps={s.options?.[o] ?? []} iface={iface} onSelectInterface={onSelectInterface} />
            </Nested>
          ))}
        </div>
      );
    }
    case "foreach": {
      const src = celOf(s.foreach);
      return (
        <div className="mt-0.5">
          <div className="flex flex-wrap items-baseline gap-1.5 text-[12px]">
            <span className="text-[11px] text-faint">over</span>
            {src !== null ? <Cel>{src}</Cel> : <Tpl value={s.foreach} />}
          </div>
          <Row k="item">
            <span className="font-mono text-[11.5px] text-[#9fd2ff]">vars.{s.as || "item"}</span>
            {s.index && (
              <span className="text-[11px] text-faint">
                {" "}· index <span className="font-mono text-[#9fd2ff]">vars.{s.index}</span>
              </span>
            )}
          </Row>
          <Row k="max">
            <span className="lit">{s.max || 100}</span>
            {!s.max && <span className="text-[11px] text-faint"> iterations (default)</span>}
          </Row>
          <Nested label="each">
            <StepList steps={s.steps ?? []} iface={iface} onSelectInterface={onSelectInterface} />
          </Nested>
        </div>
      );
    }
    case "break":
      return <div className="mt-0.5 text-[12px] text-muted">leave the enclosing foreach</div>;
    case "continue":
      return <div className="mt-0.5 text-[12px] text-muted">skip to the next item of the enclosing foreach</div>;
    case "return":
      return (
        <div className="mt-0.5 text-[12px]">
          <Tpl value={s.return} />
        </div>
      );
    case "fail":
      return (
        <div className="mt-0.5 text-[12px]">
          <Tpl value={s.fail} />
        </div>
      );
    case "emit":
      return (
        <div className="mt-0.5">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-faint">async ⇢</span>
            <IfaceRef id={s.emit!} onSelect={onSelectInterface} />
          </div>
          {s.input !== undefined && (
            <Row k="input">
              <Tpl value={s.input} />
            </Row>
          )}
        </div>
      );
    case "wait": {
      const c = celOf(s.wait);
      return <div className="mt-0.5 text-[12px]">{c !== null ? <Cel>{c}</Cel> : <span className="lit">{String(s.wait)} ms</span>}</div>;
    }
    default:
      return null;
  }
}

/** A declarative datastore operation (interface.store) on state.<table>. */
export function StoreView({ store }: { store: StoreSpec }) {
  const writes = store.op !== "get" && store.op !== "query";
  return (
    <div className="rounded-md border border-[#1d4a44] bg-[#0f2523]/60 px-2 py-1.5">
      <div className="flex flex-wrap items-baseline gap-1.5 text-[12px]">
        <span className="font-semibold text-[#7fe0cf]">⛁ store</span>
        <span className="rounded border border-[#1d4a44] px-1 font-mono text-[11px] font-semibold uppercase text-[#7fe0cf]">{store.op}</span>
        <span className="text-faint">on</span>
        <span className="font-mono text-[11.5px] text-[#9fd2ff]">state.{store.table}</span>
      </div>
      {store.key !== undefined && (
        <Row k="key">
          <Tpl value={store.key} />
        </Row>
      )}
      {store.value !== undefined && (
        <Row k={store.op === "update" ? "patch" : store.op === "incr" ? "deltas" : "value"}>
          <Tpl value={store.value} />
        </Row>
      )}
      {store.where && (
        <Row k={writes ? "condition" : "where"}>
          <Cel>{store.where}</Cel>
        </Row>
      )}
      {store.default !== undefined && (
        <Row k="on miss">
          <Tpl value={store.default} />
        </Row>
      )}
      {store.not_found && (
        <Row k="not found">
          <span className="font-mono text-[11.5px] text-bad">{store.not_found}</span>
        </Row>
      )}
      {store.conflict && (
        <Row k="conflict">
          <span className="font-mono text-[11.5px] text-bad">{store.conflict}</span>
        </Row>
      )}
    </div>
  );
}

function OnErrorView({ s, iface, onSelectInterface }: { s: Step; iface?: string; onSelectInterface?: (id: string) => void }) {
  const oe = s.on_error;
  if (oe === undefined) {
    return (
      <Row k="on_error">
        <span className="text-faint">propagate (default)</span>
      </Row>
    );
  }
  if (typeof oe === "string") {
    return (
      <Row k="on_error">
        <span className={oe === "continue" ? "text-warn" : "text-muted"}>{oe}</span>
      </Row>
    );
  }
  return (
    <Nested label={<span className="text-bad">on_error</span>}>
      <StepList steps={oe} iface={iface} onSelectInterface={onSelectInterface} />
    </Nested>
  );
}

export function StepList({
  steps,
  iface,
  onSelectInterface,
}: {
  steps: Step[];
  /** The interface the behavior belongs to (for choice keys). */
  iface?: string;
  onSelectInterface?: (id: string) => void;
}) {
  if (steps.length === 0) return <div className="text-[12px] text-faint">(no steps)</div>;
  return (
    <ol className="space-y-1.5">
      {steps.map((s, i) => {
        const action = actionOf(s);
        return (
          <li key={i} className="flex gap-2">
            <Pill action={action} />
            <div className="min-w-0 flex-1">
              {(s.title || s.detail || s.source) && (
                <div className="mb-0.5">
                  {s.title && <div className="text-[12.5px] font-semibold text-ink">{s.title}</div>}
                  {s.detail && <div className="text-[12px] leading-snug text-muted">{s.detail}</div>}
                  {s.source && (
                    <ClaimScope claim={s.detail ? `${s.title ?? "Step"}: ${s.detail}` : s.title}>
                      <SourceRef source={s.source} />
                    </ClaimScope>
                  )}
                </div>
              )}
              {s.when && (
                <div className="flex items-baseline gap-1.5 text-[12px]">
                  <span className="text-[11px] text-faint">when</span>
                  <Cel>{s.when}</Cel>
                </div>
              )}
              <StepBody s={s} action={action} iface={iface} onSelectInterface={onSelectInterface} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
