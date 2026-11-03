// Pure helpers for the code viewer (src/components/code): the language of a
// path, the GitHub blob link of a cited range, and the window's title. Kept
// free of CodeMirror so `pnpm test` can run them and pages don't load it.

/** A language the viewer can color; "plain" when none matches. */
export type LangKey =
  | "go"
  | "python"
  | "cpp"
  | "cuda"
  | "javascript"
  | "typescript"
  | "jsx"
  | "tsx"
  | "rust"
  | "java"
  | "yaml"
  | "json"
  | "markdown"
  | "sql"
  | "shell"
  | "hcl"
  | "protobuf"
  | "dockerfile"
  | "toml"
  | "plain";

const BY_EXT: Record<string, LangKey> = {
  go: "go",
  py: "python",
  pyi: "python",
  pyx: "python",
  c: "cpp",
  h: "cpp",
  cc: "cpp",
  cpp: "cpp",
  cxx: "cpp",
  "c++": "cpp",
  hh: "cpp",
  hpp: "cpp",
  hxx: "cpp",
  inl: "cpp",
  ipp: "cpp",
  cu: "cuda",
  cuh: "cuda",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  jsx: "jsx",
  ts: "typescript",
  mts: "typescript",
  cts: "typescript",
  tsx: "tsx",
  rs: "rust",
  java: "java",
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  jsonc: "json",
  md: "markdown",
  markdown: "markdown",
  sql: "sql",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  ksh: "shell",
  hcl: "hcl",
  tf: "hcl",
  tfvars: "hcl",
  nomad: "hcl",
  proto: "protobuf",
  dockerfile: "dockerfile",
  toml: "toml",
};

/** Hints the server may send (language_hint) that name a key directly. */
const HINTS = new Set<string>(Object.values(BY_EXT));

/**
 * The language of a path, by its extension or file name; the server's
 * language_hint is the fallback when the path says nothing.
 */
export function languageOf(path: string, hint?: string): LangKey {
  const base = (path.split("/").pop() ?? "").toLowerCase();
  if (base === "dockerfile" || base.startsWith("dockerfile.") || base.endsWith(".dockerfile") || base === "containerfile") return "dockerfile";
  if (base === ".bashrc" || base === ".profile" || base === ".zshrc") return "shell";
  if (base === "build" || base === "workspace" || base.endsWith(".bzl") || base.endsWith(".bazel")) return "python";
  const dot = base.lastIndexOf(".");
  if (dot >= 0) {
    const lang = BY_EXT[base.slice(dot + 1)];
    if (lang) return lang;
  }
  const h = (hint ?? "").toLowerCase();
  if (h === "c" || h === "c++") return "cpp";
  if (h === "bash" || h === "sh") return "shell";
  if (h === "terraform") return "hcl";
  if (HINTS.has(h)) return h as LangKey;
  return "plain";
}

/** The cited lines as GitHub's anchor: "#L10-L20", "#L10" or "". */
export function lineAnchor(line?: number, end?: number): string {
  if (!line) return "";
  return end && end > line ? `#L${line}-L${end}` : `#L${line}`;
}

/** The github.com blob URL of the cited range. */
export function blobUrl(url: string, line?: number, end?: number): string {
  if (!url) return "";
  return url.replace(/#.*$/, "") + lineAnchor(line, end);
}

/** ":10-20", ":10" or "". */
export function rangeSuffix(line?: number, end?: number): string {
  if (!line) return "";
  return end && end > line ? `:${line}-${end}` : `:${line}`;
}

/** The viewer's title: "repo@shortsha path:L-L". */
export function viewerTitle(f: { repo?: string; sha?: string; path: string; line?: number; end_line?: number }): string {
  const at = f.repo ? `${f.repo}${f.sha ? `@${f.sha.slice(0, 7)}` : ""} ` : "";
  return `${at}${f.path}${rangeSuffix(f.line, f.end_line)}`;
}

/** The cited range clamped to the file: [first, last], 1-based; null without a line. */
export function citedRange(lines: number, line?: number, end?: number): [number, number] | null {
  if (!line || lines < 1) return null;
  const first = Math.min(Math.max(1, line), lines);
  const last = Math.min(Math.max(first, end ?? first), lines);
  return [first, last];
}
