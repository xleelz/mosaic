// Serves web/fixtures to the fixture client. Only enabled in fixture mode.

import { readFile } from "node:fs/promises";
import path from "node:path";

const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export async function GET(_req: Request, ctx: RouteContext<"/fixture-data/[...path]">) {
  if (process.env.NEXT_PUBLIC_MOSAIC_FIXTURES !== "1") {
    return Response.json({ error: { code: "not_found", message: "fixture mode is off" } }, { status: 404 });
  }
  const { path: segments } = await ctx.params;
  if (!segments.length || !segments.every((s) => SEGMENT.test(s) && !s.includes("..")) || !segments.at(-1)!.endsWith(".json")) {
    return Response.json({ error: { code: "bad_request", message: "invalid fixture path" } }, { status: 400 });
  }
  const file = path.join(process.cwd(), "fixtures", ...segments);
  try {
    const body = await readFile(file, "utf8");
    return new Response(body, { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: { code: "not_found", message: `no fixture ${segments.join("/")}` } }, { status: 404 });
  }
}
