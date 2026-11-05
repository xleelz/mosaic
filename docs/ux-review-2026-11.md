# Mosaic web UI: expert UX review, November 2026

**How this was done.** I drove the running app at `127.0.0.1:3000` in headless Chromium through
Playwright, at 1440x900 with one pass at 1024x768, on three models: Envoy (23 components), vLLM (659)
and the largest model, a gateway platform (634). Screenshots of Envoy and vLLM are in
[images/ux-review/](images/ux-review/). Findings not seen live are marked. Section 6 lists the limits.

---

## 1. The short version

The UI is well made at 23 components. At 650, the screens still draw correctly and the frame rate
holds, but the design stops answering the questions. The problem is legibility and honesty, more than
speed. In order of payoff:

1. **Say how far to trust the model, on every page (small to start, then medium).** Today a model
   that matches 24-30% of blind benchmark steps shows a green "✓ valid" on every page and "✓ all pass,
   1805 / 1805" on Tests. No screen mentions coverage, gaps or the benchmark. Show a model passport,
   rename "valid", and mark what is absent, shell, partial or assumed (section 5).
2. **Add an Overview, and make the map area-first (medium to large).** The largest model opens with
   100 top-level boxes at a zoom where no label can be read, while the sidebar already knows its 13
   areas. Open on areas, with semantic zoom into them (Concept A, section 4).
3. **Show a run as a story first, and the sequence diagram second (medium to large).** Traces reach
   19,005 events and 75 lanes. 71% of a sampled large trace is `set` and `note` events, and the fault
   I looked for sat at event 1,487 of 1,571 while the page opened at event 1. Open on a summary with
   jump-to-failure, group lanes by area, and add run compare.
4. **Connect the things that exist (small to medium).** A component page has no link to the flows or
   scenarios that touch it. Search doesn't cover scenarios. vLLM's happy-path generate scenario isn't
   listed under `AsyncLLM.generate`. The Run button sits about 6,100 px down the Simulate page.
5. **Stop rendering what nobody can see (medium).** The Configs tab builds 80,000 elements. A
   12,383-event run builds 77,000 elements and a 273 MB JS heap, and each step of the cursor lags. This
   is my leading suspect for the Safari reloads, not yet confirmed there.

---

## 2. What works, so it isn't lost

- **The citation viewer is the best thing in the product.** One click opens the cited lines, pinned
  to the model's commit, with the range highlighted, surrounding context, syntax color, a GitHub link,
  and working Esc. It opened in under 1.5 s with the fetch, and it worked on the largest model too. It makes the claim checkable, and that's the core of trust. Build on it.
- **Playback mechanics.** Dimming future events, the state ledger's highlight of what changed, a
  scrubber with colored ticks for failures, the sticky lane headers, and the map following the cursor
  are all right. Envoy's retry run (185 events) reads like a good textbook figure.
- **The run page's floating panels.** Hide, Show and Expand on each panel, `i` and `m` to cycle, the
  choice remembered, and a top-edge handle for the header. This is a sound way to give a dense page
  focus. The criticism in section 3 is about what's in them at scale, not the mechanism.
- **The run-scoped map.** Above 120 components, the run page draws only the components in the run.
  That's the right instinct, and Concept A extends it to the rest of the product.
- **The flows page's two panes.** The grouped sidebar with counts, search that dims groups to "1/70",
  and the smart default (feature tags where most flows have them, area otherwise) all land.
  Search took about 330 ms on the largest model.
- **Scenario names.** "A worker failure mid-step kills the engine and fails the stream" tells the
  story before you run it. Where names exist, they do more for comprehension than any diagram.
- **Tab switches are instant once loaded** (83 to 370 ms; Simulate 945 ms on the largest model), since
  the document is cached. Pan and zoom stayed smooth even with all 634 nodes expanded (p50 15 ms,
  p95 30 ms per frame, in software rendering).
- **Accessibility basics.** axe (WCAG 2 A and AA rules) found nothing on Home, Architecture, Flows or
  Simulate, and one serious issue on the run page. There's a skip link, a visible focus ring, labeled
  controls, and status shown by icon as well as color. Automated checks only cover part of this.
- **The visual language.** The dark, restrained palette with one lime accent, tabular numbers, and
  mono for ids only. Keep it.
- **States.** A 404 and a daemon-down state each give a clear message and Retry.

---

## 3. Findings per task and page

Severity: **Critical** blocks the task or misleads. **High** seriously slows it. **Medium** is
friction. **Low** is polish. Times are machine times plus my count of steps: this is one expert's
walk, not a user study.

| Task (largest scale) | Got to | Steps | Verdict |
|---|---|---|---|
| 1. What is this made of? Where do I start? | Partial: a list of 13 area names in a sidebar | No path: nothing to click toward an answer | **Fails** |
| 2. Follow one request end to end | A run, but not an understanding of it | About 4 clicks, then 1,500 to 12,000 events by hand | **Fails at scale** (fine on Envoy) |
| 3. What if this dependency is down? | Works if you already know the scenario | No path from the dependency | **Partial** |
| 4. Which scenarios fail, and why? | Tests, after 27 s with no progress display | 1 click; results gone on reload | **Partial** |
| 5. Show me the code for this claim | Exact lines | 1 click | **Works** |
| 6. How good is this model? | Nothing | No path exists | **Fails, and misleads** |

