# Brief: build the Cassandra ontology from code

You are one of eleven area agents building a mosaic ontology of **Apache Cassandra 5.0.9**
directly from its source code. Each agent writes one fragment. The fragments are merged with
`skeleton.yaml` into one ontology. A separate judge then tests that ontology against well-known
Cassandra behavior: consistency levels, hinted handoff, read repair, lightweight transactions,
batches, gossip, repair and compaction. The point is to find out whether mosaic can map a large,
well-understood system correctly from code alone. Model what the code does, not what you remember
about Cassandra. Where they differ, the code wins, and you record the difference in your notes.

This brief carries the lessons from an earlier build of a gateway platform. Contracts and naming are fixed before anyone writes a line.
Coverage is measured against an inventory of entry points. Citations are checked mechanically and
then by an independent judge.

## Rules

1. **Source of truth.** The code at `/home/lbethay/.cache/cassandra-bench/cassandra-5.0.9`
   (tag `cassandra-5.0.9`, `b5f2a54210`). It is read-only: never modify, build or run anything
   in it.
2. **Independence.** Read only these: the code, `skeleton.yaml`, the inventory, your own files,
   and, for contracts only, an owner's fragment when you call another area. Never read other
   agents' notes, `examples/cassandra/BENCHMARK.md` or anything under `examples/cassandra/judge/`.
3. **Evidence.** Every component, interface and narrated step cites code, relative to the
   checkout root: `path:line` or `path:line-end` (for example
   `src/java/org/apache/cassandra/service/StorageProxy.java:1210-1260`). Use **one source per
   string**, and the `sources` list when you need several. Cite files, not directories. The docs
   under `doc/`, `NEWS.txt`, `CHANGES.txt` and the tests under `test/` may orient you, but they
   are not evidence for the model. Cite them only in your notes, never in the ontology.
4. **Deployed config decides modes.** Code defaults aren't always what runs. The deployed
   configuration is `conf/cassandra.yaml`. Values it leaves unset or commented out fall back to
   `src/java/org/apache/cassandra/config/Config.java`. Before you model a timeout, limit, mode or
   feature flag, look it up in both. Model the effective value, and cite the yaml line (or the
   `Config.java` default) next to the code that reads it. Examples: `write_request_timeout` 2000ms,
   `read_request_timeout` 5000ms, `cas_contention_timeout` 1000ms, `hinted_handoff_enabled`,
   `max_hint_window` 3h, `commitlog_sync` periodic 10000ms, `authenticator: AllowAllAuthenticator`,
   `paxos_variant`, `batch_size_fail_threshold`, `tombstone_failure_threshold`. Record in your
   notes every place where the yaml and the `Config.java` default differ.
5. **Secrets.** Never open `*.env*`, keystores, `*.age` or credential files. `conf/credentials.sample`
   is a sample, but there's no reason to read it.
6. **Your files only.** Write `fragments/<area>.yaml` and `notes/<area>.md` under
   `/home/lbethay/workplace/mosaic/examples/cassandra/`. Edit nothing else. Don't commit.

## Areas and ownership

An area owns the classes under its paths. Where paths overlap, the more specific row wins. Some
methods are owned by function rather than by file; the overrides below say which.

