"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * A modal on the native <dialog>: top layer, background inert, focus trapped and restored, Esc
 * closes. Keys stop here so the page beneath (the run page's Space and arrows) never sees them.
 */
export function Modal({ label, onClose, className, children }: { label: string; onClose: () => void; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => d?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={label}
      className={className}
      onClose={(e) => {
        // Strict Mode re-runs the effect, whose close() event then arrives with the dialog open again.
        if (!e.currentTarget.open) onClose();
      }}
      onKeyDown={(e) => e.stopPropagation()}
      onMouseDown={(e) => {
        // A press on the dialog element itself is on its backdrop.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {children}
    </dialog>
  );
}
