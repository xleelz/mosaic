import { Suspense } from "react";
import { WorkspaceShell } from "@/components/workspace/Workspace";
import { WorkspaceSkeleton } from "@/components/overview/Skeletons";

export default function OntologyLayout({ children }: LayoutProps<"/o/[id]">) {
  return (
    <Suspense fallback={<WorkspaceSkeleton />}>
      <WorkspaceShell>{children}</WorkspaceShell>
    </Suspense>
  );
}