| Area | Owns | Typical entry points |
|---|---|---|
| `transport` | `transport/**`, `service/NativeTransportService.java`, `service/ClientState.java`, `service/QueryState.java`, `service/ClientWarn.java` | native-protocol messages (STARTUP, AUTH_RESPONSE, OPTIONS, QUERY, PREPARE, EXECUTE, BATCH, REGISTER), events pushed to clients |
| `cql` | `cql3/**` except the statement packages owned below | `QueryProcessor` process, prepare and execute; SELECT, INSERT, UPDATE, DELETE, BATCH, USE, TRUNCATE; prepared statement cache |
| `coordination` | `service/StorageProxy.java` (except the overrides below), `service/reads/**`, `service/*ResponseHandler.java` (except Batchlog), `service/pager/**`, `locator/**` except `TokenMetadata` and pending ranges, `db/ConsistencyLevel.java`, `service/TruncateResponseHandler.java` | `StorageProxy` mutate, read, range reads, truncate; consistency levels; read repair; speculative retry; replica plans and snitches |
| `paxos` | `service/paxos/**`, `service/CASRequest.java`, and the CAS methods of `StorageProxy` (`cas`, `casWithSnapshot`, and the serial-read path of `read`) | conditional updates (`IF`), SERIAL reads, Paxos verbs (prepare, propose, commit, repair, cleanup) |
| `write-path` | `db/commitlog/**`, `db/memtable/**`, `db/Keyspace.java`, `db/Mutation*.java`, `db/CounterMutation*.java`, `db/ColumnFamilyStore.java` (flush and truncate), `db/WriteType.java`, `db/view/**`, `cdc` code | MUTATION and COUNTER_MUTATION verbs, local apply, commit log sync and replay, memtable flush, materialized view updates |
| `read-path` | `db/*ReadCommand*.java`, `db/ReadExecutionController.java`, `db/rows/**`, `db/partitions/**`, `db/filter/**`, `io/**`, `db/compaction/**`, `db/lifecycle/**`, `index/**`, `cache/**` | READ and RANGE_READ verbs, local single-partition and range reads, tombstone thresholds, compaction strategies and tasks, secondary and SAI index queries, cache loading and saving |
| `hints-batchlog` | `hints/**`, `batchlog/**`, `service/BatchlogResponseHandler.java`, and `StorageProxy.mutateAtomically` and its batchlog helpers, plus `StorageProxy.submitHint` | logged batches, batchlog replay, hint writes and dispatch, the HINT verb |
| `membership` | `gms/**`, `net/**`, `dht/**`, `locator/TokenMetadata.java`, pending-range code, `service/StorageService.java` lifecycle (`initServer`, `joinTokenRing`, bootstrap, decommission, move, removenode, drain), `service/PendingRangeCalculatorService.java`, `service/LoadBroadcaster.java` | gossip rounds and the SYN, ACK and ACK2 verbs; the failure detector; node state changes; bootstrap and decommission; the messaging service and its callbacks and expiry |
| `repair-streaming` | `repair/**`, `streaming/**`, `db/streaming/**`, `service/ActiveRepairService.java`, `service/AutoRepairService.java`, `service/snapshot/**` | `nodetool repair` (full, incremental, preview), Merkle tree validation, sync and streaming sessions, snapshots |
| `schema-auth` | `schema/**`, `auth/**`, `cql3/statements/schema/**`, the role, permission and auth statements in `cql3/statements/` (`*Role*`, `Grant*`, `Revoke*`, `List*`) | CREATE, ALTER and DROP keyspace, table and type; schema pull, push and agreement; login; permission checks; role management |
| `ops` | `tools/**`, `service/CassandraDaemon.java`, `service/StartupChecks.java`, `db/virtual/**`, `tracing/**`, `audit/**`, `fql/**`, `concurrent/**`, `config/**`, `utils/**` (only as needed), `metrics/**`, `security/**`, `service/*MBean.java` | the daemon's startup, nodetool commands and the JMX operations they invoke, virtual tables, tracing sessions, the audit and full query logs |

**JMX and nodetool.** `ops` models each `nodetool` command as a flow whose entry is the command and
which calls the owner's interface: `nodetool repair` calls repair-streaming's
`storage-service.repair-async`, `nodetool flush` calls write-path's `column-family-store.force-flush`.
Owners model what the operation does. Don't model a bare MBean getter as a flow. Skip getters as a
group (see "Coverage").

## Naming (fixed, so callers can predict the owner's ids)

- **Components** are named after the Java class in kebab-case: `StorageProxy` →
  `storage-proxy`, `MutationVerbHandler` → `mutation-verb-handler`, `HintsDispatchExecutor` →
  `hints-dispatch-executor`. An inner class takes its outer class's prefix:
  `Gossiper.GossipTask` → `gossiper-gossip-task`. Put every component under your skeleton module
  (`parent: coordination` and so on), or under another of your components.
