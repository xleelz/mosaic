"use client";

import { ApiError, FIXTURE_MODE } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { Badge } from "./ui";

export function ModeBadge() {
  const health = useQuery(FIXTURE_MODE ? null : "health", (c) => c.health());
  if (FIXTURE_MODE) {
    return (
      <Badge tone="warn" className="uppercase tracking-wider" title="Serving web/fixtures (NEXT_PUBLIC_MOSAIC_FIXTURES=1). Recorded runs only.">
        ◇ fixtures
      </Badge>
    );
  }
  if (health.loading) return <Badge>mosaicd …</Badge>;
  if (health.error instanceof ApiError && health.error.status === 401) {
    return (
      <Badge tone="bad" title="mosaicd answered 401. Set MOSAIC_TOKEN (mosaicd's --token) in the web server's environment and restart it.">
        ✗ mosaicd unauthorized
      </Badge>
    );
  }
  if (health.error) {
    return (
      <Badge tone="bad" title="GET /api/mosaic/v1/health failed. Is mosaicd running? Set MOSAIC_SERVER in the web server's environment.">
        ✗ mosaicd unreachable
      </Badge>
    );
  }
  return (
    <Badge tone="ok" title={`dolt ${health.data?.dolt ?? ""}`}>
      ● mosaicd {health.data?.version}
    </Badge>
  );
}
