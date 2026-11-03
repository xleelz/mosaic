# paxos area notes

Fragment: `examples/cassandra/fragments/paxos.yaml`. Code: cassandra-5.0.9 (`b5f2a54210`). All
paths below are relative to the checkout root, and `SP` stands for
`src/java/org/apache/cassandra/service/StorageProxy.java`, `PX` for `src/java/org/apache/cassandra/service/paxos/`.

Final check (skeleton + this fragment): 65 components (20 boundary stubs), 86 interfaces,
10 schemas, 12 flows, 72 scenarios. 0 validation errors, 72 of 72 scenarios pass, and
393 of 393 citations resolve. 43 inventory entries are covered and none are skipped.

## 1. Entry points

All 43 inventory entries under the paxos paths are **covered**, and none are skipped.

| Inventory entry | Covered by |
|---|---|
| `PAXOS_PREPARE_REQ` Verb.java:127, `PrepareVerbHandler` (PrepareVerbHandler.java:26), `AbstractPaxosVerbHandler.doVerb` (AbstractPaxosVerbHandler.java:43) | `prepare-verb-handler.do-verb` (flows `lwt-cas`, `lwt-serial-read`, `paxos-v1-prepare-replica`), `abstract-paxos-verb-handler.do-verb` |
| `PAXOS_PREPARE_RSP` Verb.java:126 | `storage-proxy.prepare-paxos` (the sender) |
| `PAXOS_PROPOSE_REQ` Verb.java:129, `ProposeVerbHandler` | `propose-verb-handler.do-verb` (flow `paxos-v1-propose-replica`) |
| `PAXOS_PROPOSE_RSP` Verb.java:128 | `storage-proxy.propose-paxos` |
| `PAXOS_COMMIT_REQ` Verb.java:131, `PaxosCommit.RequestHandler.doVerb` | `paxos-commit-request-handler.do-verb` (flow `paxos-commit-replica`; v1 and v2 both send this verb) |
| `PAXOS_COMMIT_RSP` Verb.java:130 | `storage-proxy.commit-paxos`, `paxos-commit.commit` |
| `PAXOS2_COMMIT_REMOTE_RSP` Verb.java:187 | `paxos-commit.commit` (narrated; it needs a second DC) |
| `PAXOS2_PREPARE_REQ/RSP` 189/188, `PaxosPrepare.RequestHandler.doVerb` | `paxos-prepare-request-handler.do-verb` (flow `paxos-v2-prepare-replica`), `paxos-prepare.start` |
| `PAXOS2_PREPARE_REFRESH_REQ/RSP` 191/190, handler | `paxos-prepare-refresh-request-handler.do-verb` (flow `paxos-v2-prepare-refresh-replica`), `paxos-prepare-refresh.refresh` |
| `PAXOS2_PROPOSE_REQ/RSP` 193/192, handler | `paxos-propose-request-handler.do-verb` (flow `paxos-v2-propose-replica`), `paxos-propose.propose` |
| `PAXOS2_COMMIT_AND_PREPARE_REQ/RSP` 195/194, handler | `paxos-commit-and-prepare-request-handler.do-verb` (flow `paxos-v2-commit-and-prepare-replica`), `paxos-prepare.start` |
| `PAXOS2_REPAIR_REQ/RSP` 197/196, `PaxosRepair.RequestHandler.doVerb` | `paxos-repair-request-handler.do-verb` (flow `paxos-key-repair`) |
| `PAXOS2_CLEANUP_START_PREPARE_REQ/RSP` 199/198, `PaxosStartPrepareCleanup.createVerbHandler` | `paxos-start-prepare-cleanup.do-verb` / `.prepare` (flow `paxos-cleanup`) |
| `PAXOS2_CLEANUP_REQ/RSP` 201/200, `PaxosCleanupRequest.createVerbHandler` | `paxos-cleanup-request.do-verb`, `paxos-cleanup-session.run` |
| `PAXOS2_CLEANUP_RSP2` 202, `PaxosCleanupResponse.createVerbHandler` | `paxos-cleanup-response.do-verb` |
| `PAXOS2_CLEANUP_FINISH_PREPARE_REQ/RSP` 204/203, `PaxosFinishPrepareCleanup.createVerbHandler` | `paxos-finish-prepare-cleanup.do-verb` / `.finish` |
| `PAXOS2_CLEANUP_COMPLETE_REQ/RSP` 206/205, `PaxosCleanupComplete.createVerbHandler` | `paxos-cleanup-complete.do-verb` / `.run` |
| scheduled `PaxosUncommittedTracker.startAutoRepairs: maintenance` (PaxosUncommittedTracker.java:333) | `paxos-uncommitted-tracker.maintenance` (flow `paxos-auto-repair`, repeat every 300s) |
| stage `Stage.MISC PaxosRepairState.PendingCleanup.add` (PaxosRepairState.java:135) | `paxos-repair-state.add-cleanup-history` |
| stage `Stage.GOSSIP PaxosPrepare.onResponse` (PaxosPrepare.java:470) | cited by `paxos-prepare.start` (PaxosPrepare.java:442-648). The gossip-update branch itself is **not simulated** (see section 8) |