- **Interfaces** are named after the method in kebab-case: `StorageProxy.mutateWithTriggers` →
  `storage-proxy.mutate-with-triggers`, `VerbHandler.doVerb` → `<handler>.do-verb`. When overloads
  behave differently, add a suffix (`read-serial`). Cite the method's own lines, because coverage
  matches them.
- **Native-protocol messages** are interfaces on `transport`, named `<opcode>-message`
  (`query-message`, `execute-message`), with kind `cql`.
- **Schemas** take your area prefix in PascalCase: `WritePathMutation`, `CoordinationReadCommand`,
  `HintsBatchlogHint`. A shared contract keeps its owner's name, and only the owner defines it.
- IDs are globally unique across all areas. Never use generic names such as `handler` or `store`.

## Cluster convention

Every node runs the same code, and the ontology models that code once. The node we follow plays
**coordinator** for the client's request. Other nodes appear only as the receivers of internode
messages.

- **An internode message is a call to the receiving verb handler's interface**, with
  `kind: verb` and `attributes: {verb: MUTATION_REQ}` (the `Verb` enum name). The request carries
  `to` (the replica's endpoint, such as `10.0.0.2`) and the payload. The handler's behavior is
  what that replica does. The response, or the absence of one, is what the coordinator sees.
- **Fan-out to replicas** is a `foreach` over the replica plan, calling the verb handler once per
  replica with `on_error: continue`. Count the acknowledgements, and compare them with what the
  consistency level blocks for, as the code's response handler does. Because faults can target the
  Nth invocation (`calls: [2]`), a scenario can fail one replica and not another.
- **Liveness and topology are state**, so scenarios can set them. `membership` owns the
  failure detector's view of endpoint liveness and the token ring. Coordination's replica plan
  reads them through membership's interfaces (`failure-detector.is-alive`, and an interface
  that returns the natural and pending replicas for a token). Scenarios declare the cluster in
  `state`: typically 3 nodes, RF 3, `SimpleStrategy` or `NetworkTopologyStrategy` with 1 DC.
- **Local delivery.** When the coordinator is itself a replica, the code applies locally instead
  of messaging itself. Model that branch (`StorageProxy` decides it).
- **Timeouts** come from the deployed config (2000ms for writes, 5000ms for reads, and so on),
  as the code applies them through the callback expiry.
- **Parallelism.** The simulator runs a `foreach` sequentially, while Cassandra sends in parallel
  and waits for the first `blockFor` responses. Model the decision logic faithfully (which
  replicas, how many acks, when it times out or is unavailable, what gets hinted). Record every
  place where sequential execution distorts timing or ordering under "Simulator gaps" in your
  notes. Those notes feed mosaic's own roadmap.

## Contracts (fixed before fan-out)

- **The owner's definition is the contract.** Each interface has one owner: the area that owns its
  class, by the table above. When you call another area's interface, your boundary stub copies
  the owner's request, response, kind and errors if the owner's fragment exists. Read it for that
  and nothing else. If it doesn't exist yet, use the shared shapes below, declare only what your
  call site really sends and reads, and expect to align in the reconciliation round.
- **Shared shapes.** Use these field names everywhere, so stubs merge cleanly:
  - `keyspace`, `table`: strings.
  - `partition_key`: a string rendering of the key, such as `"user:42"`.
  - `token`: an integer (Murmur3).
  - `consistency`: the `ConsistencyLevel` enum name (`ONE`, `QUORUM`, `LOCAL_QUORUM`, `ALL`,
    `SERIAL`, `LOCAL_SERIAL`, `ANY`, `TWO`, `THREE`, `EACH_QUORUM`, `LOCAL_ONE`, `NODE_LOCAL`).
  - `to` and `from`: endpoint strings.
  - `replicas`: a list of endpoint strings.
  - `timestamp`: microseconds, an integer.
  - `columns`: a map from column name to value.
  - `mutation`: write-path's `WritePathMutation`, `{keyspace, table, partition_key, token, timestamp, columns}`.
  - `read_command`: read-path's `ReadPathReadCommand`, `{keyspace, table, partition_key, token, columns, limit, digest}`.
