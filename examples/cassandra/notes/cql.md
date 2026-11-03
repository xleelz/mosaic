# cql area notes

Fragment: `examples/cassandra/fragments/cql.yaml`. Code: `cassandra-5.0.9` (`b5f2a54210`). All
paths below are relative to `src/java/org/apache/cassandra/` unless they start with `conf/`.

The area covers `cql3/**`, except `cql3/statements/schema/**` and the role, permission and auth
statements (`*Role*`, `Grant*`, `Revoke*`, `List*`) owned by schema-auth. The CQL layer sits
between the transport's QUERY, PREPARE, EXECUTE and BATCH messages and `StorageProxy`.

## 1. Entry points

Inventory entries under the area's paths: 17 cql-statement entries and 1 scheduled task. 17 are
covered and 1 is skipped. The check tool reports them as `line` coverage.

| Inventory entry | Covered by |
|---|---|
| `SelectStatement` (cql3/statements/SelectStatement.java:109) | flow `cql-select`: `select-statement.execute`, `.authorize`, `.validate`, `.execute-locally`; flow `cql-parse-query`: `select-statement-raw-statement.prepare` |
| `ModificationStatement` (:76) | flows `cql-write`, `cql-delete`, `cql-conditional-write`: `modification-statement.execute`, `execute-without-condition`, `execute-with-condition`, `get-mutations`, `add-updates`, `execute-locally`, `execute-internal-without-condition` |
| `UpdateStatement` (:48) | `update-statement.add-update-for-key`, `update-statement-parsed-insert.prepare-internal`, `update-statement-parsed-update.prepare-internal` |
| `DeleteStatement` (:46) | flow `cql-delete`: `delete-statement.add-update-for-key`, `delete-statement-parsed.prepare-internal` |
| `BatchStatement` (:61) | flow `cql-batch`: `batch-statement.execute`, `validate-batch`, `get-mutations`, `execute-without-conditions`, `execute-with-conditions`, `execute-locally`; `batch-statement-parsed.prepare` |
| `UseStatement` (:37) | flow `cql-use` |
| `TruncateStatement` (:42) | flow `cql-truncate` |
| `DescribeStatement` (:66) | flow `cql-describe`: `describe-statement.execute`, `execute-locally` |
| `DescribeStatement.Listing` (:256) | `describe-statement-listing.describe` |
| `DescribeStatement.keyspaces$1` (:328) | `describe-statement-keyspaces.describe` |
| `DescribeStatement.schema$2` (:357) | `describe-statement-schema.describe` |
| `DescribeStatement.Element` (:387) | `describe-statement-element.describe` |
| `DescribeStatement.generic$5` (:629) | `describe-statement-generic.describe` |
| `DescribeStatement.cluster$6` (:692) | `describe-statement-cluster.describe` |
| `AuthenticationStatement` (:32) | flow `cql-identity`: `authentication-statement.execute`, `check-permission` |
| `AddIdentityStatement` (:39) | flow `cql-identity`: `add-identity-statement.authorize`, `validate`, `execute` |
| `DropIdentityStatement` (:38) | flow `cql-identity`: `drop-identity-statement.*` |
| scheduled-task `QueryProcessor: lastMinuteEvictionsCount.getAndSet` (QueryProcessor.java:120-126) | flow `cql-prepared-eviction-report`: `query-processor.report-last-minute-evictions` (repeat 2 x 60 s) |

The QueryHandler entry points the transport calls, and the flows that model each one:

