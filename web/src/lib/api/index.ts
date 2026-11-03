// Picks the data source: fixtures when NEXT_PUBLIC_MOSAIC_FIXTURES=1, else mosaicd
// through the /api/mosaic proxy route (which adds the token server-side).

import type { MosaicClient } from "./client";
import { FixtureClient } from "./fixtures";
import { HttpClient } from "./http";

export * from "./client";
export type * from "./types";

export const FIXTURE_MODE = process.env.NEXT_PUBLIC_MOSAIC_FIXTURES === "1";

let client: MosaicClient | null = null;

export function getClient(): MosaicClient {
  if (!client) {
    client = FIXTURE_MODE
      ? new FixtureClient()
      : new HttpClient("/api/mosaic/v1");
  }
  return client;
}