- **Errors use the Java exception name in kebab-case as the code**, and set `status` to the
  native-protocol error code where one exists: `unavailable` (0x1000, i.e. 4096), `write-timeout`
  (0x1100), `read-timeout` (0x1200), `read-failure` (0x1300), `write-failure` (0x1500),
  `cas-write-unknown` (0x1700), `syntax-error` (0x2000), `unauthorized` (0x2100), `invalid`
  (0x2200), `config-error` (0x2300), `already-exists` (0x2400), `unprepared` (0x2500),
  `overloaded` (0x1001), `is-bootstrapping` (0x1002), `truncate-error` (0x1003),
  `bad-credentials` (0x0100), `protocol-error` (0x000A), `server-error` (0x0000). Check them
  against `transport/ProtocolException`, `exceptions/ExceptionCode.java` and the code that throws.
- **Stubs merge by union.** When several areas stub the same boundary interface, the merge combines
  their properties, required lists, enums and errors, and keeps the first value of any scalar
  (kind, a schema type, an error status). The check tool warns about every disagreement. So declare
  every field your code really reads, and copy the owner's scalars.
- **Shared infrastructure.** `commitlog-disk`, `data-disk` and `hints-disk` are skeleton components
  with `owner: shared`. Calls to them are boundary-stub interfaces named after the operation
  (`commitlog-disk.segment-append`, `data-disk.sstable-write`), with `kind: io`. Stateful storage
  that scenarios must inspect (memtable contents, hint queues, the batchlog table, Paxos state)
  belongs on the owner's own component, as `store` interfaces keyed by `replica + ':' + key`,
  so each replica's copy stays separate.

## How to model

Read these first: `/home/lbethay/workplace/mosaic/.claude/skills/mosaic-ontology/SKILL.md` and
its `references/document-format.md` and `references/modeling-codebases.md`; then
`.claude/skills/mosaic-simulation/SKILL.md` and its `references/behavior-language.md` and
`references/recipes.md`. Ignore their CLI instructions: you verify with the check tool below, not
a server.

- **Fragment header.** `schema_version: 1`, `id: cassandra`, then your entities. Don't redefine
  skeleton components.
- **Depth.** Go down to the smallest components that make a decision or own state: handlers,
  response handlers, executors, managers, strategies, caches, verb handlers. Behaviors follow the
  real control flow:
  - refusals with the real exceptions and protocol codes;
  - retries and speculative retries with their real triggers;
  - timeouts from the deployed config;
  - fallbacks, state transitions;
  - async and background work (stages, executors, scheduled tasks) as `emit`, or as flows with
    `entry.repeat` for periodic tasks.
  Payload schemas come from the real classes and the native-protocol spec in the code, with
  realistic `examples`.
- **Boundary stubs.** When your behavior calls an interface another area owns, declare that
  interface in your fragment with `attributes: {boundary: true, owner: <area>}`, give it the
  owner's shapes, and leave out the behavior. Never model another area's internals.
- **Flows** come from the inventory's entry points. Each modeled flow has an `entry` and scenarios:
  a happy path plus one per significant branch (unavailable replicas, timeouts, refusals, retries,
  fallbacks). Each scenario has `expect` assertions that prove the branch, over `result`, `calls`,
  `state` and `faults`.
- **Scale.** Breadth first. Rough target per area: 20 to 80 components, 5 to 12 fully modeled flows,
  20 to 50 scenarios. Quality over volume, but every entry point is accounted for.

## Coverage: every entry point is modeled or skipped with a reason

