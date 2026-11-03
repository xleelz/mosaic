"use client";

import { useParams } from "next/navigation";
import { ComposeTreePage } from "./ComposeRuns";

export function ComposeRoute() {
  const params = useParams<{ task: string }>();
  return <ComposeTreePage task={decodeURIComponent(params.task)} />;
}
