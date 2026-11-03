# Membership area notes

Fragment: `examples/cassandra/fragments/membership.yaml`. Code root: `cassandra-5.0.9` (b5f2a54210).
All paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

## The contract other areas read

Every node is an instance (`n1`..`n4`, from `fixtures.yaml`); each holds its own gossiper, failure
detector, token metadata and storage-service state.

| Interface | Request | Response | Where the answer comes from |
|---|---|---|---|
| `failure-detector.is-alive` | `{endpoint}` | `{endpoint, alive}` | `true` for `self` (`FailureDetector.java:301-302`); otherwise the calling node's `gossiper@<node>.endpoint_state_map.<ep>.alive`, `false` when unknown |
| `token-metadata.get-write-endpoints` | `{keyspace, token}` | `{keyspace, token, natural, pending, replicas}` | SimpleStrategy ring walk over `token-metadata@<node>.ring` with RF `keyspace_rf[ks]` (base-schema: ks1 and shop = 3) or `default_rf`; pending from `pending_ranges` |
| `gossiper.get-endpoint-downtime` | `{endpoint}` | `{downtime_ms}` | `now - down_since_ms`, set by `mark-dead` only (`Gossiper.java:1529`) |
| gossip subscribers | | | subscribe to `endpoint-state-change-subscriber.{on-join, on-change, on-alive, on-dead, on-remove, on-restart}`, published `sync` |

With `three-node-rf3`, token 100 replicates to `[n3, n1, n2]`. Mark a node down as seen from n1 with
`state: {"gossiper@n1": {endpoint_state_map: {n2: {alive: false}}}}`; for a node down past the hint
window add `down_since_ms: <epoch ms - 11000000>`.

**Fixture caveat (reported to the coordinator):** the fixtures seed `failure-detector@nX.arrival_samples.*.t_last_ms: 0`,
but `now` starts at the epoch (1793318400000), so the first `interpret` convicts every peer. Scenarios that run
a gossip round seed `t_last_ms: 1793318400000` per instance (`failure-detector@n1`, ...). A plain `failure-detector`
key does not help: the fixture's `@n` keys are applied after every plain key.

## Migration round

- **Instances.** 28 `to` fields removed (handler requests, flow inputs, scenario inputs, the five message schemas);
  every verb is sent with `on:`. SYN goes to the target, ACK back to `input.from`, ACK2 back again, ECHO and
  GOSSIP_SHUTDOWN to the peer, and each handler works on its own instance's state. `state.local_endpoint` became `self`
  (54 uses). `mem-gossip-converges` shows n3's LEAVING status reaching n1's and n2's views and token metadata after
  three rounds (n3, n2, n1).
- **Parallel.** Bootstrap streams every (keyspace, source) plan concurrently; unbootstrap runs the range streams and
  the batchlog replay as concurrent branches, with hints transferred after the batchlog
  (`StorageService.java:5462-5487`). Two fan-outs converted.
- **Configs.** 22 config entities (16 owned, 6 boundary references to other areas' timeouts, plus `cluster-name` and
  `partitioner`, boundary because cql owns them). Behaviors read `config[...]`.
- **Timers.** The callback reaper (`initial_delay_ms: 1000`, every 1000 ms) and the load broadcast (2000 ms, then 60000 ms)
  use `entry.repeat`; `storage-service.excise` schedules hint deletion with `after_ms` = min rpc timeout + write timeout (4000 ms).
- **Publish/subscribe.** The gossiper's subscriber list is the `endpoint-state-change-subscriber` topics;
  `storage-service.on-*` and `load-broadcaster.on-change` subscribe. Lifecycle notifications to transport's
  `server-event-notifier` are still direct calls (transport owns the subscriber).
- **Writes flows.** 21 flows tagged `writes`, each with a multi-step read-back scenario.
- **Random.** Gossip targets and the unreachable/seed draws use `random(n)` (`Gossiper.java:992, 1023, 1051`); the
  choices stay overridable.
- **Judge fixes:** W2 (`endpoint-state-mark-dead` no longer touches `down_since_ms`; `mem-downtime-survives-failed-echo`),
  W4 (bootstrap streams each pending range from a current owner other than itself, with ranges), W5 (unbootstrap
  streams to the new owners from the pending ranges), the phi threshold as config (`mem-round-threshold-from-config`),
  the 4000 ms hint excise delay, random seed choice, and narration titles moved inside `then`.