### Task 1: overview (Architecture, Home)

**Critical. The largest model's first screen has nothing readable.** 100 root components are drawn at
fit-to-screen, and a node's text is a few pixels tall. First node at 1.9 s, so the speed is fine, but
the result is a texture. "Collapse top level" didn't change it, because its 100 boxes are already the
top level. Seen live; that screenshot stays out of this repo.

**High. A good grouping exists and the map ignores it.** The sidebar's "by area" reduces 634 components
to 13 groups, yet the map doesn't respond. The sidebar's filter doesn't touch the map either: it's
effectively a separate app in the same frame.

**High. One click takes you from 11 boxes to 405.** vLLM's opening map, 11 boxes, is the best overview
in the product ([screenshot](images/ux-review/vllm-architecture-default.png)). But expanding GPU worker,
which holds 394 of the 659 components, renders 405 nodes in the same viewport at unreadable size
([screenshot](images/ux-review/vllm-gpu-worker-expanded.png)). Two of the 11 boxes are stray classes
(`_LoRAResolverRegistry`, `MsgpackEncoder`) with the same weight as the GPU worker: a model-shape issue
the UI could help expose.

**High. Selecting from the list blows up the map.** Picking Scheduler in the list opens its ancestors'
siblings, so the map goes from 11 to 116 tiny nodes and the selected node gets lost
([screenshot](images/ux-review/vllm-filter-and-select.png)).

**High. Nothing says where to start.** No summary, no entry points, no "the main flows are...". Both big
models say "No description." on Home. Components with kind `client` or `external` and flows' entries
would seed this automatically.

**Medium. Four competing groupings:** parent, area, owner, and layer. Layer drives color, area drives
the list, parent drives the map. vLLM has 41 layers and the legend shows 8 and "other", so most nodes
fall into grey or a color that means nothing.

**Medium. Component panel.** The member list is an undifferentiated wall of links, and there's no way
to tell what matters. It has no link to flows or scenarios at all (`ComponentPanel.tsx` doesn't
reference them): see Task 3.

**Medium. Home.** Stale identity: the card says "vLLM 0.32 (round 4)" while the latest revision says
round 6. The name is the only fidelity cue, and it's wrong. "0 links" is noise. The three design
variants loaded here sit among unrelated models, with nothing showing that they're alternatives
(section 4, Draft and compare).

### Task 2: follow a request (Flows, run page)

**Critical. A flow's scenarios are misfiled, so the happy path is hidden.** The UI files a multi-step
scenario under its first step's flow (`flowOfScenario`). `AsyncLLM.generate` lists 9 scenarios, nearly
all refusals and edge cases. "A request streams to completion" is under "Engine-core busy loop". The
same rule produces misleading "0 scenarios" rows: the UI shows 35 of 276 vLLM flows and 136 of 615
flows on the largest model at zero, but only 7 and 2 are absent from every step of every scenario.
A newcomer reads those rows as untested. Index a scenario under every flow it touches.

**High. Opening a flow leads with the wrong thing.** The first panels are a static reachability list,
"831 interfaces, 249 components" for one generate call, then choice points, then 248 faultable targets.
Scenarios sit below all of this. Reachable-in-theory isn't what a newcomer asked. They asked what
happens. Lead with a run of the happy path.

**High. The sequence diagram doesn't scale, in size or in sense.** Sampling 150 scenarios per model
without saving: vLLM p50 66 events, p90 2,088, max 19,005; the largest model p50 129, p90 770, max
5,923. A 1,571-event vLLM run has 55 lanes on a 7,254 x 40,253 px canvas: 5 screens wide, 56 tall. Only
about 8 lanes fit beside the inspector. Most arrows go off-screen. In that trace 923 of 1,571 events are
`set` or `note`, and in the 12,383-event trace 8,846 are. ([screenshot](images/ux-review/vllm-run-page-failure.png))

**High. Default panels leave about a third of the screen for the diagram.** At 1440x900 the sequence
gets roughly 985 x 430 px. It's the right mechanism, but the map panel earns little: at this zoom it
shows only a moving dot. It should default to hidden on runs with over 30 lanes, or show areas.

**Medium. The ledger doesn't scale.** It lists everything, and at the end of a large run that's tables
of unrelated state (policy tables during a provisioning run). It marks changes but can't show only
those. Default to "changed in this run".

**Medium. Noisy run header.** Revealing the header shows a four-line list of 30+ component ids under
"state:". Replace with "seeded 32 components" and a disclosure. The "By instance: 68 / 1 instances" tile
reads as nonsense when there's one instance.

