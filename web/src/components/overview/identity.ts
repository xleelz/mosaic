// A model's name can go stale: "Thing 0.32 (round 4)" while its latest revision says round 6.
// The name alone must not assert a round or revision the latest revision contradicts.

export interface ModelIdentity {
  /** What to show as the name. */
  title: string;
  /** Set when the stored name carries a marker the latest revision contradicts. */
  staleNote?: string;
}

const MARKER = /\s*[([]?\b(round|rev|revision)[ #]*(\d+)\b[)\]]?/i;

export function modelIdentity(name: string | undefined, id: string, latestTitle: string | undefined): ModelIdentity {
  const shown = name || id;
  const inName = MARKER.exec(shown);
  const inTitle = latestTitle ? MARKER.exec(latestTitle) : null;
  if (!inName || !inTitle || inName[1].toLowerCase() !== inTitle[1].toLowerCase() || inName[2] === inTitle[2]) return { title: shown };
  const title = shown.replace(MARKER, "").replace(/\s+/g, " ").trim() || shown;
  return { title, staleNote: `Its stored name says "${inName[0].trim()}", but the latest revision says "${inTitle[0].trim()}".` };
}

/** The newest revision of a list. */
export function latestOf<T extends { number: number }>(revisions: readonly T[] | undefined): T | undefined {
  let best: T | undefined;
  for (const r of revisions ?? []) if (!best || r.number > best.number) best = r;
  return best;
}
