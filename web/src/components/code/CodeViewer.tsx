"use client";

// The code viewer: a floating window over the page that shows a cited file at
// the model's commit (GET /v1/ontologies/{id}/source), with the cited range
// highlighted and vim keys. CodeViewerProvider is mounted in the workspace
// shell; SourceRef (components/ui.tsx) opens citations through it. The editor
// (CodeEditor.tsx, CodeMirror) is loaded on the first open.

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Source } from "@/lib/api/types";
import { useQuery } from "@/lib/hooks";
import { blobUrl, citedRange, languageOf, rangeSuffix, viewerTitle } from "@/lib/source";
import { ErrorBox, Spinner, cx } from "@/components/ui";
import { useDocument, useWorkspace } from "@/components/workspace/Workspace";
import { CodeViewerContext } from "./context";

const CodeEditor = lazy(() => import("./CodeEditor"));

const VIM_KEY = "mosaic.codeViewer.vim";

function readVim(): boolean {
  try {
    return window.localStorage.getItem(VIM_KEY) !== "off";
  } catch {
    return true;
  }
}

export function CodeViewerProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<Source | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  const open = useCallback((source: Source, from?: HTMLElement | null) => {
    if (from) opener.current = from;
    setTarget(source);
  }, []);
  const close = useCallback(() => {
    setTarget(null);
    const el = opener.current;
    opener.current = null;
    if (el?.isConnected) el.focus({ preventScroll: true });
  }, []);

  return (
    <CodeViewerContext.Provider value={open}>
      {children}
      {target && <CodeWindow source={target} onClose={close} />}
    </CodeViewerContext.Provider>
  );
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const MIN_W = 360;
const MIN_H = 200;

function defaultRect(): Rect {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = Math.max(MIN_W, Math.round(vw * 0.7));
  const h = Math.max(MIN_H, Math.round(vh * 0.7));
  return { x: Math.max(0, Math.round((vw - w) / 2)), y: Math.max(0, Math.round((vh - h) / 2)), w, h };
}

/** Keeps the title bar reachable after a drag or a window resize. */
function clampRect(r: Rect): Rect {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const w = Math.min(Math.max(MIN_W, r.w), vw);
  const h = Math.min(Math.max(MIN_H, r.h), vh);
  return { w, h, x: Math.min(Math.max(r.x, 80 - w), vw - 80), y: Math.min(Math.max(r.y, 0), vh - 36) };
}