**Medium. Flows are sorted by id, not importance.** A 191-flow group on the largest model and 109-flow
group on vLLM are flat. 228 of 276 vLLM flows and 593 of 615 on the largest have no description, and
393 and 511 scenarios have no name. The UI falls back to ids silently. The tag hierarchy works, but it
needs a second level for these big groups, and "main flows" on top.

### Task 3: when a dependency is down (Simulate, run page)

**Critical. No path from the dependency to the answer.** On Local disk or Hugging Face Hub, nothing says
"what happens if this fails". Flows search covers flow id, name and tags, but not scenarios
(`flowMatches`), so typing "engine dead" gets nothing, although a scenario with that title exists.
The Tests page, which does list every scenario, has no search at all. The data for this is all there:
50 vLLM scenarios and 460 on the largest inject faults, and the plan knows 1,041 targets.

**Critical. The Run button is about 6,100 px down** on vLLM's Simulate page and about 3,250 px on the
largest, beneath a state editor listing every component. Only after a run does the button appear in the
top bar. Scenario rows on the Flows page do have a one-click Run, which is the path to keep.

**High. A failure opens at event 1.** In the worker-failure run the fault is event 1,487 of 1,571. The
red ticks show where it is, but the Faults tile isn't clickable, and no key jumps to it. It takes a
manual drag of the scrubber.

**High. "✗ error" beside "✓ expectations pass" with no explanation.** That's correct: the scenario
expects this failure. But a newcomer can't parse it. Say "Failed as expected: 500 engine-dead-error".
Tests has the same "✓ pass" beside "✗ error" ([screenshot](images/ux-review/vllm-tests-all-pass.png)).

**High. No compare.** The natural question is "how does this differ from the healthy run?" It takes two
tabs and memory.

**High. Simulate form layout break.** A long flow description is squeezed into a narrow column, and its
height pushes Flow and Scenario apart, leaving a blank band ([screenshot](images/ux-review/vllm-simulate-layout-gap.png)).

**Medium. Ad hoc faults.** Add fault defaults to the alphabetically first of 1,041 targets, in a native
select. It needs a searchable picker, starting from what the flow actually calls in a default run.
"unavailable, 503" as defaults are right.

### Task 4: what's failing (Tests, Exploration)

**High. Tests holds nothing.** "Run all 1805" took 27 s with only a "Running..." label. Results survive
tab changes but not a reload, and nothing shows last-run state on arrival. On arrival the page is an
empty box. The flow and component pages can't show pass or fail as a result.

**High. "Run all" has a hidden write.** The UI calls `POST /test` with no `save=false`, so each press
saves one run per scenario: 1,805 or 3,376 traces. (For this review I rewrote the request to
`save=false`.) This is likely an unnoticed storage cost, and "Run & open" on each row re-runs rather than
opening what just ran.

**Medium. 1,805 rows and no structure.** A filter for "Failed only" exists, but no grouping by area or
flow, no search and no sort by anything but scenario order.

**High. Exploration's empty state reads as good news.** "No replay files for this ontology's scenarios:
exploration has no recorded failing schedules" is true when exploration has never run, which is the case
for all 8 loaded models. It should say "Not explored yet", with when it last ran if it ever did. It also
can't be started from the UI: the instructions at the top are CLI flags.

**Low. Populated Exploration (seen with stubbed responses only).** Still fails or Passes now, recorded
and current failures, and a sensible order: this design is fine. Rename it "Race search" and explain
"schedule" in one line. Put the "Remove all passing" button further from the main action, since it deletes
files.

### Task 5: citations

**Medium. The viewer forgets why you came.** It covers the claim it was opened from, and it doesn't
repeat that claim. Show the claim as a one-line header: "Claim: Scheduler decides each step's batch". This
turns reading into checking.

**Medium. No way back or across.** There's no "what else in the model cites this file", which would
answer "how much of this file is modeled?". This is cheap to compute from sources.

**Low. Vim on by default** for a read-only viewer (`NORMAL` in the status bar). Keep the keys that move
around, and drop the mode indicator until someone turns on editing.

**Low. Citations in the configs table are 11 px links,** and a typical config cell is a paragraph of
prose. Fine for experts. Not a priority.

### Task 6: how good is this model?

**Critical. There's no answer, and the signals that exist point the wrong way.** Green "✓ valid" means
the schema validates. "✓ all pass 1805 / 1805, 4966 / 4966" means the model agrees with scenarios written
by the same process ([screenshot](images/ux-review/vllm-tests-all-pass.png)). Nothing in `web/src` refers
to inventory coverage, the oracle or blind results. "Round 6: mechanism coverage" in a revision title is
the only trace. See section 5.

### Other pages, and performance

**Medium. Eight equal tabs, ordered by build history.** Commits is empty on all three models. Tests and
Exploration are about the model; Revisions and Commits about its history; the first four are the system.
See the proposed structure below.

