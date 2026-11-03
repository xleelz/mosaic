# Fixtures: the shared world (`fixtures.yaml`)

The coordinator owns `fixtures.yaml`. It is generated from one list of tables and one list of nodes,
so the schema digest, the ring and every gossip view agree. Don't edit one copy by hand: ask the
coordinator for a change.

## How to use it

- Pick one cluster fixture per scenario: `fixtures: [three-node-rf3]` (or `four-node-rf3` or
  `one-node`). All three extend `base-schema`. Add `auth-users` when the scenario logs in or checks
  permissions, for example `fixtures: [three-node-rf3, auth-users]`.
- Then seed only what is specific to the scenario, using the same keys. For a node seen as down
  from the coordinator, use `state: {"gossiper@n1": {endpoint_state_map: {n2: {alive: false}}}}`, or
  set the key on every node that must see it down.
- **Merge rules (§11.7, §13.1):** maps deep-merge and lists replace. A plain key (`schema`) applies
  to every instance, and an `@n` key (`gossiper@n2`) then applies to that instance only.
- **Fixtures cannot delete keys.** They merge over each component's `state.initial`. If your
  initial state still holds endpoint-keyed entries (`"10.0.0.2": {...}`, `"10.0.0.1:ks1.users"`),
  they survive next to the `n2` entries. When you migrate, re-key or empty those maps in your
  `state.initial`. In particular:
  - `gossiper.endpoint_state_map`, `failure-detector.arrival_samples` and
    `token-metadata.host_ids`/`keyspace_rf` (`ks_rf1`) belong to membership;
  - `migration-coordinator.peers`/`endpoint_versions`/`version_info` and `schema-keyspace.rows`
    belong to schema-auth;
  - `keyspace.tables`, `column-family-store.tables` and `view-manager.views_by_base_table` belong
    to write-path;
  - `cassandra-table-repair-manager.digests` belongs to repair-streaming.
- **Self identity.** Behaviors should prefer `self` to a `local_endpoint`-style field. The
  fixtures still set `local_endpoint`/`local` to the instance name on the components listed below,
  so behaviors that read the field stay correct on every node. Other components that hold the old
  address (`keyspace`, `column-family-store`, `commit-log`, `fb-utilities`, `paxos-participants`,
  `server-event-notifier` and similar) are **not** seeded. Use `self` there.
- **Per-replica stores** lose their `<replica>:` key prefix and their `replica` field. Each
  instance has its own state, so `schema-keyspace@n2.rows["table:shop.users"]` replaces
  `rows["10.0.0.2:table:shop.users"]`.
- **Identities.** Instance `nK` has host id `6d194555-f6eb-41d0-c000-00000000000K`. Its gossip
  generation is `1793314800` (an hour before the epoch). `local_time_s` is `1793318400`, the epoch.

## The schema

| Keyspace | Replication | Tables (columns; partition key first) |
|---|---|---|
| `ks1` | SimpleStrategy RF 3, durable writes | `events (id timeuuid, payload text)`, `page_views (url text, views bigint)`, `users (id text, name text, email text, city text)` |
| `shop` | SimpleStrategy RF 3, durable writes | `accounts (id uuid, balance decimal)`, `entries (id uuid, body text)`, `orders (id uuid, total decimal)`, `page_views (url text, views bigint)`, `users (id text, name text, email text, city text)` |

- **Indexes** on `shop.users`: `users_email_idx` on `email` (legacy local table) and
  `users_city_sai` on `city` (SAI).
- **No views, types or UDFs** are seeded, since `materialized_views_enabled` is false. Scenarios
  that need a view or type seed it, as do DDL scenarios that create `shop.customers`,
  `shop.address` and so on.
- **Unknown tables:** `ks1.dropped_table`, `shop.nope` and `nosuch` stay unknown on purpose.
- The schema version digest (`"v:"` plus the row sigs joined with `;`, in row-key order) is:

```
v:index:shop.users_city_sai{users.city};index:shop.users_email_idx{users.email};keyspace:ks1{SimpleStrategy:3};keyspace:shop{SimpleStrategy:3};table:ks1.events{id timeuuid,payload text};table:ks1.page_views{url text,views bigint};table:ks1.users{id text,name text,email text,city text};table:shop.accounts{id uuid,balance decimal};table:shop.entries{id uuid,body text};table:shop.orders{id uuid,total decimal};table:shop.page_views{url text,views bigint};table:shop.users{id text,name text,email text,city text}
```

Call it `V` below.

## `base-schema` (plain keys: the same on every instance; no topology, no clock)

