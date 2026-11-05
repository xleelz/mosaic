"use client";

import { useState, type ReactNode } from "react";
import type { JsonObject, SimulationRun } from "@/lib/api/types";
import { formatDuration, formatMs, jsonInline } from "@/lib/model/format";
import type { Jumps } from "@/lib/sim/beats";
import { instanceCount, plural, runVerdict } from "@/lib/sim/wording";
import { Cel, JsonView } from "@/components/json";
import { Kbd, cx } from "@/components/ui";

type Drawer = "result" | "assertions" | "warnings" | "calls" | "passes" | "steps" | "instances" | null;

function Tile({
  label,
  children,
  sub,
  onClick,
  open,
  className,
}: {
  label: string;
  children: ReactNode;
  sub?: ReactNode;
  onClick?: () => void;
  open?: boolean;
  className?: string;
}) {
  const body = (
    <>
      <div className="text-[10.5px] text-faint">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-1.5 text-[15px] font-semibold leading-tight text-ink">{children}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-faint">{sub}</div>}
    </>
  );
  const cls = cx(
    "min-w-[92px] rounded-md border px-2.5 py-1.5 text-left",
    open ? "border-accent bg-[#141d0c]" : "border-line-soft bg-panel-2/60",
    onClick && "hover:border-line hover:bg-panel-2",
    className,
  );
  if (!onClick) return <div className={cls}>{body}</div>;
  return (
    <button type="button" className={cls} onClick={onClick} aria-expanded={open}>
      {body}
    </button>
  );
}

/** A jump tile's hint: what it does, and its key. */
function JumpHint({ k, children }: { k: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1">
      {children} <Kbd>{k}</Kbd>
    </span>
  );
}