**Medium. Revision diff is a JSON line diff.** r2 to r3 on vLLM is "749 changed entities" that opens on
schema lines ([screenshot](images/ux-review/vllm-revision-diff.png)). It needs a summary first: what appeared per area, then the JSON. This is the
base for Draft and Compare, so it matters more than its current use suggests.

**Medium. Hidden shortcuts.** The keyboard hints on the run page are hidden below the `2xl` breakpoint, so
they don't show at 1440. `?` does nothing. There's no global search or `/` to focus.

**Low. Loading is a one-line spinner on an empty page.** With a 15 MB document that's up to 2 s. A
skeleton of the map's frame would help. `Sequence diagram`'s scroll region isn't keyboard focusable (axe:
scrollable-region-focusable, serious).

| Measure (Chromium, loopback) | Envoy | vLLM | Largest |
|---|---|---|---|
| First map node after navigation | 0.4 s | 1.5 s | 1.9 s |
| All requests settled (validate last) | 0.9 s | 1.6 s | 5.0 s |
| Document size (no compression through the Next proxy) | 64 KB | 7.4 MB | 15 MB |
| Configs tab, elements | 388 | 57,764 | 79,919 |
| Expand all on the map | n/a | n/a | 2.4 s, one 1.8 s long task |
| Run page, 1,571 events: elements / heap | n/a | 13,287 / 51 MB | n/a |
| Run page, 12,383 events: elements / heap | n/a | 77,474 / 273 MB | n/a |
| 30 cursor steps on that run | n/a | 36 long tasks, 4.2 s blocked | n/a |

Reading these numbers:

- **Time to first useful paint is fine.** Slowness people feel on big models comes from three spots: the
  validate call (4.4 s on the largest, re-run on every full page load, and it delays the badge only), big
  run pages, and big tabs.
- **The cached documents aren't the main memory cost in Chromium.** Visiting all three models then
  collecting garbage settled at about 50 MB. The query cache never evicts, though, so it grows with each
  run opened.
- **So suspect big DOMs and traces first for Safari.** `SequenceDiagram` isn't windowed, the Configs
  fixture panes render every JSON token, and Simulate's state editors render for every component. This is
  inference: I could not test Safari.
- **Quick transport win:** the Next proxy passes 15 MB uncompressed. On loopback that barely matters, but
  over a tunnel it does.

---

## 4. Redesign proposals

### Choosing a display, per task

| Task | Best display | Why |
|---|---|---|
| What is it made of? | Area map with semantic zoom | Answers at a human count (9 to 13 things); drills down without a change of model |
| Where do I start? | Overview page: entry points, main flows, how far to trust | A map doesn't say what's important. A page can |
| Find a thing I can name | Search palette over everything | Fastest at any scale, useless if you don't know names, so it complements rather than replaces |
| Follow a request | Summary trace, with swimlanes by area, then the sequence on demand | Most events are noise until you care |
| What if X is down? | Failure lens on the map, and a section on each component | Starts from the dependency |
| Who depends on what, at area level | Dependency matrix | 84 of 156 directed area pairs connect on the largest model, a hairball as node-link |
| How much is modeled? | Treemap or area strips colored by fidelity | Here size means something: mechanisms per area |

**What I'd reject:**

- **The full node-link graph as a default.** That's the current screen. It's kept only as an explicit
  "everything" view, since it's cheap and pans fine.
- **Force-directed layouts.** They're unstable between visits, and they destroy the spatial memory a
  newcomer is building.
- **A treemap as the main map.** It shows size and hides flows, and it's poor for what calls what. In a
  generated model, component count reflects how the generator split things, not importance.
- **Plain C4 levels as a fixed hierarchy.** Here depth varies from 0 to 5 and the root level is sometimes
  11 and sometimes 100. Levels need to come from area and role, not nesting.
- **Search-first alone.** A newcomer doesn't know the names yet.

### Concept A: Atlas, an area-first map with semantic zoom (my pick)

Data already exists: the sidebar's area grouping gives 9 on vLLM and 13 on the largest. An area's box
carries its role, what it holds and its fidelity. Part and flow counts below are real; role text, bars and
edges in all wireframes here are illustrative.

```
 vLLM 0.32   [Generated. Blind benchmark 30% of steps. Details]              r3 v  Search /
 Overview  Map  Flows  Runs  |  Evidence  History  |  Drafts
 Lens: (Area) Data  Flow  Failure                   Connections: strong only v
+----------------------------------------------------------------------------------+
| ENTRY         +--serving-api--------+      +--engine-core--------+               |
|  API client ->| HTTP routes, render |=====>| busy loop, scheduler|               |
|  Operator     | 113 parts  [####..] |      | 106 parts  [##....] |--+            |
|  Python user  | 34 flows            |<-----| 70 flows            |  |            |
|               +---------------------+      +---------+-----------+  v            |
|               +--config-platform----+                |    +--worker-runner-----+ |
|               | 41 parts   [###...] |                +--->| GPU ranks, runner  | |
|               +---------------------+                     | 221 parts  [##....]| |
|  EXTERNAL     +--models-layers------+  +--kernels-ops--+  | 109 flows          | |
|  HF Hub       | 106 parts  [#.....] |  | 66 [##....]   |  +--------------------+ |
|  Local disk   +---------------------+  +---------------+                         |
|                                                                                  |
| Double-click an area to enter.  [####..] = mechanisms modeled or partial         |
+----------------------------------------------------------------------------------+
```

