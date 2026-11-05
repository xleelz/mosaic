// Run with `pnpm test` (node --test, with Node's built-in type stripping).

import assert from "node:assert/strict";
import { test } from "node:test";
import { gunzipSync } from "node:zlib";
import { acceptsGzip, gzipped, shouldGzip } from "./compress.ts";

test("acceptsGzip reads Accept-Encoding as a browser or curl sends it", () => {
  for (const v of ["gzip", "gzip, deflate, br, zstd", "br;q=1.0, gzip;q=0.8", "*", "GZIP", "x-gzip"]) assert.ok(acceptsGzip(v), v);
  for (const v of [null, "", "br", "identity", "gzip;q=0", "*;q=0", "gzip;q=0, *"]) assert.ok(!acceptsGzip(v), String(v));
});

const big = { method: "GET", status: 200, acceptEncoding: "gzip", contentType: "application/json", contentLength: "15000000" };

test("large JSON is compressed", () => {
  assert.ok(shouldGzip(big));
  assert.ok(shouldGzip({ ...big, contentType: "application/json; charset=utf-8" }));
  assert.ok(shouldGzip({ ...big, contentType: "application/problem+json" }));
  assert.ok(shouldGzip({ ...big, contentLength: null }), "a chunked reply has no length");
  assert.ok(shouldGzip({ ...big, status: 404 }), "an error body is JSON too");
  assert.ok(shouldGzip({ ...big, method: "POST" }));
});

test("the rest passes through", () => {
  assert.ok(!shouldGzip({ ...big, acceptEncoding: null }));
  assert.ok(!shouldGzip({ ...big, contentLength: "1023" }));
  assert.ok(!shouldGzip({ ...big, method: "HEAD" }));
  assert.ok(!shouldGzip({ ...big, status: 204 }));
  assert.ok(!shouldGzip({ ...big, status: 304 }));
  for (const t of ["text/event-stream", "application/x-ndjson", "text/plain", "application/octet-stream", null]) assert.ok(!shouldGzip({ ...big, contentType: t }), String(t));
});

test("the body comes out gzipped, with the headers saying so", async () => {
  const text = JSON.stringify({ a: "x".repeat(10000) });
  const headers = new Headers({ Vary: "rsc" });
  const out = gzipped(new Blob([text]).stream(), headers);
  const bytes = Buffer.from(await new Response(out).arrayBuffer());
  assert.ok(bytes.length < text.length / 10);
  assert.equal(gunzipSync(bytes).toString(), text);
  assert.equal(headers.get("Content-Encoding"), "gzip");
  assert.equal(headers.get("Vary"), "rsc, Accept-Encoding");
});
