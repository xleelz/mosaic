// Server-side proxy: /api/mosaic/<path> -> ${MOSAIC_SERVER}/<path>.
//
// Both MOSAIC_SERVER and MOSAIC_TOKEN are read from the server's environment
// on every request, so `pnpm start` picks them up at run time and neither is
// ever compiled into the client bundle. The browser never sees the token: the
// proxy adds `Authorization: Bearer ${MOSAIC_TOKEN}` itself and drops any
// Authorization or Cookie header the browser sent. Status codes, error bodies
// and response bodies are passed through unchanged (streamed), except that JSON
// is gzipped for a browser that accepts it (compress.ts), and a 404 is a 204 for a
// request marked X-Mosaic-Absent-Ok, where nothing stored is a normal answer.

import { gzipped, shouldGzip } from "./compress";

const DEFAULT_SERVER = "http://127.0.0.1:7878";

// Hop-by-hop headers (RFC 9110 §7.6.1) plus headers the proxy owns.
const DROP_REQUEST = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
  "authorization",
  "cookie",
  "accept-encoding",
  "x-mosaic-absent-ok",
]);

// fetch() has already decoded the body, so the length and encoding no longer apply.
const DROP_RESPONSE = new Set([
  "connection",
  "keep-alive",
  "proxy-connection",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "content-encoding",
  "content-length",
  "set-cookie",
]);

function upstreamBase(): string {
  return (process.env.MOSAIC_SERVER || DEFAULT_SERVER).replace(/\/+$/, "");
}

async function proxy(req: Request, ctx: RouteContext<"/api/mosaic/[...path]">): Promise<Response> {
  const { path: segments } = await ctx.params;
  const base = upstreamBase();
  const incoming = new URL(req.url);
  const target = `${base}/${segments.map(encodeURIComponent).join("/")}${incoming.search}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!DROP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  const token = process.env.MOSAIC_TOKEN;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const hasBody = req.method !== "GET" && req.method !== "HEAD" && req.body !== null;
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // Required by Node's fetch to send a streamed request body.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
      signal: req.signal,
    } as RequestInit);
  } catch (err) {
    const reason = err instanceof Error ? (err.cause instanceof Error ? err.cause.message : err.message) : String(err);
    return Response.json(
      { error: { code: "unreachable", message: `mosaicd at ${base} is unreachable: ${reason}` } },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (upstream.status === 404 && req.headers.has("x-mosaic-absent-ok")) {
    return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!DROP_RESPONSE.has(key.toLowerCase())) out.set(key, value);
  });
  out.set("Cache-Control", "no-store");
  let body = req.method === "HEAD" ? null : upstream.body;
  // A compressed upstream reply's length is the compressed one, so it isn't used.
  const compress = shouldGzip({
    method: req.method,
    status: upstream.status,
    acceptEncoding: req.headers.get("accept-encoding"),
    contentType: upstream.headers.get("content-type"),
    contentLength: upstream.headers.has("content-encoding") ? null : upstream.headers.get("content-length"),
  });
  if (body && compress) body = gzipped(body, out);
  return new Response(body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
