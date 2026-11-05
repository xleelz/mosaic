"use client";

import { useMemo } from "react";
import type { EvidenceMechanism, SimulationRun } from "@/lib/api/types";
import { useEvidence, weakMechanismsOnRun } from "@/lib/evidence";

/**
 * The mechanisms a run passed through that the model doesn't fully do, worst first. Reads the
 * summary's call counts, so it works on a run listed without its trace. Empty when no evidence
 * is stored or it can't be read: the warning is silent then, and "Not benchmarked" is said elsewhere.
 */
export function useRunMechanisms(run: SimulationRun): EvidenceMechanism[] {
  const { evidence } = useEvidence(run.ontology, run.revision || "draft");
  const calls = run.summary.calls;
  return useMemo(() => {
    const items = evidence?.mechanisms?.items;
    if (!items?.length) return [];
    const called = Object.entries(calls ?? {}).filter(([, n]) => n > 0).map(([i]) => i);
    return weakMechanismsOnRun(items, called);
  }, [evidence, calls]);
}
