import { Suspense } from "react";
import { WorkspaceShell } from "@/components/workspace/Workspace";
import { Spinner } from "@/components/ui";

export default function OntologyLayout({ children }: LayoutProps<"/o/[id]">) {
  return (
    <Suspense fallback={<Spinner label="Loading workspace" />}>
      <WorkspaceShell>{children}</WorkspaceShell>
    </Suspense>
  );
}
