// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { blobUrl, citedRange, languageOf, viewerTitle } from "./source.ts";

test("languageOf picks the language by extension or file name", () => {
  const cases: [string, string][] = [
    ["pkg/server/main.go", "go"],
    ["vllm/engine/llm_engine.py", "python"],
    ["source/common/http/conn_manager_impl.cc", "cpp"],
    ["source/common/http/conn_manager_impl.h", "cpp"],
    ["csrc/attention/attention_kernels.cu", "cuda"],
    ["csrc/ops.cuh", "cuda"],
    ["web/src/app/page.tsx", "tsx"],
    ["web/src/lib/a.ts", "typescript"],
    ["x/index.mjs", "javascript"],
    ["src/lib.rs", "rust"],
    ["A.java", "java"],
    ["deploy/values.yml", "yaml"],
    ["package.json", "json"],
    ["README.md", "markdown"],
    ["schema.sql", "sql"],
    ["scripts/serve.sh", "shell"],
    ["infra/main.tf", "hcl"],
    ["api/envoy/config/v3/route.proto", "protobuf"],
    ["docker/Dockerfile", "dockerfile"],
    ["ci/Dockerfile.cuda", "dockerfile"],
    ["LICENSE", "plain"],
  ];
  for (const [path, want] of cases) assert.equal(languageOf(path), want, path);
});

test("languageOf falls back to the server's hint", () => {
  assert.equal(languageOf("bin/run", "shell"), "shell");
  assert.equal(languageOf("bin/run", "c++"), "cpp");
  assert.equal(languageOf("bin/run", "klingon"), "plain");
  assert.equal(languageOf("a.go", "python"), "go");
});

test("blobUrl adds the cited range as GitHub's anchor", () => {
  const u = "https://github.com/envoyproxy/envoy/blob/dc2d309/source/a.cc";
  assert.equal(blobUrl(u, 10, 20), `${u}#L10-L20`);
  assert.equal(blobUrl(u, 10), `${u}#L10`);
  assert.equal(blobUrl(u, 10, 10), `${u}#L10`);
  assert.equal(blobUrl(u), u);
  assert.equal(blobUrl(`${u}#L1`, 3), `${u}#L3`);
});

test("viewerTitle shows repo@shortsha path:range", () => {
  assert.equal(
    viewerTitle({ repo: "vllm-project/vllm", sha: "5df63a7deadbeef", path: "vllm/config.py", line: 10, end_line: 20 }),
    "vllm-project/vllm@5df63a7 vllm/config.py:10-20",
  );
  assert.equal(viewerTitle({ path: "a.go", line: 3 }), "a.go:3");
});

test("citedRange clamps to the file", () => {
  assert.deepEqual(citedRange(100, 10, 20), [10, 20]);
  assert.deepEqual(citedRange(100, 10), [10, 10]);
  assert.deepEqual(citedRange(15, 10, 20), [10, 15]);
  assert.deepEqual(citedRange(5, 10, 20), [5, 5]);
  assert.equal(citedRange(100), null);
});