export function SummaryCard({ run, jumps, onJump }: { run: SimulationRun; jumps?: Jumps; onJump?: (target: "fault" | "error" | "state") => void }) {
  const s = run.summary;
  const [drawer, setDrawer] = useState<Drawer>(null);
  const toggle = (d: Drawer) => setDrawer((cur) => (cur === d ? null : d));
  const totalCalls = Object.values(s.calls).reduce((a, b) => a + b, 0);
  const byInstance = s.calls_by_instance ?? {};
  const instanceKeys = Object.keys(byInstance);
  const steps = s.steps ?? [];
  const passed = s.assertions.filter((a) => a.passed).length;
  const failed = s.assertions.length - passed;
  const verdict = runVerdict(s);
  const instances = instanceCount(byInstance);
  const statusEl = <span className={cx("text-[13px]", verdict.tone === "bad" ? "text-bad" : verdict.tone === "warn" ? "text-warn" : "text-ink")}>{verdict.text}</span>;
  const result = s.result.ok ? (
    <span className="truncate font-mono text-[13px] text-ink">{jsonInline(s.result.value ?? null, 46)}</span>
  ) : (
    <span className="truncate font-mono text-[13px] text-bad">
      {s.result.error?.status ? `${s.result.error.status} ` : ""}
      {s.result.error?.code ?? "error"}
    </span>
  );

  return (
    <section aria-label="Run summary" className="rounded-lg border border-line bg-panel">
      <div className="flex flex-wrap gap-1.5 p-1.5">
        <Tile label="Outcome" sub={s.abort ? s.abort : s.assertions.length ? (s.passed ? "in simulation" : "not what the model expects") : "no expectations"} className="max-w-[340px]">
          {statusEl}
        </Tile>
        <Tile label={s.result.ok ? "Result" : "Error"} sub={s.result.ok ? "the entry call returned, in simulation" : s.result.error?.message} onClick={() => toggle("result")} open={drawer === "result"} className="min-w-[180px] max-w-[320px] flex-1">
          {result}
        </Tile>
        <Tile label="Duration" sub={`${s.events} events · seed ${s.seed}`}>
          {formatDuration(s.duration_ms, s.duration_us)} virtual
        </Tile>
        {s.passes?.length ? (
          <Tile
            label="Passes"
            sub="repeated flow entry"
            onClick={() => toggle("passes")}
            open={drawer === "passes"}
          >
            <span>✓ {s.passes.filter((p) => p.result.ok).length}</span>
            <span className={s.passes.some((p) => !p.result.ok) ? "text-bad" : "text-faint"}>✗ {s.passes.filter((p) => !p.result.ok).length}</span>
          </Tile>
        ) : null}
        {steps.length > 0 && (
          <Tile label="Steps" sub="multi-step scenario" onClick={() => toggle("steps")} open={drawer === "steps"}>
            <span>✓ {steps.filter((x) => x.result.ok).length}</span>
            <span className={steps.some((x) => !x.result.ok) ? "text-bad" : "text-faint"}>✗ {steps.filter((x) => !x.result.ok).length}</span>
          </Tile>
        )}
        <Tile label="Calls" sub={`${Object.keys(s.calls).length} interfaces`} onClick={() => toggle("calls")} open={drawer === "calls"}>
          {totalCalls}
        </Tile>
        {instances > 1 && (
          <Tile label="Instances" sub={plural(instanceKeys.length, "instance call count")} onClick={() => toggle("instances")} open={drawer === "instances"}>
            {instances}
          </Tile>
        )}
        {s.queued ? (
          <Tile label="Queued" sub="waits for capacity">
            <span className="text-warn">⧗ {s.queued}</span>
          </Tile>
        ) : null}
        {s.mocks ? (
          <Tile label="Mocks" sub="mocked calls">
            <span className="text-violet">{s.mocks}</span>
          </Tile>
        ) : null}
        <Tile label="Retries">
          <span className={s.retries ? "text-violet" : ""}>
            {s.retries ? "↻ " : ""}
            {s.retries}
          </span>
        </Tile>
        <Tile label="Faults" sub={jumps && jumps.firstFault >= 0 ? <JumpHint k="f">first fault</JumpHint> : undefined} onClick={jumps && jumps.firstFault >= 0 ? () => onJump?.("fault") : undefined}>
          <span className={s.faults ? "text-[#f5b294]" : ""}>
            {s.faults ? "⚡ " : ""}
            {s.faults}
          </span>
        </Tile>
        {jumps && jumps.errors > 0 && (
          <Tile label="Errors" sub={<JumpHint k="e">first error</JumpHint>} onClick={() => onJump?.("error")}>
            <span className="text-bad">✗ {jumps.errors}</span>
          </Tile>
        )}
        {jumps && jumps.stateChanges.length > 0 && (
          <Tile label="State changes" sub={<JumpHint k="n">next</JumpHint>} onClick={() => onJump?.("state")}>
            {jumps.stateChanges.length}
          </Tile>
        )}
        <Tile label="Expectations" onClick={() => toggle("assertions")} open={drawer === "assertions"} sub={s.assertions.length ? "self-checks, not accuracy" : "none"}>
          <span>✓ {passed}</span>
          <span className={failed ? "text-bad" : "text-faint"}>✗ {failed}</span>
        </Tile>
        <Tile label="Warnings" onClick={s.warnings.length ? () => toggle("warnings") : undefined} open={drawer === "warnings"}>
          <span className={s.warnings.length ? "text-warn" : ""}>
            {s.warnings.length ? "⚠ " : ""}
            {s.warnings.length}
          </span>
        </Tile>
      </div>
      {drawer && (
        <div className="max-h-[220px] overflow-auto border-t border-line-soft px-3 py-2">
          {drawer === "result" && (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <div>
                <div className="mb-1 text-[10.5px] uppercase tracking-[0.08em] text-faint">{s.result.ok ? "value" : "error"}</div>
                <JsonView value={s.result.ok ? (s.result.value ?? null) : s.result.error ? ({ ...s.result.error } as JsonObject) : null} maxHeight={170} />
              </div>
              <div>
                <div className="mb-1 text-[10.5px] uppercase tracking-[0.08em] text-faint">final ctx</div>
                <JsonView value={s.ctx} maxHeight={170} />
              </div>
            </div>
          )}
          {drawer === "assertions" &&
            (s.assertions.length === 0 ? (
              <div className="text-[12px] text-faint">This run had no expectations.</div>
            ) : (
              <ul className="space-y-1">
                {s.assertions.map((a, i) => (
                  <li key={i} className="flex items-baseline gap-2 text-[12px]">
                    <span className={a.passed ? "text-muted" : "text-bad"} aria-label={a.passed ? "passed" : "failed"}>
                      {a.passed ? "✓" : "✗"}
                    </span>
                    <Cel>{a.expr}</Cel>
                    {a.error && <span className="text-bad">{a.error}</span>}
                  </li>
                ))}
              </ul>
            ))}
          {drawer === "warnings" && (
            <ul className="space-y-0.5 text-[12px] text-warn">
              {s.warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}
          {drawer === "passes" && s.passes?.length ? (
            <table className="w-full max-w-[720px] text-[12px]">
              <thead>
                <tr className="text-left text-[11px] text-faint">
                  <th className="pb-0.5 font-normal">pass</th>
                  <th className="pb-0.5 font-normal">start</th>
                  <th className="pb-0.5 font-normal">duration</th>
                  <th className="pb-0.5 font-normal">result</th>
                </tr>
              </thead>
              <tbody>
                {s.passes.map((p) => (
                  <tr key={p.pass} className="border-t border-line-soft">
                    <td className="tnum py-0.5 text-ink">{p.pass}</td>
                    <td className="tnum py-0.5 text-muted">{formatMs(p.start_ms)}</td>
                    <td className="tnum py-0.5 text-muted">{formatMs(p.duration_ms)}</td>
                    <td className="py-0.5 font-mono text-[11.5px]">
                      {p.result.ok ? (
                        <span className="text-ink">✓ {jsonInline(p.result.value ?? null, 60)}</span>
                      ) : (
                        <span className="text-bad" title={p.result.error?.message}>
                          ✗ {p.result.error?.status ? `${p.result.error.status} ` : ""}
                          {p.result.error?.code ?? "error"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {drawer === "steps" && steps.length > 0 && (
            <table className="w-full max-w-[860px] text-[12px]">
              <thead>
                <tr className="text-left text-[11px] text-faint">
                  <th className="pb-0.5 font-normal">step</th>
                  <th className="pb-0.5 font-normal">entry</th>
                  <th className="pb-0.5 font-normal">on</th>
                  <th className="pb-0.5 font-normal">start</th>
                  <th className="pb-0.5 font-normal">duration</th>
                  <th className="pb-0.5 font-normal">status</th>
                  <th className="pb-0.5 font-normal">result</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((p, i) => (
                  <tr key={i} className="border-t border-line-soft">
                    <td className="py-0.5 font-mono text-[11.5px] text-ink">{p.as || i}</td>
                    <td className="py-0.5 font-mono text-[11.5px] text-muted">{p.flow || p.interface || "—"}</td>
                    <td className="py-0.5 font-mono text-[11.5px] text-muted">{p.on || "—"}</td>
                    <td className="tnum py-0.5 text-muted">{formatMs(p.start_ms)}</td>
                    <td className="tnum py-0.5 text-muted">{formatMs(p.duration_ms)}</td>
                    <td className="py-0.5 text-muted">{p.status}</td>
                    <td className="py-0.5 font-mono text-[11.5px]">
                      {p.result.ok ? (
                        <span className="text-ink">✓ {jsonInline(p.result.value ?? null, 60)}</span>
                      ) : (
                        <span className="text-bad" title={p.result.error?.message}>
                          ✗ {p.result.error?.status ? `${p.result.error.status} ` : ""}
                          {p.result.error?.code ?? "error"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {drawer === "instances" && (
            <table className="w-full max-w-[560px] text-[12px]">
              <tbody>
                {instanceKeys.sort().map((k) => (
                  <tr key={k} className="border-t border-line-soft first:border-t-0">
                    <td className="py-0.5 font-mono text-[11.5px] text-ink">{k}</td>
                    <td className={cx("tnum py-0.5 text-right", byInstance[k] === 0 ? "text-faint" : "text-ink")}>{byInstance[k]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {drawer === "calls" && (
            <table className="w-full max-w-[560px] text-[12px]">
              <tbody>
                {Object.entries(s.calls)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([k, n]) => (
                    <tr key={k} className="border-t border-line-soft first:border-t-0">
                      <td className="py-0.5 font-mono text-[11.5px] text-ink">{k}</td>
                      <td className={cx("tnum py-0.5 text-right", n === 0 ? "text-faint" : "text-ink")}>{n}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
