import { Suspense } from "react";
import { ComposeRoute } from "@/components/compose/ComposeRoute";
import { Spinner } from "@/components/ui";

export default function ComposeTreeRoutePage() {
  return (
    <Suspense fallback={<Spinner label="Loading the run tree" />}>
      <ComposeRoute />
    </Suspense>
  );
}
