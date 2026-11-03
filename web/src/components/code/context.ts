"use client";

// The code viewer's context: SourceRef (components/ui.tsx) opens a citation
// through it. Outside a CodeViewerProvider it is null and citations stay text.

import { createContext, useContext } from "react";
import type { Source } from "@/lib/api/types";

export type OpenSource = (source: Source, from?: HTMLElement | null) => void;

export const CodeViewerContext = createContext<OpenSource | null>(null);

/** Opens a citation in the code viewer; null outside a CodeViewerProvider. */
export function useOpenSource(): OpenSource | null {
  return useContext(CodeViewerContext);
}