| QueryHandler method | Interface | Flow |
|---|---|---|
| `parse` (QueryProcessor.java:345) | `query-processor.parse` | `cql-parse-query` |
| `process` (:359) | `query-processor.process` | `cql-select`, `cql-write`, `cql-delete`, `cql-conditional-write`, `cql-use`, `cql-truncate`, `cql-describe`, `cql-identity` |
| `prepare` (:728) | `query-processor.prepare` | `cql-prepare` |
| `getPrepared` (:244) | `query-processor.get-prepared` | `cql-get-prepared` |
| `processPrepared` (:851) | `query-processor.process-prepared` | `cql-execute-prepared` |
| `processBatch` (:883) | `query-processor.process-batch` | `cql-batch` |
| `CQL3CasRequest.appliesTo` (called by Paxos) | `cql3-cas-request.applies-to` | `cql-cas-condition-check` |
| `StatementInvalidatingListener.onDropTable` / `onDropKeyspace` (called by schema changes) | `query-processor-statement-invalidating-listener.on-drop-table` / `.on-drop-keyspace` | `cql-invalidate-on-drop-table`, `cql-invalidate-on-drop-keyspace` |

### Skipped entry points

- cql-statement `AuthorizationStatement` (cql3/statements/AuthorizationStatement.java:34): an
  abstract base class. Its only concrete subclasses are `GrantPermissionsStatement`,
  `RevokePermissionsStatement` and `ListPermissionsStatement`, which schema-auth owns.
  `execute(QueryState, ...)` only delegates to `execute(ClientState)` (lines 41-45), and
  `executeLocally` throws `UnsupportedOperationException`. There is no behavior of its own to model.

## 2. Components

29 components of its own and 10 boundary-stub components.

| Component | Code |
|---|---|
| `query-processor` (state: cache size, NODE_LOCAL flag, prepared-id behaviour, eviction count, persisted count) | cql3/QueryProcessor.java:82-130 |
| `query-processor-prepared-statements` (Caffeine cache as a `store`, table `entries`) | QueryProcessor.java:111-118 |
| `query-processor-statement-invalidating-listener` | QueryProcessor.java:975-1134 |
| `cql-fragment-parser` | cql3/CQLFragmentParser.java:63-83 |
| `statement-restrictions` | cql3/restrictions/StatementRestrictions.java:585-601 |
| `select-statement` (state: allow_filtering_enabled, read CL guardrail) and `select-statement-raw-statement` | cql3/statements/SelectStatement.java:109-120, 1182-1275 |
| `modification-statement` (state: user_timestamps_enabled, write CL guardrail) and `modification-statement-parsed` | ModificationStatement.java:76-159, 923-1055 |
| `update-statement`, `update-statement-parsed-insert`, `update-statement-parsed-update` | UpdateStatement.java:48-111, 113-201, 272-336 |
| `delete-statement`, `delete-statement-parsed` | DeleteStatement.java:46-124, 126-195 |
| `cql3-cas-request` | CQL3CasRequest.java:49-91 |
| `batch-statement` (state: batch thresholds) and `batch-statement-parsed` | BatchStatement.java:61-136, 611-662 |
| `use-statement` (state: use_statements_enabled) | UseStatement.java:37-93 |
| `truncate-statement` (state: drop_truncate_table_enabled) | TruncateStatement.java:42-131 |
| `describe-statement` and its six implementations (`-listing`, `-keyspaces`, `-schema`, `-element`, `-generic`, `-cluster`; cluster has the cluster name, partitioner and snitch) | DescribeStatement.java:66-786 |
| `authentication-statement`, `add-identity-statement`, `drop-identity-statement` | AuthenticationStatement.java:32-74, AddIdentityStatement.java:39-90, DropIdentityStatement.java:38-102 |

Anonymous inner classes take their outer class's prefix plus the factory method's name
(`DescribeStatement.keyspaces$1` becomes `describe-statement-keyspaces`).

## 3. Boundary stubs

In the reconciliation round every stub was aligned to its owner's fragment: request, response, kind
and errors, with no `retryable` the owner doesn't declare (RECONCILE.md decision 1).