| State key | Area | Shape seeded |
|---|---|---|
| `schema` | schema-auth (read by transport, cql) | `version: V`; `keyspaces: {ks1\|shop: {name, exists: true, durable_writes: true, replication: {class: SimpleStrategy, replication_factor: 3}, tables: [names]}}` |
| `schema-keyspace` | schema-auth | `rows: {"<kind>:<ks>[.<name>]": {kind, keyspace, name, def, sig}}` with kinds `keyspace` (`def: {class, replication_factor}`), `table` (`def: {columns: ["col type"], partition_key: [col]}`) and `index` (`def: {table, column, kind}`, `sig: index:<ks>.<name>{<table>.<column>}`) |
| `keyspace` | write-path | `durable_writes: {ks1: true, shop: true, system: true}`; `tables: {"<ks>.<table>": {cdc: false, skip_commitlog: false}}` for all 8 tables and `system.batches` |
| `column-family-store` | write-path | `tables: {"<ks>.<table>": {durable_writes: true, allow_auto_snapshot: true}}` for all 8 tables, and `system.batches` with `allow_auto_snapshot: false` |
| `view-manager` | write-path | `views_by_base_table: {"<ks>.<table>": []}` for all 8 tables |
| `secondary-index-manager` | read-path | `indexes: {"shop.users.email": {name: users_email_idx, kind: legacy_local_table, sstable_indexes: 0}, "shop.users.city": {name: users_city_sai, kind: sai, sstable_indexes: 3}}` |
| `token-metadata` | membership | `default_rf: 3`, `keyspace_rf: {ks1: 3, shop: 3}` |
| `storage-service` | membership | `distributed_keyspaces: [ks1, shop]`; `user_tables: [{keyspace, table}]` for all 8 tables |
| `abstract-replication-strategy` | coordination | `strategies: {default: SimpleStrategy, ks1: SimpleStrategy, shop: SimpleStrategy}` |
| `storage-service-mbean` | ops | `keyspaces: [system, system_schema, system_auth, system_distributed, system_traces, ks1, shop]`; `distributed_keyspaces: [system_auth, system_distributed, system_traces, ks1, shop]`; `tables: {system: [local, peers_v2], system_schema: [tables], system_auth: [roles], system_distributed: [repair_history], system_traces: [sessions, events], ks1: [events, page_views, users], shop: [accounts, entries, orders, page_views, users]}` |
| `repair-coordinator` | repair-streaming | `schema_tables: {ks1: [events, page_views, users], shop: [accounts, entries, orders, page_views, users]}` |
| `snapshot-manager` | repair-streaming | `schema_tables:` as above |
| `auto-repair` | repair-streaming | `keyspaces: [ks1, shop]` |
| `cassandra-table-repair-manager` | repair-streaming | `digests: {"<ks>.<table>": "d41d8cd9"}` for all 8 tables, so every node is in sync |

## `auth-users` (plain keys)

| State key | Area | Shape seeded |
|---|---|---|
| `auth-config` | schema-auth (read by transport) | `{authenticator: PasswordAuthenticator, authorizer: CassandraAuthorizer, role_manager: CassandraRoleManager}` (network and CIDR authorizers stay AllowAll) |
| `auth-keyspace` | schema-auth | `roles`: `cassandra` (superuser, login, `salted_hash: "bcrypt:cassandra"`), `alice` (login, `"bcrypt:s3cret"`, `member_of: [analyst]`) and `analyst` (no login, empty hash), each `{role, is_superuser, can_login, salted_hash, member_of, password_updated_at: 0}`; `role_members: {"analyst\|alice": {role, member}}`; `role_permissions: {"analyst\|data/shop": [SELECT], "alice\|data/shop/orders": [MODIFY]}` as `{role, resource, permissions}`; `identity_to_roles: {"spiffe://shop/app": {identity, role: alice}}`; `cidr_groups: {office: {cidr_group, cidrs: [10.0.0.0/24]}}` |
| `client-state` | transport | `{user: ""}`: a fresh connection that has not logged in, as `ClientState.forExternalCalls` leaves it under PasswordAuthenticator. Seed `{user: alice}` (or `cassandra`) for an already logged-in session |

- **Passwords:** `cassandra`/`cassandra` and `alice`/`s3cret`.
- **Not seeded:** `bob` and `mallory`. CREATE ROLE scenarios create `bob`, and `mallory` is
  unknown on purpose.
- **Deployed setting:** the deployed `cassandra.yaml` uses AllowAll. Without `auth-users`, the
  component defaults apply.

## `three-node-rf3` (extends `base-schema`)

- **Topology:** `{cassandra-node: [n1, n2, n3]}`. `n1` is the seed and the default entry instance,
  so it coordinates by default.
- **Clock:** `epoch: 2026-10-30T00:00:00Z`.
- **Ring:** `n1` at -6148914691236517206, `n2` at 0 and `n3` at 6148914691236517205. RF 3 puts
  every token on all three nodes.

For each node `X` in `n1..n3`:

