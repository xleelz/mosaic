# Coordination area notes

Fragment: `examples/cassandra/fragments/coordination.yaml`. It has 69 components (51 owned, 18
boundary stubs), 117 interfaces (82 owned, 35 stubs), 10 schemas, 17 flows and 75 scenarios.
Standalone check: 0 errors, 0 warnings, 75/75 scenarios pass, and 364/364 citations resolve.

All paths below are relative to the checkout root, and `SP` means
`src/java/org/apache/cassandra/service/StorageProxy.java`.

## 1. Entry points

### Modelled (19)

| Inventory entry | Covered by |
|---|---|
| messaging-verb `MUTATION_RSP` (Verb.java:115) | `write-response-handler.on-response`, called per ack in `storage-proxy.send-to-hinted-replicas` |
| messaging-verb `COUNTER_MUTATION_RSP` (Verb.java:136) | `write-response-handler.on-response` (counter leader ack) |
| messaging-verb `READ_RSP` (Verb.java:139), `RANGE_RSP` (Verb.java:141) | `read-callback.on-response` |
| messaging-verb `READ_REPAIR_REQ` (Verb.java:120) | `read-repair-verb-handler.do-verb` (flow `read-repair-replica`) |
| messaging-verb `READ_REPAIR_RSP` (Verb.java:119) | `blocking-partition-repair.on-response` |
| messaging-verb `TRUNCATE_RSP` (Verb.java:133) | `truncate-response-handler.on-response` (flow `truncate`) |
| verb-handler `ReadRepairVerbHandler.doVerb` | `read-repair-verb-handler.do-verb` |
| stage-task `Stage.COUNTER_MUTATION StorageProxy: counterWriteTask` (SP:250) | `storage-proxy.counter-write-task` (flows `counter-write`, `counter-leader`) |
| stage-task `Stage.READ AbstractReadExecutor.makeRequests` (AbstractReadExecutor.java:165) | `abstract-read-executor.make-requests` |
| stage-task `Stage.READ AbstractReadRepair.sendReadCommand` (AbstractReadRepair.java:99) | `abstract-read-repair.send-read-command` |
| stage-task `Stage.READ RangeCommandIterator.query` (RangeCommandIterator.java:207) | `range-command-iterator.query` (scenario `range-read-one-local`) |
| stage-task `Stage.READ ReplicaFilteringProtection.executeReadCommand` (:172) | `replica-filtering-protection.execute-read-command` (scenario `range-read-filtered-protection`) |
| stage-task `Stage.READ ShortReadPartitionsProtection.executeReadCommand` (:186) | `short-read-partitions-protection.execute-read-command` (reached through the `data-resolver.resolve.short_read` choice) |
| scheduled-task `DynamicEndpointSnitch.<init>: update` (:110), `applyConfigChanges: update` (:128) | `dynamic-endpoint-snitch.update-scores` (flow `dynamic-snitch-update`, repeat every 100ms) |
| scheduled-task `DynamicEndpointSnitch.<init>: reset` (:111), `applyConfigChanges: reset` (:138) | `dynamic-endpoint-snitch.reset` (flow `dynamic-snitch-reset`, repeat every 600000ms) |
| jmx-operation `DynamicEndpointSnitchMBean.setSeverity` | `dynamic-endpoint-snitch.set-severity` (flow `snitch-set-severity`) |

The coverage tool also counts a few neighbouring `Verb.java` lines and
`AbstractMutationVerbHandler.doVerb` as covered, because of its ±3-line tolerance and the
superclass citation. Those entries belong to their own handler owners, not to this area.

### Skipped entry points (11)

- **The 8 JMX attributes and operations in `DynamicEndpointSnitchMBean` other than `setSeverity`**
  (`getScoresWithPort`, `getScores`, `getUpdateInterval`, `getResetInterval`, `getBadnessThreshold`,
  `getSubsnitchClassName`, `getSeverity`, `dumpTimings`). Reason: they read snitch configuration,
  scores or latency samples and have no behaviour.
- **The 3 operations in `EndpointSnitchInfoMBean`** (`getRack`, `getDatacenter`, `getSnitchName`).
  Reason: they read the snitch's topology answers and have no behaviour.

