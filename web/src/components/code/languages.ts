// CodeMirror language support per LangKey (lib/source.ts), each loaded on
// demand so a Go file doesn't pull in the C++ parser.

import type { StreamParser } from "@codemirror/language";
import type { Extension } from "@codemirror/state";
import type { LangKey } from "@/lib/source";

async function legacy(load: () => Promise<StreamParser<unknown>>): Promise<Extension> {
  const [{ StreamLanguage }, parser] = await Promise.all([import("@codemirror/language"), load()]);
  return StreamLanguage.define(parser);
}

const LOADERS: Record<Exclude<LangKey, "plain">, () => Promise<Extension>> = {
  go: async () => (await import("@codemirror/lang-go")).go(),
  python: async () => (await import("@codemirror/lang-python")).python(),
  cpp: async () => (await import("@codemirror/lang-cpp")).cpp(),
  cuda: async () => (await import("@codemirror/lang-cpp")).cpp(),
  javascript: async () => (await import("@codemirror/lang-javascript")).javascript(),
  jsx: async () => (await import("@codemirror/lang-javascript")).javascript({ jsx: true }),
  typescript: async () => (await import("@codemirror/lang-javascript")).javascript({ typescript: true }),
  tsx: async () => (await import("@codemirror/lang-javascript")).javascript({ jsx: true, typescript: true }),
  rust: async () => (await import("@codemirror/lang-rust")).rust(),
  java: async () => (await import("@codemirror/lang-java")).java(),
  yaml: async () => (await import("@codemirror/lang-yaml")).yaml(),
  json: async () => (await import("@codemirror/lang-json")).json(),
  markdown: async () => (await import("@codemirror/lang-markdown")).markdown(),
  sql: async () => (await import("@codemirror/lang-sql")).sql(),
  shell: () => legacy(async () => (await import("@codemirror/legacy-modes/mode/shell")).shell),
  protobuf: () => legacy(async () => (await import("@codemirror/legacy-modes/mode/protobuf")).protobuf),
  dockerfile: () => legacy(async () => (await import("@codemirror/legacy-modes/mode/dockerfile")).dockerFile),
  toml: () => legacy(async () => (await import("@codemirror/legacy-modes/mode/toml")).toml),
  hcl: () => legacy(async () => (await import("./hcl")).hcl as StreamParser<unknown>),
};

/** The language extension for key; an empty extension for plain text. */
export async function loadLanguage(key: LangKey): Promise<Extension> {
  if (key === "plain") return [];
  return LOADERS[key]();
}
