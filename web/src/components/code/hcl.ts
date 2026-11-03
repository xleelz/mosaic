// A small stream mode for HCL / Terraform: comments, strings with ${...}
// interpolation, heredocs, numbers, block types, attributes and keywords.
// @codemirror/legacy-modes has none.

import type { StreamParser } from "@codemirror/language";

interface HclState {
  /** Inside "..." (depth of ${ } nesting is tracked by `interp`). */
  inString: boolean;
  interp: number;
  heredoc: string | null;
  inComment: boolean;
  lineStart: boolean;
}

const KEYWORDS = new Set(["for", "in", "if", "else", "endif", "endfor", "for_each", "count", "depends_on", "dynamic", "lifecycle"]);
const ATOMS = new Set(["true", "false", "null"]);
const BLOCKS = new Set(["resource", "data", "variable", "output", "locals", "module", "provider", "terraform", "backend", "required_providers", "moved", "import", "check"]);

export const hcl: StreamParser<HclState> = {
  name: "hcl",
  startState: () => ({ inString: false, interp: 0, heredoc: null, inComment: false, lineStart: true }),
  token(stream, state) {
    if (stream.sol()) state.lineStart = true;
    if (state.heredoc !== null) {
      if (stream.sol() && stream.match(new RegExp(`^\\s*${state.heredoc}\\s*$`))) {
        state.heredoc = null;
        return "string";
      }
      stream.skipToEnd();
      return "string";
    }
    if (state.inComment) {
      if (stream.skipTo("*/")) {
        stream.next();
        stream.next();
        state.inComment = false;
      } else stream.skipToEnd();
      return "comment";
    }
    if (state.inString && state.interp === 0) {
      while (!stream.eol()) {
        if (stream.match("${", false)) {
          if (stream.current()) return "string";
          stream.match("${");
          state.interp = 1;
          return "meta";
        }
        const ch = stream.next();
        if (ch === "\\") stream.next();
        else if (ch === '"') {
          state.inString = false;
          break;
        }
      }
      return "string";
    }
    if (stream.eatSpace()) return null;
    const first = state.lineStart;
    state.lineStart = false;
    if (stream.match("#") || stream.match("//")) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.match("/*")) {
      state.inComment = true;
      return "comment";
    }
    const here = stream.match(/^<<-?([A-Za-z_]+)/) as RegExpMatchArray | null;
    if (here) {
      state.heredoc = here[1];
      return "string";
    }
    if (stream.peek() === '"') {
      stream.next();
      state.inString = true;
      return "string";
    }
    if (state.interp > 0) {
      if (stream.peek() === "{") state.interp++;
      if (stream.peek() === "}") {
        state.interp--;
        stream.next();
        return state.interp === 0 ? "meta" : null;
      }
    }
    if (stream.match(/^-?\d+(\.\d+)?([eE][+-]?\d+)?/)) return "number";
    const word = stream.match(/^[A-Za-z_][\w-]*/) as RegExpMatchArray | null;
    if (word) {
      const w = word[0];
      if (ATOMS.has(w)) return "atom";
      if (KEYWORDS.has(w)) return "keyword";
      if (first && BLOCKS.has(w)) return "keyword";
      if (stream.match(/^\s*=(?!=)/, false)) return "propertyName";
      if (stream.match(/^\s*\(/, false)) return "variableName.function";
      if (first) return "typeName";
      return "variableName";
    }
    stream.next();
    return /[=!<>+\-*/%&|?:]/.test(stream.current()) ? "operator" : null;
  },
  languageData: { commentTokens: { line: "#", block: { open: "/*", close: "*/" } } },
};
