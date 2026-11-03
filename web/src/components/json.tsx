"use client";

import type { ReactNode } from "react";
import type { JsonValue } from "@/lib/api/types";
import { celOf, isPlainObject } from "@/lib/model/format";
import { cx } from "./ui";

function renderJson(v: JsonValue | undefined, indent: number, out: ReactNode[], keyPrefix: string) {
  const pad = "  ".repeat(indent);
  if (v === undefined) {
    out.push(<span key={keyPrefix} className="json-null">undefined</span>);
  } else if (v === null) {
    out.push(<span key={keyPrefix} className="json-null">null</span>);
  } else if (typeof v === "string") {
    out.push(<span key={keyPrefix} className="json-str">{JSON.stringify(v)}</span>);
  } else if (typeof v === "number") {
    out.push(<span key={keyPrefix} className="json-num">{String(v)}</span>);
  } else if (typeof v === "boolean") {
    out.push(<span key={keyPrefix} className="json-bool">{String(v)}</span>);
  } else if (Array.isArray(v)) {
    if (v.length === 0) {
      out.push(<span key={keyPrefix}>[]</span>);
      return;
    }
    out.push(<span key={`${keyPrefix}o`}>{"[\n"}</span>);
    v.forEach((x, i) => {
      out.push(<span key={`${keyPrefix}p${i}`}>{pad + "  "}</span>);
      renderJson(x, indent + 1, out, `${keyPrefix}.${i}`);
      out.push(<span key={`${keyPrefix}c${i}`}>{i < v.length - 1 ? ",\n" : "\n"}</span>);
    });
    out.push(<span key={`${keyPrefix}e`}>{pad + "]"}</span>);
  } else {
    const keys = Object.keys(v);
    if (keys.length === 0) {
      out.push(<span key={keyPrefix}>{"{}"}</span>);
      return;
    }
    out.push(<span key={`${keyPrefix}o`}>{"{\n"}</span>);
    keys.forEach((k, i) => {
      out.push(
        <span key={`${keyPrefix}k${i}`}>
          {pad + "  "}
          <span className="json-key">{JSON.stringify(k)}</span>
          {": "}
        </span>,
      );
      renderJson(v[k], indent + 1, out, `${keyPrefix}.${k}`);
      out.push(<span key={`${keyPrefix}c${i}`}>{i < keys.length - 1 ? ",\n" : "\n"}</span>);
    });
    out.push(<span key={`${keyPrefix}e`}>{pad + "}"}</span>);
  }
}

export function JsonView({ value, className, maxHeight = 260 }: { value: JsonValue | undefined; className?: string; maxHeight?: number }) {
  const out: ReactNode[] = [];
  renderJson(value, 0, out, "r");
  return (
    <pre
      className={cx(
        "overflow-auto rounded-md border border-line-soft bg-[#0c1116] px-2.5 py-2 font-mono text-[11.5px] leading-[1.5] text-muted",
        className,
      )}
      style={{ maxHeight }}
      tabIndex={0}
    >
      {out}
    </pre>
  );
}

/** A behavior template: "=cel" strings render as CEL, everything else as literal JSON. */
export function Tpl({ value }: { value: JsonValue | undefined }): ReactNode {
  if (value === undefined) return <span className="text-faint">—</span>;
  const cel = celOf(value);
  if (cel !== null) return <code className="cel">{cel}</code>;
  if (value === null || typeof value !== "object") {
    return <span className="lit">{JSON.stringify(value)}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="lit">[]</span>;
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        <span className="text-faint">[</span>
        {value.map((x, i) => (
          <span key={i} className="inline-flex items-center gap-1">
            <Tpl value={x} />
            {i < value.length - 1 && <span className="text-faint">,</span>}
          </span>
        ))}
        <span className="text-faint">]</span>
      </span>
    );
  }
  return <TplObject value={value} />;
}

function TplObject({ value }: { value: Record<string, JsonValue> }) {
  const keys = Object.keys(value);
  if (keys.length === 0) return <span className="lit">{"{}"}</span>;
  return (
    <span className="block">
      {keys.map((k) => (
        <span key={k} className="flex items-baseline gap-1.5 py-[1px]">
          <span className="shrink-0 font-mono text-[11.5px] text-[#9fd2ff]">{k}:</span>
          <span className="min-w-0">{isPlainObject(value[k]) ? <TplObject value={value[k] as Record<string, JsonValue>} /> : <Tpl value={value[k]} />}</span>
        </span>
      ))}
    </span>
  );
}

/** A CEL expression that is always CEL (if, when, expect). */
export function Cel({ children }: { children: string }) {
  return <code className="cel">{children}</code>;
}
