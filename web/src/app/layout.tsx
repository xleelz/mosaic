import type { Metadata } from "next";
import Link from "next/link";
import { ModeBadge } from "@/components/ModeBadge";
import { UpdateChip } from "@/components/UpdateChip";
import "./globals.css";

export const metadata: Metadata = {
  title: "mosaic",
  description: "Browse software ontologies and watch simulated flows through their components.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only z-50 rounded bg-accent px-3 py-1 text-accent-ink focus:not-sr-only focus:absolute focus:left-3 focus:top-2"
        >
          Skip to content
        </a>
        <header className="app-topbar sticky top-0 z-40 flex h-11 shrink-0 items-center justify-between border-b border-line bg-bg/95 px-4 backdrop-blur">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 rounded text-[15px] font-bold tracking-tight text-ink">
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
                <rect x="1" y="1" width="7" height="7" rx="1.5" fill="#ccff78" />
                <rect x="10" y="1" width="7" height="7" rx="1.5" fill="#3987e5" />
                <rect x="1" y="10" width="7" height="7" rx="1.5" fill="#199e70" />
                <rect x="10" y="10" width="7" height="7" rx="1.5" fill="#2a3742" />
              </svg>
              mosaic
            </Link>
            <span className="text-faint">/</span>
            <span className="text-[12px] text-muted">ontology explorer &amp; simulator</span>
            <nav aria-label="Site" className="ml-3 flex items-center gap-3 text-[12px]">
              <Link href="/" className="text-muted hover:text-ink">
                Ontologies
              </Link>
              <Link href="/compose" className="text-muted hover:text-ink">
                Compose runs
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <UpdateChip />
            <ModeBadge />
          </div>
        </header>
        <main id="main" className="flex min-h-0 flex-1 flex-col">
          {children}
        </main>
      </body>
    </html>
  );
}
