"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Document, Graph, SimulationRun } from "@/lib/api/types";
import { buildPlayback, activeFor, eventTone, laneComponent, openSpans } from "@/lib/sim/playback";
import { ArchitectureMap, COLLAPSE_ABOVE, useColorScale, type MapHighlight } from "@/components/map/ArchitectureMap";
import { runGraph } from "@/lib/model/rungraph";
import { Panel, cx } from "@/components/ui";
import { Inspector } from "./Inspector";
import { SequenceDiagram } from "./SequenceDiagram";
import { StateLedger } from "./StateLedger";
import { SummaryCard } from "./SummaryCard";
import { Transport } from "./Transport";

// Dwell time per event type at 1×, so playback lingers on what matters.
const DWELL: Record<string, number> = {
  "call.start": 320,
  "call.end": 260,
  note: 520,
  set: 110,
  choice: 380,
  fault: 650,
  retry: 650,
  timeout: 700,
  emit: 380,
  warning: 500,
  queue: 450,
  publish: 420,
  "parallel.start": 420,
  "parallel.end": 520,
  "step.start": 600,
  "step.end": 420,
  deadline: 650,
  yield: 380,
  put: 380,
  receive: 380,
  kill: 700,
};

function isTyping(el: EventTarget | null, key: string): boolean {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (el as HTMLInputElement).type;
    // The scrubber handles its own arrows; text inputs take every key.
    return type !== "checkbox" && type !== "radio" ? true : key !== " ";
  }
  // Space on a focused button or link activates it; don't double-handle.
  if (key === " " && (tag === "BUTTON" || tag === "A" || el.getAttribute("role") === "button")) return true;
  return false;
}

