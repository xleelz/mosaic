"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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

/**
 * "page" is the run page: the sequence diagram fills the stage, with the
 * inspector and ledger in a floating right panel and the map along the bottom.
 * "embedded" is the inline playback in Simulate and Exploration: a grid.
 */
export type PlaybackLayout = "page" | "embedded";

/** A floating panel's state: collapsed to a tab or bar, docked, or expanded over its neighbours. */
type FloatState = "hidden" | "open" | "expanded";

const FLOAT_STATES: FloatState[] = ["hidden", "open", "expanded"];
const nextFloat = (s: FloatState): FloatState => (s === "hidden" ? "open" : s === "open" ? "expanded" : "hidden");

/** A floating panel's state, remembered in localStorage. */
function useFloatState(key: string, fallback: FloatState): [FloatState, (s: FloatState | ((s: FloatState) => FloatState)) => void] {
  const [state, setState] = useState<FloatState>(() => {
    if (typeof window === "undefined") return fallback;
    try {
      const v = window.localStorage.getItem(key);
      return FLOAT_STATES.includes(v as FloatState) ? (v as FloatState) : fallback;
    } catch {
      return fallback;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(key, state);
    } catch {
      // Storage may be unavailable (private mode, quota); the state just isn't remembered.
    }
  }, [key, state]);
  return [state, setState];
}

/** Three buttons, one per state, for a floating panel. */
function FloatControls({
  state,
  setState,
  controls,
  name,
  shortcut,
  labels,
}: {
  state: FloatState;
  setState: (s: FloatState) => void;
  controls: string;
  name: string;
  shortcut: string;
  labels: Record<FloatState, ReactNode>;
}) {
  const title: Record<FloatState, string> = { hidden: `Hide the ${name}`, open: `Show the ${name} at its normal size`, expanded: `Expand the ${name}` };
  return (
    <span className="flex items-center rounded-md border border-line bg-panel-2 p-0.5" role="group" aria-label={`${name} size`}>
      {FLOAT_STATES.map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => setState(s)}
          aria-controls={controls}
          aria-expanded={state !== "hidden"}
          aria-pressed={state === s}
          title={`${title[s]} (${shortcut} cycles)`}
          className={cx(
            "inline-flex h-5 items-center justify-center rounded px-1.5 text-[11px] leading-none",
            state === s ? "bg-panel-3 text-ink" : "text-faint hover:text-ink",
          )}
        >
          {labels[s]}
        </button>
      ))}
    </span>
  );
}

