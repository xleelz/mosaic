"use client";

// Loading frames: the page's shape, so a large document's load doesn't look like an empty page.

import { cx } from "@/components/ui";

export function SkeletonBlock({ className }: { className?: string }) {
  return <div aria-hidden className={cx("animate-pulse rounded bg-panel-2", className)} />;
}

function Status({ label }: { label: string }) {
  return (
    <span role="status" className="sr-only">
      {label}…
    </span>
  );
}

/** The map's frame: a toolbar, a list on the left and a canvas of a few boxes. */
export function MapSkeleton({ label = "Loading the map" }: { label?: string }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Status label={label} />
      <div className="flex shrink-0 items-center gap-2 border-b border-line-soft px-4 py-2">
        <SkeletonBlock className="h-7 w-28" />
        <SkeletonBlock className="h-7 w-40" />
        <SkeletonBlock className="ml-auto h-5 w-48" />
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="w-[250px] shrink-0 space-y-2 border-r border-line p-2">
          <SkeletonBlock className="h-7 w-full" />
          {Array.from({ length: 9 }, (_, i) => (
            <SkeletonBlock key={i} className="h-4 w-4/5" />
          ))}
        </div>
        <div className="grid flex-1 grid-cols-3 content-center gap-8 p-10">
          {Array.from({ length: 6 }, (_, i) => (
            <SkeletonBlock key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  );
}

/** Overview's sections. */
export function OverviewSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1280px] space-y-4 p-4">
      <Status label="Loading the overview" />
      <SkeletonBlock className="h-4 w-2/3" />
      <SkeletonBlock className="h-4 w-1/2" />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="space-y-2 rounded-lg border border-line p-3">
            <SkeletonBlock className="h-3 w-24" />
            <SkeletonBlock className="h-4 w-full" />
            <SkeletonBlock className="h-4 w-5/6" />
            <SkeletonBlock className="h-4 w-3/4" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** The whole workspace before its frame can render. */
export function WorkspaceSkeleton() {
  return (
    <div className="flex h-[calc(100dvh-2.75rem)] min-h-[560px] flex-col">
      <div className="shrink-0 space-y-2 border-b border-line bg-panel/60 px-4 pb-2 pt-3">
        <SkeletonBlock className="h-5 w-72" />
        <SkeletonBlock className="h-5 w-96 max-w-full" />
      </div>
      <div className="min-h-0 flex-1">
        <OverviewSkeleton />
      </div>
    </div>
  );
}

/** Home's card grid. */
export function HomeSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <Status label="Loading models" />
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="space-y-3 rounded-lg border border-line bg-panel p-4">
          <SkeletonBlock className="h-4 w-1/2" />
          <SkeletonBlock className="h-6 w-3/4" />
          <SkeletonBlock className="h-10 w-full" />
          <SkeletonBlock className="h-14 w-full" />
        </div>
      ))}
    </div>
  );
}