export function Playback({
  run,
  doc,
  graph,
  initialCursor,
  onCursorChange,
  className,
}: {
  run: SimulationRun;
  doc?: Document;
  graph?: Graph;
  initialCursor?: number;
  onCursorChange?: (seq: number) => void;
  className?: string;
}) {
  const playback = useMemo(() => buildPlayback(run), [run]);
  const n = playback.events.length;
  const [cursor, setCursorRaw] = useState(() => Math.min(Math.max(0, initialCursor ?? 0), Math.max(0, n - 1)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [mapOpen, setMapOpen] = useState(true);
  const colorScale = useColorScale(graph, "layer");

  const setCursor = useCallback(
    (i: number) => {
      const c = Math.min(Math.max(0, i), Math.max(0, n - 1));
      setCursorRaw(c);
      onCursorChange?.(playback.events[c]?.seq ?? 0);
    },
    [n, onCursorChange, playback],
  );

  // Playback clock.
  useEffect(() => {
    if (!playing || cursor >= n - 1) return;
    const e = playback.events[cursor];
    const t = window.setTimeout(() => {
      setCursor(cursor + 1);
      if (cursor + 1 >= n - 1) setPlaying(false);
    }, (DWELL[e?.type ?? ""] ?? 300) / speed);
    return () => window.clearTimeout(t);
  }, [playing, cursor, n, speed, playback, setCursor]);

  // Keyboard: Space play/pause, ←/→ step (Shift: 10), Home/End.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      if (isTyping(ev.target, ev.key)) return;
      if (ev.key === " ") {
        ev.preventDefault();
        if (!playing && cursor >= n - 1) setCursor(0);
        setPlaying((p) => !p);
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault();
        setPlaying(false);
        setCursor(cursor + (ev.shiftKey ? 10 : 1));
      } else if (ev.key === "ArrowLeft") {
        ev.preventDefault();
        setPlaying(false);
        setCursor(cursor - (ev.shiftKey ? 10 : 1));
      } else if (ev.key === "Home") {
        ev.preventDefault();
        setPlaying(false);
        setCursor(0);
      } else if (ev.key === "End") {
        ev.preventDefault();
        setPlaying(false);
        setCursor(n - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, n, playing, setCursor]);

  const current = playback.events[cursor];
  const highlight: MapHighlight = useMemo(() => {
    const act = activeFor(current);
    const tone = current ? eventTone(current) : "note";
    const busy = new Set(openSpans(playback, cursor).map((s) => laneComponent(s.to)));
    return {
      active: act.component,
      edge: act.edge,
      involved: new Set(playback.lifelines.map(laneComponent)),
      busy,
      error: tone === "error" || tone === "fault",
      seq: current?.seq ?? 0,
    };
  }, [current, playback, cursor]);

  // A large ontology's map draws only the run's components (and their groups): see runGraph.
  const involvedKey = playback.lifelines.map(laneComponent).sort().join("\n");
  const mapGraph = useMemo(
    () => (graph && graph.nodes.length > COLLAPSE_ABOVE ? runGraph(graph, new Set(involvedKey.split("\n"))) : graph),
    [graph, involvedKey],
  );
  const nodesById = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);
  const colorKey = useCallback((c: string) => nodesById.get(laneComponent(c))?.layer, [nodesById]);

  if (n === 0) {
    return (
      <div className={cx("flex flex-col gap-2", className)}>
        <SummaryCard run={run} />
        <div className="rounded-lg border border-dashed border-line p-6 text-center text-muted">This run has no trace to play back.</div>
      </div>
    );
  }

  return (
    <div className={cx("flex min-h-0 flex-col gap-2", className)}>
      <SummaryCard run={run} />
      <Transport playback={playback} cursor={cursor} setCursor={setCursor} playing={playing && cursor < n - 1} setPlaying={setPlaying} speed={speed} setSpeed={setSpeed} />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(330px,30%)]">
        <div className="flex min-h-0 flex-col gap-2">
          <Panel
            title="Sequence"
            className="min-h-[300px] flex-[3]"
            bodyClassName="p-0"
            actions={
              <span className="hidden items-center gap-3 text-[10.5px] text-faint md:flex" aria-label="Legend">
                <span>→ request</span>
                <span>← response</span>
                <span className="text-bad">✗ error</span>
                <span className="text-violet">↻ retry</span>
                <span className="text-[#f5b294]">⚡ fault</span>
                <span className="text-warn">⏱ timeout</span>
                <span className="text-warn">⇠ late (dashed)</span>
                <span className="text-[#7fe0cf]">⇢ async (dotted)</span>
                {playback.parallels.length > 0 && <span className="text-[#8fc1e8]">⫴ parallel</span>}
                {playback.events.some((e) => e.type === "queue") && <span className="text-warn">⧗ queue</span>}
                {playback.events.some((e) => e.type === "yield") && <span className="text-[#7fe0cf]">↟ yield</span>}
                {playback.events.some((e) => e.type === "put" || e.type === "receive") && <span className="text-warn">⇥ channel</span>}
                {playback.events.some((e) => e.type === "kill") && <span className="text-bad">✖ kill</span>}
              </span>
            }
          >
            <SequenceDiagram playback={playback} doc={doc} scale={colorScale} colorKey={colorKey} cursor={cursor} onCursor={(i) => { setPlaying(false); setCursor(i); }} />
          </Panel>
          {graph && (
            <Panel
              title="Architecture"
              className={mapOpen ? "min-h-[220px] flex-[2]" : ""}
              bodyClassName={mapOpen ? "p-0" : "hidden"}
              actions={
                <button type="button" className="text-[11px] text-link hover:underline" onClick={() => setMapOpen((o) => !o)} aria-expanded={mapOpen}>
                  {mapOpen ? "Hide map" : "Show map"}
                </button>
              }
            >
              {mapOpen && mapGraph && <ArchitectureMap graph={mapGraph} highlight={highlight} ariaLabel="Architecture map highlighting the current event" />}
            </Panel>
          )}
        </div>
        <div className="flex min-h-0 flex-col gap-2">
          <Panel title="Inspector" className="max-h-[52%] min-h-[180px]" bodyClassName="overflow-y-auto p-0">
            <Inspector playback={playback} cursor={cursor} doc={doc} onJump={(i) => { setPlaying(false); setCursor(i); }} />
          </Panel>
          <Panel title="State ledger" className="min-h-[200px] flex-1" bodyClassName="overflow-y-auto p-0">
            <StateLedger playback={playback} cursor={cursor} doc={doc} />
          </Panel>
        </div>
      </div>
    </div>
  );
}
