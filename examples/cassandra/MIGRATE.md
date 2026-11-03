# Migration round: move the Cassandra model onto mosaic's new building blocks, and fix it

The engine now implements docs/DESIGN.md §11–13: instances, `parallel` with joins, deadlines,
timers, capacity, publish/subscribe, configs, fixtures, multi-step scenarios, trace assertions and
mocks. Read **§11 and §13.1 in full**, plus `.claude/skills/mosaic-simulation/references/` and
`docs/PIPELINE.md`.

The rules in `BRIEF.md` still apply: code only, citations, your files only, and no
`BENCHMARK.md` or `judge/` until this round's last step. One exception: this round, you **must**
read the judge findings for your area (listed per area below), since they're your fix list.

## 1. Shared world: `fixtures.yaml` (written first, by the fixtures agent)

- **Instances are named `n1`, `n2`, `n3`, and `n4` when needed.** Endpoint strings such as
  `10.0.0.2` disappear from behaviors. Wherever the code uses an endpoint, the model uses the
  instance name, so data and topology agree.
- **`fixtures.yaml` is owned by the coordinator and authored by the fixtures agent.** It defines:
  - `base-schema`: keyspaces `ks1` and `shop` with their tables. Every area's keyspace, table and
    schema state is seeded from here, and no area may keep a private keyspace list. This fixes
    the `shop.users` seam.
  - `auth-users`: roles and passwords, as transport and schema-auth seeded them.
  - `three-node-rf3`: topology `cassandra-node: [n1, n2, n3]`, the token ring, endpoint states
    (all alive), the clock epoch `2026-10-30T00:00:00Z`, and `extends: [base-schema]`.
  - `four-node-rf3`: as above with n4, for "coordinator not a replica" and "all replicas down"
    cases.
  - Fixtures carry config **overrides** only. The config entities themselves (§2) belong to the
    areas that read them.
- Scenarios use `fixtures: [three-node-rf3]` (or another fixture) instead of seeding their own
  ring, schema or users. Seed only what is specific to the scenario.

## 2. What each area converts

1. **Instances instead of the `to` field.** Verb-handler calls take `on: "= vars.replica"`.
   Per-replica stores (`replica + ':' + key`) become plain keys on per-instance state. Faults
   that target "the Nth call" become `instance: n2` faults or state (a node down in
   `gossiper@n1`'s endpoint state map). Membership's gossip state becomes per instance, so each
   node has its own view.
2. **`parallel` instead of sequential `foreach` fan-out.** Replica fan-out uses `parallel` with
   `join: {need: "= vars.block_for"}` and `on_insufficient` set to the real exception. Speculative
   retry uses `stagger_ms`. Every "simulator gap" in your notes that this resolves gets resolved,
   and your scenarios must then show the real timing (for example, a QUORUM write with two hung
   replicas times out at 2000 ms).
3. **Deadlines and config.** Every timeout or limit read from `cassandra.yaml` or `Config.java`
   becomes a `config` entity in your fragment: its id, `value` (deployed), `default` (code), and
   sources for both. Behaviors read `config['…']`. Request timeouts become `deadline_ms` on the
   coordinator's entry, or `timeout_ms` on the join, matching where the code applies them.
4. **Timers and capacity.**
   - Periodic tasks use `entry.repeat` with `initial_delay_ms` (for example, the 30 s batchlog
     replay start), or `emit` with `every_ms`.
   - Stages and executors whose queueing matters get `capacity`.
5. **Publish and subscribe** for endpoint lifecycle subscribers, schema change listeners and
   client events, where the code uses listener lists.
6. **Multi-step scenarios.** Tag every flow that writes state with `tags: [writes]`, and give it
   at least one write-then-read scenario. Use steps for PREPARE then EXECUTE, login then query,
   gossip rounds then a hint dispatch, and similar sequences.
7. **Incidental state.** Tag caches, rate limiters, metrics and warning buffers `incidental` (or
   give them the kind `cache`, `limiter` or `metrics`).
8. **No mocks** in any scenario.

## 3. Fix the judged errors in your area

These are from `RESULTS.md` and `judge/<group>.md`. Read the judge files for detail and evidence.

| Area | Fixes |
|---|---|
| write-path | Know every table through `base-schema`; unknown tables fail as the code fails. Commit log append before the unknown-table check (`Keyspace.java:624-634`). Startup replay is reachable with real segments. A flush submits background compaction (read-path's stub) |
| read-path | Replicas keep tombstones in responses, and the coordinator merges them (`DataResolver.java:315-317`). Equal-timestamp merges use `Cells.reconcile`. Tombstone warnings reach the client (`ClientWarn.warn`, `ReadCommand.java:631`). STCS picks the hottest bucket. Promoting SSTables after incremental repair FINALIZED (`RepairFinishedCompactionTask`) |
| coordination | `parallel` replica fan-out for writes, reads, digests and speculation. One hint runnable for all down replicas (`StorageProxy.java:1563`). Read repair writes reach storage |
| hints-batchlog | `should-hint` uses the one clock (`now`). Hint dispatch is the 10 s alive-check poll (judge H1). Batchlog replay starts after the delay the code uses |
| membership | Per-instance gossip state. `mark-dead` keeps the original down-since time. Decommission streams to the real new owners, and is refused when RF equals the cluster size (judge G4). Bootstrap streams from the other owners, not itself, with ranges. The phi conviction threshold as config |
| paxos | A v1 commit runs `forWrite`'s live-replica check (`StorageProxy.java:785`, `ReplicaPlans.java:475`). CAS and SERIAL results carry the `[applied]` column. Contention as concurrent proposers where `parallel` allows |
| cql | DDL and role statements are reachable from QUERY (`process-statement` dispatches them to schema-auth). CAS results expose `[applied]` |
| schema-auth | DDL is dispatched from cql's `process-statement`. Push and pull agreement across instances (`S1`) |
| repair-streaming | Incremental repair marks pending-repair SSTables and finalizes (`P2`). Validation and sync fan-out with `parallel` |
| transport | Overload behavior per the deployed config (`T3`). PREPARE then EXECUTE and login then query as multi-step scenarios |
| ops | Re-copy the owners' contracts. nodetool flows use the shared fixtures |

## 4. Verify

The merged check with the full quality gate, from `/home/lbethay/workplace/mosaic`:

```sh
F=""; for f in examples/cassandra/fragments/*.yaml; do F="$F -f $f"; done
PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly go run ./internal/devtools/check \
  -f examples/cassandra/skeleton.yaml -f examples/cassandra/fixtures.yaml $F \
  --code /home/lbethay/.cache/cassandra-bench/cassandra-5.0.9 --strict-citations \
  --inventory examples/cassandra/inventory.json \
  --behavior-coverage --lint hollow --no-mocks
```

**Exit criteria for your fragment:**
- 0 errors, and none of your scenarios fail.
- No merge warnings or lint gate findings name your fragment.
- No mocks.
- Your behavior coverage is no lower than in `quality-baseline.md`.
- Every `writes` flow has a read-back scenario.

Other areas are editing at the same time. A failure caused by another area isn't yours: report
it, and don't work around it.

## 5. Report (≤150 words)

- What you converted: counts of `to` fields removed, foreach fan-outs turned into `parallel`,
  configs added and `writes` flows.
- The judged errors you fixed, with citations.
- The simulator gaps resolved, and those still open.
- Your gate results: coverage before and after, and lint findings.
