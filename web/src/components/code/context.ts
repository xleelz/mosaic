"use client";

// The code viewer's context: SourceRef (components/ui.tsx) opens a citation
// through it. Outside a CodeViewerProvider it is null and citations stay text.

import { createContext, createElement, useContext, useMemo, type ReactNode } from "react";
import type { Source } from "@/lib/api/types";

export interface OpenSourceOptions {
  /** What the citation backs up, in words: "Scheduler decides each step's batch". The viewer shows it as its header. */
  claim?: string;
}

export type OpenSource = (source: Source, from?: HTMLElement | null, options?: OpenSourceOptions) => void;

export const CodeViewerContext = createContext<OpenSource | null>(null);

/** Opens a citation in the code viewer; null outside a CodeViewerProvider. */
export function useOpenSource(): OpenSource | null {
  return useContext(CodeViewerContext);
}

/**
 * Gives the citations inside it a claim, for the viewer's header:
 *
 *   <ClaimScope claim={component.summary || component.name}>
 *     <SourceRef source={s} />
 *   </ClaimScope>
 *
 * SourceRef needs no change. A caller opening the viewer itself can pass
 * `{ claim }` as the third argument instead.
 */
export function ClaimScope({ claim, children }: { claim: string | undefined; children: ReactNode }) {
  const open = useOpenSource();
  const value = useMemo<OpenSource | null>(() => (open ? (source, from, options) => open(source, from, { claim, ...options }) : null), [open, claim]);
  return createElement(CodeViewerContext.Provider, { value }, children);
}
