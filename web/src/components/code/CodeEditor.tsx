"use client";

// The code viewer's editor: CodeMirror 6, read-only, with vim keys
// (@replit/codemirror-vim). Loaded with a dynamic import by CodeViewer.tsx, so
// pages pay for it only once a citation is clicked.

import { useEffect, useRef, useState } from "react";
import { defaultKeymap } from "@codemirror/commands";
import { bracketMatching, HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { highlightSelectionMatches, search, searchKeymap } from "@codemirror/search";
import { Compartment, EditorSelection, EditorState, RangeSetBuilder, Text, type Extension } from "@codemirror/state";
import {
  Decoration,
  drawSelection,
  EditorView,
  GutterMarker,
  gutterLineClass,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import { getCM, vim, Vim } from "@replit/codemirror-vim";
import type { LangKey } from "@/lib/source";
import { loadLanguage } from "./languages";

// ---- vim: :q, :quit and q close the viewer of the editor they run in ----

const closers = new WeakMap<EditorView, () => void>();
let vimReady = false;

function setupVim() {
  if (vimReady) return;
  vimReady = true;
  const quit = (cm: { cm6: EditorView }) => closers.get(cm.cm6)?.();
  Vim.defineEx("quit", "q", quit);
  Vim.defineEx("xit", "x", quit);
  Vim.defineEx("wq", "wq", quit);
  Vim.map("q", ":quit<CR>", "normal");
}

// ---- theme: the app's palette (globals.css @theme) ----

const C = {
  bg: "#0a0e12",
  panel: "#11181f",
  panel2: "#17212b",
  line: "#2a3742",
  lineSoft: "#1d2731",
  ink: "#edf3f6",
  muted: "#a2b1bc",
  faint: "#8796a1",
  accent: "#ccff78",
  accentInk: "#0a0e12",
  link: "#76ccff",
  bad: "#ff9b99",
  warn: "#ffd08a",
  violet: "#b4a8ff",
  string: "#a6e3a1",
  prop: "#9fcbe6",
};

const theme = EditorView.theme(
  {
    "&": { height: "100%", backgroundColor: C.bg, color: C.ink, fontSize: "12.5px" },
    ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.6" },
    ".cm-content": { caretColor: C.accent },
    ".cm-gutters": { backgroundColor: C.panel, color: C.faint, borderRight: `1px solid ${C.lineSoft}` },
    ".cm-lineNumbers .cm-gutterElement": { padding: "0 10px 0 12px" },
    ".cm-activeLine": { backgroundColor: "rgba(255,255,255,0.035)" },
    ".cm-activeLineGutter": { backgroundColor: C.panel2, color: C.ink },
    ".cm-cited": { backgroundColor: "rgba(204,255,120,0.085)", boxShadow: `inset 2px 0 0 ${C.accent}` },
    ".cm-cited.cm-activeLine": { backgroundColor: "rgba(204,255,120,0.13)" },
    ".cm-gutterElement.cm-cited-gutter": { color: C.accent, backgroundColor: "rgba(204,255,120,0.06)" },
    "&.cm-focused .cm-cursor": { borderLeftColor: C.accent, borderLeftWidth: "2px" },
    ".cm-fat-cursor": { background: `${C.accent} !important`, color: `${C.accentInk} !important` },
    "&:not(.cm-focused) .cm-fat-cursor": { background: "none !important", outline: `1px solid ${C.accent}`, color: "inherit !important" },
    "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection": {
      backgroundColor: "rgba(118,204,255,0.25) !important",
    },
    ".cm-searchMatch": { backgroundColor: "rgba(255,208,138,0.22)", outline: "1px solid rgba(255,208,138,0.45)" },
    ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "rgba(255,208,138,0.45)" },
    ".cm-selectionMatch": { backgroundColor: "rgba(118,204,255,0.12)" },
    "&.cm-focused .cm-matchingBracket": { backgroundColor: "rgba(204,255,120,0.18)", outline: "none" },
    ".cm-panels": { backgroundColor: C.panel2, color: C.ink, fontFamily: "var(--font-mono)" },
    ".cm-panels.cm-panels-bottom": { borderTop: `1px solid ${C.line}` },
    ".cm-panels input, .cm-panels button": { color: C.ink, fontFamily: "var(--font-mono)" },
    ".cm-panels input": { backgroundColor: "transparent", outline: "none", border: "none" },
    ".cm-vim-panel": { padding: "2px 8px", fontSize: "12px" },
    ".cm-vim-panel input": { backgroundColor: "transparent", color: C.ink, border: "none", outline: "none" },
    ".cm-specialChar": { color: C.bad },
  },
  { dark: true },
);

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.moduleKeyword, t.operatorKeyword, t.definitionKeyword, t.modifier, t.self], color: C.violet },
  { tag: [t.string, t.special(t.string), t.character, t.regexp, t.escape], color: C.string },
  { tag: [t.number, t.bool, t.atom, t.null, t.integer, t.float], color: C.warn },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], color: C.faint, fontStyle: "italic" },
  { tag: [t.typeName, t.className, t.namespace, t.standard(t.typeName), t.definition(t.typeName)], color: C.link },
  {
    tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName)), t.labelName],
    color: C.accent,
  },
  { tag: [t.propertyName, t.attributeName], color: C.prop },
  { tag: [t.meta, t.processingInstruction, t.annotation, t.macroName, t.tagName], color: C.bad },
  { tag: [t.operator, t.punctuation, t.separator, t.bracket, t.derefOperator], color: C.muted },
  { tag: [t.variableName, t.definition(t.variableName)], color: C.ink },
  { tag: t.heading, color: C.accent, fontWeight: "600" },
  { tag: t.strong, fontWeight: "600" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: [t.link, t.url], color: C.link, textDecoration: "underline" },
  { tag: t.invalid, color: C.bad },
]);

