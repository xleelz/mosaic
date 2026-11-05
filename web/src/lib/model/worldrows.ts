// The rows of the World tab's configs list: search, then grouping by area.
// Pure, so `pnpm test` can run it.

import type { Config } from "../api/types";

export interface ConfigItem {
  config: Config;
  area: string;
  differs: boolean;
}

export type ConfigRow =
  | { type: "group"; key: string; area: string; count: number; differing: number; open: boolean }
  | { type: "config"; key: string; item: ConfigItem };

/** True when the config contains every word of the query, in any field a person would search. */
export function configMatches(c: Config, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const key = c.attributes?.key;
  const hay = [c.id, c.type ?? "", c.summary ?? "", c.description ?? "", typeof key === "string" ? key : "", ...(c.tags ?? []), ...(c.sources ?? []).map((s) => s.path)].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

export interface ConfigRowOptions {
  query: string;
  differsOnly: boolean;
  groupByArea: boolean;
  /** Open areas. A search opens every area, to show its matches. */
  open: ReadonlySet<string>;
  /** The area sorted last. */
  last?: string;
}

/** The rows to show, areas largest first. Also returns how many configs match. */
export function configRows(items: ConfigItem[], o: ConfigRowOptions): { rows: ConfigRow[]; matches: number; areas: string[] } {
  const shown = items.filter((it) => (!o.differsOnly || it.differs) && configMatches(it.config, o.query));
  if (!o.groupByArea) return { rows: shown.map((item) => ({ type: "config", key: item.config.id, item })), matches: shown.length, areas: [] };
  const groups = new Map<string, ConfigItem[]>();
  for (const it of shown) {
    const l = groups.get(it.area);
    if (l) l.push(it);
    else groups.set(it.area, [it]);
  }
  const areas = Array.from(groups.keys()).sort((a, b) => {
    if ((a === o.last) !== (b === o.last)) return a === o.last ? 1 : -1;
    return groups.get(b)!.length - groups.get(a)!.length || a.localeCompare(b);
  });
  const searching = o.query.trim().length > 0;
  const rows: ConfigRow[] = [];
  for (const area of areas) {
    const list = groups.get(area)!;
    const open = searching || o.open.has(area);
    rows.push({ type: "group", key: `area:${area}`, area, count: list.length, differing: list.filter((it) => it.differs).length, open });
    if (open) for (const item of list) rows.push({ type: "config", key: item.config.id, item });
  }
  return { rows, matches: shown.length, areas };
}