| Stub | Owner, contract copied from | Notes |
|---|---|---|
| `storage-proxy.mutate-with-triggers` | coordination (`CoordinationWriteRequest`) | `{mutations[], consistency, mutate_atomically}`. Each mutation follows the WritePathMutation shape plus `counter` (coordination's name), `ttl`, `deletion` and `primary_key_liveness`. Coordination's schema says `maxItems: 1`, but `mutateWithTriggers` takes the whole list (StorageProxy.java:1116-1160) and a LOGGED batch is atomic only with more than one mutation. So cql sends the list, and coordination should drop `maxItems`. |
| `storage-proxy.read` | coordination (`CoordinationReadRequest`, decision 2) | `{read_command, consistency}`. `read_command` is the ReadPathReadCommand shape, with `columns` as a list of names. The code sends one `SinglePartitionReadCommand.Group`; the contract takes one command, so IN and list reads make one call per partition key. Response `{rows[]}`. |
| `storage-proxy.get-range-slice` | coordination (`CoordinationRangeReadRequest`) | `{command: {keyspace, table, start_token, end_token, limit, filtered}, consistency}`. An unrestricted SELECT is the full ring: start = end = Long.MIN_VALUE. |
| `storage-proxy.truncate-blocking` | coordination | errors `unavailable`, `timeout`, `truncate-error` |
| `storage-proxy.cas` | paxos (`PaxosCasRequest` / `PaxosCasResult`) | `{keyspace, table, partition_key, token, conditions, if_not_exists, if_exists, columns, consistency (serial), commit_consistency}`. Response `{applied, contentions, rows}`. A conditional batch sends the first statement's `columns`, because CEL can't merge maps. |
| `consistency-level.validate-*` | coordination | response `{ok}` |
| `schema.validate-table`, `schema.get-distributed-schema-blocking` | schema-auth | The stub's version example equals schema-auth's initial `state.version`, so paging scenarios work in both runs. |
| `client-state.*` | transport | |
| `cassandra-role-manager.*`, `roles.has-superuser-status` | schema-auth | Object responses: `{is_super}`, `{exists}`, `{role}`. |
| `storage-service.is-bootstrap-mode` | membership (decision 6) | `{bootstrap_mode}` |
| `storage-service.get-range-to-address-map`, `gossiper.get-min-version` | membership | No owner definition yet; my original shapes are kept. |
| `read-command.execute-locally` | read-path | `{read_command}` in, then `{partitions: [{partition_key, cells[]}]}` out. The local CAS can't rebuild a column map from cells, so only IF [NOT] EXISTS is exact there. |
| `mutation.apply` | write-path | `{mutation}` |

DELETE mutations set `partition_deletion: true` (write-path's contract, migration round) for a partition or row deletion (DeleteStatement.java:67-86), and carry `cells: [{column, value: null, timestamp, deleted: true}]` for a deletion of named columns, so that write-path applies tombstones and read-path counts them. Coordination has since dropped `maxItems: 1`, so batches send their whole mutation list without warnings.

Interfaces cql defines for other areas (decision 6): `query-processor.process-query-string`
(QueryProcessor.java:377-393; a pass-through that checks syntax and returns no rows, because
callers send only text), `query-processor.preload-prepared-statements` (:165-206) and
`query-processor.clear-prepared-statements` (:208-213). `query-processor.get-prepared` now
returns `{found: true, ...row}` on a hit.

Contract requests for the other areas:

- **transport**: the QUERY, PREPARE, EXECUTE and BATCH message interfaces should call
  `query-processor.parse`, then `query-processor.process`; `query-processor.prepare`;
  `query-processor.get-prepared` (and answer UNPREPARED, 0x2500, when it returns
  `{found: false}`), then `query-processor.process-prepared`; and `query-processor.process-batch`.
  The request shape is `CqlRequest` `{statement, options, client_state}`.
- **paxos**: call `cql3-cas-request.applies-to` with `{row_exists, current, conditions,
  if_not_exists, if_exists}` after the Paxos read, so that `[applied] = false` comes from real
  comparisons.
- **schema-auth**: when a table or keyspace is dropped, emit to
  `query-processor-statement-invalidating-listener.on-drop-table` or `.on-drop-keyspace`.

## 4. Deployed config read

Since the migration round, each value below is a `config` entity in the fragment (`configs:`,
15 ids: `prepared-statements-cache-size-mib`, `enable-nodelocal-queries`,
`force-new-prepared-statement-behaviour`, `allow-filtering-enabled`,
`read-consistency-levels-disallowed`, `write-consistency-levels-disallowed`,
`user-timestamps-enabled`, `drop-truncate-table-enabled`, `use-statements-enabled`,
`batch-size-warn-threshold-kib`, `batch-size-fail-threshold-kib`,
`unlogged-batch-across-partitions-warn-threshold`, `cluster-name`, `partitioner`,
`endpoint-snitch`). Behaviors read `config['...']`, and scenarios override them with
`config:` instead of seeding component state.


| Setting | cassandra.yaml | Config.java default | Effective | Read at |
|---|---|---|---|---|
| prepared_statements_cache_size | `conf/cassandra.yaml:508` empty ("auto") | `Config.java:585` null | max(heap/256, 10) MiB (`DatabaseDescriptor.java:796`). **Modeled as 10 MiB** | QueryProcessor.java:107, 825 |
| batch_size_warn_threshold | `:1840` 5KiB | `:330` 5KiB | 5 KiB | BatchStatement.java:337 |
| batch_size_fail_threshold | `:1844` 50KiB | `:332` 50KiB | 50 KiB | BatchStatement.java:349 |
| unlogged_batch_across_partitions_warn_threshold | `:1847` 10 | `:334` 10 | 10 | BatchStatement.java:388 |
| use_statements_enabled | `:2003` commented out | `:611` true | true | UseStatement.java:60 |
| allow_filtering_enabled (guardrail) | `:2173` commented out | `:906` true | true | SelectStatement.java:276 |
| user_timestamps_enabled (guardrail) | `:2069` commented out | `:886` true | true | ModificationStatement.java:281 |
| drop_truncate_table_enabled (guardrail) | `:2082` commented out | `:889` true | true | TruncateStatement.java:62 |
| read/write_consistency_levels_disallowed | `:2109`, `:2113` commented out | `:883`, `:885` empty | none | SelectStatement.java:286, ModificationStatement.java:497, BatchStatement.java:416 |
| read_thresholds_enabled | `:2015` commented out | `:526` false | false (no read-size warnings) | SelectStatement.java:334 |
| force_new_prepared_statement_behaviour | absent | `:119` false | false; the behaviour switches when gossip reports every node at 4.0.2 or later | QueryProcessor.java:692 |
| authenticator | `:198` AllowAllAuthenticator | `:82` null | AllowAll, so every ClientState user is ANONYMOUS_USER (ClientState.java:175-176) | |
| authorizer | `:217` AllowAllAuthorizer | `:83` null | AllowAll; `requireAuthorization()` is false, so permission checks pass | ClientState.java:477 |
| role_manager | `:232` CassandraRoleManager | `:84` null | CassandraRoleManager | |
| cluster_name / partitioner / endpoint_snitch | `:26` 'Test Cluster' / `:389` Murmur3Partitioner / `:1556` SimpleSnitch | `:81` "Test Cluster" / `:109` null / `:423` null | as in the yaml | DescribeStatement.java:717-719 |
| cassandra.enable_nodelocal_queries (system property) | n/a | `CassandraRelevantProperties.java:219`, no default | false | QueryProcessor.java:283 |

Where yaml and `Config.java` differ: `authenticator`, `authorizer`, `role_manager`, `partitioner`
and `endpoint_snitch` are null in `Config.java` and set in the yaml.
`prepared_statements_cache_size` is unset in both and resolved by DatabaseDescriptor. All the
other values above agree, or the yaml leaves them commented out.

## 5. What the code didn't settle, and assumptions

- **Parsing.** The ANTLR grammar can't run in the simulator. Callers supply the parsed structure
  (`CqlStatement`) next to the query text. `cql-fragment-parser` only refuses text that doesn't
  start with a known statement keyword. Prepare-time checks are driven by statement flags
  (`needs_filtering`, `table_kind`, `partition_keys`, `table_has_clustering`) that stand in for
  `TableMetadata` and the `StatementRestrictions` analysis.
- **Prepared statement ids** are `'md5:' + keyspace + query` strings instead of MD5 digests. With
  no keyspace, both ids coincide, as in the code (`computeId`, QueryProcessor.java:786-790).
- **Prepared size**: `prepared_size_bytes` (default 3072) stands in for `ObjectSizes.measureDeep`.
- **Heap**: the cache size takes the 10 MiB floor, because the heap size depends on the host
  (`cassandra-env.sh`).
- **Timestamps**: the server timestamp is `now * 1000` µs (the one clock, §11.3), standing in for
  `ClientState.getTimestamp()`. USING TIMESTAMP wins over the protocol default timestamp, which
  wins over the server clock (`Attributes.getTimestamp`, `QueryOptions.getTimestamp`).
- **Paging**: `select-statement.execute` calls `storage-proxy.read` or `get-range-slice` directly
  with `limit = page_size` when the code would use a `QueryPager` (owned by coordination). The
  decision to page matches the code (SelectStatement.java:338): no aggregation, and either
  page_size <= 0 or limit <= page_size means no pager. `has_more_pages` is approximated as "the
  page came back full".
- **ensureNotAnonymous** (identity statements) is decided at my call site from
  `client_state.is_anonymous`, because the outcome depends on input the transport stub can't vary.
- **The batch collector** keeps one mutation per `keyspace:partition_key`, with one update per
  table (`MutationBuilder.modifications` is keyed by TableId, BatchUpdatesCollector.java:193-231).
  When a second table joins, `updates` becomes the complete per-table list and the top-level
  `table`, `columns` and `cells` mirror its first entry (write-path's `WritePathMutation.updates`
  contract); single-table mutations keep `updates` empty. Statements on the same table and key
  merge their column maps with `merge()` (`getPartitionUpdateBuilder`, :93-105). Fix round
  (B1-xtable): before this, a second table's columns were merged into the first table's update,
  so `total` went to `shop.users` and nothing reached `shop.orders`. Scenarios
  `cql-batch-same-partition-two-tables-one-mutation` and
  `cql-batch-two-tables-same-partition-then-read`.
- **The CAS request** passes the first conditional statement's `conditions`, `if_not_exists` and
  `if_exists` if any statement has them, plus one update per statement. The code holds
  per-clustering RowConditions.
- **The CAS result** (`modification-statement.build-cas-result-set`) is one `[applied]` column;
  when not applied it is followed by the current values of the condition columns (every column
  for IF [NOT] EXISTS), rebuilt from the cells Paxos read (ModificationStatement.java:605-677).
  The primary key columns a batch adds are not, because the model carries no key column names.
- **Result rows** (`select-statement.process`) are rebuilt from the coordinator's partitions of
  cells: one column per live cell of a selected column (SelectStatement.java:994-1021).
- **Column conditions** are equality only. `ColumnCondition` also supports `<`, `<=`, `!=`, `IN`,
  `CONTAINS` and collection element conditions, and an `= null` condition holds on a missing row,
  which the model doesn't reproduce.

- **Session keyspace.** `get-statement` and `parse-and-prepare` fill an unqualified statement's
  keyspace (and each unqualified statement of a batch) from `client_state.keyspace`, as
  QualifiedStatement.setKeyspace does (QualifiedStatement.java:44-53); with no session keyspace
  they refuse with "No keyspace has been specified...".

## 6. Where common knowledge or docs disagree with the code

1. **A LOGGED batch on a single partition does not use the batchlog.**
   `mutateAtomic = isLogged() && mutations.size() > 1` (BatchStatement.java:443-445). Statements
   on the same partition merge into one Mutation, which is already atomic.
2. **Batch size limits apply only to multi-partition batches.** `verifyBatchSize` returns early
   for one mutation (BatchStatement.java:333-335, CASSANDRA-10876). A 60 KiB single-partition
   batch passes the 50 KiB fail threshold (scenario `cql-batch-large-single-partition-allowed`).
3. **The unlogged-batch threshold only warns.** More than 10 partitions in an UNLOGGED batch adds
   a client warning, never a refusal.
4. **Guardrails don't apply to superusers or internal callers.** `Guardrail.enabled` checks
   `isOrdinaryUser()` (db/guardrails/Guardrail.java:93-96).
5. **IN on the partition key in a conditional batch is a SERVER_ERROR**, not INVALID. It is
   thrown as `IllegalArgumentException` (BatchStatement.java:503-504), and
   `ErrorMessage.fromException` maps unknown exceptions to ServerError.
6. **NODE_LOCAL is refused unless `-Dcassandra.enable_nodelocal_queries=true`**
   (QueryProcessor.java:283-284). Even then only writes and SELECT are allowed, and
   `processBatch` never routes NODE_LOCAL (only `processStatement` does).
7. **`BatchStatement.execute` never calls `ConsistencyLevel.validateForWrite`**, unlike a single
   modification (ModificationStatement.java:512-515). A non-conditional BATCH at SERIAL isn't
   refused by the CQL layer, so whatever happens next is up to StorageProxy.
8. **Under the deployed AllowAllAuthenticator, ADD IDENTITY and DROP IDENTITY always fail with
   UNAUTHORIZED**: "You have to be logged in and not anonymous" (AddIdentityStatement.java:64,
   DropIdentityStatement.java:78).
9. **INSERT writes a primary key liveness marker and UPDATE does not**
   (UpdateStatement.java:72-73, CASSANDRA-6782). A row created by UPDATE disappears when all its
   cells are deleted.
10. **USE validates the keyspace whenever a user is set.** With AllowAll the user is
    ANONYMOUS_USER, so USE of a missing keyspace fails (ClientState.java:369-370).
11. **Server-side DESCRIBE is always local and needs no permission**, whatever the consistency
    level (DescribeStatement.java:113-133).
12. **An unqualified prepared statement is cached under two ids**, with and without the keyspace
    (QueryProcessor.java:773-782). Clients receive the keyspace-qualified id once every node is
    at 4.0.2 or later.
13. Reading `cassandra.yaml` alone suggests that `batch_size_fail_threshold` caps every batch.
    See item 2.

## 7. Simulator gaps

Resolved in the migration round: multi-request sessions (PREPARE then EXECUTE, DESCRIBE paging
round trips and write-then-read are multi-step scenarios); map merging (`merge()` now rebuilds
rows from cells and merges batch updates to one partition); the one clock (no wall-clock
literals). Still open: no parser, stub outputs that can't be steered in a standalone run, cache
eviction, and scenario input that can't delete map keys.

- **Shared datasets differ between the standalone and merged runs.** Stubs return fixed examples, while the owners return their seeded state (schema-auth's schema has only `shop`, and read-path has no rows). So DESCRIBE, SELECT row-count and LWT scenarios assert structure and consistency (rows all of type table, `applied == ctx.casApplied`), not exact counts. Run-mode-specific fixtures would help.

- **Stub outputs can't be steered per scenario.** A boundary stub always returns the same fake
  response for a seed. To reach `[applied] = false` through `storage-proxy.cas`, or
  `is-bootstrap-mode = true`, a scenario would need a "stub returns X" override, such as
  `stub_responses: {storage-proxy.cas: {applied: false}}`. Today only faults can change a stub's
  outcome. The not-applied path is tested only through the local CAS (`cql-lwt-node-local-not-applied`).
- **Scenario input can't remove map keys.** A deep merge can't turn the flow's
  `columns: {name, email}` into `{}`, so DELETE needed its own flow (`cql-delete`). A `$replace`
  or null-deletes merge option would fix this.
- **PartitionUpdate merging inside a batch** merges only the column maps of updates to the same
  table and key; cells and deletions of the later statement are not merged.
- **Cache eviction isn't simulated.** The Caffeine weight-based eviction that feeds
  `lastMinuteEvictionsCount` can't happen, so the count is seeded through state.
- **No multi-request client sessions.** Paging state round trips (page 1, then page 2 with the
  returned state) and PREPARE-then-EXECUTE need two entry calls in one run. They are modeled as
  separate scenarios with hand-made paging state or seeded cache rows.
- **Parallel fan-out**: not relevant at this layer. The CQL layer makes one blocking
  StorageProxy call per statement. The batch per-statement loops are sequential in the code too.
- **No parser.** The grammar can't run, so syntax errors are approximated by a keyword regex
  (example: `SELECT * FORM t` passes the model but fails the real parser).

## 8. Known gaps

- **DDL and role statements through QUERY** (judge `schema-repair-protocol.md` §2.1) now go
  through `query-processor.process-statement`: DDL types (`CREATE_TABLE` and the rest, schema-auth's
  `SchemaAuthDdlRequest`) to `alter-schema-statement.authorize/validate/execute` with the same
  `CqlRequest`, and role, permission and LIST statements to schema-auth's classes with their
  `SchemaAuthRoleStatement` plus the executing user. `ListRolesStatement.authorize` and
  `ListPermissionsStatement.authorize` (ListRolesStatement.java:78, ListPermissionsStatement.java:83)
  are not modelled by schema-auth, so they are skipped.
- **DDL at NODE_LOCAL** is refused by `processNodeLocalStatement` (QueryProcessor.java:281-292,
  which only accepts BATCH, modification and SELECT statements), after authorize and validate. So
  `alter-schema-statement.execute-locally` is not reachable from QUERY, although schema-auth's
  notes suggest routing NODE_LOCAL DDL there; the code wins (scenario `cql-ddl-node-local-refused`).
- **Migration counts.** No `to` fields (the CQL layer runs on the coordinator) and no replica
  fan-out, so no `parallel`. 15 configs (13 owned, `cluster-name` and `partitioner` as boundary
  references to membership's). 10 flows tagged `writes`, each with a multi-step read-back.
  `query-processor-prepared-statements` is kind `cache` (incidental). The eviction report is a
  repeated entry with `initial_delay_ms: 60000` (scheduleAtFixedRate(…, 1, 1, MINUTES)).
- `query-processor-statement-invalidating-listener` subscribes to the topics
  `schema-change-notifier.on-drop-table` and `.on-drop-keyspace`; schema-auth's
  SchemaChangeNotifier must publish `{keyspace, table}` there for the listener to fire in the
  merged model.

- Restriction analysis is reduced to flags: clustering slices, token restrictions, IN on
  clustering columns, secondary index and SAI selection, ORDER BY, GROUP BY, aggregates,
  PER PARTITION LIMIT and DISTINCT checks are not modeled.
- Top-K (ANN vector) queries are not modeled: the CL downgrade to ONE/LOCAL_ONE, the refusal of
  SERIAL and the page-size override (SelectStatement.java:298-330).
- EXECUTE permission on functions, UNMASK/SELECT_MASKED for masked columns, and MODIFY on views
  are not modeled. Only the second SELECT check for tables with views is.
- JSON INSERT, collection operations other than the read-before-write flag, counters' CL rules
  (inside `consistency-level`), and `Mutation.validateSize` / `validateIndexedColumns` (write-path)
  are not modeled.
- These are not modeled: `QueryProcessor.preloadPreparedStatements` (called at startup by the
  daemon, owned by ops), the `internalStatements` cache, the `executeInternal*` / `executeAsync`
  helpers other subsystems use for system-table queries, the `onAlterTable` and function and
  aggregate invalidation listeners, and `CustomPayloadMirroringQueryHandler`.
- DESCRIBE renders `CREATE ... ...` placeholders instead of real CQL, and sorts by the order the
  schema stub returns.
- Virtual-table TRUNCATE (`VirtualKeyspaceRegistry`, owned by ops) is only narrated.

## Breaking changes (fix round)

None. Batch mutations covering two tables of one partition key now carry `updates` (all tables;
top level mirrors the first), per write-path's revised `WritePathMutation.updates` contract, which
`keyspace.apply-internal` and commit-log replay already apply per table (Keyspace.java:626-653).
Single-table mutations are unchanged.