| State key | Area | Shape seeded |
|---|---|---|
| `gossiper@X` | membership | `local_endpoint: X`, `seeds: [n1]`, `configured_seeds: [n1]`, `local_time_s: 1793318400`, `live_endpoints: [the other nodes]`, `unreachable_endpoints: []`, `endpoint_state_map: {n1..n3: {endpoint, alive: true, status: NORMAL, generation: 1793314800, heartbeat, max_version, host_id, dc: datacenter1, rack: rack1, tokens: [token], load: 1048576, rpc_ready: true, update_ms: 0}}`. Heartbeat and max_version are n1 400/420, n2 350/360, n3 330/340 (n4 300/300). Every node holds its own copy of this view |
| `failure-detector@X` | membership | `local_endpoint: X`, `arrival_samples: {<each other node>: {t_last_ms: 0, mean_ms: 1000}}` |
| `token-metadata@X` | membership | `ring: [{token, endpoint: nK}]` sorted by token; `host_ids: {nK: uuid}`; `bootstrap_tokens: []`, `leaving_endpoints: []`, `moving_endpoints: []`, `pending_ranges: []` (entries are `{keyspace, left, right, endpoint}`) |
| `storage-service@X` | membership | `local_endpoint: X`, `is_seed` (true on n1 only), `saved_tokens: [own token]`, `num_tokens: 1` |
| `schema@X` | schema-auth | `local: X` (`version` comes from base-schema) |
| `default-schema-update-handler@X` | schema-auth | `local: X` |
| `migration-coordinator@X` | schema-auth | `local: X`; `peers: {<other>: {release_version: 5.0.9, messaging_version: 13, gossip_only: false, schema_version: V}}`; `endpoint_versions: {<other>: {endpoint, version: V}}`; `version_info: {V: {version: V, received: true, endpoint: <first other node>}}`; `last_pull_failures: {}` |

## `four-node-rf3` (extends `three-node-rf3`)

- **Topology:** `{cassandra-node: [n1, n2, n3, n4]}`. The clock and schema are inherited.
- **Ring:** `n4` at 3000000000000000000, so the order is n1, n2, n4, n3. Every key above is
  re-seeded for n1..n4. The lists (`ring`, `live_endpoints`) are replaced, and the maps gain an
  `n4` entry.
- **Coordinator not a replica:** a token in (-6148914691236517206, 0], such as `-5`, replicates to
  `[n2, n4, n3]`. Checked: `token-metadata.get-write-endpoints {keyspace: shop, token: -5}` on n1
  returns `natural == [n2, n4, n3]`.
- **All replicas down:** use the same token and mark n2, n3 and n4 `alive: false` in
  `gossiper@n1`.

## `one-node` (extends `base-schema`)

- **Topology:** `{cassandra-node: [n1]}`, with the same clock.
- **Ring:** n1 alone. `gossiper@n1` knows only n1 and has `live_endpoints: []`.
  `failure-detector@n1.arrival_samples: {}`. `migration-coordinator@n1` has no peers and
  `version_info: {}`.
- **Use it for** local-only flows: the local write path, local reads, flush, compaction, commit
  log replay and startup.
- **Replication:** the keyspaces keep RF 3, so only ONE and LOCAL_ONE can succeed. Seed
  `token-metadata: {keyspace_rf: {...: 1}}` if a scenario needs QUORUM on one node.

## Decisions on conflicting seeding contracts

1. **The `shop.users` seam.** write-path knew only `ks1`, while read-path, cql, transport,
   coordination and hints used `shop`. Both keyspaces now exist with the union of their tables on
   every table-keeping component.
2. **The `users` columns.** schema-auth had `id, name, email`, while read-path and write-path
   used a `city` column (and an SAI index on it). Both `users` tables now have
   `id, name, email, city`. This changes schema-auth's version string. Assert with
   `contains(...)`, or compare against `V`.
3. **Two shapes for `schema`.** transport seeded `schema.keyspaces.shop = {exists, name}`, while
   schema-auth derives keyspaces from `schema-keyspace.rows`. Both are seeded and agree:
   `schema.keyspaces` is the readable keyspace list, and `schema-keyspace.rows` stays the
   source of the digest.
4. **`client-state.authenticator`.** schema-auth seeded `{authenticator: PasswordAuthenticator}`
   on `client-state`, but transport's ClientState reads the backend from `auth-config`, as the
   code does. `auth-users` sets `auth-config` and leaves `client-state` with only `user`. Drop
   `authenticator` and `authorizer` from client-state seeds.
5. **Keyspaces outside the shared world.** These are not part of it:
   - paxos's `bank.accounts` should become `shop.accounts`;
   - membership's `ks_rf1` and repair's `ks_empty`, if still needed, are seeded by those
     scenarios;
   - coordination's `abstract-read-executor.table_params` is keyed by bare table name and was
     left alone. Key it by `<ks>.<table>` if you seed per-table params.
6. **n4's token.** coordination used 3000000000000000000, and membership's bootstrap scenarios
   used 3074457345618258602 for a joining node. The fixture takes coordination's value, since
   `four-node-rf3` is a settled ring. Bootstrap scenarios seed their own joining node.
7. **Generation.** It moved from 1761800000 (2025) to 1793314800, to sit just before the
   2026-10-30 epoch. `local_time_s` is seeded to the epoch so the generation-difference check
   stays meaningful. Better still, membership should read `now`.

## Change log

- **2026-10-30, coordinator:** `failure-detector@nX.arrival_samples.*.t_last_ms` changed from 0 to
  1793318400000, the fixture clock's epoch. With 0, the phi detector saw peers as silent since
  1970 and convicted all of them (reported by membership).
