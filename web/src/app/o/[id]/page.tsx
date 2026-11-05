import { OverviewRoute } from "@/components/overview/Overview";

// Renders client-side from live mosaicd data, so there's no static shell to validate:
// opt out of instant-navigation validation (enabled app-wide by partialPrefetching).
export const instant = false;

export default function OverviewPage() {
  return <OverviewRoute />;
}
