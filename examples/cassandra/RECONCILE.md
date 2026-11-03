# Reconciliation round

All 11 fragments pass on their own. Merged, they produce 0 validation errors and 4,323 of 4,323 citations
ok, but **140 of 1,084 scenarios fail** and there are 54 merge warnings. This round fixes that.
The rules in `BRIEF.md` still apply in full: write only your own fragment and notes, plus your
own skips file.

## Your inputs

- `reconcile/<area>.txt`: your failing scenarios in the merged run, and the merge warnings that
  name your fragment.
- `reconcile/merged-check.txt`: the full merged check output.
- The other areas' fragments, which you may now read **for contracts**: the interfaces you call
  and the state you seed. Still never read other areas' notes, `BENCHMARK.md` or `judge/`.

## Decisions (the coordinator's, binding)

1. **The owner's contract wins.** Callers align their call sites and stubs to the owner's
   request, response, kind and errors, including `retryable`. Owners don't loosen a contract to
   fit a caller's guess. The exception is a contract that's wrong about the code; then the owner
   fixes it and says so.
2. **`storage-proxy.read` requires `read_command`** (coordination owns it). Every caller, from
   cql, transport and schema-auth, sends `read_command` in the `ReadPathReadCommand` shape
   (`{keyspace, table, partition_key, token, columns, limit, digest}`). `columns` is a **list of
   column names** in a read command. The fix is cql's, because it's cql's statements that make
   the call. This one change accounts for 63 failures.
3. **`query-processor.parse` and the rest of `query-processor.*`** belong to cql. Transport sends
   exactly what cql's request schema requires (`statement`, `client_state` and so on).
4. **Cluster state lives with membership.** Scenarios mark nodes down through
   `state: {gossiper: {endpoint_state_map: {"<ep>": {alive: false}}}}`, and set topology on
   `token-metadata`. Coordination, paxos and hints-batchlog re-point the scenario `state` they set
   on their own stubs (failure-detector, token-metadata, fb-utilities) to membership's components,
   and drop the stub state.
5. **Repair mutations.** A mutation carries `columns` as a map. Write-path's `keyspace.apply` and
   `mutation.apply` also accept an optional `cells` list (`[{column, value, timestamp}]`) for
   mutations built by read repair, since CEL can't build a map from a list. Write-path adds it,
   and coordination keeps sending `cells`.
