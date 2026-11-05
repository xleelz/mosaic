// Every key in the app, and the global shortcut decision. Only data and pure functions:
// node --test runs this file with type stripping.

export interface ShortcutRow {
  keys: string[];
  does: string;
}

export interface ShortcutGroup {
  title: string;
  rows: ShortcutRow[];
}

export const SHORTCUTS: ShortcutGroup[] = [
  {
    title: "Anywhere",
    rows: [
      { keys: ["?"], does: "This sheet" },
      { keys: ["Esc"], does: "Close a dialog, panel or the code viewer" },
    ],
  },
  {
    title: "Inside a model",
    rows: [
      { keys: ["/"], does: "Search everything" },
      { keys: ["⌘K", "Ctrl K"], does: "Search everything, even while typing" },
    ],
  },
  {
    title: "In search",
    rows: [
      { keys: ["↑", "↓"], does: "Move through results" },
      { keys: ["PgUp", "PgDn"], does: "Move a page of results" },
      { keys: ["Enter"], does: "Open the result" },
    ],
  },
  {
    title: "On a run",
    rows: [
      { keys: ["Space"], does: "Play or pause" },
      { keys: ["←", "→"], does: "Step back or forward" },
      { keys: ["Shift ←", "Shift →"], does: "Step 10 events" },
      { keys: ["Home", "End"], does: "Go to the first or last event" },
      { keys: ["f"], does: "Jump to the first fault" },
      { keys: ["e"], does: "Jump to the first error" },
      { keys: ["n"], does: "Jump to the next state change" },
      { keys: ["s"], does: "Cycle the run's view" },
      { keys: ["i"], does: "Cycle the inspector panel" },
      { keys: ["m"], does: "Cycle the map panel" },
    ],
  },
  {
    title: "In the code viewer",
    rows: [
      { keys: ["Vim keys"], does: "Move around the file" },
      { keys: ["Esc"], does: "Close the viewer" },
    ],
  },
];

export interface KeyLike {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}

export type GlobalAction = "palette" | "sheet" | null;

/** What a keydown means globally. `typing`: the focus is in a text field or the code viewer. */
export function globalAction(ev: KeyLike, typing: boolean): GlobalAction {
  if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && ev.key.toLowerCase() === "k") return "palette";
  if (typing || ev.metaKey || ev.ctrlKey || ev.altKey) return null;
  if (ev.key === "/") return "palette";
  if (ev.key === "?") return "sheet";
  return null;
}