function CodeWindow({ source, onClose }: { source: Source; onClose: () => void }) {
  const { id, rev, dataRev } = useWorkspace();
  const doc = useDocument();
  const [rect, setRect] = useState<Rect>(defaultRect);
  const [expanded, setExpanded] = useState(false);
  const [vimOn, setVimOn] = useState(readVim);
  const [copied, setCopied] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  const key = `source:${id}:${dataRev}:${source.repo ?? ""}:${source.sha ?? ""}:${source.path}`;
  const file = useQuery(key, (c) => c.getSource(id, source.path, { rev, repo: source.repo, sha: source.sha }));

  const repo = file.data?.repo || source.repo || doc.data?.source?.repo;
  const sha = file.data?.sha || source.sha || doc.data?.source?.sha;
  const title = viewerTitle({ repo, sha, path: source.path, line: source.line, end_line: source.end_line });
  const github = file.data ? blobUrl(file.data.url, source.line, source.end_line) : "";
  const content = file.data?.content;
  const range = useMemo(() => {
    if (content === undefined) return null;
    return citedRange(content.split("\n").length, source.line, source.end_line);
  }, [content, source.line, source.end_line]);

  // The viewer owns the keyboard while focus is inside it: page shortcuts
  // (the run page's Space and arrows, the header's Escape) never see its keys.
  // Esc outside the editor (the title bar's buttons) closes it.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const onKey = (ev: KeyboardEvent) => {
      ev.stopPropagation();
      if (ev.key === "Escape" && !ev.defaultPrevented && !(ev.target instanceof Element && ev.target.closest(".cm-editor"))) {
        ev.preventDefault();
        onClose();
      }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const onResize = () => setRect((r) => clampRect(r));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const toggleVim = () => {
    setVimOn((v) => {
      try {
        window.localStorage.setItem(VIM_KEY, v ? "off" : "on");
      } catch {
        // storage unavailable: the choice lasts for this page
      }
      return !v;
    });
  };

  const copyPath = () => {
    const text = `${source.path}${rangeSuffix(source.line, source.end_line)}`;
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      },
      () => {},
    );
  };

  // Drag by the title bar; resize from the corner.
  const startDrag = (ev: ReactPointerEvent<HTMLDivElement>, mode: "move" | "resize") => {
    if (ev.button !== 0 || expanded) return;
    if (mode === "move" && (ev.target as Element).closest("button, a, input")) return;
    ev.preventDefault();
    const start = { px: ev.clientX, py: ev.clientY, ...rect };
    const el = ev.currentTarget;
    el.setPointerCapture(ev.pointerId);
    const onMove = (e: PointerEvent) => {
      const dx = e.clientX - start.px;
      const dy = e.clientY - start.py;
      setRect(
        clampRect(
          mode === "move"
            ? { x: start.x + dx, y: start.y + dy, w: start.w, h: start.h }
            : { x: start.x, y: start.y, w: start.w + dx, h: start.h + dy },
        ),
      );
    };
    const onUp = () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
  };

  const style = expanded ? { left: "2.5vw", top: "2.5vh", width: "95vw", height: "95vh" } : { left: rect.x, top: rect.y, width: rect.w, height: rect.h };

  return createPortal(
    <div
      ref={root}
      data-testid="code-viewer"
      data-code-viewer=""
      role="dialog"
      aria-label={`Source: ${title}`}
      style={style}
      className="fixed z-[200] flex flex-col overflow-hidden rounded-lg border border-line bg-panel shadow-[0_18px_60px_rgba(0,0,0,0.6)]"
    >
      <div
        onPointerDown={(e) => startDrag(e, "move")}
        onDoubleClick={(e) => {
          if (!(e.target as Element).closest("button, a")) setExpanded((x) => !x);
        }}
        className={cx("flex h-9 shrink-0 select-none items-center gap-2 border-b border-line bg-panel-2 px-3", !expanded && "cursor-move")}
      >
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink" title={title}>
          {title}
        </span>
        <button
          type="button"
          onClick={toggleVim}
          aria-pressed={vimOn}
          title={vimOn ? "Vim keys on (click to turn off)" : "Vim keys off (click to turn on)"}
          className={cx(
            "rounded border px-1.5 py-0.5 font-mono text-[11px]",
            vimOn ? "border-accent/50 text-accent" : "border-line text-faint hover:text-ink",
          )}
        >
          vim
        </button>
        {github && (
          <a href={github} target="_blank" rel="noreferrer" className="text-[12px] text-link hover:underline">
            ↗ Open on GitHub
          </a>
        )}
        <button type="button" onClick={copyPath} title="Copy the path" className="rounded px-1.5 py-0.5 text-[12px] text-muted hover:bg-panel-3 hover:text-ink">
          {copied ? "✓ copied" : "Copy path"}
        </button>
        <button
          type="button"
          onClick={() => setExpanded((x) => !x)}
          aria-label={expanded ? "Restore the window" : "Expand the window"}
          title={expanded ? "Restore" : "Expand"}
          className="rounded px-1.5 py-0.5 text-[13px] text-muted hover:bg-panel-3 hover:text-ink"
        >
          {expanded ? "❐" : "□"}
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the code viewer"
          title={vimOn ? "Close (:q or q)" : "Close (Esc)"}
          className="rounded px-1.5 py-0.5 text-[13px] text-muted hover:bg-panel-3 hover:text-ink"
        >
          ✕
        </button>
      </div>
      <div className="relative min-h-0 flex-1 bg-bg">
        {file.error ? (
          <div className="p-4">
            <ErrorBox error={file.error} onRetry={file.reload} />
          </div>
        ) : content === undefined ? (
          <Spinner label={`Fetching ${source.path}`} />
        ) : (
          <Suspense fallback={<Spinner label="Loading the editor" />}>
            <CodeEditor
              key={`${key}:${source.line ?? ""}:${source.end_line ?? ""}`}
              content={content}
              lang={languageOf(source.path, file.data?.language_hint)}
              range={range}
              vimOn={vimOn}
              onClose={onClose}
            />
          </Suspense>
        )}
      </div>
      {!expanded && (
        <div
          onPointerDown={(e) => startDrag(e, "resize")}
          aria-hidden
          className="absolute bottom-0 right-0 h-3.5 w-3.5 cursor-nwse-resize"
          style={{ background: "linear-gradient(135deg, transparent 50%, #2a3742 50%, #2a3742 60%, transparent 60%, transparent 72%, #2a3742 72%, #2a3742 82%, transparent 82%)" }}
        />
      )}
    </div>,
    document.body,
  );
}
