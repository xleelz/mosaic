// Gzip for the proxy. `next start` compresses pages but not this route's
// responses, and a 15 MB document matters over an SSH tunnel. The body arrives
// here decoded whatever mosaicd sent (fetch decodes it), so this is the only
// compression the browser sees. The compression Next applies to pages leaves
// anything with a Content-Encoding alone, so it can't happen twice.

const MIN_BYTES = 1024;

/** JSON only: mosaicd's documents and traces. Anything streamed stays as it is. */
function compressible(contentType: string | null): boolean {
  const type = (contentType ?? "").split(";")[0].trim().toLowerCase();
  return type === "application/json" || type.endsWith("+json");
}

/** True when the client accepts gzip: "gzip" or "*", with a q above 0. */
export function acceptsGzip(acceptEncoding: string | null): boolean {
  if (!acceptEncoding) return false;
  let star = false;
  for (const part of acceptEncoding.toLowerCase().split(",")) {
    const [name, ...params] = part.split(";").map((p) => p.trim());
    const q = params.find((p) => p.startsWith("q="));
    const accepted = !q || Number(q.slice(2)) > 0;
    if (name === "gzip" || name === "x-gzip") return accepted;
    if (name === "*") star = accepted;
  }
  return star;
}

export function shouldGzip(r: { method: string; status: number; acceptEncoding: string | null; contentType: string | null; contentLength: string | null }): boolean {
  if (r.method === "HEAD" || r.status === 204 || r.status === 304) return false;
  if (!acceptsGzip(r.acceptEncoding) || !compressible(r.contentType)) return false;
  // Without a length (a chunked reply) it's probably a large one.
  return r.contentLength === null || Number(r.contentLength) >= MIN_BYTES;
}

/** The body gzipped, with the headers saying so. The caller has dropped Content-Length. */
export function gzipped(body: ReadableStream<Uint8Array<ArrayBuffer>>, headers: Headers): ReadableStream<Uint8Array<ArrayBuffer>> {
  headers.set("Content-Encoding", "gzip");
  headers.append("Vary", "Accept-Encoding");
  return body.pipeThrough(new CompressionStream("gzip"));
}
