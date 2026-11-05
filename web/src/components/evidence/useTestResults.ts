"use client";

import { ApiError } from "@/lib/api/client";
import type { StoredTestReport } from "@/lib/api/types";
import { useQuery, type QueryState } from "@/lib/hooks";
import { useWorkspace } from "@/components/workspace/Workspace";

/** The last recorded test report at the viewed revision. null: answered, and it's never been run. */
export function useTestResults(): QueryState<StoredTestReport | null> {
  const { id, rev, dataRev } = useWorkspace();
  return useQuery<StoredTestReport | null>(`test-results:${id}:${dataRev}`, async (c) => {
    try {
      return await c.getTestResults(id, rev);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
}