Entering an area keeps a breadcrumb and turns neighbors into labeled stubs at the edge. The rule that
fixes the 11-to-405 jump: **a view never draws more than about 40 boxes**. Beyond that it groups (by next
parent, then by role) and says "and 38 more". Selecting from search navigates into the right area, not
expands it in place.

```
 Map > engine-core                                                        Lens: Area
 from serving-api -->  +--Scheduling (9)---+   +--Engine loop (12)--+  --> worker-runner
 from Python user -->  | Scheduler *       |-->| EngineCoreProc *   |
                       | KVCacheManager *  |   | Output processor   |
                       | + 7 more          |   | + 9 more           |
                       +-------------------+   +--------------------+
                       +--KV connectors (14)-+  +--Metrics (11)--+  (collapsed)
 Right panel: Scheduler
   What it does.  Flows through here (12).  If this fails (4 scenarios).  Run one.
   Sources.  Fidelity: partial, with the list's note.
```

The lenses reuse the layout, so spatial memory holds:

- **Area** is the default.
- **Failure** tints by the number of fault scenarios, and clicking a part lists them.
- **Flow** highlights the path a chosen flow takes.
- **Data** shows stateful components and who writes them.

**Trade-offs.** It depends on the area attribute being good: it's strong on these two, and absent on
Envoy, where nesting serves perfectly and the current map should stay. Grouping inside areas needs a rule
or an agent-written label; the generate pipeline could output one. Drawing 84 area pairs needs a threshold,
with thickness for call count and hover to reveal the rest. **Effort: large,** though a first version on
the existing ELK layout, with area as a synthetic parent, is medium.

### Concept B: Journeys, flows as the main way in

The system is explained by what it does. Overview lists 5 to 15 main journeys, each opening a summary
trace. The map appears only as the run-scoped context.

```
 Run: A worker failure kills the engine and fails the stream     Failed as expected
 500 engine-dead-error after 177 ms (virtual)   Jump to: [First fault] [First error]
 Show: (Summary) Calls  Everything        Compare with: [Happy path v]
+--Summary----------------------------+  Swimlanes by area (expand any)
| 1  Step loop starts                 |   client  serving  engine  worker  external
| 2  Request arrives, is admitted     |     o-------->o
|    > 41 calls in serving-api        |               o------->o
| 3  Scheduler picks the batch        |                        o<>
| 4  Model runs on the ranks          |                        o------->o
| !  FAULT execute-model: cuda-error  |                        o<-------X
| 5  Engine marks itself dead         |                        o
| 6  Every stream gets EngineDeadError|     o<--------o<-------o
| State left changed: engine_dead=true|
+-------------------------------------+
 Click a beat to open its spans.  Sequence diagram is one tab, centered on the beat.
```

How the summary comes from data, with no LLM needed at first:

- **Collapse** `set` and `note` events, which alone cut the 12,383-event trace to 3,537.
- **Fold** the call tree at each area crossing, so a run of calls inside one area becomes one line.
- **Beats** are `step.start`, area crossings, choices, faults, errors, retries, and notes at shallow depth.
- **Swimlanes by area** turn 55 to 75 lanes into 5 to 13, each expandable to its components.

Compare two runs:

```
 Happy path                         |  Worker failure            first divergence: beat 4
 3  Scheduler picks the batch       |  3  Scheduler picks the batch
 4  Model runs on the ranks       ok|  4  Model runs on the ranks  X cuda-error
 5  Outputs reach the client        |  5  Engine marks itself dead
                                    |  6  Every stream gets EngineDeadError
 Result 200, 4 tokens               |  Result 500 engine-dead-error
 State only here: ...               |  State only here: engine_dead=true
```

Alignment by span path (interface plus depth) is good enough and deterministic, since seeds are fixed.

**Trade-offs.** This gives the highest comprehension per screen for "what happens when". But used alone,
it hides the structure, and it depends on the model having good flows: 228 of 276 vLLM flows have no
description, and flow names vary. **Effort: medium** for summary and jumps, **medium** for area swimlanes,
**medium** for compare.

### Concept C: Ask the catalog, search and lenses

A command palette (`/` or Cmd-K) over components, interfaces, flows, scenarios, configs and citations,
including failure language. Results are the navigation, each with a preview.

```
 / local disk down
 COMPONENT   Local disk                       datastore, 6 interfaces, 3 flows
 SCENARIO    Weights missing on disk: load fails       [Run] [Open]
 FAULT       Add local-disk.read: unavailable to a run of...   (ad hoc)
 FILE        vllm/model_executor/model_loader/weight_utils.py  cited 4 times
```