// ---- the cited range ----

const citedGutter = new (class extends GutterMarker {
  elementClass = "cm-cited-gutter";
})();

function citedLines(doc: Text, range: [number, number] | null): Extension {
  if (!range) return [];
  const lines = new RangeSetBuilder<Decoration>();
  const gutter = new RangeSetBuilder<GutterMarker>();
  const deco = Decoration.line({ class: "cm-cited" });
  for (let n = range[0]; n <= range[1]; n++) {
    const from = doc.line(n).from;
    lines.add(from, from, deco);
    gutter.add(from, from, citedGutter);
  }
  return [EditorView.decorations.of(lines.finish()), gutterLineClass.of(gutter.finish())];
}

// ---- the editor ----

interface Status {
  mode: string;
  pending: string;
  line: number;
  col: number;
}

function modeLabel(e: { mode?: string; subMode?: string }): string {
  const m = (e.mode || "normal").toUpperCase();
  if (e.mode === "visual" && e.subMode === "linewise") return "VISUAL LINE";
  if (e.mode === "visual" && e.subMode === "blockwise") return "VISUAL BLOCK";
  return m;
}

export interface CodeEditorProps {
  content: string;
  lang: LangKey;
  /** The cited lines, 1-based and inclusive, already clamped to the file. */
  range: [number, number] | null;
  vimOn: boolean;
  onClose: () => void;
}