Not mine, and recorded here so nobody double-counts them:
- `PAXOS2_COMMIT_REMOTE_REQ` (Verb.java:186) is handled by `MutationVerbHandler`, so write-path owns it. The paxos area only sends it.
- The Paxos JMX entries (`StorageProxyMBean.*Paxos*`, `StorageServiceMBean.*Paxos*`,
  `ActiveRepairServiceMBean.*PaxosRepairParallelism`) live in `service/*MBean.java`, so ops owns them. Most of them
  are getters and setters for the config in section 4. `StorageServiceMBean.clearPaxosRepairs` and
  `getPaxosBallotLowBound` correspond to `PaxosRepairState.clearRepairs` and `PaxosBallotTracker.getLowBound`.
- `StorageProxy.casWithSnapshot` (named in the brief's ownership table) **does not exist in 5.0.9**.

## 2. Components and flows

Flows:
- `lwt-cas` (`cql` → `storage-proxy.cas`) has 18 v1 scenarios and 12 v2 scenarios. v2 is selected with the choice
  `paxos.get-paxos-variant.variant`.
- `lwt-serial-read` (`coordination` → `storage-proxy.read-with-paxos`) has 6 v1 and 5 v2 scenarios.
- The replica-side handler flows are `paxos-v1-prepare-replica`, `paxos-v1-propose-replica`, `paxos-commit-replica`,
  `paxos-v2-prepare-replica`, `paxos-v2-propose-replica`, `paxos-v2-commit-and-prepare-replica` and
  `paxos-v2-prepare-refresh-replica`.
- `paxos-key-repair` (PaxosRepair), `paxos-cleanup` (PaxosCleanup, called by repair) and `paxos-auto-repair`
  (the 5-minute tracker maintenance).

Components, under the `paxos` module unless a parent is given:
- **Shared:** `cas-request` (CASRequest.java:25-47), `ballot-generator` (BallotGenerator.java:43-84),
  `paxos-state` (PaxosState.java:68-169), the datastore holding `rows` keyed `"<replica>:<partition key>"`, and
  `paxos-state-snapshot`.
- **v1:** `abstract-paxos-verb-handler` with children `prepare-verb-handler` and `propose-verb-handler`, and
  `abstract-paxos-callback` with children `prepare-callback` and `propose-callback` (all under `PX/v1/`). The CAS
  methods of StorageProxy are interfaces on the coordination-owned `storage-proxy` component: `cas`, `legacy-cas`,
  `do-paxos`, `begin-and-repair-paxos`, `prepare-paxos`, `propose-paxos`, `commit-paxos`, `commit-paxos-local`,
  `send-commit`, `read-with-paxos` and `legacy-read-with-paxos`.
- **v2:** `paxos-participants` (Paxos.java:322-490), `paxos-maybe-failure` (Paxos.java:501-570),
  `paxos-request-callback`, `paxos-prepare` and its `-request-handler`, `paxos-prepare-refresh` and its `-request-handler`,
  `paxos-propose` and its `-request-handler`, `paxos-commit` and its `-request-handler`, `paxos-commit-and-prepare` and its
  `-request-handler`, and `contention-strategy`. `Paxos.cas`, `Paxos.read` and `Paxos.begin` are interfaces on the skeleton
  module `paxos`, because the class `Paxos` would kebab to the module's own id.
- **Repair and cleanup:** `abstract-paxos-repair`, `paxos-repair` and its `-request-handler`, `paxos-cleanup`,
  `paxos-start-prepare-cleanup`, `paxos-finish-prepare-cleanup`, `paxos-cleanup-session`, `paxos-cleanup-request`,
  `paxos-cleanup-response`, `paxos-cleanup-complete`, `paxos-cleanup-local-coordinator`, `paxos-table-repairs` and
  `paxos-repair-state`.
- **Uncommitted tracking:** `paxos-uncommitted-tracker` and `paxos-ballot-tracker`.

## 3. Boundary stubs and their contracts

| Stub | Owner | Contract source |
|---|---|---|
| `replica-plans.for-paxos` | coordination | Copied from coordination.yaml. It matches `PaxosReplicaPlan` field for field. |
| `replica-layout.for-token-write-live-and-down` | coordination | coordination.yaml. I read `natural` and `pending`. Component kind set to `function` to match the owner. |
| `storage-proxy.read-one`, `storage-proxy.fetch-rows` | coordination | Copied the fields of `CoordinationReadRequest` and `CoordinationReadResult` (inline). `columns` is a list. |
| `storage-proxy.should-hint` | coordination | coordination.yaml (`{replica}` → `{should_hint}`). |
| `storage-proxy.submit-hint` | hints-batchlog | hints-batchlog.yaml (`{mutation, targets: [one endpoint], consistency?, coordinator}`). No consistency is sent, because Paxos commits pass a null handler. |
| `failure-detector.is-alive` | membership | `MembershipEndpoint` → `MembershipIsAliveResponse` (`{endpoint, alive}`). |
| `storage-service.auto-repair-paxos` | membership | Not yet defined by membership. Shared shapes plus `table_id`. |
| `keyspace.apply` | write-path | `WritePathKeyspaceApply` fields (`mutation`, `replica`, `write_commit_log`, `update_indexes`). |
| `read-command.execute-locally` | read-path | read-path.yaml: `{replica, read_command}` → `{partitions: [{partition_key, cells: [{column, value, timestamp}]}]}`. |
| `column-family-store.on-paxos-repair-complete`, `.sync-paxos-repair-history` | write-path | Not yet defined. Shared shapes. |

I own interfaces that other areas stub: `storage-proxy.cas` (cql), `storage-proxy.read-with-paxos`
(coordination) and `paxos-cleanup.cleanup` (repair-streaming). My contract for `storage-proxy.cas` is
`PaxosCasRequest`: `consistency` (the serial level), `commit_consistency`, `conditions`, `if_not_exists`,
`if_exists` and `columns`. cql's stub currently sends `consistency_for_paxos`, `consistency_for_commit` and `updates`, and
marks the errors `retryable: true`. cql needs to align, since the owner's definition wins. `paxos-cleanup.cleanup` now accepts
a missing `table_id` (it derives `keyspace.table`), so repair-streaming's stub works unchanged.

## 4. Deployed config

| Setting | conf/cassandra.yaml | Config.java default | Effective value |
|---|---|---|---|
| `paxos_variant` | commented out, `#paxos_variant: v1` (1602) | `v1` (1051) | **v1**, legacy Paxos: StorageProxy.legacyCas and legacyReadWithPaxos |
| `cas_contention_timeout` | **1000ms** (1339) | **1800ms** (157) | 1000ms (yaml and Config differ) |
| `write_request_timeout` | 2000ms (1330) | 2000ms (151) | 2000ms: v1 callback await, commit, v2 commit deadline |
| `read_request_timeout` | 5000ms (1322) | 5000ms (145) | 5000ms: v2 SERIAL read deadline |
| `repair_request_timeout` (Verb `repairTimeout` for PAXOS2_CLEANUP_*) | unset | 120000ms (163) | 120000ms |
| `paxos_state_purging` | unset | null, forced to `legacy` (DatabaseDescriptor.java:1011-1012) | legacy (TTL purging, MRC age cut-off in PrepareCallback) |
| `paxos_repair_enabled` | unset | true (1100) | true |
| `paxos_repair_parallelism` | unset | -1, so `max(1, concurrent_writes/8)` (DatabaseDescriptor.java:1007-1008) | 4 (`concurrent_writes: 32`, yaml 723) |
| `paxos_repair_race_wait` | unset | true (1402) | true |
| `paxos_purge_grace_period` | unset | 60s (1064) | 60s (not modelled) |
| `paxos_contention_*` | unset | null, so ContentionStrategy defaults (ContentionStrategy.java:125-128) | min `0 <= p50*0.66`, max `10ms <= p95*1.8^n <= 100ms` |
| `reject_out_of_token_range_requests` / `log_...` | unset | false / true (Config.java:792-793) | v1 handlers log out-of-range requests and still process them |
| `partition_denylist_enabled` | commented out (1438) | false (759) | the CAS denylist refusal never fires |
| `hinted_handoff_enabled` | true (68) | true (112) | consulted through coordination's `should-hint` |
| `cassandra.auto_repair_frequency_seconds` | system property | 300 (CassandraRelevantProperties.java:64) | 5 minutes |
| `cassandra.enable_dc_local_commit` | system property | true (CassandraRelevantProperties.java:215) | only matters with more than one DC |
| `cassandra.paxos_repair_retry_timeout_millis` | system property | 60000 (CassandraRelevantProperties.java:402) | bounded in the model by 5 attempts |
| `cassandra.paxos_cleanup_session_timeout_seconds` | system property | 2h (CassandraRelevantProperties.java:395) | not reached |

## 5. What the code did not settle, and the assumptions I made

- **Liveness levers.** `replica-plans.for-paxos` is coordination's, and the stub always returns three live replicas
  with `local_endpoint` 10.0.0.1, so the coordinator is always a replica. v1 Unavailable is driven by an `unavailable`
  fault on that stub. Liveness inside `commit-paxos`, the `ReplicaPlans.forWrite` isAlive check, and in v2
  `Participants.get` is read through `failure-detector.is-alive`. **A fault on `is-alive` stands in for the
  failure detector convicting that endpoint** (`calls: [3]` downs the third replica). When membership's real
  `is-alive` reads its own state, scenarios can set liveness there instead.
- **Token ownership** (`isInRangeAndShouldProcess`, `StorageService.isEndpointValidForWrite`) is a choice
  `token_ownership`, default `owned`, on each handler. It stands in for membership's ring.
- **The CAS condition** is evaluated generically by `cas-request.applies-to`: per-column equality, IF NOT EXISTS
  and IF EXISTS. CQL3CasRequest (cql) has richer conditions. The default flow is `INSERT ... IF NOT EXISTS` on an empty
  table, because the read stubs return no rows and read-path's real local read also starts empty.
- **Ballots** are integer microseconds starting at 1767225600000000. The random LSBs and the GLOBAL/LOCAL flag are not
  part of the comparison. `ballot-generator` keeps the last ballot in `ctx.lastBallot`, which stands in for
  ClientState's monotonic clock.
- **Paxos state** ignores TTL expiry (legacy purging) and the ballot low bound (`latestWitnessedOrLowBound` treats
  the low bound as 0). `legacyPropose` with a ballot equal to the commit is saved like any other acceptance.
- **The v1 prepare latch** counts the first `requiredParticipants` responses in plan order. Later responses,
  including a late rejection, are ignored. The real PrepareCallback keeps processing responses that arrive before
  the coordinator reads the summary, which is a race.
- **v2 prepare resolution** (`paxos-prepare.start`) follows `permitted()` and the quorum decision. It skips gossip and
  electorate verification, so ELECTORATE_MISMATCH is unreachable. It also skips short-read protection and
  linearizability-violation checks. `FOUND_INCOMPLETE_COMMITTED` is reachable only when no permitted response carries a
  read, and every non-pending voter sends one. The DataResolver merge of read responses (coordination) is replaced by
  "first non-empty response".
- **The v2 message timeout** is fixed at 1000ms per prepare and propose call (the propose deadline). Reads really use
  the 5000ms read deadline.
- **PaxosRepair** sets `successCriteria` to the incomplete ballot and does not model clashing-timestamp handling.
  Its restart loop is bounded at 5 attempts with a 50ms back-off, standing in for the 60s
  `PAXOS_REPAIR_RETRY_TIMEOUT`. The poison path's stale ballot is the next ballot above the latest witnessed one, not
  a random ballot in `[latest+1, now - min(gap/2, 5s)]`.
- **Cleanup:** each participant's local cleanup coordinator reads the same `paxos-uncommitted-tracker.tables` state,
  because one component models every node. A PAXOS2_CLEANUP_REQ call returns the endpoint's eventual RSP2 result. The
  RSP2 is also sent, through `paxos-cleanup-response.do-verb` into `paxos-repair-state.sessions`. The finish-prepare
  handler acknowledges after the MISC-stage work, inline.

## 6. Where the docs or common knowledge disagree with the code

- **"LWT uses 4 round trips"** is true only for the deployed **v1**. The v2 code (not deployed) takes 2 round trips plus
  the commit, and 1 for a stable SERIAL read. The yaml comment (cassandra.yaml:1578) and the Config javadoc agree that
  v1 is "4RTs for a write and 3RTs for a read".
- **A failed condition is still proposed.** In v1 a CAS whose condition fails is proposed as an empty update (one more
  round trip) but never committed (SP:529-534). v2 skips the proposal when the read was already linearizable
  (Paxos.java:710-714).
- **Write timeout type.** A v1 commit timeout reports `write_type: SIMPLE`, not CAS (doPaxos rewraps keeping
  `e.writeType`, SP:558-562). Prepare and propose timeouts are CAS. In v2 every Paxos timeout, commit included, is
  `CasWriteTimeoutException(WriteType.CAS)`.
- **Down replicas at commit.** A v1 commit to a down replica is hinted but does not count as a failure, so you get a
  write timeout (scenario `cas-v1-commit-all-down-replica`). In v2 it counts as a NODE_DOWN failure, which makes commit at ALL a **write failure** (5376) instead
  (scenario `cas-v2-commit-all-down-replica`).
- **Timed-out commits are not hinted.** A live replica that times out on a v1 commit is not hinted. Only replicas
  already down are (RequestCallbacks.onExpired only calls onFailure).
- **Out-of-range handling differs by verb.** v1 PREPARE and PROPOSE process out-of-range tokens by default
  (`reject_out_of_token_range_requests: false`), but PAXOS_COMMIT_REQ is always refused through
  `Paxos.isInRangeAndShouldProcess`, even in v1, because v1 uses `PaxosCommit.requestHandler`.
- **v1 failure responses only log.** AbstractPaxosCallback.onFailure does not count down the latch, so a failure
  response in v1 prepare or propose is a timeout, never a fast failure.
- **v2 SERIAL read reports a write timeout.** When superseded with possible side effects, or when out of contention
  time, it throws `CasWriteTimeoutException` (`isWrite = true`, Paxos.java:886-901) rather than a read timeout.
- **cas_contention_timeout** defaults to 1800ms in Config but is 1000ms in the shipped yaml.
- `StorageProxy.casWithSnapshot` (in the brief) does not exist in this version.

## 7. Simulator gaps

- **Parallel fan-out, waiting for k of n.** Every prepare, propose and commit is a sequential `foreach`. Example:
  `cas-v1-one-replica-slow-prepare` takes more than 2000ms of virtual time, because the hung replica is called (and
  times out) before the third replica answers. Cassandra answers as soon as the local replica and the third respond.
  The decision is right but the latency is wrong.
- **Latch semantics.** "First N responses win" depends on plan order rather than arrival time. Responses after the
  latch is released are discarded, deterministically.
- **Contention needs concurrency.** Competing proposers cannot run at the same time as the request. Contention is
  seeded as state (a higher promise), so a retry always wins on the next round. `cas-v1-contention-timeout` needs a
  latency fault to push the clock past cas_contention_timeout.
- **CasWriteUnknownResult (v1) is unreachable in a scenario.** It needs a replica that promised our ballot to refuse
  our proposal, meaning a competing prepare lands between our prepare and propose. The branch is modelled in
  `storage-proxy.propose-paxos`, but no scenario reaches it. v2's equivalent (SUPERSEDED with MAYBE side effects) is
  reached by combining a failure with a refusal.
- **Random back-off.** `ThreadLocalRandom.nextInt(100)` sleeps are a fixed 50ms, and ContentionStrategy's randomized wait
  is a deterministic table: 10, 18, 32, 58, 100ms, halved.
- **Timeouts are per call, not per request.** `timeout_ms` must be a literal, so per-call timeouts stand in for
  deadlines computed from the request start (`requestTime.computeTimeout`). v2 uses 1000ms everywhere.
- **Asynchronous stages.** The local execution on the PAXOS_*_REQ stages, the MISC-stage cleanup and the
  GOSSIP-stage notifyFailureDetector all run inline.
- **The read result is not reconciled.** The cell lists from a v2 prepare cannot be turned into column maps in CEL,
  so v2 results carry `{partition_key, cells}` rows.
- **Dynamic map keys.** `set` cannot write `state.x[runtimeKey]`, so per-replica state goes through `store`
  interfaces, and the auto-repair "in progress" set is read-only.

## 8. Known gaps

- Not modelled: the PaxosState coordinator lock under contention, `paxos_on_linearizability_violations`, ballot
  low-bound rejection, TTL purging and `paxos_purge_grace_period`, the PaxosUncommittedIndex and file
  consolidation internals, the PaxosRepairHistory merge, topology-change Paxos repair (`StorageService.repairPaxosForTopologyChange`,
  which calls `paxos-cleanup.cleanup` through ActiveRepairService), electorate mismatch and the gossip update
  (PaxosPrepare.java:470-480), and pending replicas in scenarios (the plan stubs never return pending replicas).
- `PaxosTableRepairs` queueing and joining of concurrent key repairs, and the 5-minute eviction, are narrated only.
- `cas-request.make-updates` does not run triggers. The TriggerExecutor step is narrated.
- In the merged ontology, scenarios that rely on fake stub data will see the owners' real behaviors instead. Run with
  read-path, membership, write-path and hints-batchlog, all 72 scenarios still pass. coordination's fragment
  currently fails validation on its own, so that combination is untested.

## Reconciliation round

- **Liveness now comes from membership (decision 4).** Scenarios mark nodes down with
  `state: {gossiper: {endpoint_state_map: {"10.0.0.3": {alive: false}}}}`. `gossiper` is declared as a
  membership boundary component, and the faults on `failure-detector.is-alive` and `replica-plans.for-paxos` are gone.
  In the merged ontology, coordination's real `replica-plans.for-paxos` and membership's `failure-detector.is-alive`
  read that state. Standalone, those 9 scenarios (the `*-unavailable` ones, the commit-down-replica ones,
  `paxos-repair-key-unavailable` and `paxos-cleanup-key-repair-fails`) fail by design, because the stubs ignore the state.
- **Replica order.** The scenario token changed to -7509452495886106294. With coordination's SimpleStrategy over
  membership's ring, that token's replica order is [10.0.0.1, 10.0.0.2, 10.0.0.3], which is what the
  order-sensitive seeded scenarios assume. The old token put 10.0.0.2 first.
- The skips file `skips/paxos.json` is empty, because every entry is covered.
- The remaining merge warnings come from cql's `storage-proxy.cas` stub (`retryable: true`). cql is aligning it.

## Migration round (instances, parallel, configs, fixtures)

This section supersedes the earlier notes wherever they disagree.

**Conversions**
- **Instances.** Nodes are the instances n1..n3 (or n4) from `fixtures.yaml`, and every scenario uses `fixtures: [three-node-rf3]` (or `four-node-rf3`).
  - All `to`/`from` routing fields are gone from the Paxos messages. Verb calls take `on: <replica>`, and handlers use `self`.
  - `paxos-state` is per instance, keyed `<keyspace>.<table>:<partition key>`. `bank.accounts` became `shop.accounts`.
  - Liveness comes from `gossiper@n1.endpoint_state_map` through coordination's plans and membership's failure detector. Token ownership comes from the ring (four nodes, token -5 on n1), not from choices.
- **`parallel` with the code's joins.** There are 13 fan-outs:
  - v1 prepare (`prepare-callback.await`) and v1 propose (`propose-callback.await`);
  - v1 commit, including fire-and-forget commit at ANY, and `send-commit` (join need 0);
  - v2 prepare, propose and commit (`*.await-until`) and v2 refresh;
  - the PaxosRepair query;
  - the cleanup start-prepare, finish-prepare and complete fan-outs.

  How the joins behave:
  - Timeouts run from the request start: write_request_timeout for v1 callbacks and the commit; the propose and commit deadlines (`cas_contention_timeout` and `max(cas, write)`) and read_request_timeout for v2.
  - v1 failure responses only log: the branch waits out the timeout, so the outcome is a timeout, not a fast failure.
  - A v1 prepare rejection counts toward the latch, and any counted rejection means "not promised".
- **Configs.** There are 15 config entities (11 owned, 4 references). `paxos.get-paxos-variant` reads `config['paxos-variant']`, so v2 scenarios set `config: {paxos-variant: v2}`.
- **Back-off and timers.** Back-off is `random(100)` (v1) and the ContentionStrategy table (v2). Auto-repair uses `entry.repeat.initial_delay_ms: 300000`.
- **Writes flows.** 11 flows are tagged `writes`, and each has a multi-step read-back scenario. Examples: CAS insert then SERIAL read; CAS insert then `IF balance = 80`; prepare then an older propose refused; commit then a prepare reporting it; key repair then a prepare on n3; cleanup then key repair.

**Judged errors fixed**
- **The v1 commit runs `ReplicaPlans.forWrite`** (StorageProxy.java:785 → ReplicaPlans.java:469-476), with its live-replica check, through coordination's `replica-plans.for-write`. A commit at ALL with a replica down is now `unavailable` (4096) after the proposal was accepted: nothing is sent and nothing is hinted (`cas-v1-commit-all-down-replica`). My earlier note claiming a write timeout was wrong.
- **CAS results carry `[applied]`.** The result is `rows: [{'[applied]': true}]`, or `[{'[applied]': false, <current columns>}]` (ModificationStatement.buildCasResultSet, cql3/statements/ModificationStatement.java:605-618).
- **SERIAL and CAS rows are column maps.** Cells are turned into maps with `transformMapEntry`, dropping deleted cells.
- **L4 contention.** Back-off is now a random 0-99ms. Seeded competing promises on two replicas now arrive concurrently with the local promise. Sustained contention is still not expressible (see below).

**Simulator gaps resolved:** parallel fan-out with k-of-n joins and real timing (a quorum with one hung replica answers in milliseconds; two hung replicas time out at 2000ms, v2 at 1000ms or 5000ms), per-replica state, request deadlines measured from the request start, random back-off, result reshaping, and the initial delay on periodic tasks.

**Still open**
- **Sustained contention.** `parallel` branches don't interleave shared state, so a competing proposer can't win repeatedly. Reaching `cas_contention_timeout` still needs a latency fault.
- **CasWriteUnknownResult (v1) is still unreachable.** It needs a promiser to refuse our proposal.
- **Arrival order within a join** is the branches' finish times. Ties and the processing order of the v2 aggregation follow voter order.
- **v2 electorate mismatch and the gossip update** (PaxosPrepare.java:470-480) are not modelled.

**Gates:** behavior coverage went from 87.8% to 90.2%. Hollow lint: 0 failing for paxos (was 32 unchecked scenarios) and 0 writes flows without read-back. There is 1 advisory (`paxos-repair-key-unavailable`, a refusal). There are no mocks.

**Standalone checks (skeleton plus this fragment).** 19 scenarios need other areas' real definitions and fail standalone:
- membership's gossip and failure detector (down replicas, Unavailable);
- the ring (out of range, not owned);
- read-path data (write then read).