**Trade-offs.** Very cheap compared with the others, since `docIndex` holds everything client-side. It
serves experts and known-name tasks at once. But it can't teach a newcomer the shape of the system, so as
a home screen it fails Task 1. **Effort: small to medium.**

### My pick

**A as the spine, B's trace as the run view, C's palette as the first thing shipped.** They don't compete:
C answers "find it", A answers "what is it made of", B answers "what happens". Ship C and the quick wins
first, because they make the existing screens useful at scale within days. Keep the current compound map
for models under 120 components and for Envoy-shaped models with no areas.

### Information architecture and naming

```
 Overview  Map  Flows  Runs   |   Evidence   History   |   Drafts
 system                           the model              the change
```

- **Overview** (new): what this is, its entry points, main flows, how far to trust it, and where to go.
- **Map** replaces Architecture. Configs and fixtures join as a panel or lens, since they describe the
  world around the system.
- **Runs** combines Simulate and recent runs, with the form behind "New run".
- **Evidence** gathers the passport, mechanisms, Tests and Exploration.
- **History** gathers Revisions and Commits.
- **Drafts** is a placeholder slot for pillar 2.

| Term now | Lands? | Change |
|---|---|---|
| Ontology | No: it's jargon, and it's the first word on Home | "Model" in the UI. Keep "ontology" for docs and CLI |
| Component, interface | Mostly | Keep. Explain "interface" in one line: any callable the model tracks |
| Flow | Yes, loosely | Keep; subtitle "one entry point and all it can do" |
| Scenario | Yes | Keep. This is the best word here |
| Fixture | For developers, no for others | "World setup", with "fixture" in parentheses |
| Choice point | No | "Open decision: the model doesn't compute this, so you pick" |
| Plan, Reachable | No | "Could reach (static)", shown below the fold |
| Exploration, replay, schedule | No | "Race search"; "failing interleaving" |
| Valid | Misleading | "Schema OK", neutral grey |
| Layer, area, owner, parent | Too many | One word, "area", for the top grouping. Nesting is "inside" |

### Draft and compare: leaving room

Nothing above should block pillars 2 and 3, and three choices make them cheap later:

- **Every view takes a pair, not just a revision.** Map, flows, and run views should accept `(base, head)`.
  `ArchitectureDiff` and `FlowsChanged` already prove it can work. The map's diff tints become another lens,
  on areas first: "engine-core: 12 added, 3 changed, flows affected 8".
- **Compare is one component across uses.** Run compare (happy against fault) is the same component as draft
  against current for one scenario, and candidate against candidate.
- **Models need family ties.** The three design variants loaded today are peers with no relationship shown.
  A draft or candidate should say what it's based on, and Home should show a family as one card.

```
 Compare: Current  |  Draft A  |  Draft B
 Scenarios pass        1805    |  1790     |  1802
 Changed areas           -     |  3        |  5
 Mechanisms absent      131    |  131      |  128
 p50 latency (assumed)  ...    |  ...      |  ...
 Scenario diverges at:  beat 4 ...     [Open trace compare]
```

Scores like this inherit the trust display from section 5: a candidate's simulated win is a model claim.

### Quick wins and real redesigns

| Change | Effort | Addresses |
|---|---|---|
| Rename "✓ valid" to neutral "Schema OK"; add a "generated model" chip on every page | Small | Task 6 |
| "Not explored yet" empty state; "Not run yet" on Tests | Small | Tasks 4, 6 |
| "Failed as expected" wording for error plus passing expectations | Small | Task 3 |
| Duplicate Run at the top of Simulate; collapse state editors by default | Small | Task 3 |
| Fix the Simulate header layout | Small | Task 3 |
| Index scenarios under every flow they touch; fix "0 scenarios" | Small | Task 2 |
| Search scenarios from the Flows page | Small | Task 3 |
| Component panel: "Flows through here", "If this fails" | Small | Tasks 1, 3 |
| Jump to first fault, first error, next state change; clickable tiles; keys `f` and `e` | Small | Task 3 |
| Ledger defaults to changed-only; trim run header | Small | Task 2 |
| Hide `set` and `note` by default above 300 events | Small | Task 2 |
| Show shortcuts at all widths and on `?` | Small | Keyboard |
| Pass `save=false` from Tests, with an explicit "keep traces" toggle | Small | Task 4 |
| Virtualize Configs; lazy state editors; collapse JSON | Small to medium | Performance |
| Command palette (Concept C) | Small to medium | Tasks 1, 3, 5 |
| Model passport and Evidence tab | Medium | Task 6 |
| Stored test results; show pass or fail on flows and scenarios | Medium | Task 4 |
| Overview page | Medium | Task 1 |
| Summary trace; windowed sequence diagram | Medium | Tasks 2, 3, performance |
| Swimlanes by area | Medium | Task 2 |
| Run compare | Medium | Task 3, pillar 3 |
| Semantic revision diff | Medium | Pillars 2, 3 |
| Atlas map with semantic zoom and lenses | Large | Task 1 |
| Mechanism data served by mosaicd, joined across the UI | Medium to large | Task 6 |