- **Application states.** `gossiper.add-local-application-state` accepts every `ApplicationState` constant
  (`ApplicationState.java:30-75`); states other than STATUS, TOKENS, LOAD, RPC_READY and SCHEMA are kept under `app_states`.

## Reconciliation round

- Defined the 36 interfaces other areas already called (decision 6), with their exact names: `gossiper.{get-endpoint-downtime,
  get-min-version, get-unreachable-token-owners, is-alive, reload-seeds, wait-for-schema-agreement, wait-to-settle}`,
  `messaging-service-mbean-impl.reload-ssl-certificates`, `pending-range-calculator-service.calculate-pending-ranges`,
  25 `storage-service.*` and `token-metadata.{get-pending-ranges, get-size-of-all-endpoints, sorted-tokens}`.
  Contract notes for callers:
  - `storage-service.is-bootstrap-mode` returns `{bootstrap_mode}` (callers that read `bootstrapping` or a bare boolean must align).
  - `gossiper.get-endpoint-downtime` returns `{downtime_ms}` = `now - endpoint_state_map.<ep>.down_since_ms` when the
    endpoint is down (mark-dead sets `down_since_ms`); a scenario sets `{alive: false, down_since_ms: -11000000}` for a node down past `max_hint_window`.
  - `storage-service.get-range-to-address-map` returns `{ranges: [{range: "(l,r]", endpoints}]}` (CEL can't build a dynamic-key map).
  - `token-metadata.sorted-tokens` returns `{tokens, ring: [{token, endpoint}], min_token}`.
  - `storage-service.is-endpoint-valid-for-write` takes an optional `replica` (defaults to this node).
  - `gossiper.get-min-version` returns a bare string (`state.release_version`, "5.0.9").
  - `gossiper.wait-for-schema-agreement` is a choice (`agreed`/`disagree`): schema versions are not in the modeled gossip state.
- Boundary stubs aligned to owners: stub components no longer state a `kind`; the `server-event-notifier.*`,
  `stream-plan.execute`, `hints-service.excise`, `column-family-store.force-flush` stubs no longer restate request
  schemas; `hints-service.pause-dispatch` is `jmx`; `hints-service.transfer-hints` now gets `target_host_id` from
  `storage-service.get-preferred-hints-stream-target` (`StorageService.java:5497-5525`).

## Fix round

- **G3, strict bootstrap sources.** `range-streamer.fetch-async` now picks, per keyspace and range, the old replica that
  is not a replica once the joining node owns its tokens (`dht/RangeStreamer.java:494-538`), when strict sources apply:
  BOOTSTRAP with tokens, `consistent-range-movement` on, and more nodes than RF (`RangeStreamer.java:394-416`; the node
  count includes the joining node, registered by `prepareToJoin`, `StorageService.java:1208`). Otherwise the first old
  replica (`:542-551`). For n4 at -7686143364045646507: (n1,n2] from n1, (n2,n3] from n2, (n3,n4] from n3
  (`mem-startup-new-node-bootstraps`, `mem-bootstrap-sources-not-strict`). The request gained an optional `tokens`.
- **G1, `gossiper.start`.** Builds the seed list from `configured_seeds` minus this node (`Gossiper.java:2126-2137`),
  creates the local state only when absent (putIfAbsent, `:2198-2204`; an existing generation is kept; the new state has
  no STATUS, read as empty), and schedules the GossipTask every gossip interval from start (`:2028-2031`), on by default.
  A timer needs a finite count, so config `gossip-task-rounds` (a model bound, default 60) caps it; the task does nothing
  once `gossiper.stop` has run (`:2301-2302`). `storage-service.start-gossiping` now calls the new
  `gossiper.force-newer-generation` first (`StorageService.java:619`). `bench-g1-scheduled-every-second` passes.
  Timer deliveries wait for the caller's call tree, so rounds scheduled by `init-server` land after RING_DELAY and the
  join: peers learn the new node as NORMAL and never see BOOT.
- **Live peers from the alive flag.** The gossip round, `get-live-members`, `stop` (GOSSIP_SHUTDOWN targets) and
  `get-unreachable-token-owners` derive live and unreachable peers from `endpoint_state_map.<ep>.alive`
  (`Gossiper.java:1437-1472`). `live_endpoints` and `unreachable_endpoints` are still kept in step by mark-alive/mark-dead,
  but nothing reads them for decisions (`mem-round-live-from-alive-flag`).
- **Gossip during RING_DELAY.** `mem-join-gossip-during-ring-delay` (concurrent, `max_virtual_ms`): n4 starts, a round
  on n4 at 5 s reaches n1 (BOOT, pending ranges), a QUORUM write on n1 at 10 s has blockFor 3 and reaches n4, and a round
  at 40 s carries NORMAL to n1's ring.
- **Fixture change (n1 is not its own seed).** `mem-reload-seeds-empty-keeps-current` now starts with seeds `[n2]` and
  expects them kept (the reload of `[n1]` minus self is empty, `Gossiper.java:2164-2168`).
  `mem-startup-concurrent-range-movement-allowed` makes n2 the seed: a bootstrapping n1 that was its own only seed has no
  seed to see and fails with "Unable to contact any seeds" (`StorageService.java:2232-2235`), as the code does.
  `mem-round-gossips-to-unreachable-and-seed` now marks n2 and n3 down through their alive flags.

### Breaking changes

Gossip rounds on by default from `gossiper.start` (`Gossiper.java:2028-2031`); they run after the starting call tree:
- judge `bench-g3-join-end-to-end` (G3, left for the re-scorer): n4's rounds after the join carry NORMAL to n1 at a higher
  version, so the later injected BOOT (max_version 5) is ignored as older and the QUORUM write has blockFor 2, not 3.
  To pass, it must deliver BOOT during RING_DELAY (an `at_ms` gossip round, as `mem-join-gossip-during-ring-delay`).
- mine, fixed: `mem-startup-new-node-bootstraps` (peers now record `n4:NORMAL` ×3 and add n4 to their rings),
  `mem-gossiper-start-fresh-local-state` (heartbeat 60 after 60 rounds), `mem-gossiper-start-builds-seeds-keeps-local-state`
  (60 task runs). No other area's scenario broke. `range-streamer.fetch-async` only gained an optional `tokens`.

## 1. Entry points

### Modeled

| Inventory entry | Covered by (interface; flow) |
|---|---|
| verb-handler `GossipDigestSynVerbHandler.doVerb` (`gms/GossipDigestSynVerbHandler.java:42`); verb `GOSSIP_DIGEST_SYN` (`net/Verb.java:144`) | `gossip-digest-syn-verb-handler.do-verb`; `membership-gossip-syn` |
| verb-handler `GossipDigestAckVerbHandler.doVerb` (`:41`); verb `GOSSIP_DIGEST_ACK` (`Verb.java:145`) | `gossip-digest-ack-verb-handler.do-verb`; `membership-gossip-ack` |
| verb-handler `GossipDigestAck2VerbHandler.doVerb` (`:34`); verb `GOSSIP_DIGEST_ACK2` (`Verb.java:146`) | `gossip-digest-ack2-verb-handler.do-verb`; `membership-gossip-ack2` |
| verb-handler `GossipShutdownVerbHandler.doVerb` (`:32`); verb `GOSSIP_SHUTDOWN` (`Verb.java:147`) | `gossip-shutdown-verb-handler.do-verb`; `membership-gossip-shutdown` |
| verb-handler `GossipVerbHandler.doVerb` (`gms/GossipVerbHandler.java:26`) | `gossip-verb-handler.do-verb` (called by SYN, ACK, ACK2) |
| verb-handler `EchoVerbHandler.doVerb` (`service/EchoVerbHandler.java:36`); verb `ECHO_REQ` (`Verb.java:150`) | `echo-verb-handler.do-verb`; `membership-echo`, and every `markAlive` |
| verb-handler `PingVerbHandler.doVerb` (`net/PingVerbHandler.java:25`); verb `PING_REQ` (`Verb.java:152`) | `ping-verb-handler.do-verb`; `membership-ping` |
| verb-handler `ResponseVerbHandler.doVerb` (`net/ResponseVerbHandler.java:36`); verbs `ECHO_RSP` (149), `PING_RSP` (151), `FAILURE_RSP` (209), `REQUEST_RSP` (219), `INTERNAL_RSP` (222) | `response-verb-handler.do-verb`; `membership-internode-response` |
| scheduled-task `Gossiper.start: GossipTask` (`gms/Gossiper.java:2028`) | `gossiper-gossip-task.run`; `membership-gossip-round` |
| stage-task `Stage.GOSSIP Gossiper.runInGossipStageBlocking` (`Gossiper.java:585`) | cited on `gossiper.convict` (the GOSSIP-stage conviction) |
| scheduled-task `RequestCallbacks: expire` (`net/RequestCallbacks.java:71`) | `request-callbacks.expire`; `membership-callback-expiry`, `membership-callback-expiry-rounds` |
| scheduled-task `OutboundConnection.setDisconnected: queue::maybePruneExpired` (`net/OutboundConnection.java:1406`) | `outbound-message-queue.maybe-prune-expired`; `membership-outbound-prune` |
| scheduled-task `OutboundConnections.scheduleUnusedConnectionMonitoring` (`net/OutboundConnections.java:339`) | `outbound-connections-unused-connection-monitor.close-unused-since-last-run`; `membership-unused-connection-monitor` |
| scheduled-task `LoadBroadcaster.startBroadcasting: runnable` (`service/LoadBroadcaster.java:92`) | `load-broadcaster.start-broadcasting`; `membership-load-broadcast` |
| jmx `GossiperMBean.assassinateEndpoint` (`gms/GossiperMBean.java:32`), `unsafeAssassinateEndpoint` (`:30`, calls through) | `gossiper.assassinate-endpoint`; `membership-assassinate` |

StorageService lifecycle methods are not inventory entries (their MBean operations belong to `ops`), but
`ops` will call them: `storage-service.init-server` (`membership-node-startup`), `storage-service.decommission`
(`membership-decommission`), `storage-service.remove-node` (`membership-removenode`), `storage-service.move`
(`membership-move`), `storage-service.drain` (`membership-drain`).

`EchoVerbHandler` lives in `service/` and no row of the ownership table names it. It answers the gossiper's
ECHO_REQ, so membership models it.

### Skipped entry points

- The 12 JMX getters in `gms/FailureDetectorMBean.java` (`getPhiConvictThreshold`, `getAllEndpointStates`,
  `getAllEndpointStatesWithResolveIp`, `getAllEndpointStatesWithPort`, `getAllEndpointStatesWithPortAndResolveIp`,
  `getEndpointState`, `getSimpleStates`, `getSimpleStatesWithPort`, `getDownEndpointCount`, `getUpEndpointCount`,
  `getPhiValues`, `getPhiValuesWithPort`): reads of failure-detector or gossip state, no behavior.
- `FailureDetectorMBean.dumpInterArrivalTimes` (`:28`): writes the arrival windows to a temp file for diagnosis; no effect on membership.
- `FailureDetectorMBean.setPhiConvictThreshold` (`:30`): config setter (`DatabaseDescriptor.setPhiConvictThreshold`); the threshold is modeled as `failure-detector.phi_convict_threshold` state.
- The 3 JMX getters in `gms/GossiperMBean.java` (`getCurrentGenerationNumber`,
  `getReleaseVersionsWithPort`, `getLooseEmptyEnabled`): reads of gossip state, no behavior.
  (`getCurrentGenerationNumber` at `:28` shows as covered only because the assassinate citation at `:30` is within the checker's 3-line tolerance.)
- `GossiperMBean.setLooseEmptyEnabled` (`:43`): flips the static `EndpointState.LOOSE_DEF_OF_EMPTY_ENABLED` flag (`Gossiper.java:2663-2667`); config.
- `GossiperMBean.compareGossipAndTokenMetadata` (`:49`): read-only diagnostic comparing gossip tokens with token metadata.
- The 25 JMX getters in `net/MessagingServiceMBean.java` (`get*` and `is*`: pending/completed/dropped task counts per
  connection type and their `WithPort` forms, `getDroppedMessages`, `getTotalTimeouts`, `getTimeoutsPerHost`,
  `getTimeoutsPerHostWithPort`, `getBackPressurePerHost`, `isBackPressureEnabled`, `getVersion`): metrics and version reads, no behavior.
- `MessagingServiceMBean.setBackPressureEnabled` (`:137`): always throws `UnsupportedOperationException("This feature has been removed")` (`net/MessagingServiceMBeanImpl.java:264-267`).

Totals for membership-owned entries: 30 covered (8 verb handlers, 11 messaging verbs, 5 scheduled tasks, 1 stage
task, 5 JMX operations: assassinateEndpoint, unsafeAssassinateEndpoint, getEndpointDowntime, reloadSeeds,
reloadSslCertificates) and 46 skipped (20 FailureDetector/Gossiper JMX, 26 MessagingService JMX). The exact list is
`examples/cassandra/skips/membership.json`. The other
`net/Verb.java` lines belong to the areas that own their handlers.

## 2. Components modeled

| Component | Code |
|---|---|
| `gossiper` (state: endpoint state map, live/unreachable sets, seeds, quarantine) | `gms/Gossiper.java:120-200` |
| `gossiper-gossip-task` | `gms/Gossiper.java:337-400` |
| `failure-detector` (state: arrival windows, threshold 8, local-pause guard) | `gms/FailureDetector.java:64-102` |
| `gossip-verb-handler`, `gossip-digest-syn-verb-handler`, `gossip-digest-ack-verb-handler`, `gossip-digest-ack2-verb-handler`, `gossip-shutdown-verb-handler` | `gms/Gossip*VerbHandler.java` |
| `echo-verb-handler` | `service/EchoVerbHandler.java:30-49` |
| `token-metadata` (state: ring, bootstrap tokens, leaving, moving, pending ranges, host ids, RF inputs) | `locator/TokenMetadata.java:55-117` |
| `pending-range-calculator-service` | `service/PendingRangeCalculatorService.java:39-98` |
| `storage-service` (lifecycle and gossip subscriber) | `service/StorageService.java` (lines per interface) |
| `load-broadcaster` | `service/LoadBroadcaster.java:35-94` |
| `boot-strapper`, `range-streamer` | `dht/BootStrapper.java:63-181`, `dht/RangeStreamer.java:697-782` |
| `messaging-service` | `net/MessagingService.java:207-539` |
| `request-callbacks` (state: callbacks keyed `id:peer`) | `net/RequestCallbacks.java:58-305` |
| `request-callback` | `net/RequestCallback.java:31-58` |
| `response-verb-handler`, `ping-verb-handler` | `net/ResponseVerbHandler.java`, `net/PingVerbHandler.java` |
| `outbound-message-queue` | `net/OutboundMessageQueue.java:209-220`, `net/OutboundConnection.java:475-483` |
| `outbound-connections-unused-connection-monitor` | `net/OutboundConnections.java:273-340` |

Flows (22): liveness contract, replica contract, gossip round, SYN, ACK, ACK2, SHUTDOWN, ECHO, PING, response
verb, callback expiry (single and 3 passes), outbound prune, unused-connection monitor, load broadcast, node
startup, decommission, removenode, move, drain, assassinate, pending-range calculation. 96 scenarios.

## 3. Boundary stubs

None of the owners' fragments existed when I wrote mine, so the stubs use the shared shapes and only the fields
my call sites send. Expect to align in reconciliation.

| Stub | Owner | Used by |
|---|---|---|
| `server-event-notifier.on-up` / `on-down` / `on-join-cluster` / `on-leave-cluster` (`transport/Server.java:450-483`) | transport | `StorageService.notifyUp/Down/Joined/Left` |
| `stream-plan.execute` (`streaming/StreamPlan.java:195`), request `{operation, peers}` | repair-streaming | bootstrap, unbootstrap, move |
| `hints-service.excise` / `transfer-hints` / `pause-dispatch` | hints-batchlog | excise, decommission, drain |
| `batchlog-manager.start-batchlog-replay` | hints-batchlog | decommission |
| `column-family-store.force-flush` `{keyspace, table, reason}` | write-path | drain |

The stub components (`server-event-notifier`, `stream-plan`, `hints-service`, `batchlog-manager`,
`column-family-store`) are also declared as boundary stubs under the owners' skeleton modules.

## 4. Deployed config

| Setting | `conf/cassandra.yaml` | `Config.java` default | Modeled value |
|---|---|---|---|
| `cluster_name` | `'Test Cluster'` (26) | `"Test Cluster"` (81) | SYN check |
| `num_tokens` | `16` (42) | `null` (132) | **1 per node** in the model (see gaps) |
| `allocate_tokens_for_local_replication_factor` | `3` (59) | `null` (136) | token allocation (approximated) |
| `partitioner` | `Murmur3Partitioner` (389) | `null` (109) | SYN check |
| `seeds` | `"127.0.0.1:7000"` (706) | n/a | seeds `[10.0.0.1]` in the 3-node model |
| `endpoint_snitch` | `SimpleSnitch` (1556) | `null` (423) | one DC, one rack |
| `phi_convict_threshold` | commented, 8 (1471) | `8.0` (177) | 8.0 |
| `auto_bootstrap` | not set | `true` (111) | true |
| `transfer_hints_on_decommission` | commented, true (120) | `true` (452) | true |
| `request_timeout` (rpcTimeout: ECHO, GOSSIP_SHUTDOWN) | `10000ms` (1349) | `10000ms` (142) | 10000 ms |
| `write_request_timeout` | `2000ms` (1330) | `2000ms` (151) | min rpc timeout, so the callback reaper runs every 1000 ms |
| `cas_contention_timeout` | `1000ms` (1339) | `1800ms` (157) | not used here; **differs** |
| `internode_timeout` | commented, true (1408) | `true` (170) | not modeled |
| `block_for_peers_timeout_in_secs` (PING timeout) | not set | `10` (694) | 10000 ms |
| `cassandra.ring_delay_ms` | system property | 30000 ms (`StorageService.java:313-325`) | 30000 ms waits |
| `cassandra.broadcast_interval_ms` | system property | 60000 (`CassandraRelevantProperties.java:76`) | 60000 |
| `cassandra.max_local_pause_in_ms` | system property | 5000 (`CassandraRelevantProperties.java:352`) | 5000 |
| `cassandra.gossip_quarantine_delay_ms` | system property | `RING_DELAY * 2` = 60000 (`Gossiper.java:143`) | 60000; fat-client timeout 30000; failed-bootstrap timeout 300000 (`Gossiper.java:158, 297-312`) |
| `cassandra.very_long_time_ms` | system property | 259200000 (3 days) (`CassandraRelevantProperties.java:624`) | dead-state expiry |
| `cassandra.consistent.rangemovement` | system property | `true` (`CassandraRelevantProperties.java:176`) | true |
| `cassandra.shutdown_announce_in_ms` | system property | 2000 (`CassandraRelevantProperties.java:493`) | 2000 ms wait in `gossiper.stop` |
| gossip interval | constant | 1000 ms (`Gossiper.java:142`) | round period |
| FD initial interval | `cassandra.fd_initial_value_ms` | `2 * interval` = 2000 ms (`FailureDetector.java:110-118`) | 2000 |

Where yaml and `Config.java` differ: `num_tokens` (16 vs null), `allocate_tokens_for_local_replication_factor`
(3 vs null), `partitioner` (Murmur3 vs null), `endpoint_snitch` (SimpleSnitch vs null), `cas_contention_timeout`
(1000ms vs 1800ms). The yaml values are what runs.

## 5. What the code didn't settle, and assumptions

- **Phi.** The arrival window keeps `t_last_ms` and `mean_ms` instead of the 1000-sample window; phi is
  `(now - t_last) / mean` as in `ArrivalWindow.phi` (`FailureDetector.java:541-547`). With a 1 s mean a peer is
  convicted after about 18.4 s of silence (0.434 * phi > 8).
- **Application states.** An endpoint's state is flattened into `status`, `tokens`, `generation`, `heartbeat`,
  `max_version`, `host_id`, `dc`, `rack`, `load`, `rpc_ready`. Per-state versions are collapsed into
  `max_version`, so `applyNewStates` merges all fields when the remote max version is higher.
- **Replication factors** are inputs on `token-metadata` (`keyspace_rf`, `default_rf`) because keyspace metadata
  belongs to schema-auth. Pending ranges are computed once with `keyspace: "*"` and `default_rf`.
- **Token allocation.** `get-bootstrap-tokens` returns `first ring token - 1537228672809129301` instead of
  running `TokenAllocation` for local RF 3.
- **removenode** waits in a 100 ms loop until every replicating node sends REPLICATION_FINISHED
  (`StorageService.java:5743-5746`); the model makes that wait a choice (`confirmed` or `never_confirmed`).
- **Handlers that would NPE.** `GossipShutdownVerbHandler` dereferences the local state of the sender without a
  null check (`GossipShutdownVerbHandler.java:39`); the model treats an unknown sender as generation 0.
- **Replacement** (`replace_address`, BOOT_REPLACE, host-id collisions in `handleStateNormal`) is not modeled.

## 6. Docs and common knowledge versus the code

- "A node is marked down when phi > 8": the code compares `PHI_FACTOR * phi` (PHI_FACTOR = 1/ln 10 = 0.434)
  with the threshold (`FailureDetector.java:99, 360`), so phi itself must exceed about 18.4.
- "Gossip marks a node up when it hears from it": the gossiper first marks it **dead** and only marks it alive
  when the ECHO_REQ is answered (`Gossiper.java:1437-1472`). A node whose echo fails joins the ring (its tokens
  are applied by `onJoin`) but stays down.
- "decommission refuses when it would break RF": the refusal is thrown inside the try block, so the node's mode
  becomes `DECOMMISSION_FAILED` even though nothing started (`StorageService.java:5330-5416`).
- "nodetool move": with the deployed `num_tokens: 16`, every node has more than one token and `move` always
  throws `This node has more than one token and cannot be moved thusly.` (`StorageService.java:5559-5563`).
- A node that receives its own LEFT status (decommission's `leaveRing`) runs `handleStateLeft` on itself through
  `doOnChangeNotifications` (`Gossiper.java:2259`), which removes itself from the seeds list.

## 7. Simulator gaps

Resolved this round:
- **Per-node state and two-sided gossip** (instances and `on:`): every node has its own view and SYN/ACK/ACK2 cross instances.
- **Randomness** (`random(n)`): gossip targets and probabilistic draws.
- **Concurrent streaming and batchlog replay** (`parallel`, `branches`).
- **Timers** (`entry.repeat` with `initial_delay_ms`, `after_ms`) and **chained entries** (multi-step scenarios).
- **Asserting call inputs**: `trace` expectations check `stream-plan.execute`'s peers and ranges.

Still open:
- **Shared state between concurrent branches** can't interleave; branches run in list order.
- **`entry.repeat` intervals are literals**, so the reaper period (min rpc timeout / 2) can't follow a config override.
- **Timers wait for the caller's call tree**, so the GossipTask scheduled by `gossiper.start` inside `init-server`
  runs only after RING_DELAY; gossip during RING_DELAY is written as overlapping scenario steps (`at_ms`). Timers need a
  finite count (`gossip-task-rounds`).
- **Per-instance fixture overrides beat plain keys**, so a scenario can't override one field on every node with one key.

## 8. Known gaps

- One token per node instead of `num_tokens: 16`; ring walks over 48 vnodes would multiply the events in every
  coordination scenario.
- NetworkTopologyStrategy, racks and multiple DCs are not modeled in the ring walk.
- Replacement (`replace_address_first_boot`), write survey mode beyond the flag, `joinRing` via JMX,
  `resumeBootstrap`, `forceRemoveCompletion` and `drain`'s commit-log/compaction shutdown details are not
  modeled.
- Internode connection handshakes, framing, back-pressure (`ResourceLimits`) and the inbound pipeline
  (`InboundMessageHandler`, `InboundSink`) are not modeled; other areas call verb handlers directly.
- The shadow round (`doShadowRound`) is modeled only on the receiving side (empty SYN, minimal ACK, finishing on a full ACK).
- The checker matches citations within 3 lines, so some of my `Verb.java` citations also mark neighbouring verbs
  of other areas as covered (`RANGE_RSP`, `RANGE_REQ`, `SCHEMA_PUSH_RSP`, `PAXOS2_CLEANUP_COMPLETE_REQ`), and
  the `HintsService.pauseDispatch` stub citation (232) marks `HintsService.startDispatch: trigger` (229). The
  owners should cite those entries themselves.