export function Playback({
  run,
  doc,
  graph,
  initialCursor,
  onCursorChange,
  layout = "embedded",
  className,
}: {
  run: SimulationRun;
  doc?: Document;
  graph?: Graph;
  initialCursor?: number;
  onCursorChange?: (seq: number) => void;
  layout?: PlaybackLayout;
  className?: string;
}) {
  const playback = useMemo(() => buildPlayback(run), [run]);
  const n = playback.events.length;
  const [cursor, setCursorRaw] = useState(() => Math.min(Math.max(0, initialCursor ?? 0), Math.max(0, n - 1)));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [mapOpen, setMapOpen] = useState(true);
  const page = layout === "page";
  const [side, setSide] = useFloatState("mosaic.run.inspector", "open");
  const [mapState, setMapState] = useFloatState("mosaic.run.map", "open");
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

  // Keyboard: Space play/pause, ←/→ step (Shift: 10), Home/End; on the run
  // page, i cycles the inspector panel and m the map.
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
      } else if (page && !ev.shiftKey && ev.key === "i") {
        ev.preventDefault();
        setSide(nextFloat);
      } else if (page && !ev.shiftKey && ev.key === "m" && graph) {
        ev.preventDefault();
        setMapState(nextFloat);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, n, playing, setCursor, page, graph, setSide, setMapState]);

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

  const onJump = (i: number) => {
    setPlaying(false);
    setCursor(i);
  };
  const legend = (
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
  );
  const sequence = <SequenceDiagram playback={playback} doc={doc} scale={colorScale} colorKey={colorKey} cursor={cursor} onCursor={onJump} />;
  const map = mapGraph && <ArchitectureMap graph={mapGraph} highlight={highlight} ariaLabel="Architecture map highlighting the current event" />;
  const inspector = <Inspector playback={playback} cursor={cursor} doc={doc} onJump={onJump} />;
  const ledger = <StateLedger playback={playback} cursor={cursor} doc={doc} />;
  const transport = (
    <Transport playback={playback} cursor={cursor} setCursor={setCursor} playing={playing && cursor < n - 1} setPlaying={setPlaying} speed={speed} setSpeed={setSpeed} />
  );

  if (page) {
    // The stage below the transport: the sequence diagram fills it, and the
    // floating panels dock over its edges. Docked panels inset the diagram (so
    // the cursor row never scrolls under them); expanded ones overlay it.
    const sideDocked = side !== "hidden";
    const right = cx("right-9", sideDocked && "lg:right-[428px]");
    const bottom = !graph ? "bottom-0" : mapState === "hidden" ? "bottom-[46px]" : "bottom-[calc(30%+8px)]";
    return (
      <div className={cx("flex min-h-0 flex-col gap-2", className)}>
        <div className="max-h-[40%] shrink-0 overflow-y-auto">
          <SummaryCard run={run} />
        </div>
        {transport}
        <div className="relative min-h-0 flex-1 overflow-hidden">
          <Panel title="Sequence" className={cx("absolute left-0 top-0", right, bottom)} bodyClassName="p-0" actions={legend}>
            {sequence}
          </Panel>
          {graph && (
            <Panel
              id="run-map"
              title="Architecture"
              className={cx(
                "absolute bottom-0 left-0 z-10",
                right,
                mapState === "open" && "h-[30%]",
                mapState === "expanded" && "h-[75%] shadow-[0_-8px_28px_rgba(0,0,0,0.5)]",
              )}
              bodyClassName={mapState === "hidden" ? "hidden" : "p-0"}
              actions={
                <FloatControls
                  state={mapState}
                  setState={setMapState}
                  controls="run-map"
                  name="map"
                  shortcut="m"
                  labels={{ hidden: "Hide", open: "Open", expanded: "Expand ▴" }}
                />
              }
            >
              {mapState !== "hidden" && map}
            </Panel>
          )}
          <aside
            id="run-inspector"
            aria-label="Inspector and state ledger"
            className={cx(
              "absolute bottom-0 right-0 top-0 z-20 flex flex-col gap-2 rounded-lg",
              side === "hidden" && "w-7",
              side === "open" && "w-[min(420px,100%)] bg-bg max-lg:shadow-[-8px_0_28px_rgba(0,0,0,0.5)]",
              side === "expanded" && "w-[max(min(420px,100%),60%)] bg-bg shadow-[-8px_0_28px_rgba(0,0,0,0.5)]",
            )}
          >
            {side === "hidden" ? (
              <button
                type="button"
                onClick={() => setSide("open")}
                aria-controls="run-inspector"
                aria-expanded={false}
                title="Show the inspector and state ledger (i)"
                className="flex h-full w-7 flex-col items-center gap-2 rounded-lg border border-line bg-panel py-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted hover:bg-panel-2 hover:text-ink"
              >
                <span aria-hidden>‹</span>
                <span className="[writing-mode:vertical-rl]">Inspector · State</span>
              </button>
            ) : (
              <>
                <Panel
                  title="Inspector"
                  className="max-h-[52%] min-h-[140px] shrink-0"
                  bodyClassName="overflow-y-auto p-0"
                  actions={
                    <FloatControls
                      state={side}
                      setState={setSide}
                      controls="run-inspector"
                      name="inspector"
                      shortcut="i"
                      labels={{ hidden: "Hide »", open: "Dock", expanded: "« Expand" }}
                    />
                  }
                >
                  {inspector}
                </Panel>
                <Panel title="State ledger" className="min-h-[120px] flex-1" bodyClassName="overflow-y-auto p-0">
                  {ledger}
                </Panel>
              </>
            )}
          </aside>
        </div>
      </div>
    );
  }

  return (
    <div className={cx("flex min-h-0 flex-col gap-2", className)}>
      <SummaryCard run={run} />
      {transport}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(330px,30%)]">
        <div className="flex min-h-0 flex-col gap-2">
          <Panel title="Sequence" className="min-h-[300px] flex-[3]" bodyClassName="p-0" actions={legend}>
            {sequence}
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
              {mapOpen && map}
            </Panel>
          )}
        </div>
        <div className="flex min-h-0 flex-col gap-2">
          <Panel title="Inspector" className="max-h-[52%] min-h-[180px]" bodyClassName="overflow-y-auto p-0">
            {inspector}
          </Panel>
          <Panel title="State ledger" className="min-h-[200px] flex-1" bodyClassName="overflow-y-auto p-0">
            {ledger}
          </Panel>
        </div>
      </div>
    </div>
  );
}