---

## 5. Trust and fidelity display

**The principle: the UI should never let a simulated result read as a fact about the real system.** Every
output is a claim by a generated model. A newcomer's natural reading today is the opposite, since a clean
polished UI with green checks and exact numbers implies authority. The more polish this product gets, the
more this matters.

### Four things that need fixing regardless of data

1. **Don't use green for self-checks.** "Schema OK" and "self-checks pass" are hygiene. They're neutral. Save
   green for checks against something outside the model.
2. **Caption "all pass".** "1805 of 1805 self-checks pass. These scenarios were written alongside the model,
   so they show consistency, not accuracy. Blind benchmark: 30% of steps."
3. **Label invented quantities on the run page.** Duration "177 ms" looks measured. It's virtual, and many
   latencies are assumed: 45 vLLM entities literally say `ASSUMPTION:` in their summaries. Say "177 ms virtual".
   Input is fake data: say "generated input" in the run header.
4. **Show when a claim was measured.** A blind figure belongs to a revision. If the viewed revision is newer,
   say "measured on r2, not re-measured".

### The model passport

A persistent chip in the workspace header, on the Home card, and at the top of Overview:

```
 [ Generated model - blind benchmark 30% of steps - 24% of mechanisms modeled  v ]
+--------------------------------------------------------------------------------+
| vLLM 0.32 @ 5df63a7 (pinned)                       Revision r3, Nov 5          |
| HOW THIS WAS BUILT   by agents from source. No one has reviewed it end to end. |
| HOW GOOD IS IT                                                                 |
|   Blind benchmark     30% of steps   measured on r3, oracle not seen by builders|
|   Mechanisms          ####......  108 modeled of 452 (see below)               |
|   Self-checks         1805 of 1805 pass (consistency, not accuracy)            |
| USE IT TO   find where things live, and form hypotheses you check in code.     |
| DON'T USE IT TO   conclude that the system does or doesn't do something.       |
|                                                       [Open Evidence]          |
+--------------------------------------------------------------------------------+
```

The "use it to / don't use it to" lines are the most valuable copy in the product. Which figure goes with
which model must come from stored benchmark results; I only have the two figures, 30% and 24%, from the
brief, so the 30% here is illustrative. Unmeasured models say so: "Not benchmarked". Envoy, a small example with
a citation on each claim, may deserve a different passport from the generated models.

### The mechanism list as a data source

Real data from the in-progress vLLM lists (`examples/vllm/mechanisms/`, untracked at review time, so these
numbers will move): 452 mechanisms, **108 modeled (24%), 177 partial (39%), 36 shell (8%), 131 absent (29%)**.
This is the most honest statement about any model so far, and each row is written in plain language with a
note and citations. It's far more useful to a newcomer than a percentage, because "stream interval token
batching: reaches sampling params but no behavior reads it" tells you precisely what not to believe.

**On Evidence, per area.** Sorted as the lists are sorted, by what an operator would miss first:

```
 Evidence > Mechanisms          Filter: [Absent] [Shell] [Partial] [Modeled]   Search
 Area           modeled partial shell absent
 engine-core    ########|#######|##|####     72
 serving-api    #########|#######|#|#######  86
 scheduler-kv   ####|#########|###|#########  92
 worker-runner  ########|##########|#|#####  89
 distributed    #|###############|###|#########  113
--------------------------------------------------------------------------------
 engine-core.stream-interval  ABSENT  pipeline
   Stream interval token batching
   Reaches sampling params, but no output-processor behavior reads it.
   Code: vllm/v1/engine/output_processor.py:324-345 [view]     Claims: none
```

**On the map.** Modeled and partial attach to components through `interfaces`, so each area and component
gets a small strip. **Absent mechanisms have `interfaces: []` and nothing to attach to,** which is why they're
what a map hides best. Show them as dashed ghost rows inside the area: "14 mechanisms aren't in this model".
A gap you can see, in the place you'd look, is the point of the whole section.

```
 +--engine-core--------------------+
 | 106 parts   ####....  28 of 72  |
 | ...                             |
 | - - - - - - - - - - - - - - - - |
 | 14 mechanisms not modeled    >  |   <- dashed, always visible
 +---------------------------------+
```

**On interfaces and behaviors.** A badge on the component panel, the same strip on each interface: `partial`,
with the note on hover.

**On runs, the place it matters most.** Intersect the run's called interfaces with mechanism fidelity:

```
 This run passed through 3 partial and 1 shell mechanism.  [list]
 ! Continuous-batching schedule step (partial): budget is always max_num_batched_tokens
```

Mark those spans in the summary and the sequence. A run that goes through a shell shouldn't look like a run
that went through a model, and the failure-as-expected wording should inherit it: "as the model expects".

**On "what if X is down".** Where X's area lists its failure handling as absent, say so before the run.

### A display scale for claims

Use one small vocabulary everywhere, shown by shape and word as well as color:

| Mark | Meaning | Source today |
|---|---|---|
| (solid) cited, exercised | Has a citation, and a scenario runs it | Sources, executed set |
| (solid outline) cited | Has a citation, nothing runs it | Sources |
| (half) partial | Main path only | Mechanism list |
| (hollow) shell | Claims it, doesn't do it | Mechanism list |
| (dashed) absent | Known to exist in the code, not here | Mechanism list |
| "assumed" | A number or choice with no basis in the code | `ASSUMPTION:` text; should become a field |
| "open decision" | The model can't compute this | Choice points; their notes already say so, as in "data the model does not hold" |

**A citation is not verification.** "Cited" means someone pointed at those lines, and the blind results show
this can still be wrong. Label the link as source, not as proof. The viewer's claim header (Task 5) is where
a reader does the check, and a later "this claim looks wrong" action could feed a fix round directly.

### What the data path needs

- The lists live in a workspace or `examples/`, with no API. They should be stored with the revision, like the
  document, and served by mosaicd. So should blind results, with their measured revision.
- `ASSUMPTION:` is a text convention. Promote it to a field, or at least lint it.
- **The list's areas don't match the UI's.** On vLLM the list has `scheduler-kv`, which no component uses as
  an owner, and 113 mechanisms under `distributed`, which owns 2 components. It has no list for `models-layers`,
  `kernels-ops` or `config-platform`. One vocabulary is needed before strips can roll up.
- Gate outputs (`check --inventory`, modeled coverage, hollow-scenario lint, behavior coverage) currently end
  in the terminal. Stored per revision, they can fill out Evidence.

---

## 6. What I couldn't check

- **Safari.** I tested only headless Chromium, so the memory reloads weren't reproduced. The link to big DOMs
  and traces is inference from Chromium numbers.
- **Real rendering speed.** Headless used software rendering on a server, over loopback. Frame times and load
  times will differ on a laptop, and tunnels or remote daemons will be slower.
- **Real newcomers.** Times and verdicts come from one expert walk through. Before building Concept A, test the
  naming and first screen with 3 to 5 people who don't know vLLM.
- **Exploration with real data.** No model has replay files. I saw its populated state only through stubbed
  responses, and I didn't press Remove or Replay.
- **Failures on Tests.** vLLM passes everything, so the failing layout was never seen live. On the largest model
  I didn't run Tests at all (3,376 scenarios). vLLM's run used `save=false`.
- **Commits and architecture diff.** Commits is empty on all three models, so the commit diff views and
  `FlowsChanged` weren't seen with data. I saw the revision diff only.
- **Compose pages.** Only the list, and not in depth.
- **Mechanism data in context.** The vLLM lists exist but aren't served, so all mechanism displays here are
  proposals. Those files are in progress. Bars in the mechanism wireframe are approximate.
- **Which figure goes with which model.** The 30% and 24% come from the brief. I didn't verify them.
- **Screen readers and full keyboard walks.** axe is automated, and doesn't judge whether the map or sequence
  make sense through a screen reader. My guess is they don't, and an outline trace would help a lot here.
- **Narrow screens.** One pass at 1024x768: the map works, the toolbar wraps, and the run panels weren't checked.

**Side effects of this review.** Six saved simulation runs were added through the UI (one Envoy, three vLLM, two
on the largest model). Other sampling used `save=false`. No model, replay or setting changed.

---

## Status

Built in November 2026 to [ux-plan-2026-11.md](ux-plan-2026-11.md), then checked together in Chromium on three models.

**Shipped.**

- Passport on the model cards, workspace header and Overview, read from stored evidence, with "Not benchmarked" when there's none.
- "Schema OK", no green for self-checks, "virtual" durations and "generated" inputs.
- Overview, and the new tabs. Old URLs still work.
- Atlas map with a 40-box rule, semantic zoom, four lenses and absent-mechanism ghost rows.
- Happy path first on Flows, scenario search, and scenarios indexed under each flow they touch.
- Run at the top of Simulate, the searchable fault picker, and "If this fails" on the component panel.
- Summary trace, jump keys, swimlanes by area, the run's mechanism warning, and run compare.
- Windowed lists and sequence diagram, a bounded query cache, gzip through the proxy, and validate results kept per revision.
- Evidence tab: per-area strips, mechanism filters, stored self-check reports with their caption, `save=false` by default, and "Not explored yet" in Race search.
- The citation viewer's claim header and "what else cites this file".
- Command palette and `?` sheet.
- Per-area revision diff.

**Not shipped.**

- Pass or fail from stored reports on flow and scenario rows.
- A dependency matrix, and a second tag level for big flow groups.
- A field for `ASSUMPTION:`, and the "assumed" mark.
- The "cited" and "cited, exercised" marks.
- Starting a race search from the UI.
- Drafts, which has only its slot, and family ties between models.

**Still not checked.** Safari, real newcomers, screen readers, populated Race search, a failing Tests layout, and the commit views with data.