The coordinator generates the inventory once, at `examples/cassandra/inventory.json`. It lists the
messaging verbs and their handlers, native-protocol messages, CQL statements, nodetool commands,
JMX operations, scheduled and background tasks, and main classes, each with
`{kind, name, file, line}`.

There are 1,353 entries: 913 `jmx-operation`, 159 `cli-command`, 82 `messaging-verb`, 57 `cql-statement`,
43 `scheduled-task`, 37 `verb-handler`, 26 `java-main`, 19 `stage-task`, 8 `native-message`, 5
`background-task` and 4 `python-cli`.

**Which area owns an entry:**
- A `messaging-verb` entry is a line of `net/Verb.java`. It belongs to the area that owns its
  handler (named in `detail`), not to `membership`. Cover it by adding that `Verb.java` line to the
  handler interface's `sources`. Response verbs (`*_RSP`, handled by `ResponseVerbHandler`) belong
  to the area that sends the request.
- `jmx-operation` entries in `service/*MBean.java` belong to `ops`, and so do MBeans under other
  paths when their operation is just a call through to another area.
- The four `python-cli` entries and the `doc/scripts` entries are `ops` skips.

For every entry under your area's paths:
- **model it**: a flow-reachable interface or component cites its lines (or is named after it by
  the rules above). Covering an entry can be cheap: an entry interface whose behavior calls an
  already modeled component, with one happy-path scenario.
- **or skip it with a reason**: list it in your notes under "Skipped entry points" with a
  one-line reason. **Group skips are allowed** when one reason covers many entries, as long as the
  group is exact. Example: "the 212 JMX getters in `StorageServiceMBean` (`get*`, `is*`): reads of
  config or metrics, no behavior". The coordinator copies these reasons into the inventory's `skip`
  fields.
- **heuristic false positives** (not really an entry point) are skips too, with the reason "not an
  entry point: ...".

## Verify before hand-off

```sh
cd /home/lbethay/workplace/mosaic
PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly go run ./internal/devtools/check \
  -f examples/cassandra/skeleton.yaml -f examples/cassandra/fragments/<area>.yaml \
  --code /home/lbethay/.cache/cassandra-bench/cassandra-5.0.9 --strict-citations \
  --inventory examples/cassandra/inventory.json -v
```

Hand off only when:
1. **0 errors and 0 failed scenarios.** Fix scenario warnings, which are schema mismatches.
2. **Citations resolve** (`--strict-citations` passes).
3. **Citations support their claims.** Run `--cite-sample 15 --seed <any>`, and read each sampled
   claim next to its code. A citation that resolves but points at the wrong lines is a bug. Fix
   every bad one, then sample again with another seed.
4. **No merge warnings that mention your fragment.**
5. **Coverage.** Every inventory entry under your area's paths appears either as covered in the
   `-v` coverage output or as skipped in your notes.

## Independent judge

After hand-off, a judge that didn't build your fragment reviews it against the code, and the merged
ontology is run against benchmark scenarios you haven't seen. The judge's findings come back to
you as fixes, not suggestions. Write your notes so that a stranger can check them.

## Notes file (`notes/<area>.md`)

1. Entry points: each inventory entry in your area, with the flow or interface that covers it,
   or its skip reason ("Skipped entry points").
2. The components you modeled, with code references.
3. The boundary stubs you declared, and whose contract you copied.
4. The deployed config you read: values from `cassandra.yaml` and `Config.java`, with references,
   and where they differ.
5. What the code didn't settle, and the assumptions you made.
6. Where the docs, or common knowledge about Cassandra, disagree with the code.
7. **Simulator gaps**: behavior you couldn't express in mosaic's behavior language, or could
   express only approximately (parallel fan-out, waiting for k of n, speculative timing,
   streaming). Give each one an example.
8. Known gaps.

## Report back (≤200 words)

- Entity counts.
- The check tool's final output lines, including the citation and coverage lines.
- The flows you modeled.
- How many entries you covered and how many you skipped.
- The top modeling gaps and the top simulator gaps.