6. **Unowned stubs.** Each owner below defines these interfaces. Pass-through stubs are fine:
   correct kind and shapes, and a short behavior citing the method. Keep their names exactly,
   because callers already use them.
   - **membership (36):** `gossiper.{get-endpoint-downtime, get-min-version, get-unreachable-token-owners, is-alive, reload-seeds, wait-for-schema-agreement, wait-to-settle}`, `messaging-service-mbean-impl.reload-ssl-certificates`, `pending-range-calculator-service.calculate-pending-ranges`, `storage-service.{auto-repair-paxos, check-service-allowed-to-start, confirm-replication, force-remove-completion, get-bootstrap-state, get-endpoint-for-host-id, get-host-id-for-endpoint, get-live-ring-members, get-local-host-uuid, get-local-replicas, get-nativeaddress, get-operation-mode, get-range-to-address-map, is-bootstrap-mode, is-decommissioning, is-endpoint-valid-for-write, is-rpc-ready, join-ring, populate-token-metadata, rebuild, resume-bootstrap, set-rpc-ready, start-gossiping, stop-gossiping}`, `token-metadata.{get-pending-ranges, get-size-of-all-endpoints, sorted-tokens}`.
     `storage-service.is-bootstrap-mode` returns `{bootstrap_mode: bool}`; callers that assumed a
     bare boolean align to it.
   - **read-path (20):** `auto-saving-cache.{clear, set-capacity}`, `column-family-store.{disable-auto-compaction, enable-auto-compaction, force-compaction-keys-ignoring-gc-grace, rebuild-secondary-index, set-compaction-thresholds}`, `compaction-manager.{force-compaction-for-token-range, get-pending-tasks, perform-garbage-collection, perform-scrub, perform-sstable-rewrite, perform-verify, relocate-sstables, set-concurrent-compactors, set-concurrent-view-builders, set-rate-in-bytes, submit-view-builder}`, `secondary-index-manager.truncate-all-indexes-blocking`, `single-partition-read-command.execute-locally`. Read-path also takes the compaction operations in `ColumnFamilyStoreMBean`, and write-path takes its flush, load and import ones.
   - **write-path (13):** `column-family-store.{add-sstables, import-new-sstables, load-new-sstables, on-paxos-repair-complete, reload, sync-paxos-repair-history}`, `commit-log.start`, `keyspace.{drop-cf, get-column-family-stores, init-cf, open, unload}`, `view-utils.get-view-natural-endpoint`. Also add name validation and snapshot registration to `column-family-store.snapshot` (from repair-streaming).
   - **schema-auth (12):** `cidr-groups-mapping-manager.{drop-cidr-group, load-cidr-groups-cache, update-cidr-group}`, `cidr-permissions-manager.invalidate-cidr-permissions-cache`, `partition-denylist.{get-denied-keys-in-range-count, is-key-permitted}`, `password-authenticator.{evaluate-response, get-authenticated-user}` (or re-point callers to the inner-class names, and tell transport), `schema.{get-distributed-schema-blocking, largest-gcgs, load-from-disk, validate-table}`.
   - **cql (3):** `query-processor.{clear-prepared-statements, preload-prepared-statements, process-query-string}`.
   - **ops (5):** `diagnostic-snapshot-service.snapshot`, `fb-utilities.get-broadcast-address-and-port`, `tracing.{begin, new-session, stop-session}`.
   - **hints-batchlog (2):** `batchlog-manager.{set-rate, start-batchlog-replay}`.
   - **coordination (1):** `storage-proxy.is-safe-to-perform-read`.
   - **transport (1):** `client-state.ensure-not-anonymous`.
7. **One copy of each piece of logic.** Hints-batchlog replaces its inline copy of
   `sendToHintedReplicas` with calls to coordination's interfaces, and adjusts its scenarios.
8. **Ownership claims made during the build stand.** Write-path keeps `TruncateVerbHandler`,
   `MemtableCleanerThread`, the memtable pool and the `Cassandra*WriteHandler` classes.
   Coordination keeps `ReadRepairVerbHandler`. Cql keeps `AuthenticationStatement` and ADD/DROP
   IDENTITY. On a shared component, the owning area's kind wins. Transport owns `ClientWarn`,
   so `client-warn` keeps transport's kind, and schema-auth aligns.
9. **Scenario expectations about another area's internals.** Assert on your own calls and on the
   outcome, not on how many times another area's internal interfaces are called. Read-path
   showed two such assertions that contradict the code (in coordination and ops); fix yours.

## Skips go into a machine-readable file

Write `skips/<area>.json`: a JSON array of `{"kind", "name", "file", "line", "reason"}`, with
**one object per inventory entry**. Expand group skips into their exact entries, copying `kind`,
`name`, `file` and `line` from `inventory.json`. The coordinator merges these into the inventory's
`skip` fields. Your notes keep the grouped, human-readable form.

## Verify

Run the merged check of all fragments (put your updated fragment in the list), and make sure none
of **your** scenarios fail and no merge warning names your fragment:

```sh
cd /home/lbethay/workplace/mosaic
F=""; for f in examples/cassandra/fragments/*.yaml; do F="$F -f $f"; done
PATH=/usr/local/go/bin:$PATH GOFLAGS=-mod=readonly go run ./internal/devtools/check \
  -f examples/cassandra/skeleton.yaml $F \
  --code /home/lbethay/.cache/cassandra-bench/cassandra-5.0.9 --strict-citations \
  --inventory examples/cassandra/inventory.json
```

Other areas are editing their fragments at the same time, so a failure caused by another area's
unfinished fix isn't yours. Name it in your report, and don't work around it. Also run your
standalone check (skeleton plus your fragment). It must stay green, apart from scenarios that now
need another area's real definitions.

## Report (≤120 words)

Your failures and warnings fixed and remaining (each remaining one with its cause and the area it
waits on), the stubs you defined, your skips file count, and the final check lines.