export default function CodeEditor({ content, lang, range, vimOn, onClose }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const [status, setStatus] = useState<Status>({ mode: "NORMAL", pending: "", line: range?.[0] ?? 1, col: 1 });
  const first = range?.[0];
  const last = range?.[1];

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    if (vimOn) setupVim();
    const language = new Compartment();
    const cited: [number, number] | null = first && last ? [first, last] : null;
    const doc = Text.of(content.split(/\r\n?|\n/));
    const state = EditorState.create({
      doc,
      extensions: [
        vimOn ? vim({ status: false }) : [],
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        drawSelection(),
        highlightActiveLine(),
        bracketMatching(),
        highlightSelectionMatches(),
        search({ top: false }),
        keymap.of([...searchKeymap, ...defaultKeymap]),
        EditorState.readOnly.of(true),
        // Read-only for vim too: its operators (dd, x, p) dispatch changes.
        EditorState.changeFilter.of(() => false),
        EditorState.tabSize.of(4),
        language.of([]),
        syntaxHighlighting(highlight),
        theme,
        citedLines(doc, cited),
        EditorView.contentAttributes.of({ "aria-label": "Source code", "aria-readonly": "true" }),
        EditorView.updateListener.of((u) => {
          if (!u.selectionSet && !u.docChanged && !u.focusChanged) return;
          const head = u.state.selection.main.head;
          const ln = u.state.doc.lineAt(head);
          setStatus((s) => (s.line === ln.number && s.col === head - ln.from + 1 ? s : { ...s, line: ln.number, col: head - ln.from + 1 }));
        }),
      ],
    });
    const view = new EditorView({ state, parent: el });
    closers.set(view, () => closeRef.current());

    let cancelled = false;
    loadLanguage(lang).then(
      (ext) => {
        if (!cancelled) view.dispatch({ effects: language.reconfigure(ext) });
      },
      () => {}, // plain text when a language chunk fails to load
    );

    const cm = vimOn ? getCM(view) : null;
    if (cm) {
      cm.on("vim-mode-change", (e: { mode?: string; subMode?: string }) => setStatus((s) => ({ ...s, mode: modeLabel(e), pending: "" })));
      cm.on("vim-keypress", (key: string) => setStatus((s) => ({ ...s, pending: (s.pending + key).slice(-12) })));
      cm.on("vim-command-done", () => setStatus((s) => (s.pending ? { ...s, pending: "" } : s)));
    }

    // Esc belongs to vim: it closes the viewer only with vim off, or in
    // normal mode with nothing pending. Capture runs before vim's handler.
    const onEsc = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape") return;
      if (!vimOn) {
        ev.preventDefault();
        closeRef.current();
        return;
      }
      if (!(ev.target instanceof Node) || !view.contentDOM.contains(ev.target)) return; // the : or / prompt
      const v = getCM(view)?.state.vim;
      if (!v) return;
      const is = v.inputState;
      const pending =
        v.insertMode || v.visualMode || is.operator || is.motion || is.prefixRepeat.length || is.motionRepeat.length || is.keyBuffer.length || is.registerName;
      if (!pending) {
        ev.preventDefault();
        ev.stopPropagation();
        closeRef.current();
      }
    };
    view.dom.addEventListener("keydown", onEsc, true);

    if (cited) {
      const a = view.state.doc.line(cited[0]);
      const b = view.state.doc.line(cited[1]);
      view.dispatch({
        selection: { anchor: a.from },
        // Centered; when the range is taller than the window, its first line wins.
        effects: EditorView.scrollIntoView(EditorSelection.range(b.to, a.from), { y: "center" }),
      });
    }
    view.focus();

    return () => {
      cancelled = true;
      view.dom.removeEventListener("keydown", onEsc, true);
      closers.delete(view);
      view.destroy();
    };
  }, [content, lang, first, last, vimOn]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={host} className="min-h-0 flex-1 overflow-hidden" />
      <div
        data-testid="code-viewer-status"
        className="tnum flex h-6 shrink-0 items-center gap-3 border-t border-line bg-panel px-3 font-mono text-[11px] text-muted"
      >
        {vimOn && <span className={status.mode === "NORMAL" ? "text-accent" : "text-warn"}>{status.mode}</span>}{" "}
        {vimOn && status.pending && <span className="text-ink">{status.pending}</span>}{" "}
        <span className="ml-auto">
          {status.line}:{status.col}
        </span>
      </div>
    </div>
  );
}
