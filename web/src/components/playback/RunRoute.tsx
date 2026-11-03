"use client";

import { useParams, useSearchParams } from "next/navigation";
import { RunPage } from "./RunView";

export function RunRoute() {
  const params = useParams<{ id: string; runId: string }>();
  const search = useSearchParams();
  const at = search.get("at");
  return <RunPage ontology={decodeURIComponent(params.id)} runId={decodeURIComponent(params.runId)} at={at ? Number(at) || undefined : undefined} />;
}
