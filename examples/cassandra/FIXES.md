# Fix round (Cassandra, after round 2)

`RESULTS.md` (round 2) lists the claims still wrong, and the simulator gaps since closed (DESIGN
§13.1 items 12–18). This round fixes them.

- The rules in `BRIEF.md`, `RECONCILE.md` and `MIGRATE.md` still apply.
- **You may now read `judge/v2/`** files that concern your area. Fix the model, never the judges'
  scenarios.

## New tools since round 2

- **Joins:**
  - fail-fast joins (`join.count_unstarted: false`);
  - `on_late` for branches that finish after the join.
- **Concurrency:** the cooperative scheduler, overlapping steps (`at_ms`, `await: false`),
  `rendezvous`, and channels (`put`/`receive`).
- **Cancellation:** tokens.
- **Instances:** `kill` and `restart`.
- **Streams:** a callee uses `yield`; the caller sets `stream: true`.
- **Time:** microseconds.
- **Gates:** `--lint trivial`, `--min-substantive` and `--tests`.

## Breaking changes

When making an interface match the code changes its shape, change it. Never keep a shim or a
parallel interface just so old callers still pass. List every caller you break, with
citations, under **Breaking changes** in `notes/<area>.md` and in your report: the area, the
interface or scenario, and what it must now read. Fix callers in your own fragment. The
coordinator routes the rest.

**Fix through your generator.** If `gen/<area>/` builds your fragment, put the fixes there and
regenerate; a rebuild must reproduce your fragment byte for byte.

## Fix list by area

| Area | Fix |
|---|---|
| write-path | A flush moves the memtable's cells into the new SSTable, and later reads go to the SSTable (W9). Commit-log discard deletes only unused segments (`CommitLog.java:366-370`) |
| cql + write-path | A batch writing two tables with the same partition key writes both tables (`B1-xtable`) |
| coordination | A tombstone-overwhelmed replica fails the read at once. Use a fail-fast join, `count_unstarted: false`, so a pending speculative read doesn't hold it open (R6, `ReadCallback.java:247-248`). Read repair sends each replica its own diff, not the whole merged partition (R2) |
| repair-streaming + read-path | SSTables streamed in during incremental repair are marked pending repair (P2, `CassandraStreamReader.java:105,135`). `gc_grace_seconds` is evaluated when purging tombstones (C1) |
| membership | Bootstrap streams each range from the replica that is losing it (G3, `RangeStreamer.java:494-521`). `gossiper.start` schedules the gossip task, builds the seed list and creates the node's own state (G1), or narrows its citations to what it models. Live peers come from each node's `alive` flag. Peers gossip during RING_DELAY (overlapping steps) |
| hints-batchlog | Batchlog cleanup reacts to late acks (`on_late`). The replay throttle timing |
| fixtures (coordinator, done) | n1 is removed from its own seed list. Membership must now fix two scenarios that depended on it: `mem-reload-seeds-empty-keeps-current` and `mem-startup-concurrent-range-movement-allowed` |

## Verify

The gate is MIGRATE.md's command plus
`--lint hollow,trivial --max-trivial 0.35 --min-substantive 0.5`. Also re-run your
`judge/v2/scenarios` cases against the merged model.

**Exit criteria:** the cases that failed or were partial now pass, or are explained, and the gate
is green.

## Report (≤120 words)

Report the fixes with citations, the cases now passing, and what's still open.
