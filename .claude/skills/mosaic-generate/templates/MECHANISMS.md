<!--
Template: the mechanism list, per area (written by an enumerator agent, read by
`check --mechanisms`). The workspace and the area come from the agent's prompt.
-->

# Enumerate an area's mechanisms from the code

Inventory coverage counts entry points. It reads 100% while whole mechanisms are absent, and a
behavior can pass its own scenario while its result never reaches anyone. This list gives the model
a real denominator. You read the area's code and list every mechanism it runs, then map each one to
what the model has today. **You don't change the model.**

## What a mechanism is

A unit of system behavior that someone could observe working or not working, that takes more than
one function, and that a person would name when describing how the system works. Its kinds:

| Kind | Example |
|---|---|
| `loop` | a periodic pass, a reconcile tick, a watchdog |
| `sweep` | a garbage collector, a reaper, a janitor with a grace period |
| `lifecycle` | the states of a resource and what moves it between them |
| `pipeline` | data going through stages: buffer, flush, rate, write |
| `handshake` | a multi-message exchange: signed calls, enrollment, ready signals |
| `cache` | a cache with its fill, TTL and invalidation |
| `money` | a flow that moves or computes money or quota |
| `retry` | retries, backoff, recovery, fallbacks across failures |
| `gate` | an admission or policy chain with an order of checks |
| `dispatch` | routing or selection among implementations by capability or config |
| `metric` | a family of metrics someone operates on, with who feeds it |

Not mechanisms: one validation, one getter, one route with no behavior of its own, a helper. Group
them under the mechanism they serve. Aim for what a senior engineer would list on a whiteboard:
usually 15 to 60 per area. List what the code does, not what its docs say.

## Sources

- **The code:** the profile's `snapshot.path`, read-only. Your area's owned paths are in the profile's
  `areas`. Honor the profile's `snapshot.forbidden` list: never open those files.
- **The model:** `<workspace>/fragments/<area>.yaml`, or the merged `<workspace>/<repo>.json`, to map
  mechanisms to interfaces.
- **Never read** `BENCHMARK*.md`, `judge*/`, `oracle*/`, `build-oracle/`, `RESULTS.md`, `FIXES*.md` or
  `reconcile/`. The list has to come from the code; a list built from the last benchmark's misses
  would only re-measure that benchmark.

## How to enumerate

1. Walk your owned paths top down: process mains and what they start, background goroutines, tasks and
   threads, schedulers and timers, workers and consumers, then the request paths and what they
   trigger. Grep for loops, tickers, sleeps, retries and caches, so nothing long-running hides.
2. For each mechanism, read enough to state its trigger, its observable result and its citations.
3. Map it to the model: search for interfaces that claim to implement it, by citation first
   (a behavior or interface citing those lines), then by name. Read the behavior before you map it:
   an interface that only cites nearby lines, or returns a constant, doesn't implement the mechanism.
   List the interface a caller enters the mechanism through, and those that do its main work.

## Output

Write `<workspace>/mechanisms/<area>.json`, and nothing else:

```json
{
  "area": "<area>",
  "mechanisms": [
    {
      "id": "<area>.<kebab-name>",
      "kind": "sweep",
      "name": "Orphan-replica sweep",
      "trigger": "every reconcile tick, on the lease holder",
      "observable": "a replica with no owner is stopped and its row deleted within 5 minutes",
      "citations": ["path/to/file.go:120", "path/to/file.go:188"],
      "interfaces": ["serving-reaper.sweep"],
      "fidelity": "modeled"
    }
  ]
}
```

- `interfaces`: entity ids in the model, `[]` when the mechanism is absent. Their ids must exist.
- `fidelity`: your honest reading of the behavior against the code:
  - `absent`: nothing models it;
  - `shell`: an interface claims it but doesn't do it (returns a constant, has no caller, skips the
    work). Say why in a `note`;
  - `partial`: the main path is modeled; say what's missing in a `note`;
  - `modeled`: it runs as the code runs. Rate this only after reading the behavior's steps against
    the code, not its summary or step titles. If you only skimmed, say `partial`, with a note.
- Citations must resolve: real paths and lines in the snapshot.
- Sort by importance within the file: what an operator would miss first.

Don't commit, don't edit anything else, and don't spawn helper agents.

## Report (≤80 words)

The count per fidelity level, the three most important absent or shell mechanisms, and anything that
made the list incomplete.