### Under my paths but owned elsewhere

- **stage-task `Stage.MUTATION StorageProxy.submitHint`** (SP:2827) belongs to hints-batchlog,
  by the `submitHint` override.
- **The `StorageProxyMBean` jmx-operations** belong to ops (`service/*MBean.java`).
- **`TRUNCATE_REQ` and `TruncateVerbHandler.doVerb`** belong to write-path, which models
  `truncate-verb-handler`. I had claimed the handler at first, then turned my copy into a
  boundary stub.
- **I claim `ReadRepairVerbHandler`.** No row of the ownership table names
  `db/ReadRepairVerbHandler.java`, and the brief lists read repair as a coordination entry point.
  No other fragment defines the handler.

## 2. Components modelled (owned)

| Component | Code |
|---|---|
| `storage-proxy` and its runnables `storage-proxy-local-read-runnable`, `-local-mutation-runnable`, `-droppable-runnable` | SP:187-266, 2178-2275, 2623-2680, 2586-2616 |
| `abstract-write-response-handler`, `write-response-handler`, `datacenter-write-response-handler`, `datacenter-sync-write-response-handler` | service/*WriteResponseHandler.java |
| `truncate-response-handler` | service/TruncateResponseHandler.java:44-115 |
| `consistency-level` | db/ConsistencyLevel.java:35-278 |
| `replica-plans`, `replica-layout` | locator/ReplicaPlans.java, locator/ReplicaLayout.java |
| `abstract-replication-strategy`, `simple-strategy`, `network-topology-strategy`, `local-strategy` | locator/*Strategy.java |
| `dynamic-endpoint-snitch`, `simple-snitch`, `gossiping-property-file-snitch`, `property-file-snitch`, `endpoint-snitch-info` | locator/*Snitch*.java |
| `abstract-read-executor` and its never-, always- and speculating executors; the five speculative retry policies | service/reads/AbstractReadExecutor.java, service/reads/*SpeculativeRetryPolicy.java |
| `read-callback`, `digest-resolver`, `data-resolver`, `replica-filtering-protection`, `short-read-partitions-protection`, `coordinator-warnings` | service/reads/** |
| `abstract-read-repair`, `blocking-read-repair`, `read-only-read-repair`, `blocking-partition-repair`, `row-iterator-merge-listener` | service/reads/repair/** |
| `read-repair-verb-handler` | db/ReadRepairVerbHandler.java:25-44 |
| `range-commands`, `replica-plan-iterator`, `replica-plan-merger`, `range-command-iterator`, `scan-all-ranges-command-iterator` | service/reads/range/** |
| `abstract-query-pager`, `single-partition-pager`, `partition-range-query-pager`, `multi-partition-pager` | service/pager/** |

Flows: `coordinator-write`, `counter-write`, `counter-leader`, `coordinator-read`, `range-read`,
`truncate`, `paged-read`, `read-repair-replica`, `view-mutation`, `batchlog-endpoints`,
`applies-locally`, `dynamic-snitch-update`, `dynamic-snitch-reset`, `snitch-set-severity`, and three
`validate-*-consistency` flows.

I also define these interfaces because other areas stub them:
- `storage-proxy.read-one`, `storage-proxy.fetch-rows` and `replica-plans.for-paxos` (for paxos);
- `replica-plans.for-batchlog-write` and `storage-proxy.applies-locally` (for hints-batchlog);
- `storage-proxy.apply-counter-mutation-on-leader` and `storage-proxy.mutate-mv` (for write-path);
- `consistency-level.validate-for-read`, `validate-for-write` and `validate-counter-for-write`
  (for cql).

## 3. Boundary stubs and whose contract I copied

- **membership**, copied from membership.yaml:
  - `failure-detector.is-alive` ({endpoint} → {endpoint, alive});
  - `token-metadata.get-write-endpoints` (the natural + pending contract);
  - `token-metadata.get-replication-factor`, `token-metadata.get-host-id`,
    `token-metadata.get-all-endpoints`;
  - `gossiper.get-live-members` ({members}), `gossiper.add-local-application-state`;
  - `storage-service.is-joined`.
- **membership, not defined there yet** (shared shapes; I need them added):
  - `token-metadata.sorted-tokens` (the ring for range splitting);
  - `gossiper.get-endpoint-downtime`, `gossiper.get-unreachable-token-owners`;
  - `storage-service.is-bootstrap-mode` (aligned with read-path's stub: {bootstrapping});
  - `storage-service.is-rpc-ready` (as transport has it);
  - `storage-service.get-live-ring-members`;
  - `storage-service.is-endpoint-valid-for-write` (as write-path has it).
- **write-path**, copied from write-path.yaml: `keyspace.apply`, `mutation-verb-handler.do-verb`,
  `counter-mutation-verb-handler.do-verb` ({counter_mutation}), `counter-mutation.apply-counter-mutation`,
  `column-family-store.truncate-blocking`, `truncate-verb-handler.do-verb` and
  `view-manager.updates-affect-view` ({affected}). `view-utils.get-view-natural-endpoint` is not
  in write-path's fragment yet.
- **read-path**, copied from read-path.yaml: `read-command-verb-handler.do-verb`,
  `read-command.execute-locally` and `read-command.create-response`. The response is
  ReadPathReadResponse: digest plus partitions of cells.
- **hints-batchlog**, copied: `storage-proxy.submit-hint` (one target per call),
  `storage-proxy.mutate-atomically`, `hints-service.find-oldest-hint-timestamp` ({timestamp}),
  `hints-service.get-total-hints-size` and `batchlog-manager.store`.
- **paxos**, copied: `storage-proxy.read-with-paxos`.
- **schema-auth** (their fragment didn't parse when I checked; shared shapes):
  `partition-denylist.is-key-permitted`, `partition-denylist.get-denied-keys-in-range-count`.
- **ops**: `fb-utilities.get-broadcast-address-and-port`, which gives this node's address.

The membership, ops and some schema-auth stubs carry a `store` with defaults, so standalone
scenarios can set liveness, the ring and so on. In the merge the owner's definition wins, so my
scenarios' `state` keys for those components (`failure-detector.endpoints`,
`token-metadata.write_endpoints`, `fb-utilities.local`) will need re-pointing to the owners'
state in the reconciliation round.

## 4. Deployed configuration read

| Setting | conf/cassandra.yaml | Config.java default | Used in |
|---|---|---|---|
| write_request_timeout | 2000ms (:1330) | 2000ms (:151) | `timeout_ms: 2000` on MUTATION_REQ and READ_REPAIR_REQ calls |
| read_request_timeout | 5000ms (:1322) | 5000ms (:145) | READ_REQ calls; speculation cut-off |
| range_request_timeout | 10000ms (:1326) | 10000ms (:148) | RANGE_REQ calls |
| counter_write_request_timeout | 5000ms (:1334) | 5000ms (:154) | COUNTER_MUTATION_REQ calls |
| truncate_request_timeout | 60000ms (:1345) | 60000ms (:160) | TRUNCATE_REQ calls |
| cas_contention_timeout | **1000ms** (:1339) | **1800ms** (:157) | paxos area; **differs** |
| hinted_handoff_enabled | true (:68) | true (:112) | `storage-proxy` state |
| hinted_handoff_disabled_datacenters | commented (:72) | empty | state |
| max_hint_window | 3h (:80) | 3h (:115) | state 10800000 |
| hint_window_persistent_enabled | commented (:152) | true (:117) | state |
| max_hints_size_per_host | commented (:111) | 0 = off (:448) | state |
| use_creation_time_for_hint_ttl | not set | true (:453) | not modelled (hint TTL) |
| endpoint_snitch | SimpleSnitch (:1556) | none | every node in datacenter1/rack1 |
| dynamic_snitch | not set | true (:424) | DynamicEndpointSnitch wraps SimpleSnitch |
| dynamic_snitch_update_interval | 100ms (:1561) | 100ms (:426) | flow repeat interval |
| dynamic_snitch_reset_interval | 600000ms (:1565) | 10m (:428) | same value |
| dynamic_snitch_badness_threshold | 1.0 (:1573) | 1.0 (:429) | state |
| ideal_consistency_level | commented (:1883) | null (:560) | no ideal-CL handler |
| partition_denylist_enabled | commented (:1438) | false (:759) | state; checks skipped by default |
| denylist_{writes,reads,range_reads}_enabled | commented | true (:761-765) | state |
| reject_out_of_token_range_requests | not set | false (:793) | `read-repair-verb-handler` state |
| read_thresholds_enabled | commented false (:2015) | false (:526) | warnings/abort path not modelled |
| repaired_data_tracking_for_*_reads_enabled | false (:1952-1953) | false (:721-722) | not tracked |
| replica_filtering_protection cached rows warn/fail | 2000 / 32000 (:1834-1835) | same | thresholds not modelled |
| batchlog_endpoint_strategy | commented (:183) | random_remote (:442) | `for-batchlog-write` |
| table speculative_retry | n/a | 99p (TableParams.java:366) | `abstract-read-executor` state |
| table read_repair | n/a | BLOCKING (TableParams.java:374) | state |
| sampleReadLatencyMicros (initial) | n/a | read timeout / 2 = 2500ms (ColumnFamilyStore.java:498) | state |

The only yaml/Config difference I touched is cas_contention_timeout: 1000ms in the yaml against
1800ms in Config.java. dynamic_snitch_reset_interval is written differently (600000ms vs 10m) but
is the same value.

## 5. What the code didn't settle, and assumptions

- **Ring and tokens.** Three nodes, one token each, matching membership:
  10.0.0.1:-6148914691236517206, 10.0.0.2:0, 10.0.0.3:6148914691236517205. RF 3 and
  SimpleStrategy. Token 100 → natural replicas [10.0.0.3, 10.0.0.1, 10.0.0.2]. This node is
  10.0.0.1.
- **Single datacenter.** SimpleSnitch puts every node in datacenter1, so LOCAL_ONE, LOCAL_QUORUM
  and EACH_QUORUM count the same replicas as ONE and QUORUM. The DC-specific branches are cited
  but not exercised.
- **Random choices are `choice` points:** the counter leader
  (`storage-proxy.find-suitable-replica.leader`) and the batchlog endpoint shuffle
  (`replica-plans.for-batchlog-write.pick`).
- **Standalone read repair is forced through choices.** Stub replicas all return the same data,
  so `digest-resolver.responses-match.digests` and `row-iterator-merge-listener.close.divergence`
  have data-driven defaults (digest equality, and per-partition cell comparison after a
  newest-cell-wins merge), and scenarios override them. With the override and no real divergence,
  the last responder is treated as stale.
- **Read-repair mutations carry `cells`** ([{column, value, timestamp}]) and an empty `columns`
  map. CEL can't build a map from a list (see §7). write-path's `keyspace.apply` would need to
  apply `cells` for repairs to land in the merged model.
- **`rows` returned by reads are read-path partitions** (`{partition_key, cells, timestamp}`), not
  column maps.
- **`mutate-mv` uses "not joined"** in place of `isStarting() || isJoining() || isMoving()`.
- **`storage-proxy.read` takes a single `read_command`**, a Group of one. IN-query groups and the
  cross-command limit filter (SP:2015-2018) aren't modelled.
- **Range reads model only the full-ring query** (MIN..MIN) split at ring tokens. Read repair of a
  range uses the piece's right token for its write plan.

## 6. Where docs or common knowledge disagree with the code

- **No probabilistic background read repair.** `read_repair_chance` is gone. Read repair happens
  only on a digest mismatch inside the read, and the read blocks on the repair writes (BLOCKING is
  the default; NONE never writes).
- **Hints are also written for live replicas that time out or fail**
  (AbstractWriteResponseHandler.java:309-310), not only for nodes known to be down.
- **QUORUM with one replica down and another failing gives WriteTimeout, not WriteFailure.** The
  never-sent request to the down node isn't counted as a failure, so blockFor + failures never
  exceeds the candidate count (AbstractWriteResponseHandler.java:129). Scenario:
  `write-quorum-down-plus-failure-times-out`.
- **SimpleSnitch doesn't prefer the local node.** A CL.ONE read goes to the first natural replica
  in ring order, which may be remote (scenario `read-one-closest-replica`).
- **`speculative_retry = ALWAYS` at QUORUM with RF 3 doesn't speculate.** blockFor + 1 equals every
  candidate, and the "no extra replicas" check comes first, so a NeverSpeculatingReadExecutor is
  used (AbstractReadExecutor.java:209-216).
- **The counter leader is a random live local-DC replica**, not preferentially the coordinator
  (SP:1785-1801).
- **A replica failure decides a read before speculation can help.** A tombstone failure on the
  data replica signals the callback at once, so no speculative read is sent and the read fails
  (scenario `read-tombstone-failure`).
- **Truncate needs every token owner up**, as if it were CL.ALL (SP:2514-2522).
- **`forBatchlogWrite(isAny=true)` with no live peer still fails.** It falls back to this node but
  keeps CL TWO, computed before the fallback, so the plan is still Unavailable (required 2,
  alive 1).
- **Read-repair mutations use their own verb** (no hints on timeout). They expire after
  write_request_timeout, but the coordinator waits until the read deadline.
- **`ConsistencyLevel.blockFor` throws UnsupportedOperationException for NODE_LOCAL**
  (ConsistencyLevel.java:167-168).

## 7. Simulator gaps

- **Parallel fan-out is sequential.** Example: a QUORUM write where both remote replicas hang takes
  2 × 2000ms in the simulator (scenario `write-quorum-two-timeouts`, `duration_ms >= 4000`), where
  Cassandra waits 2000ms once.
- **No "wait for the first k of n".** Every replica call completes, in order, before the handler
  decides. Responses that would arrive after blockFor is met are still counted. Late responses and
  the race between callback expiry and `get()` can't be shown.
- **Speculative timing.** Cassandra speculates after the p99 sample latency (2500ms initially).
  The simulator can only decide after the initial calls finished, so a hung replica costs the full
  5000ms before the speculative read (scenario `read-speculative-retry`). The model treats "timeout
  failures" as not yet arrived and "error failures" as already arrived, to reproduce the
  signal-before-speculation ordering.
- **Async hint writes and callback expiry.** onFailure hints run when the callback expires; here
  they run inline. The ack that a stored hint gives for CL.ANY is counted once per submit, whatever
  the order.
- **No map construction in CEL.** The engine's CEL lacks two-variable comprehensions
  (`transformMap`), so a list of cells can't become a `columns` map. Repair mutations therefore
  carry `cells`, and read results stay as partitions.
- **Unordered choices for randomness.** ThreadLocalRandom picks (counter leader, batchlog shuffle,
  forwarding replica) are fixed choice options, not seeded random draws.
- **Stage queues and deadlines.** DroppableRunnable and LocalMutationRunnable drop work whose
  deadline has passed (a local mutation then becomes a hint for this node). The simulator has no
  queueing delay to trigger it.
- **Range concurrency.** `concurrencyFactor` batches of sub-range queries, and the row-count
  feedback that grows them, become one sequential pass over the merged plans.

## 8. Known gaps

- Multi-DC behaviour isn't exercised: DatacenterSyncWriteResponseHandler per-DC counting,
  forwarding to one replica per remote DC (SP:1604-1642), and EACH_QUORUM read contacts.
- Transient replication and the cheap-quorum `maybeTryAdditionalReplicas` sends are cited, but
  always no-ops.
- Ideal-CL tracking, coordinator warnings and read-threshold aborts, repaired-data tracking, and
  DuplicateRowChecker aren't modelled.
- Short read protection is reachable only through a choice. Replica filtering protection runs one
  re-query, without row caching or its thresholds.
- `dynamic-endpoint-snitch.receive-timing` (latency samples from responses) isn't wired into the
  read path. Scores come from scenario-set samples, and gossip SEVERITY isn't added to scores.
- LocalStrategy (system keyspaces) and the TokenMetadata replica cache aren't modelled.
- Paging state serialisation and MultiPartitionPager chaining are reduced to one `fetch-page`
  interface.
- After the merge, my scenarios still set my store-stub state (liveness, ring, local endpoint).
  They must be rewritten against membership's and ops' state in the reconciliation round. cql
  currently calls `storage-proxy.read` without `read_command`, and its stubs mark my errors
  `retryable: true`.

## Reconciliation round changes

- **Scenario state moved to membership's components** (decision 4).
  - Nodes go down through `gossiper.endpoint_state_map`.
  - Pending replicas come from `token-metadata.pending_ranges`.
  - The topology comes from `token-metadata.ring`.
  - "Coordinator not a replica" now uses a 4-node ring (10.0.0.4 at token 3000000000000000000)
    with a mutation token of -100, so the replicas are 10.0.0.2, .4 and .3.
  - Bootstrap mode is `storage-service.is_bootstrap_mode`, and "not joined" is
    `storage-service.survey_mode`.
  - Materialized views are `view-manager.views_by_base_table`.
  - My stubs keep their `store` defaults only so the standalone run has values. In the merge the
    owners' definitions replace them.
- **`storage-service.is-bootstrap-mode`** now returns `{bootstrap_mode}`.
- **New owned interface `storage-proxy.is-safe-to-perform-read`** (SP:1888-1896, 1840-1846).
  `storage-proxy.read` calls it.
- **Assertions now count only my own interfaces** (decision 9).
  - Local reads are `storage-proxy-local-read-runnable.run`, not `read-command.execute-locally`,
    because ReadCommandVerbHandler.java:92-93 also runs `execute-locally` on remote replicas.
  - Local writes are `storage-proxy.perform-locally`, not `keyspace.apply`.
  - The counter leader is `storage-proxy.counter-write-task`, not
    `counter-mutation.apply-counter-mutation`.
- **Stub kinds now match their owners:** `batchlog-manager` and `hints-service` are `module`.
- **Skips** are expanded into `skips/coordination.json` (11 entries).
- **`counter-no-live-replica` was impossible as written.** It marked this node down, but
  FailureDetector.java:301-302 always reports the local node alive. It now uses a 4-node ring where
  this node is not a replica, with the three replicas down.
- **Batches.** `CoordinationWriteRequest.mutations` no longer has `maxItems: 1`, because
  mutateWithTriggers takes the whole list of a batch. New scenario
  `write-unlogged-batch-two-mutations`.
- **Re-pointed to the owners' real interfaces:**
  - out-of-range read repair uses membership's ring (token -100 sent to 10.0.0.1);
  - the hint window uses `gossiper.endpoint_state_map.<ep>.down_since_ms`;
  - view pairing uses write-path's `view-utils.get-view-natural-endpoint.pairing` choice. My stub
    mirrors that choice so the standalone run still validates.
- **Standalone failures that are expected:** 24 scenarios now depend on the real definitions in
  membership (liveness, ring, pending ranges, bootstrap mode, survey mode) and write-path
  (`views_by_base_table`). They fail when run with my stubs alone.

## Migration round (instances, parallel joins, deadlines, configs)

**Converted.**
- **Instances.** Verb calls now take `on: <replica>`, and `to` fields are gone: 10 call sites,
  plus the request schemas of my 5 verb stubs and of `read-repair-verb-handler`. `fb-utilities` is
  replaced by `self`. Every `10.0.0.x` is now `n1`–`n4`.
- **Scenario setup.** Scenarios use `three-node-rf3` or `four-node-rf3`, and nodes go down through
  `gossiper@n1.endpoint_state_map`.
- **Faults.** Faults that targeted "the Nth call" now target an instance.
- **Fan-outs.** Six sequential fan-outs became `parallel`:
  - the write fan-out, with `need` = blockFor minus any ANY-hint ack;
  - the read executor, with data and digest requests plus a speculative branch due after the
    sampled latency;
  - the repair reads, with a speculative branch;
  - the repair writes, with speculative writes after the additional-write latency;
  - the range sub-queries;
  - truncate (join all).
- **Configs.** 20 config entities: the five request timeouts, the hint settings, the denylist
  switches, the dynamic snitch settings, reject-out-of-token-range-requests, and the initial
  sample-read and additional-write latencies.
- **Read-back scenarios.** Eight flows are tagged `writes`, each with a multi-step read-back
  scenario.

**Judged errors fixed.**
- **W4.** A QUORUM write with two hung replicas now fails with WriteTimeout at 2000 ms, not
  4082 ms (`write-quorum-two-timeouts`).
- **W5.** A ONE write returns on the first ack, and the slow replica is hinted late
  (`write-one-replica-timeout-hinted`, duration under 100 ms).
- **Down replicas get one HintRunnable** (SP:1563-1564; `write-any-all-replicas-down` makes one
  submit-hint call with 3 targets).
- **R4.** Speculation fires at the 2500 ms sample latency, both for a hung replica and for a slow
  one (`read-speculative-retry`, `read-slow-replica-speculates`).
- **R2.** The coordinator merge keeps tombstones and partition deletions, picks the winner with
  `Cells.reconcile` (newest wins, then the tombstone, then the greater value), sends tombstones in
  repairs, and filters only after merging (DataResolver.java:315-317; DigestResolver.java:81-84).
  Scenario: `read-repair-newer-delete-wins`.
- **Read repair writes reach storage** (`read-repair-reaches-storage`: n3 serves the repaired value
  locally afterwards).

**How the write join decides.** `abstract-write-response-handler.get` replays the code's rule over
the recorded ack and failure times. It signals early only when blockFor + failures exceeds the
candidates, which counts down replicas too, and otherwise waits until the request start plus the
timeout. A side effect: a mix of one timeout and one failure now gives WriteTimeout, because the
handler's deadline comes before the callback expiry.

**Simulator gaps.**
- *Resolved:* parallel fan-out and the shared deadline; returning on the first k acks; speculation
  timing; work after the response (late hints); the map-from-list problem (`merge`, two-variable
  macros).
- *Still open:*
  - Mutations in one batch are still awaited one after another.
  - A digest-only quorum, with no data response, ends the join without waiting for data.
  - ~~A failure-decided read with a speculative branch pending is decided at the speculation time,
    not at the failure.~~ Fixed in the fix round (fail-fast join).
  - The clock can't be rewound to the signal time.

**Engine issues found.**
- A number config deployed as `1.0` reaches CEL as an int type that has no `double()` or
  `string()` overload. I work around it with `double(int(...))`.
- `entry.deadline_ms` accepts only a literal, which currently breaks write-path's fragment.

## Fix round (R6, R2)

- **R6, fail-fast read join.** `abstract-read-executor.execute-async` now delays the speculative
  branch through `stagger_ms` (the sampled read latency, 2500ms before any sample) instead of a
  `wait` inside the branch, and its join sets `count_unstarted: false`. A tombstone-overwhelmed
  replica's failure response now fails the read at once once blockFor + failures > contacts
  (`ReadCallback.java:241-250`, the check at 247-248); the unsent speculative request is skipped.
  `bench-r6-failure-signals-immediately` passes (ReadFailure in ms, not at 2500ms).
- **R2, per-replica repair diffs.** `row-iterator-merge-listener.close` builds one mutation per
  stale replica holding only the merged cells that replica lacks or holds older, plus the
  partition deletion if its own is older (`RowIteratorMergeListener.java:382-398`). A replica
  with an empty diff gets no mutation (`createRepairMutation` returns null). Only a forced
  `stale_replicas` choice with no real divergence still sends the merged partition. Speculated
  repair writes to uncontacted replicas carry the union of the diffs
  (`mergeUnackedUpdates`, `BlockingPartitionRepair.java:132-137`). Approximation: the union covers
  every diff, not only the unacked ones.

### Breaking changes

- coordination, `blocking-read-repair.repair-partition`: request `{mutation, targets,
  write_plan}` is now `{mutations: [{replica, mutation}], write_plan}`.
- coordination, `blocking-partition-repair.send-initial-repairs`: request `{mutation, targets,
  write_plan, block_for}` is now `{mutations: [{replica, mutation}], write_plan, block_for}`.
- Callers: only `row-iterator-merge-listener.close` and `blocking-read-repair.repair-partition`,
  both in this fragment and both fixed. No other area or judge scenario calls these.
